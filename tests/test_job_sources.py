import httpx
import pytest

from careeros.jobs.arbeitnow import ArbeitnowSource
from careeros.jobs.boards import GreenhouseSource, LeverSource
from careeros.jobs.models import JobListing, JobQuery


def client_with_json(payload):
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))


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
