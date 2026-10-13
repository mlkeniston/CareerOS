"""Conservative employer-page checks. Page text is data, never instructions."""
from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from careeros.queue import now

MAX_BODY = 1024 * 1024
MAX_REDIRECTS = 5
VerificationOutcome = Literal['verified', 'closed', 'identity_mismatch', 'insufficient_detail',
                              'access_restricted', 'not_found', 'transient_error', 'unsafe_destination']


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: Literal['verified', 'held']
    reason: str
    final_url: str | None
    checked_at: str
    text: str = ''
    fingerprint: str | None = None
    outcome: VerificationOutcome | None = None
    checked_url: str | None = None
    evidence_summary: str = ''

    def __post_init__(self):
        # Existing positional callers still supply the compatibility gate status.
        if self.outcome is None:
            object.__setattr__(self, 'outcome', 'verified' if self.status == 'verified' else 'insufficient_detail')
        elif self.outcome != 'verified':
            object.__setattr__(self, 'status', 'held')
        elif self.status != 'verified':
            object.__setattr__(self, 'outcome', 'insufficient_detail')

    @property
    def verified(self) -> bool:
        return self.status == 'verified' and self.outcome == 'verified'


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


def _unauthenticated_request(request: httpx.Request) -> None:
    # HTTPX collects response cookies automatically, including across pinned IP
    # origins. Public posting checks must never forward those session credentials.
    for header in ('cookie', 'authorization', 'proxy-authorization'):
        request.headers.pop(header, None)


class EmployerPostingVerifier:
    def __init__(self, *, transport=None, resolver=None):
        self.resolver = resolver or _resolve
        self.client = httpx.Client(transport=transport, trust_env=False, follow_redirects=False,
                                  # A pinned IP origin must not pool TLS authenticated for another hostname.
                                  http2=False, limits=httpx.Limits(max_keepalive_connections=0),
                                  timeout=httpx.Timeout(12, connect=4), headers={'User-Agent': 'CareerOS/0.1', 'Accept-Encoding': 'identity'},
                                  event_hooks={'request': [_unauthenticated_request]})

    def close(self):
        self.client.close()

    def verify(self, url: str, expected_company: str, expected_title: str) -> VerificationResult:
        stamp, checked_url, final_url = now(), None, None

        def result(outcome: VerificationOutcome, reason, text='', fingerprint=None):
            return VerificationResult(
                'verified' if outcome == 'verified' else 'held', reason, final_url, stamp,
                text, fingerprint, outcome, checked_url, reason,
            )

        try:
            current, host, port = _safe_url(url)
            checked_url = current
        except (ValueError, UnicodeError):
            return result('unsafe_destination', 'Employer URL could not be safely verified')

        visited = set()
        redirects = 0
        try:
            while True:
                if current in visited:
                    return result('unsafe_destination', 'Employer redirect loop is blocked')
                visited.add(current)
                try:
                    addresses = self.resolver(host, port)
                    if not addresses or any(not _public(address) for address in addresses):
                        return result('unsafe_destination', 'Private/reserved DNS destination is blocked')
                except (ValueError, UnicodeError):
                    return result('unsafe_destination', 'Employer DNS destination is invalid')
                final_url = current
                # Pin each hop to its validated IP. SNI keeps hostname certificate
                # validation and Host keeps virtual hosting; no pooled cross-host TLS.
                target = httpx.URL(current).copy_with(host=addresses[0])
                authority = urlsplit(current).netloc
                with self.client.stream('GET', target, headers={'Host': authority, 'Connection': 'close'},
                                        extensions={'sni_hostname': host}, follow_redirects=False) as response:
                    if 300 <= response.status_code < 400:
                        if redirects >= MAX_REDIRECTS:
                            return result('unsafe_destination', 'Employer redirect limit exceeded')
                        destination = response.headers.get('location', '')
                        try:
                            if not destination.strip():
                                raise ValueError('Missing redirect destination')
                            # Validate the reference before urljoin can strip controls.
                            if any(ord(c) < 32 for c in destination) or '\\' in destination:
                                raise ValueError('Invalid redirect destination')
                            resolved, next_host, next_port = _safe_url(urljoin(current, destination))
                            if urlsplit(current).scheme == 'https' and urlsplit(resolved).scheme != 'https':
                                raise ValueError('HTTPS downgrade')
                        except (ValueError, UnicodeError):
                            return result('unsafe_destination', 'Unsafe employer redirect destination is blocked')
                        current, host, port = resolved, next_host, next_port
                        redirects += 1
                        continue
                    status = response.status_code
                    if status != 200:
                        if status in {401, 403}:
                            outcome = 'access_restricted'
                        elif status in {404, 410}:
                            outcome = 'not_found'
                        elif status == 429 or 500 <= status < 600:
                            outcome = 'transient_error'
                        else:
                            outcome = 'insufficient_detail'
                        return result(outcome, f'Employer page returned HTTP {status}')
                    content_type = response.headers.get('content-type', '').split(';')[0].strip().lower()
                    if content_type not in {'text/html', 'text/plain', 'application/xhtml+xml'}:
                        return result('insufficient_detail', 'Employer page has unsupported content type')
                    if response.headers.get('content-encoding', 'identity').strip().lower() != 'identity':
                        return result('insufficient_detail', 'Employer page uses unsupported content encoding')
                    declared = response.headers.get('content-length')
                    if declared and int(declared) > MAX_BODY:
                        return result('insufficient_detail', 'Employer page body is too large')
                    body = bytearray()
                    for chunk in response.iter_bytes(chunk_size=8192):
                        if len(body) + len(chunk) > MAX_BODY:
                            return result('insufficient_detail', 'Employer page body is too large')
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
                        return result('closed', 'Employer listing is closed or expired', text, fingerprint)
                    if not text or identity_text is None:
                        return result('insufficient_detail', 'Employer page has insufficient or ambiguous primary posting detail', text, fingerprint)
                    if not _primary_matches(identity_text, headings, companies, paragraphs, expected_company, expected_title):
                        return result('identity_mismatch', 'Employer primary posting does not match the company and role', text, fingerprint)
                    return result('verified', 'Employer primary company and role match', text, fingerprint)
        except (OSError, httpx.TransportError):
            return result('transient_error', 'Employer page has a temporary network or timeout error')
        except (ValueError, UnicodeError, httpx.HTTPError):
            return result('insufficient_detail', 'Employer page could not be safely verified')
