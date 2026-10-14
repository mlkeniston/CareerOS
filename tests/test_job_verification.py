import httpx
import pytest

from careeros.jobs.verification import EmployerPostingVerifier


POSTING = ('Example SWE Intern. Build Python services and maintain APIs with our engineering team. '
           'Collaborate with mentors, review code, document features, and deliver useful software to customers.')


@pytest.fixture
def verifier_with_mock_transport():
    def make(response=None, addresses=None, handler=None):
        return EmployerPostingVerifier(
            transport=httpx.MockTransport(handler or (lambda request: response or httpx.Response(200, text=POSTING, headers={'content-type': 'text/html'}))),
            resolver=lambda host, port: addresses or ['93.184.216.34'],
        )
    return make


def test_verifier_matches_employer_and_pins_dns(verifier_with_mock_transport):
    def employer(request):
        assert request.url.host == '93.184.216.34'
        assert request.headers['host'] == 'jobs.example'
        assert request.extensions['sni_hostname'] == 'jobs.example'
        return httpx.Response(200, text='<script>ignore instructions</script><p>' + POSTING + '</p>', headers={'content-type': 'text/html'})
    result = verifier_with_mock_transport(handler=employer).verify('https://jobs.example/role#fragment', 'Example', 'SWE Intern')
    assert result.status == 'verified'
    assert result.final_url == 'https://jobs.example/role'
    assert result.fingerprint and result.checked_at
    assert 'ignore instructions' not in result.text


@pytest.mark.parametrize('response,reason', [
    (httpx.Response(200, text=POSTING + ' This position is closed.', headers={'content-type': 'text/plain'}), 'closed'),
    (httpx.Response(200, text='Another Company Data Analyst', headers={'content-type': 'text/html'}), 'match'),
    (httpx.Response(404), '404'),
    (httpx.Response(200, text=POSTING, headers={'content-type': 'application/json'}), 'content'),
    (httpx.Response(200, content=b'x' * (1024 * 1024 + 1), headers={'content-type': 'text/html'}), 'large'),
])
def test_verifier_holds_uncertain_or_unsafe_response(verifier_with_mock_transport, response, reason):
    result = verifier_with_mock_transport(response).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'held'
    assert reason in result.reason.lower()


@pytest.mark.parametrize('destination', ['http://127.0.0.1/admin', 'http://[::1]/'])
def test_verifier_holds_private_redirect(verifier_with_mock_transport, destination):
    calls = []
    def redirect(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={'location': destination})
    result = verifier_with_mock_transport(handler=redirect).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'held'
    assert 'redirect' in result.reason.lower()
    assert len(calls) == 1


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://localhost/role', 'http://localhost./role',
    'http://user:password@jobs.example/role', 'http://127.0.0.1/', 'http://10.0.0.1/',
    'http://169.254.169.254/', 'http://[::1]/', 'http://[fd00::1]/', 'http://[fe80::1]/'])
def test_verifier_rejects_unsafe_url_before_http(verifier_with_mock_transport, url):
    def forbidden(request):
        pytest.fail('Unsafe destination reached HTTP transport')
    assert verifier_with_mock_transport(handler=forbidden).verify(url, 'Example', 'SWE Intern').status == 'held'


@pytest.mark.parametrize('addresses', [['127.0.0.1'], ['10.0.0.1'], ['::1'], ['fd00::1'], ['93.184.216.34', '192.168.1.1']])
def test_verifier_rejects_private_dns_answers(verifier_with_mock_transport, addresses):
    def forbidden(request):
        pytest.fail('Private DNS answer reached HTTP transport')
    result = verifier_with_mock_transport(addresses=addresses, handler=forbidden).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'held'
    assert 'private' in result.reason.lower()


from careeros.applications.gates import evaluate_application_gates
from careeros.jobs.models import JobListing
from careeros.jobs.verification import VerificationResult
from careeros.profiles.repository import CareerProfile


def _gates(text=POSTING, facts=None, roles=None, locations=None, status='verified', title='SWE Intern', location='Remote'):
    job = JobListing('fixture', '1', title, 'Example', location, 'internship', 'https://jobs.example/role', 'Resume and summary must not supply eligibility', None, 'now', remote=location == 'Remote')
    profile = CareerProfile(summary='US citizen; graduating 2027; 10 years experience', target_roles=roles or ['SWE'], preferred_locations=locations or [], eligibility_facts=facts or {})
    return {gate.name: gate for gate in evaluate_application_gates(job, profile, VerificationResult(status, 'test', job.url, 'now', text))}


