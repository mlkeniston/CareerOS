import pytest

from careeros.jobs.location import classify_location
from careeros.jobs.models import JobListing, JobQuery
from careeros.jobs.repository import JobRepository
from careeros.jobs.sources import matches_query


@pytest.mark.parametrize("location", [
    "Seattle, WA",
    "New York, New York",
    "Remote - United States",
    "US Remote",
    "California, USA",
])
def test_classifies_confirmed_us_locations(location):
    assert classify_location(location) == "us"


@pytest.mark.parametrize("location", [
    "London, UK",
    "Toronto, Canada",
    "Remote - Germany",
])
def test_classifies_explicit_international_locations(location):
    assert classify_location(location) == "outside_us"


@pytest.mark.parametrize("location", ["", "Remote", "Springfield", "Anywhere"])
def test_holds_locations_without_clear_country_evidence(location):
    assert classify_location(location) == "unknown"


def test_source_refresh_us_filter_only_accepts_confirmed_us_locations():
    query = JobQuery(us_only=True)
    us = JobListing("fixture", "us", "Intern", "Acme", "Boston, MA", "internship", "https://jobs.example/us", "Build", None, "now")
    foreign = JobListing("fixture", "foreign", "Intern", "Acme", "London, UK", "internship", "https://jobs.example/foreign", "Build", None, "now")
    unknown = JobListing("fixture", "unknown", "Intern", "Acme", "Remote", "internship", "https://jobs.example/unknown", "Build", None, "now", True)

    assert matches_query(us, query)
    assert not matches_query(foreign, query)
    assert not matches_query(unknown, query)


def test_us_only_job_search_excludes_foreign_and_unknown_before_limit(db):
    repository = JobRepository(db)
    listings = [
        JobListing("fixture", "london", "Software Intern", "A London Co", "London, UK", "internship", "https://jobs.example/london", "Build APIs", None, "now"),
        JobListing("fixture", "remote", "Software Intern", "B Remote Co", "Remote", "internship", "https://jobs.example/remote", "Build APIs", None, "now", True),
        JobListing("fixture", "seattle", "Software Intern", "C Seattle Co", "Seattle, WA", "internship", "https://jobs.example/seattle", "Build APIs", None, "now"),
        JobListing("fixture", "boston", "Software Intern", "D Boston Co", "Boston, MA", "internship", "https://jobs.example/boston", "Build APIs", None, "now"),
    ]
    repository.upsert_many(listings)

    results = repository.search(JobQuery(us_only=True, limit=1))

    assert len(results) == 1
    assert results[0].external_id == "seattle"
