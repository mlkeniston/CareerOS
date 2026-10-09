from __future__ import annotations

from careeros.autopilot.matching import score_technology_role
from careeros.jobs.models import JobQuery
from careeros.jobs.repository import JobRepository
from careeros.queue import Task
from careeros.worker import TaskOutcome


class JobDiscoveryService:
    def __init__(self, repository: JobRepository, sources):
        self.repository = repository
        self.sources = list(sources)

    def handle_task(self, task: Task) -> TaskOutcome:
        if not self.sources:
            raise RuntimeError("No public job sources are configured. Configure a source and retry discovery.")
        jobs_found = 0
        warnings = []
        successful_sources = 0
        failed_sources = 0
        for source in self.sources:
            name = _clean(getattr(source, "name", "job source"), 48)
            try:
                result = source.fetch(JobQuery(limit=500))
                jobs_found += self.repository.upsert_many(result.jobs)
                successful_sources += 1
                warnings.extend(f"{name}: {_clean(warning, 120)}" for warning in result.warnings)
            except Exception:
                failed_sources += 1
                warnings.append(f"{name}: feed unavailable or malformed")

        if successful_sources == 0:
            raise RuntimeError("All configured job sources failed; check network access. Cached jobs remain available.")

        jobs_matched = sum(
            1 for job in self.repository.recent(limit=500)
            if score_technology_role(job)[0] >= 70
        )
        result = {
            "jobs_found": jobs_found,
            "jobs_matched": jobs_matched,
            "successful_sources": successful_sources,
            "failed_sources": failed_sources,
            "source_warnings": warnings[:10],
        }
        return TaskOutcome("completed", result)


def _clean(value: object, limit: int) -> str:
    return " ".join(str(value).replace("\x00", " ").split())[:limit]