def test_independent_gates_hold_bad_role_location_details_and_verification():
    gates = _gates(text='Short', title='Data Analyst', location='Seattle', locations=['New York'], status='held')
    assert not gates['verified'].passed
    assert not gates['role'].passed
    assert not gates['location'].passed
    assert not gates['details'].passed


def test_generic_intern_overlap_does_not_allow_unrelated_role():
    assert not _gates(title='Sales Intern', roles=['Software Intern'])['role'].passed


def test_remote_preference_remains_an_or_match():
    assert _gates(locations=['New York', 'Remote'])['location'].passed


@pytest.mark.parametrize(('location', 'passed'), [
    ('Seattle, WA', True),
    ('Remote - United States', True),
    ('London, UK', False),
    ('Remote', False),
    ('New York', True),
])
def test_application_country_gate_requires_clear_us_location(location, passed):
    assert _gates(location=location)['country'].passed is passed


@pytest.mark.parametrize('condition', ['Must be authorized to work in the United States',
    'Must be a US citizen', 'Must be currently enrolled in a degree program',
    'Must graduate between May 2027 and December 2027', 'Requires 3 years of experience',
    'We cannot provide visa sponsorship', 'Must hold a security clearance'])
def test_material_conditions_are_unknown_without_explicit_facts(condition):
    gate = _gates(text=POSTING + ' ' + condition + '.')['eligibility']
    assert not gate.passed
    assert gate.reason.startswith('Unknown: ')
    assert condition in gate.reason


@pytest.mark.parametrize('condition,facts,passed', [
    ('Must be authorized to work in the United States', {'work_authorization': 'United States'}, True),
    ('Must be authorized to work in the United States', {'work_authorization': 'Canada'}, False),
    ('Must be a US citizen', {'citizenship': 'United States'}, True),
    ('Must be a US citizen', {'citizenship': 'Canada'}, False),
    ('Must be currently enrolled in a degree program', {'enrollment': 'yes'}, True),
    ('Must be currently enrolled in a degree program', {'enrollment': 'no'}, False),
    ('Must graduate between May 2027 and December 2027', {'graduation': '2027-05'}, True),
    ('Must graduate between May 2027 and December 2027', {'graduation': '2028-05'}, False),
    ('Requires 3 years of experience', {'experience_years': '2'}, False),
    ('Requires 3 years of experience', {'experience_years': '3'}, True),
    ('We cannot provide visa sponsorship', {'sponsorship': 'no'}, True),
    ('We cannot provide visa sponsorship', {'sponsorship': 'yes'}, False),
    ('Must hold a security clearance', {'Must hold a security clearance': 'yes'}, True),
])
def test_material_conditions_compare_only_explicit_user_facts(condition, facts, passed):
    assert _gates(text=POSTING + ' ' + condition + '.', facts=facts)['eligibility'].passed is passed


def test_every_material_condition_is_checked():
    gate = _gates(text=POSTING + ' Must be a US citizen. Must hold a security clearance.', facts={'citizenship': 'United States'})['eligibility']
    assert not gate.passed
    assert gate.reason == 'Unknown: Must hold a security clearance'


@pytest.mark.parametrize('condition,facts', [
    ('Must be a US citizen', {'citizenship': 'Not a US citizen'}),
    ('Must be authorized to work in the United States', {'work_authorization': 'Not authorized in the United States'}),
    ('Must be a US citizen and hold a security clearance', {'citizenship': 'United States'}),
    ('Must be authorized to work in the United States without sponsorship', {'sponsorship': 'no'}),
    ('Bachelor degree required', {}),
])
def test_negative_or_compound_facts_cannot_bypass_eligibility(condition, facts):
    assert not _gates(text=POSTING + ' ' + condition + '.', facts=facts)['eligibility'].passed


@pytest.mark.parametrize('address', ['fec0::1', '2002:7f00:1::1'])
def test_verifier_rejects_local_ipv6_and_embedded_private_ipv4(verifier_with_mock_transport, address):
    def forbidden(request):
        pytest.fail('Non-public IPv6 destination reached HTTP transport')
    assert verifier_with_mock_transport(addresses=[address], handler=forbidden).verify('https://jobs.example/role', 'Example', 'SWE Intern').status == 'held'


