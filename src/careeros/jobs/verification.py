"""Conservative employer-page checks. Page text is data, never instructions."""
from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx

from careeros.queue import now

MAX_BODY = 1024 * 1024


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: Literal['verified', 'held']
    reason: str
    final_url: str | None
    checked_at: str
    text: str = ''
    fingerprint: str | None = None


def _resolve(host: str, port: int) -> list[str]:
    return [answer[4][0] for answer in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if not ip.is_global or ip.is_multicast or ip.is_reserved or getattr(ip, 'is_site_local', False):
        return False
    if getattr(ip, 'ipv4_mapped', None):
        return False
    if getattr(ip, 'sixtofour', None) and not _public(str(ip.sixtofour)):
        return False
    if getattr(ip, 'teredo', None) and any(not _public(str(item)) for item in ip.teredo):
        return False
    return True


def _safe_url(url: str) -> tuple[str, str, int]:
    if any(ord(c) < 32 for c in url) or '\\' in url:
        raise ValueError('Invalid URL')
    parsed = urlsplit(url)
    host = parsed.hostname
    if parsed.scheme not in {'http', 'https'} or not host:
        raise ValueError('Employer URL must use HTTP or HTTPS')
    if parsed.username is not None or parsed.password is not None:
        raise ValueError('Employer URL contains credentials')
    host = host.rstrip('.').encode('idna').decode('ascii').lower()
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')) or '.' not in host and ':' not in host:
        raise ValueError('Local/private destination is blocked')
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not _public(str(ip)):
            raise ValueError('Private/reserved destination is blocked')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    authority = f'[{host}]' if ':' in host else host
    if parsed.port:
        authority += f':{port}'
    return urlunsplit((parsed.scheme, authority, parsed.path or '/', parsed.query, '')), host, port


class _Text(HTMLParser):
    """Keep posting identity separate from navigation and related-job links."""
    _inert = {'script', 'style', 'noscript', 'template'}
    _identity_excluded = {'nav', 'aside', 'footer'}
    _void = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    _blocks = {'h1', 'h2', 'h3', 'p', 'div', 'main', 'article', 'section', 'header', 'li', 'br'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.full_parts = []
        self.stack = []
        self.scopes = []
        self.scope_kinds = {}
        self.headings = []
        self.companies = []
        self.paragraphs = []
        self._next_scope = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        parent = self.stack[-1] if self.stack else {}
        annotation = ' '.join(attrs.get(key) or '' for key in ('class', 'id', 'aria-label'))
        hidden = parent.get('hidden', False) or tag in self._inert
        excluded = (parent.get('excluded', False) or hidden or tag in self._identity_excluded
                    or attrs.get('role') == 'navigation'
                    or bool(re.search(r'(?i)related|recommended|similar[-_ ]jobs', annotation)))
        scope = parent.get('scope')
        if tag in {'main', 'article'} and scope is None and not excluded:
            self._next_scope += 1
            scope = self._next_scope
            self.scope_kinds[scope] = tag
        if tag in self._blocks and not hidden:
            self._append('\n')
        if tag not in self._void:
            if len(self.stack) >= 64:
                raise ValueError('Employer HTML nesting is too deep')
            self.stack.append({'tag': tag, 'attrs': attrs, 'excluded': excluded, 'hidden': hidden,
                               'anchor': parent.get('anchor', False) or tag == 'a',
                               'scope': scope, 'parts': [], 'plain': []})

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]['tag'] == tag:
                while len(self.stack) > index:
                    self._finish_element()
                if tag in self._blocks:
                    self._append('\n')
                break

    def _append(self, data):
        parent = self.stack[-1] if self.stack else {}
        if parent.get('hidden', False):
            return
        # Evidence covers the full visible page, including links and notices
        # outside the posting. Only identity candidates use the narrower filter.
        self.full_parts.append(data)
        if parent.get('excluded', False):
            return
        if not parent.get('anchor', False):
            self.parts.append(data)
        for frame in self.stack:
            frame['parts'].append(data)
            if not parent.get('anchor', False):
                frame['plain'].append(data)

    def handle_data(self, data):
        self._append(data)

    def _finish_element(self):
        frame = self.stack.pop()
        if frame['excluded']:
            return
        scope, tag = frame['scope'], frame['tag']
        text = ' '.join(''.join(frame['parts']).split())
        plain = ''.join(frame['plain'])
        if tag == 'h1':
            self.headings.append((scope, text))
        attrs = frame['attrs']
        company_marker = (attrs.get('itemprop') == 'hiringOrganization'
                          or any(value in {'company', 'company-name', 'employer', 'employer-name'}
                                 for value in (attrs.get('class') or '').split()))
        if company_marker:
            self.companies.append((scope, text))
        if tag == 'p' and plain.strip():
            self.paragraphs.append((scope, ' '.join(plain.split())))
        if tag in {'main', 'article'} and scope in self.scope_kinds:
            self.scopes.append((scope, plain))

    def finish(self):
        while self.stack:
            self._finish_element()

    def primary(self):
        scopes = [scope for scope, kind in self.scope_kinds.items() if kind == 'main']
        if not scopes:
            scopes = list(self.scope_kinds)
        if len(scopes) > 1:
            return None, [], [], [], ''.join(self.full_parts)
        scope = scopes[0] if scopes else None
        # The outer main/article is finalized last for each scope.
        parts = [plain for candidate, plain in self.scopes if candidate == scope]
        text = parts[-1] if parts else ''.join(self.parts)
        select = lambda values: [value for candidate, value in values if candidate == scope]
        # Visible posting headers may sit just outside main; conflicting identity
        # there cannot be overridden by expected words later in the body.
        return text, [value for _, value in self.headings], [value for _, value in self.companies], select(self.paragraphs), ''.join(self.full_parts)


def _normalize(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', value.casefold()).strip()


def _primary_matches(text, headings, companies, paragraphs, company, title):
    company, title = _normalize(company), _normalize(title)
    if not company or not title or text is None:
        return False
    allowed_headings = {title, f'{title} at {company}', f'{title} {company}', f'{company} {title}'}
    if headings and any(_normalize(heading) not in allowed_headings for heading in headings):
        return False
    if companies:
        company_matches = all(_normalize(value) == company for value in companies)
    elif any(_normalize(heading) != title and _contains(heading, company) for heading in headings):
        company_matches = True
    else:
        lines = [line.strip() for line in text.splitlines() if line.strip() and _normalize(line) not in allowed_headings]
        lead = paragraphs[0] if paragraphs else (lines[0] if lines else '')
        normalized_lead = _normalize(lead)
        company_matches = (normalized_lead == company or normalized_lead.startswith(company + ' ')
                           or normalized_lead.startswith('company ' + company)
                           or normalized_lead.startswith('employer ' + company))
    if not company_matches:
        return False
    if headings:
        return True
    # Unstructured text must identify this posting together in its opening sentence.
    lead = paragraphs[0] if paragraphs else text.strip().split('\n')[0]
    opening = re.split(r'[.!?]', lead, maxsplit=1)[0]
    return _normalize(opening) in {f'{company} {title}', f'{title} at {company}',
                                   f'{company} is hiring a {title}', f'{company} is hiring an {title}'}


def _contains(text: str, value: str) -> bool:
    term = _normalize(value)
    return bool(term) and f' {term} ' in f' {_normalize(text)} '


class EmployerPostingVerifier:
    def __init__(self, *, transport=None, resolver=None):
        self.resolver = resolver or _resolve
        self.client = httpx.Client(transport=transport, trust_env=False, follow_redirects=False,
                                  # A pinned IP origin must not pool TLS authenticated for another hostname.
                                  http2=False, limits=httpx.Limits(max_keepalive_connections=0),
                                  timeout=httpx.Timeout(12, connect=4), headers={'User-Agent': 'CareerOS/0.1', 'Accept-Encoding': 'identity'})

    def close(self):
        self.client.close()

    def verify(self, url: str, expected_company: str, expected_title: str) -> VerificationResult:
        stamp, sanitized = now(), None
        def held(reason, text='', fingerprint=None):
            return VerificationResult('held', reason, sanitized, stamp, text, fingerprint)
        try:
            sanitized, host, port = _safe_url(url)
            addresses = self.resolver(host, port)
            if not addresses or any(not _public(address) for address in addresses):
                return held('Private/reserved DNS destination is blocked')
            # Pin the validated address for the actual connection to prevent DNS rebinding.
            # TLS still validates the employer hostname; Host preserves virtual hosting.
            target = httpx.URL(sanitized).copy_with(host=addresses[0])
            authority = urlsplit(sanitized).netloc
            with self.client.stream('GET', target, headers={'Host': authority, 'Connection': 'close'},
                                    extensions={'sni_hostname': host}, follow_redirects=False) as response:
                if 300 <= response.status_code < 400:
                    destination = response.headers.get('location', '')
                    try:
                        destination = _safe_url(destination)[0]
                    except ValueError:
                        destination = '(unsafe or relative destination)'
                    return held(f'Redirect blocked: {destination[:180]}')
                if response.status_code != 200:
                    return held(f'Employer page returned HTTP {response.status_code}')
                content_type = response.headers.get('content-type', '').split(';')[0].strip().lower()
                if content_type not in {'text/html', 'text/plain', 'application/xhtml+xml'}:
                    return held('Employer page has unsupported content type')
                if response.headers.get('content-encoding', 'identity').strip().lower() != 'identity':
                    return held('Employer page uses unsupported content encoding')
                declared = response.headers.get('content-length')
                if declared and int(declared) > MAX_BODY:
                    return held('Employer page body is too large')
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=8192):
                    if len(body) + len(chunk) > MAX_BODY:
                        return held('Employer page body is too large')
                    body.extend(chunk)
                fingerprint = hashlib.sha256(body).hexdigest()
                raw = body.decode('utf-8', errors='replace')
                identity_text = raw
                headings, companies, paragraphs = [], [], []
                if content_type != 'text/plain':
                    parser = _Text()
                    parser.feed(raw)
                    parser.close()
                    parser.finish()
                    identity_text, headings, companies, paragraphs, raw = parser.primary()
                text = '\n'.join(' '.join(line.split()) for line in raw.splitlines() if line.strip())
                if re.search(r'(?i)\b((?:position|job|role|listing|posting)(?: posting| listing)? (?:is |has been |has )?(?:closed|expired|filled)|no longer (?:accepting applications|available)|applications? (?:are |is )?closed|position (?:has been |is )?filled)\b', text):
                    return held('Employer listing is closed or expired', text, fingerprint)
                if identity_text is None:
                    return held('Employer page has ambiguous primary postings', text, fingerprint)
                if not _primary_matches(identity_text, headings, companies, paragraphs, expected_company, expected_title):
                    return held('Employer primary posting does not match the company and role', text, fingerprint)
                return VerificationResult('verified', 'Employer primary company and role match', sanitized, stamp, text, fingerprint)
        except (ValueError, UnicodeError, OSError, httpx.HTTPError):
            return held('Employer page could not be safely verified')
