import httpx

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


class SourceUnavailableError(ValueError):
    """Keep aggregate failure causes without exposing them in user messages."""
    def __init__(self, message: str, failures: list[Exception]):
        super().__init__(message)
        self.failures = tuple(failures)


def is_transient_source_error(error: Exception) -> bool:
    if isinstance(error, SourceUnavailableError):
        return bool(error.failures) and all(is_transient_source_error(item) for item in error.failures)
    if isinstance(error, httpx.TimeoutException):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return 500 <= error.response.status_code < 600
    if error.__cause__ is not None:
        return is_transient_source_error(error.__cause__)
    return False
