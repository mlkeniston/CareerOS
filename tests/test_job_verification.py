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


@pytest.mark.parametrize('destination', ['http://127.0.0.1/admin', 'https://public.example/role', 'http://[::1]/'])
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


def test_distinct_hosts_on_one_ip_receive_separate_tls_checks(monkeypatch):
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
        assert handshakes == ['one.example', 'two.example']
        assert connections == [('93.184.216.34', 443), ('93.184.216.34', 443)]
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
