import httpx
import pytest
import threading
import time

from careeros.jobs.arbeitnow import ArbeitnowSource
from careeros.jobs.boards import GreenhouseSource, LeverSource
from careeros.jobs.models import JobListing, JobQuery
from careeros.jobs.speedyapply import SpeedyApplySource


def client_with_json(payload):
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))


def test_speedyapply_extracts_company_position_location_and_application_url():
    row = '| <a href="https://acme.example"><strong>Acme</strong></a> | Backend Intern | Boston, MA | $40/hr | <a href="https://jobs.acme.example/1">Apply</a> | 2d |'
    jobs, warnings = SpeedyApplySource.parse_markdown(row, source_url="https://github.com/speedyapply/2027-SWE-College-Jobs")
    assert warnings == []
    assert jobs[0].company == "Acme"
    assert jobs[0].title == "Backend Intern"
    assert jobs[0].location == "Boston, MA"
    assert jobs[0].employer_url is None
    assert jobs[0].url == jobs[0].application_url == "https://jobs.acme.example/1"
    assert jobs[0].source_url.endswith("2027-SWE-College-Jobs")
    assert jobs[0].source_age == "2d"


def test_speedyapply_parses_escaped_pipes_and_location_count_without_using_salary_or_age_as_evidence():
    markdown = '''| Company | Position | Location | Salary | Apply | Age |
| --- | --- | --- | --- | --- | --- |
| <a href="https://example.test">A \\| B</a> | <a href="https://example.test/post">Software Intern</a> | New York, NY <br> +2 | $55/hr | <a href="https://jobs.example.test/apply">Apply</a> | 3d |
'''
    jobs, warnings = SpeedyApplySource.parse_markdown(markdown, source_url="https://github.com/speedyapply/2027-SWE-College-Jobs/blob/main/README.md")
    assert warnings == []
    assert len(jobs) == 1
    assert jobs[0].company == "A | B"
    assert jobs[0].title == "Software Intern"
    assert jobs[0].location == "New York, NY +2"
    assert jobs[0].description == ""
    assert jobs[0].published_at is None
    assert jobs[0].source_age == "3d"
    assert jobs[0].employer_url is None
    assert jobs[0].application_url == "https://jobs.example.test/apply"


def test_speedyapply_parses_current_five_column_posting_table():
    markdown = """| Company | Position | Location | Posting | Age |
| --- | --- | --- | --- | --- |
| <a href="https://acme.example"><strong>Acme</strong></a> | Software Intern | Boston, MA | <a href="https://jobs.acme.example/123"><img alt="Apply"/></a> | 2d |
"""

    jobs, warnings = SpeedyApplySource.parse_markdown(markdown, "https://github.com/speedyapply/2027-SWE-College-Jobs/blob/main/README.md")

    assert warnings == []
    assert len(jobs) == 1
    assert jobs[0].company == "Acme"
    assert jobs[0].title == "Software Intern"
    assert jobs[0].location == "Boston, MA"
    assert jobs[0].employer_url is None
    assert jobs[0].application_url == "https://jobs.acme.example/123"
    assert jobs[0].source_age == "2d"


def test_speedyapply_skips_missing_and_unsafe_application_links_with_bounded_warnings():
    bad = '| Acme | Software Intern | Remote | $40/hr | <a href="javascript:alert(1)">Apply</a> | 1d |'
    empty = '| Acme | Software Intern | Remote | $40/hr | Apply | 1d |'
    malformed = '| Acme | Software Intern | Remote | $40/hr | Apply |'
    jobs, warnings = SpeedyApplySource.parse_markdown("\n".join([bad, empty, malformed] * 50), source_url="https://github.com/speedyapply/2027-SWE-College-Jobs")
    assert jobs == []
    assert 1 <= len(warnings) <= 5


def test_speedyapply_fetches_four_files_filters_and_keeps_partial_results():
    files = {"README.md", "NEW_GRAD_USA.md", "INTERN_INTL.md", "NEW_GRAD_INTL.md"}
    row = '| Acme | Software Intern | Remote | $40/hr | <a href="https://jobs.example.test/1">Apply</a> | 1d |'
    requests = []

    def respond(request):
        requests.append(str(request.url))
        name = request.url.path.rsplit("/", 1)[-1]
        if name == "INTERN_INTL.md":
            return httpx.Response(503)
        return httpx.Response(200, text=row)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    source = SpeedyApplySource(client)
    result = source.fetch(JobQuery(text="software intern", remote_only=True))
    assert len(requests) == 4
    assert {url.rsplit("/", 1)[-1] for url in requests} == files
    assert len(result.jobs) == 1
    assert result.jobs[0].source_url == "https://github.com/speedyapply/2027-SWE-College-Jobs/blob/main/README.md"
    assert result.warnings
    assert not source.fetch(JobQuery(text="accountant")).jobs


