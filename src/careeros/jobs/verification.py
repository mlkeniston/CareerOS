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
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'noscript', 'template'}:
            self.hidden += 1
        elif not self.hidden:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript', 'template'}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _contains(text: str, value: str) -> bool:
    normalize = lambda s: re.sub(r'[^a-z0-9]+', ' ', s.casefold()).strip()
    term = normalize(value)
    return bool(term) and f' {term} ' in f' {normalize(text)} '


class EmployerPostingVerifier:
    def __init__(self, *, transport=None, resolver=None):
        self.resolver = resolver or _resolve
        self.client = httpx.Client(transport=transport, trust_env=False, follow_redirects=False,
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
            with self.client.stream('GET', target, headers={'Host': authority},
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
                if content_type != 'text/plain':
                    parser = _Text()
                    parser.feed(raw)
                    raw = ''.join(parser.parts)
                text = '\n'.join(' '.join(line.split()) for line in raw.splitlines() if line.strip())
                if re.search(r'(?i)\b((?:position|job|role|listing|posting)(?: posting| listing)? (?:is |has been |has )?(?:closed|expired|filled)|no longer (?:accepting applications|available)|applications? (?:are |is )?closed|position (?:has been |is )?filled)\b', text):
                    return held('Employer listing is closed or expired', text, fingerprint)
                if not _contains(text, expected_company) or not _contains(text, expected_title):
                    return held('Employer page does not match the company and role', text, fingerprint)
                return VerificationResult('verified', 'Employer company and role match', sanitized, stamp, text, fingerprint)
        except (ValueError, UnicodeError, OSError, httpx.HTTPError):
            return held('Employer page could not be safely verified')
