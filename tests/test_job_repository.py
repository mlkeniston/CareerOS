from dataclasses import replace

from careeros.jobs.models import JobListing, JobQuery
from careeros.jobs.repository import JobRepository


def test_upsert_deduplicates_and_searches(db):
    repo = JobRepository(db)
    listing = JobListing("arbeitnow", "abc", "Software Intern", "Acme", "Remote", "internship", "https://jobs.example/abc", "Build APIs", None, "2026-10-09", True)
    repo.upsert_many([listing])
    repo.upsert_many([replace(listing, title="Updated Internship")])
    found = repo.search(JobQuery(text="Updated"))
    assert len(found) == 1
    assert found[0].title == "Updated Internship"


def test_search_fallback_treats_percent_as_text(db):
    repo = JobRepository(db, fts_enabled=False)
    listing = JobListing("manual", "x", "Intern 100%", "Acme", "NYC", "internship", "https://jobs.example/x", "", None, "2026-10-09")
    repo.upsert_many([listing])
    assert len(repo.search(JobQuery(text="100%"))) == 1


def test_fts_search_treats_punctuation_as_literal_text(db):
    repo = JobRepository(db, fts_enabled=True)
    listing = JobListing("manual", "punct", 'Intern 100% " OR *', "Acme", "NYC", "internship", "https://jobs.example/punct", "", None, "2026-10-09")
    repo.upsert_many([listing])
    assert len(repo.search(JobQuery(text='100% " OR *'))) == 1


def test_fts_search_matches_all_terms_in_any_order(db):
    repo = JobRepository(db, fts_enabled=True)
    listing = JobListing("manual", "multi", "Backend Engineer", "Acme", "NYC", "internship", "https://jobs.example/multi", "Student summer intern program", None, "2026-10-09")
    repo.upsert_many([listing])
    assert len(repo.search(JobQuery(text="intern backend"))) == 1