def test_speedyapply_raises_when_every_file_fails():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    with pytest.raises(ValueError, match="SpeedyApply"):
        SpeedyApplySource(client).fetch(JobQuery())


def test_speedyapply_limit_applies_across_files():
    def respond(request):
        filename = request.url.path.rsplit("/", 1)[-1]
        row = f'| Acme | Software Intern | Remote | $40/hr | <a href="https://jobs.example.test/{filename}">Apply</a> | 1d |'
        return httpx.Response(200, text=row)

    source = SpeedyApplySource(httpx.Client(transport=httpx.MockTransport(respond)))

    result = source.fetch(JobQuery(limit=1))

    assert len(result.jobs) == 1
    assert result.jobs[0].employer_url is None
    assert result.jobs[0].application_url == "https://jobs.example.test/README.md"


@pytest.mark.parametrize("body", ["", "# Repository layout has changed\nNo table here.", "| Company | Position | Location | Apply |\n| --- | --- | --- | --- |"])
def test_speedyapply_rejects_successful_http_responses_without_expected_table(body):
    source = SpeedyApplySource(httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body))))

    with pytest.raises(ValueError, match="SpeedyApply"):
        source.fetch(JobQuery())


def test_speedyapply_reports_non_table_file_but_keeps_valid_file():
    row = '| Acme | Software Intern | Remote | $40/hr | <a href="https://jobs.example.test/1">Apply</a> | 1d |'

    def respond(request):
        body = row if request.url.path.endswith("README.md") else "# Changed format"
        return httpx.Response(200, text=body)

    source = SpeedyApplySource(httpx.Client(transport=httpx.MockTransport(respond)))

    result = source.fetch(JobQuery())

    assert len(result.jobs) == 1
    assert len(result.warnings) == 3
    assert all("feed unavailable or malformed" in warning for warning in result.warnings)


def test_speedyapply_accepts_identifiable_empty_six_column_table():
    table = "| Company | Position | Location | Salary | Apply | Age |\n| --- | --- | --- | --- | --- | --- |"
    source = SpeedyApplySource(httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=table))))

    result = source.fetch(JobQuery())

    assert result.jobs == []
    assert result.warnings == []


def test_speedyapply_accepts_identifiable_empty_current_five_column_table():
    table = "| Company | Position | Location | Posting | Age |\n| --- | --- | --- | --- | --- |"
    source = SpeedyApplySource(httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=table))))

    result = source.fetch(JobQuery())

    assert result.jobs == []
    assert result.warnings == []


def test_listing_rejects_missing_title_and_unsafe_url():
    with pytest.raises(ValueError):
        JobListing("test", "1", "", "Acme", "Remote", "internship", "javascript:alert(1)", "", None, "2026-10-09")


def test_query_limits_are_bounded():
    with pytest.raises(ValueError):
        JobQuery(limit=10001)


def test_arbeitnow_normalizes_and_filters_fixture(arbeitnow_fixture):
    result = ArbeitnowSource(client=client_with_json(arbeitnow_fixture)).fetch(JobQuery(text="software intern", kind="internship"))
    assert len(result.jobs) == 1
    assert result.jobs[0].source == "arbeitnow"


def test_greenhouse_and_lever_normalize( greenhouse_fixture, lever_fixture):
    gh = GreenhouseSource(client_with_json(greenhouse_fixture), ["acme"])
    lever = LeverSource(client_with_json(lever_fixture), ["acme"])
    assert gh.fetch(JobQuery()).jobs[0].source == "greenhouse:acme"
    assert lever.fetch(JobQuery()).jobs[0].source == "lever:acme"


def test_sources_reject_malformed_top_level_json():
    with pytest.raises(ValueError):
        ArbeitnowSource(client=client_with_json([])).fetch(JobQuery())
    with pytest.raises(ValueError):
        GreenhouseSource(client_with_json([]), ["acme"]).fetch(JobQuery())
    with pytest.raises(ValueError):
        GreenhouseSource(client_with_json({"jobs": {}}), ["acme"]).fetch(JobQuery())


