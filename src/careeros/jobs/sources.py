from typing import Protocol

from careeros.jobs.models import JobQuery, SourceResult


class JobSource(Protocol):
    name: str
    def fetch(self, query: JobQuery) -> SourceResult: ...


def matches_query(job, query: JobQuery) -> bool:
    text = " ".join((job.title, job.company, job.location, job.description)).casefold()
    if query.text and not all(term in text for term in query.text.casefold().split()):
        return False
    if query.location and query.location.casefold() not in job.location.casefold():
        return False
    if query.kind and query.kind not in {job.kind, job.original_kind.lower()}:
        return False
    return not query.remote_only or job.remote