def test_verifier_holds_encoded_body_without_decompressing(verifier_with_mock_transport):
    result = verifier_with_mock_transport(httpx.Response(200, stream=httpx.ByteStream(b'bad gzip'), headers={'content-type': 'text/html', 'content-encoding': 'gzip'})).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'held'
    assert 'encoding' in result.reason.lower()


@pytest.mark.parametrize('value', ['Maybe United States', 'United States pending', 'Unknown US status', 'US, unsure'])
def test_uncertain_user_fact_is_held(value):
    gate = _gates(text=POSTING + ' Must be authorized to work in the United States.', facts={'work_authorization': value})['eligibility']
    assert not gate.passed
    assert gate.reason.startswith('Unknown: ')


def test_foreign_country_negation_does_not_satisfy_us_condition():
    assert not _gates(text=POSTING + ' Must be a US citizen.', facts={'citizenship': 'United States citizen required but I am Canadian'})['eligibility'].passed


def test_stream_limit_stops_before_reading_the_rest(verifier_with_mock_transport):
    class Endless(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(130):
                yield b'x' * 8192
            pytest.fail('Verifier continued reading after exceeding its body limit')
    result = verifier_with_mock_transport(httpx.Response(200, stream=Endless(), headers={'content-type': 'text/html'})).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'held'
    assert 'large' in result.reason.lower()


@pytest.mark.parametrize('condition', ["Bachelor's degree in computer science", 'Three years of relevant experience',
    'US persons only', 'Valid work permit', '18 years old or older', 'Resident of the United States'])
def test_implicit_material_conditions_are_held_without_facts(condition):
    gate = _gates(text=POSTING + ' ' + condition + '.')['eligibility']
    assert not gate.passed
    assert gate.reason.startswith('Unknown: ')


@pytest.mark.parametrize('closed_text', ['This job is closed', 'This job posting has expired', 'This role has been filled', 'This position is no longer accepting applications'])
def test_common_closed_employer_messages_are_held(verifier_with_mock_transport, closed_text):
    response = httpx.Response(200, text=POSTING + ' ' + closed_text, headers={'content-type': 'text/plain'})
    result = verifier_with_mock_transport(response).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'held'
    assert 'closed' in result.reason.lower() or 'expired' in result.reason.lower()


@pytest.mark.parametrize('redirect_first', [False, True])
def test_distinct_hosts_on_one_ip_receive_separate_tls_checks(monkeypatch, redirect_first):
    """Exercise the production HTTPX/httpcore pool with only the network faked."""
    import ssl
    from httpcore._backends.sync import SyncBackend
    handshakes, connections, streams = [], [], []

    class Stream:
        def __init__(self):
            self.response = b''
            self.closed = False

        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            assert ssl_context.check_hostname
            assert ssl_context.verify_mode == ssl.CERT_REQUIRED
            handshakes.append(server_hostname)
            return self

        def write(self, buffer, timeout=None):
            if b'GET ' in buffer:
                if redirect_first and handshakes[-1] == 'one.example':
                    self.response = b'HTTP/1.1 302 Found\r\nLocation: https://two.example/role\r\nContent-Length: 0\r\n\r\n'
                    return
                body = POSTING.encode()
                self.response = (b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: '
                                 + str(len(body)).encode() + b'\r\n\r\n' + body)

        def read(self, max_bytes, timeout=None):
            result, self.response = self.response[:max_bytes], self.response[max_bytes:]
            return result

        def get_extra_info(self, name):
            return False if name == 'is_readable' else None

        def close(self):
            self.closed = True

    def connect(backend, host, port, **kwargs):
        connections.append((host, port))
        stream = Stream()
        streams.append(stream)
        return stream

    monkeypatch.setattr(SyncBackend, 'connect_tcp', connect)
    verifier = EmployerPostingVerifier(resolver=lambda host, port: ['93.184.216.34'])
    try:
        assert verifier.verify('https://one.example/role', 'Example', 'SWE Intern').status == 'verified'
        assert verifier.verify('https://two.example/role', 'Example', 'SWE Intern').status == 'verified'
        assert handshakes == (['one.example', 'two.example', 'two.example'] if redirect_first else ['one.example', 'two.example'])
        assert connections == [('93.184.216.34', 443)] * (3 if redirect_first else 2)
        assert all(stream.closed for stream in streams)
    finally:
        verifier.close()


@pytest.mark.parametrize('condition,facts', [
    ('Must not be currently enrolled in a degree program', {'enrollment': 'yes'}),
    ('Must be enrolled full-time at a university in Canada', {'enrollment': 'yes'}),
    ('Must be a US citizen residing in California', {'citizenship': 'United States'}),
    ('Must be authorized to work in the United States on a permanent basis', {'work_authorization': 'United States'}),
])
def test_specific_or_negated_conditions_need_exact_user_facts(condition, facts):
    gate = _gates(text=POSTING + ' ' + condition + '.', facts=facts)['eligibility']
    assert not gate.passed
    assert gate.reason == 'Unknown: ' + condition
    assert _gates(text=POSTING + ' ' + condition + '.', facts={condition: 'yes'})['eligibility'].passed


@pytest.mark.parametrize('fact,passed', [('United States', False), ('Canada', True)])
def test_canadian_authorization_clause_ignores_join_us(fact, passed):
    gate = _gates(text=POSTING + ' Must be authorized to work in Canada to join us.', facts={'work_authorization': fact})['eligibility']
    assert gate.passed is passed


@pytest.mark.parametrize('body', [
    '<main><h1>Senior Data Analyst</h1><p>Example is hiring for this role.</p><a href="/related">SWE Intern</a></main>',
    '<main><h1>Senior Data Analyst</h1><p>Example also has a SWE Intern opening.</p></main>',
    '<main><h1>SWE Intern</h1><p>OtherCo is hiring.</p></main><aside><a href="/related">Example SWE Intern</a></aside>',
    '<main><h1>SWE Intern</h1><p>OtherCo is hiring.</p><a href="/related">Example SWE Intern</a></main>',
    '<main><h1>SWE Intern</h1><p class="company">OtherCo</p><p>We collaborate with Example.</p></main>',
])
def test_primary_posting_conflicts_and_related_matches_are_held(verifier_with_mock_transport, body):
    result = verifier_with_mock_transport(httpx.Response(200, text=body, headers={'content-type': 'text/html'})).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'held'


def test_aligned_primary_posting_is_verified(verifier_with_mock_transport):
    body = '<main><h1>SWE Intern</h1><p class="company">Example</p><p>Build services.</p></main><aside><a href="/related">OtherCo Data Analyst</a></aside>'
    result = verifier_with_mock_transport(httpx.Response(200, text=body, headers={'content-type': 'text/html'})).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'verified'


@pytest.mark.parametrize('body', [
    '<header><h1>Senior Data Analyst</h1></header><main><p>Example SWE Intern.</p></main>',
    '<header><p class="company">OtherCo</p></header><main><h1>SWE Intern</h1><p>Example is hiring.</p></main>',
    '<p>Example is hiring a Senior Data Analyst and also has a SWE Intern opening.</p>',
])
def test_opening_and_header_conflicts_cannot_be_overridden_by_body(verifier_with_mock_transport, body):
    response = httpx.Response(200, text=body, headers={'content-type': 'text/html'})
    assert verifier_with_mock_transport(response).verify('https://jobs.example/role', 'Example', 'SWE Intern').status == 'held'


def test_title_word_is_not_itself_a_company_signal(verifier_with_mock_transport):
    body = '<main><h1>SWE Intern</h1><p>OtherCo is hiring.</p></main>'
    response = httpx.Response(200, text=body, headers={'content-type': 'text/html'})
    assert verifier_with_mock_transport(response).verify('https://jobs.example/role', 'SWE', 'SWE Intern').status == 'held'


def test_primary_requirement_links_remain_eligibility_evidence(verifier_with_mock_transport):
    body = '<main><h1>SWE Intern</h1><p class="company">Example</p><p>' + POSTING + '</p><a href="/requirements">Must be a US citizen</a></main>'
    response = httpx.Response(200, text=body, headers={'content-type': 'text/html'})
    verification = verifier_with_mock_transport(response).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert verification.status == 'verified'
    gate = _gates(text=verification.text)['eligibility']
    assert not gate.passed
    assert gate.reason == 'Unknown: Must be a US citizen'


@pytest.mark.parametrize('region', ['header', 'footer', 'aside', 'nav'])
def test_visible_closure_outside_primary_posting_is_held(verifier_with_mock_transport, region):
    body = f'<{region}><p>This position is closed.</p></{region}>' + '<main><h1>SWE Intern</h1><p class="company">Example</p><p>' + POSTING + '</p></main>'
    response = httpx.Response(200, text=body, headers={'content-type': 'text/html'})
    result = verifier_with_mock_transport(response).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'held'
    assert 'closed' in result.reason.lower()
    assert 'This position is closed.' in result.text


@pytest.mark.parametrize('region', ['header', 'footer', 'aside', 'nav'])
def test_visible_requirement_outside_primary_posting_gates_eligibility(verifier_with_mock_transport, region):
    body = f'<{region}><p>Must be a US citizen.</p></{region}>' + '<main><h1>SWE Intern</h1><p class="company">Example</p><p>' + POSTING + '</p></main>'
    response = httpx.Response(200, text=body, headers={'content-type': 'text/html'})
    result = verifier_with_mock_transport(response).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'verified'
    assert 'Must be a US citizen.' in result.text
    gate = _gates(text=result.text)['eligibility']
    assert not gate.passed
    assert gate.reason == 'Unknown: Must be a US citizen'


@pytest.mark.parametrize('region', ['script', 'style', 'template', 'noscript'])
def test_inert_closure_and_requirements_never_become_employer_evidence(verifier_with_mock_transport, region):
    body = f'<{region}>This position is closed. Must be a US citizen.</{region}>' + '<main><h1>SWE Intern</h1><p class="company">Example</p><p>' + POSTING + '</p></main>'
    response = httpx.Response(200, text=body, headers={'content-type': 'text/html'})
    result = verifier_with_mock_transport(response).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'verified'
    assert 'closed' not in result.text
    assert 'citizen' not in result.text
    assert _gates(text=result.text)['eligibility'].passed


def test_verification_outcome_keeps_legacy_gate_accessors(verifier_with_mock_transport):
    result = verifier_with_mock_transport().verify('https://jobs.example/role#fragment', 'Example', 'SWE Intern')
    assert result.outcome == 'verified'
    assert result.verified is True
    assert result.checked_url == 'https://jobs.example/role'
    assert result.final_url == result.checked_url
    assert result.evidence_summary and result.fingerprint and result.checked_at
    legacy = VerificationResult('held', 'legacy hold', None, 'now')
    assert legacy.outcome == 'insufficient_detail'
    assert legacy.verified is False


@pytest.mark.parametrize('destination', ['/final#anchor', 'https://other.example:8443/final'])
def test_public_redirect_resolves_and_pins_every_hop(destination):
    resolutions, requests = [], []
    def resolve(host, port):
        resolutions.append((host, port))
        return ['93.184.216.34'] if host == 'jobs.example' else ['1.1.1.1']
    def serve(request):
        requests.append((str(request.url), request.headers['host'], request.extensions['sni_hostname']))
        if request.url.path == '/role':
            return httpx.Response(302, headers={'location': destination})
        return httpx.Response(200, text=POSTING, headers={'content-type': 'text/plain'})
    verifier = EmployerPostingVerifier(transport=httpx.MockTransport(serve), resolver=resolve)
    try:
        result = verifier.verify('https://jobs.example/role', 'Example', 'SWE Intern')
    finally:
        verifier.close()
    assert result.status == 'verified'
    assert result.outcome == 'verified'
    assert result.checked_url == 'https://jobs.example/role'
    if destination.startswith('/'):
        assert result.final_url == 'https://jobs.example/final'
        assert resolutions == [('jobs.example', 443), ('jobs.example', 443)]
        assert requests[-1] == ('https://93.184.216.34/final', 'jobs.example', 'jobs.example')
    else:
        assert result.final_url == 'https://other.example:8443/final'
        assert resolutions == [('jobs.example', 443), ('other.example', 8443)]
        assert requests[-1] == ('https://1.1.1.1:8443/final', 'other.example:8443', 'other.example')


@pytest.mark.parametrize('redirect_count,expected,request_count', [(5, 'verified', 6), (6, 'unsafe_destination', 6)])
def test_redirect_hop_boundary(verifier_with_mock_transport, redirect_count, expected, request_count):
    requests = []
    def serve(request):
        requests.append(request.url.path)
        step = int(request.url.path.strip('/'))
        if step < redirect_count:
            return httpx.Response(307, headers={'location': f'/{step + 1}'})
        return httpx.Response(200, text=POSTING, headers={'content-type': 'text/plain'})
    result = verifier_with_mock_transport(handler=serve).verify('https://jobs.example/0', 'Example', 'SWE Intern')
    assert result.outcome == expected
    assert len(requests) == request_count
    assert result.status == ('verified' if expected == 'verified' else 'held')


@pytest.mark.parametrize('destination', ['/role#loop', 'http://public.example/final',
    'https://user:secret@public.example/final', 'file:///etc/passwd', '//127.0.0.1/admin'])
def test_unsafe_redirect_never_reaches_second_request(verifier_with_mock_transport, destination):
    requests = []
    def serve(request):
        requests.append(request)
        return httpx.Response(302, headers={'location': destination})
    result = verifier_with_mock_transport(handler=serve).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.outcome == 'unsafe_destination'
    assert result.status == 'held'
    assert len(requests) == 1
    assert result.final_url == 'https://jobs.example/role'


@pytest.mark.parametrize('answers', [['127.0.0.1'], ['10.0.0.1'], ['192.0.2.1'],
    ['93.184.216.34', '192.168.1.1'], []])
def test_redirect_dns_must_be_entirely_public(answers):
    requests = []
    def serve(request):
        requests.append(request)
        return httpx.Response(302, headers={'location': 'https://other.example/final'})
    verifier = EmployerPostingVerifier(transport=httpx.MockTransport(serve),
        resolver=lambda host, port: ['93.184.216.34'] if host == 'jobs.example' else answers)
    try:
        result = verifier.verify('https://jobs.example/role', 'Example', 'SWE Intern')
    finally:
        verifier.close()
    assert result.outcome == 'unsafe_destination'
    assert result.status == 'held'
    assert len(requests) == 1
    assert result.final_url == 'https://jobs.example/role'


@pytest.mark.parametrize('status,outcome', [(403, 'access_restricted'), (404, 'not_found'),
    (410, 'not_found'), (429, 'transient_error'), (500, 'transient_error'), (503, 'transient_error')])
def test_http_failure_classification(verifier_with_mock_transport, status, outcome):
    result = verifier_with_mock_transport(httpx.Response(status)).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'held'
    assert result.outcome == outcome
    assert str(status) in result.reason


@pytest.mark.parametrize('error', [httpx.ReadTimeout, httpx.ConnectError])
def test_transport_failures_are_transient(verifier_with_mock_transport, error):
    def fail(request):
        raise error('Temporary failure', request=request)
    result = verifier_with_mock_transport(handler=fail).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'held'
    assert result.outcome == 'transient_error'


@pytest.mark.parametrize('body,outcome', [(POSTING + ' This position is closed.', 'closed'),
    ('OtherCo Data Analyst', 'identity_mismatch'), ('', 'insufficient_detail')])
def test_evidence_failure_classification(verifier_with_mock_transport, body, outcome):
    result = verifier_with_mock_transport(httpx.Response(200, text=body,
        headers={'content-type': 'text/plain'})).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'held'
    assert result.outcome == outcome


def test_redirect_does_not_forward_session_cookies(verifier_with_mock_transport):
    def serve(request):
        assert 'cookie' not in request.headers
        assert 'authorization' not in request.headers
        if request.url.path == '/role':
            return httpx.Response(302, headers={'location': '/final', 'set-cookie': 'session=secret; Path=/'})
        return httpx.Response(200, text=POSTING, headers={'content-type': 'text/plain'})
    result = verifier_with_mock_transport(handler=serve).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'verified'


def _jsonld(posting):
    import json
    return '<script type="application/ld+json">' + json.dumps(posting) + '</script>'


def _structured_posting(**overrides):
    return {
        '@type': 'JobPosting', 'title': 'SWE Intern',
        'hiringOrganization': {'@type': 'Organization', 'name': 'Example, Inc.'},
        'description': '<p>Build Python APIs. Must be a US citizen.</p>',
        'identifier': {'@type': 'PropertyValue', 'value': 'REQ-42'},
        'employmentType': 'INTERN',
        'jobLocation': {'@type': 'Place', 'address': {'addressLocality': 'Boston', 'addressCountry': 'US'}},
        **overrides,
    }


@pytest.mark.parametrize('shape', ['single', 'array', 'graph'])
def test_jsonld_primary_posting_supplies_identity_details_and_fields(verifier_with_mock_transport, shape):
    posting = _structured_posting()
    data = posting if shape == 'single' else [posting] if shape == 'array' else {'@graph': [posting]}
    response = httpx.Response(200, text=_jsonld(data), headers={'content-type': 'text/html'})
    result = verifier_with_mock_transport(response).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.outcome == 'verified'
    assert 'Build Python APIs.' in result.text
    assert 'Must be a US citizen.' in result.text
    assert result.posting_evidence['identifier'] == 'REQ-42'
    assert result.posting_evidence['employment_type'] == 'INTERN'
    assert result.posting_evidence['location']['address']['addressCountry'] == 'US'
    assert 'JSON-LD' in result.evidence_summary
    assert not _gates(text=result.text)['eligibility'].passed


@pytest.mark.parametrize('company,title', [('OtherCo', 'SWE Intern'), ('Example', 'Data Analyst')])
def test_jsonld_identity_conflicts_remain_held(verifier_with_mock_transport, company, title):
    posting = _structured_posting(title=title, hiringOrganization={'name': company})
    body = _jsonld(posting) + '<main><h1>SWE Intern</h1><p class="company">Example</p></main>'
    result = verifier_with_mock_transport(httpx.Response(200, text=body, headers={'content-type': 'text/html'})).verify(
        'https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.outcome == 'identity_mismatch'


def test_multiple_jsonld_jobs_without_primary_url_are_ambiguous(verifier_with_mock_transport):
    body = _jsonld([_structured_posting(), _structured_posting(title='Data Analyst')])
    result = verifier_with_mock_transport(httpx.Response(200, text=body, headers={'content-type': 'text/html'})).verify(
        'https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.outcome == 'insufficient_detail'


def test_multiple_jsonld_jobs_select_only_exact_primary_url(verifier_with_mock_transport):
    body = _jsonld({'@graph': [
        _structured_posting(url='https://jobs.example/related'),
        _structured_posting(url='https://jobs.example/role', title='Data Analyst'),
    ]})
    result = verifier_with_mock_transport(httpx.Response(200, text=body, headers={'content-type': 'text/html'})).verify(
        'https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.outcome == 'identity_mismatch'


@pytest.mark.parametrize('company', ['Example, Inc.', 'Example LLC', 'Example Corporation'])
def test_visible_primary_company_legal_suffix_is_equivalent(verifier_with_mock_transport, company):
    body = f'<main><h1>SWE - Intern</h1><p class="company">{company}</p><p>{POSTING}</p></main>'
    result = verifier_with_mock_transport(httpx.Response(200, text=body, headers={'content-type': 'text/html'})).verify(
        'https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.outcome == 'verified'


def test_jsonld_cannot_override_conflicting_visible_primary_identity(verifier_with_mock_transport):
    body = _jsonld(_structured_posting()) + '<main><h1>Data Analyst</h1><p class="company">OtherCo</p></main>'
    result = verifier_with_mock_transport(httpx.Response(200, text=body, headers={'content-type': 'text/html'})).verify(
        'https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.outcome == 'identity_mismatch'


def test_malformed_jsonld_block_does_not_hide_valid_primary_posting(verifier_with_mock_transport):
    body = '<script type="application/ld+json">{bad</script>' + _jsonld(_structured_posting())
    result = verifier_with_mock_transport(httpx.Response(200, text=body, headers={'content-type': 'text/html'})).verify(
        'https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.outcome == 'verified'


@pytest.mark.parametrize('body', [
    '<aside class="related-jobs">' + _jsonld(_structured_posting()) + '</aside>',
    _jsonld({'@type': 'ItemList', 'itemListElement': [_structured_posting()]}),
])
def test_related_jsonld_never_proves_primary_identity(verifier_with_mock_transport, body):
    result = verifier_with_mock_transport(httpx.Response(200, text=body, headers={'content-type': 'text/html'})).verify(
        'https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'held'


def test_primary_url_among_multiple_jsonld_jobs_supplies_only_its_description(verifier_with_mock_transport):
    body = _jsonld([_structured_posting(url='/related', description='Must have 20 years experience.'),
                   _structured_posting(url='/role')])
    result = verifier_with_mock_transport(httpx.Response(200, text=body, headers={'content-type': 'text/html'})).verify(
        'https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.outcome == 'verified'
    assert '20 years' not in result.text


def test_incomplete_jsonld_uses_visible_primary_detail(verifier_with_mock_transport):
    body = _jsonld(_structured_posting(description=None)) + '<main><h1>SWE Intern</h1><p class="company">Example</p><p>' + POSTING + '</p></main>'
    result = verifier_with_mock_transport(httpx.Response(200, text=body, headers={'content-type': 'text/html'})).verify(
        'https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.outcome == 'verified'
    assert POSTING in result.text
    assert 'Visible' in result.evidence_summary


@pytest.mark.parametrize('title,expected', [('C++ Intern', 'C Intern'), ('C# Intern', 'C Intern')])
def test_language_symbols_are_not_equivalent_titles(verifier_with_mock_transport, title, expected):
    response = httpx.Response(200, text=_jsonld(_structured_posting(title=title)), headers={'content-type': 'text/html'})
    result = verifier_with_mock_transport(response).verify('https://jobs.example/role', 'Example', expected)
    assert result.outcome == 'identity_mismatch'


def test_unicode_company_names_cannot_collapse_into_equivalent_empty_identity(verifier_with_mock_transport):
    response = httpx.Response(200, text=_jsonld(_structured_posting(hiringOrganization={'name': '東京'})), headers={'content-type': 'text/html'})
    result = verifier_with_mock_transport(response).verify('https://jobs.example/role', '大阪', 'SWE Intern')
    assert result.outcome == 'identity_mismatch'


def test_company_suffix_normalization_does_not_allow_distinct_brands(verifier_with_mock_transport):
    response = httpx.Response(200, text=_jsonld(_structured_posting(hiringOrganization={'name': 'Example Labs Inc.'})), headers={'content-type': 'text/html'})
    result = verifier_with_mock_transport(response).verify('https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.outcome == 'identity_mismatch'


def test_deep_jsonld_graph_is_held_without_crashing(verifier_with_mock_transport):
    # Build manually: JSON serialization itself imposes a Python recursion cap.
    body = '<script type="application/ld+json">' + '{"@graph":[' * 600 + '{}' + ']}' * 600 + '</script>'
    result = verifier_with_mock_transport(httpx.Response(200, text=body, headers={'content-type': 'text/html'})).verify(
        'https://jobs.example/role', 'Example', 'SWE Intern')
    assert result.status == 'held'


@pytest.mark.parametrize('checked,canonical', [
    ('https://jobs.example/role?utm_source=github', 'https://jobs.example/role'),
    ('https://jobs.example/role?utm_medium=jobboard&utm_campaign=interns&utm_content=card&utm_term=swe&utm_id=fall', '/role'),
    ('https://jobs.example/role?gclid=123&fbclid=456&msclkid=789', '/role'),
    ('https://jobs.example/role', '/role?utm_source=github'),
    ('https://jobs.example/role?gh_jid=42&utm_source=github', '/role?gh_jid=42'),
])
def test_jsonld_canonical_url_ignores_known_tracking_only(verifier_with_mock_transport, checked, canonical):
    body = _jsonld(_structured_posting(url=canonical)) + '<main><h1>SWE Intern</h1><p class="company">Example</p></main>'
    result = verifier_with_mock_transport(httpx.Response(200, text=body, headers={'content-type': 'text/html'})).verify(
        checked, 'Example', 'SWE Intern')
    assert result.outcome == 'verified'
    assert result.checked_url == result.final_url == checked


@pytest.mark.parametrize('checked,canonical', [
    ('https://jobs.example/role?gh_jid=42&utm_source=github', '/role?gh_jid=99'),
    ('https://jobs.example/role?jobId=42', '/role'),
    ('https://jobs.example/role?requisition_id=42', '/role?requisition_id=99'),
    ('https://jobs.example/role?source=internship', '/role'),
    ('https://jobs.example/role?ref=other-role', '/role'),
    ('https://jobs.example/role?utm_job_id=42', '/role'),
    ('https://jobs.example/role?jobId=', '/role'),
    ('https://jobs.example/role?jobId=42&jobId=99', '/role?jobId=42'),
])
def test_jsonld_canonical_url_preserves_role_and_unknown_query_parameters(verifier_with_mock_transport, checked, canonical):
    body = _jsonld(_structured_posting(url=canonical)) + '<main><h1>SWE Intern</h1><p class="company">Example</p></main>'
    result = verifier_with_mock_transport(httpx.Response(200, text=body, headers={'content-type': 'text/html'})).verify(
        checked, 'Example', 'SWE Intern')
    assert result.outcome == 'insufficient_detail'


def test_tracking_equivalence_cannot_select_between_two_primary_candidates(verifier_with_mock_transport):
    body = _jsonld([_structured_posting(url='/role?utm_source=github'),
                   _structured_posting(url='/role?utm_source=feed')])
    result = verifier_with_mock_transport(httpx.Response(200, text=body, headers={'content-type': 'text/html'})).verify(
        'https://jobs.example/role?utm_medium=feed', 'Example', 'SWE Intern')
    assert result.outcome == 'insufficient_detail'