def test_greenhouse_board_fetches_run_in_parallel_with_a_five_request_cap():
    class TrackingClient:
        def __init__(self):
            self.lock = threading.Lock()
            self.active = 0
            self.peak = 0

        def get(self, url, params=None):
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            try:
                time.sleep(0.02)
                return httpx.Response(200, json={"jobs": []}, request=httpx.Request("GET", url))
            finally:
                with self.lock:
                    self.active -= 1

    client = TrackingClient()
    result = GreenhouseSource(client, [f"board-{i}" for i in range(12)]).fetch(JobQuery())

    assert result.jobs == []
    assert client.peak > 1
    assert client.peak <= 5


def test_greenhouse_preserves_ats_source_identity_and_update_time(greenhouse_fixture):
    greenhouse_fixture['jobs'][0]['requisition_id'] = 'GH-REQ-11'
    job = GreenhouseSource(client_with_json(greenhouse_fixture), ['acme']).fetch(JobQuery()).jobs[0]
    assert job.url == job.employer_url == job.application_url == 'https://jobs.example/2'
    assert job.source_url == 'https://boards-api.greenhouse.io/v1/boards/acme/jobs/11'
    assert job.external_id == '11'
    assert job.requisition_id == 'GH-REQ-11'
    assert job.published_at == '2026-10-08'
    assert job.fetched_at != job.published_at


def test_lever_preserves_hosted_and_apply_urls_and_creation_time(lever_fixture):
    lever_fixture[0]['applyUrl'] = 'https://jobs.example/3/apply'
    lever_fixture[0]['requisitionId'] = 'LV-REQ-22'
    job = LeverSource(client_with_json(lever_fixture), ['acme']).fetch(JobQuery()).jobs[0]
    assert job.url == job.employer_url == 'https://jobs.example/3'
    assert job.application_url == 'https://jobs.example/3/apply'
    assert job.source_url == 'https://api.lever.co/v0/postings/acme/22'
    assert job.external_id == '22'
    assert job.requisition_id == 'LV-REQ-22'
    assert job.published_at == '2026-10-08T00:00:00+00:00'
    assert job.fetched_at != job.published_at


def test_arbeitnow_keeps_aggregator_provenance_without_inventing_destination(arbeitnow_fixture):
    job = ArbeitnowSource(client_with_json(arbeitnow_fixture), max_pages=1).fetch(JobQuery()).jobs[0]
    assert job.url == 'https://jobs.example/1'
    assert job.source_url == 'https://www.arbeitnow.com/api/job-board-api?page=1'
    assert job.employer_url is None
    assert job.application_url is None
    assert job.requisition_id is None
    assert job.published_at == '2026-10-09'


def test_arbeitnow_preserves_explicit_destination_fields(arbeitnow_fixture):
    arbeitnow_fixture['data'][0].update(employer_url='https://employer.example/role',
        application_url='https://employer.example/role/apply', requisition_id='AB-REQ-1')
    job = ArbeitnowSource(client_with_json(arbeitnow_fixture), max_pages=1).fetch(JobQuery()).jobs[0]
    assert job.employer_url == 'https://employer.example/role'
    assert job.application_url == 'https://employer.example/role/apply'
    assert job.requisition_id == 'AB-REQ-1'


def test_speedyapply_keeps_unvalidated_clickthrough_distinct_from_employer():
    row = '| Acme | Software Intern | Boston, MA | <a href="https://redirect.example/click?id=123">Apply</a> | 2d |'
    source = 'https://github.com/speedyapply/2027-SWE-College-Jobs/blob/main/README.md'
    first = SpeedyApplySource.parse_markdown(row, source)[0][0]
    second = SpeedyApplySource.parse_markdown(row, source)[0][0]
    assert first.url == first.application_url == 'https://redirect.example/click?id=123'
    assert first.employer_url is None
    assert first.source_url == source
    assert first.external_id == second.external_id
    assert first.requisition_id is None
    assert first.published_at is None
    assert first.fetched_at


def test_arbeitnow_normalizes_unix_source_publication_time(arbeitnow_fixture):
    arbeitnow_fixture['data'][0]['created_at'] = 1791417600
    job = ArbeitnowSource(client_with_json(arbeitnow_fixture), max_pages=1).fetch(JobQuery()).jobs[0]
    assert job.published_at == '2026-10-08T00:00:00+00:00'


def test_malformed_lever_timestamp_cannot_stop_valid_listings(lever_fixture):
    bad = {**lever_fixture[0], 'id': 'bad', 'createdAt': 10 ** 100}
    result = LeverSource(client_with_json([bad, *lever_fixture]), ['acme']).fetch(JobQuery())
    assert [job.external_id for job in result.jobs] == ['22']
    assert result.warnings
