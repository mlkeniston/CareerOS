from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime

import httpx

from careeros.autopilot.matching import score_technology_role
from careeros.applications.gates import evaluate_application_gates, matches_preferred_location
from careeros.jobs.location import classify_location, is_us_location, UNKNOWN
from careeros.jobs.verification import EmployerPostingVerifier, VerificationResult
from careeros.jobs.sources import is_transient_source_error
from careeros.workflows.errors import RetryableTaskError
from careeros.workflows.repository import WorkflowRepository
from careeros.jobs.models import JobQuery
from careeros.jobs.repository import JobRepository
from careeros.profiles.repository import ProfileRepository, ResumeRepository
from careeros.queue import Task, now
from careeros.worker import TaskOutcome


_MARKET_SKILLS = (
    ("Python", ("python",)),
    ("SQL", ("sql", "postgresql", "mysql")),
    ("JavaScript", ("javascript", "node js")),
    ("TypeScript", ("typescript",)),
    ("React", ("react",)),
    ("FastAPI", ("fastapi",)),
    ("AWS", ("aws", "amazon web services")),
    ("Docker", ("docker",)),
    ("Kubernetes", ("kubernetes",)),
    ("Java", ("java",)),
)


class JobDiscoveryService:
    def __init__(
        self,
        repository: JobRepository,
        sources,
        applications=None,
        portfolios=None,
        profiles: ProfileRepository | None = None,
        resumes: ResumeRepository | None = None,
        outreach=None,
        verifier: EmployerPostingVerifier | None = None,
        project_ideas=None,
        project_engineering=None,
    ):
        self.repository = repository
        self.sources = list(sources)
        self.applications = applications
        self.portfolios = portfolios
        self.profiles = profiles
        self.resumes = resumes
        self.outreach = outreach
        self.verifier = verifier
        self.project_ideas = project_ideas
        self.project_engineering = project_engineering
        self.workflows = WorkflowRepository(repository.db)

    def handle_task(self, task: Task) -> TaskOutcome:
        if not self.sources:
            raise RuntimeError("No public job sources are configured. Configure a source and retry discovery.")
        jobs_found = 0
        warnings = []
        successful_sources = 0
        failed_sources = 0
        transient_failures = 0
        for source in self.sources:
            name = _clean(getattr(source, "name", "job source"), 48)
            try:
                result = source.fetch(JobQuery(limit=500))
                jobs_found += self.repository.upsert_many(result.jobs)
                successful_sources += 1
                warnings.extend(f"{name}: {_clean(warning, 120)}" for warning in result.warnings)
            except Exception as exc:
                failed_sources += 1
                transient_failures += int(is_transient_source_error(exc))
                warnings.append(f"{name}: feed unavailable or malformed")

        if successful_sources == 0:
            if transient_failures == len(self.sources):
                raise RetryableTaskError("All configured job sources failed temporarily. Cached jobs remain available.")
            raise RuntimeError("All configured job sources failed; check network access. Cached jobs remain available.")

        jobs_matched = sum(
            1 for job in self.repository.recent(limit=500)
            if is_us_location(job.location) and score_technology_role(job)[0] >= 70
        )
        locations_held = sum(
            1 for job in self.repository.recent(limit=500)
            if classify_location(job.location) == UNKNOWN
        )
        applications_queued = self._queue_application()
        outreach_queued = self._queue_outreach()
        portfolio_queued = self._queue_portfolio()
        recent_jobs = self.repository.recent(limit=500)
        verifications = self.repository.verifications([job.id for job in recent_jobs if job.id])
        verification_counts = Counter(record['outcome'] for record in verifications.values())
        transient_retries = sum(
            1 for record in verifications.values()
            if record['outcome'] == 'transient_error' and record['attempts'] < 3 and record['next_retry_at']
        )
        result = {
            "jobs_found": jobs_found,
            "jobs_matched": jobs_matched,
            "locations_held": locations_held,
            "application_queued": applications_queued > 0,
            "applications_queued": applications_queued,
            "outreach_queued": outreach_queued,
            "portfolio_queued": portfolio_queued,
            "successful_sources": successful_sources,
            "failed_sources": failed_sources,
            "source_warnings": warnings[:10],
            "verification_counts": dict(sorted(verification_counts.items())),
            "transient_retries": transient_retries,
        }
        return TaskOutcome("completed", result)

    def _queue_application(self) -> int:
        if not all((self.applications, self.profiles, self.resumes, self.verifier)):
            return 0
        profile = self.profiles.get()
        resume = self.resumes.most_recent()
        roles = [role.strip() for role in (profile.target_roles or []) if isinstance(role, str) and role.strip()]
        if resume is None or not roles:
            return 0
        locations = [location.strip() for location in (profile.preferred_locations or []) if isinstance(location, str) and location.strip()]
        candidates = []
        for job in self.repository.recent(limit=500):
            if not is_us_location(job.location):
                continue
            technology_score, _ = score_technology_role(job)
            if technology_score < 70 or not _matches_preferred_location(job, locations):
                continue
            relevance = max((_role_overlap(job.title, role) for role in roles), default=0)
            if relevance:
                candidates.append((technology_score, relevance, job.published_at or "", job.title.casefold(), job))
        candidates.sort(key=lambda item: item[:4], reverse=True)
        queued = 0
        seen = set()
        for candidate in candidates[:50]:
            job = candidate[4]
            previous = self.repository.get_verification(job.id)
            if previous and previous['status'] == 'held' and not _retry_due(previous):
                verification = VerificationResult(**{key: previous[key] for key in (
                    'status', 'reason', 'final_url', 'checked_at', 'text', 'fingerprint', 'outcome',
                    'checked_url', 'evidence_summary', 'posting_evidence')})
            else:
                verification = self.check_job(job, automatic=True)
            gates = evaluate_application_gates(job, profile, verification)
            with self.repository.db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                for gate in gates:
                    conn.execute(
                        """INSERT INTO job_gate_results(job_id,name,passed,reason,checked_at) VALUES(?,?,?,?,?)
                           ON CONFLICT(job_id,name) DO UPDATE SET passed=excluded.passed,
                           reason=excluded.reason,checked_at=excluded.checked_at""",
                        (job.id, gate.name, int(gate.passed), gate.reason, verification.checked_at),
                    )
            if not all(gate.passed for gate in gates):
                continue
            identity = f"application:{verification.final_url}:{_normalize(job.company)}:{_normalize(job.title)}:{resume.id}"
            fingerprint = hashlib.sha256(identity.encode()).hexdigest()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            if queued < 10:
                # create_automatic claims the fingerprint and queues in one BEGIN IMMEDIATE transaction.
                created = self.applications.create_automatic(job.id, resume.id, fingerprint)
                queued += int(created is not None)
            # Recover a missing handoff after a crash between dispatch and event recording.
            with self.repository.db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                dispatch = conn.execute(
                    "SELECT d.task_id,a.job_id,a.resume_id FROM autopilot_dispatches d "
                    "JOIN applications a ON a.task_id=d.task_id WHERE d.fingerprint=? AND d.kind='application'",
                    (fingerprint,),
                ).fetchone()
                if dispatch:
                    self.workflows.record(
                        conn, idempotency_key=f"eligible:{fingerprint}:{dispatch['task_id']}",
                        task_id=dispatch['task_id'], object_type="job", object_id=dispatch["job_id"],
                        from_worker="job_discovery", to_worker="application", event_type="application_eligible",
                        payload={"job_id": dispatch["job_id"], "resume_id": dispatch["resume_id"], "gates_passed": True},
                    )
        return queued

    def check_job(self, job, *, automatic: bool = False) -> VerificationResult:
        """Check one public posting and store its deterministic gates, without drafting."""
        if not is_us_location(job.location):
            raise ValueError('Confirm a U.S. location before checking this employer posting')
        if self.verifier is None:
            raise RuntimeError('Employer verification is unavailable')
        try:
            verification = self.verifier.verify(job.employer_url or job.url, job.company, job.title)
        except (OSError, httpx.TransportError):
            verification = VerificationResult('held', 'Employer page has a temporary network or timeout error',
                                               None, now(), outcome='transient_error')
        except Exception:
            # An unexpected parser/check failure is local to this listing. Keep
            # it held for an explicit recheck rather than swallowing the batch.
            verification = VerificationResult('held', 'Employer check could not complete safely; recheck this posting',
                                               None, now(), outcome='insufficient_detail')
        gates = evaluate_application_gates(job, self.profiles.get(), verification)
        with self.repository.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            previous = conn.execute('SELECT attempts,status FROM job_verifications WHERE job_id=?', (job.id,)).fetchone()
            attempts = previous['attempts'] if previous else 0
            if automatic:
                attempts = min(3, (attempts if previous and previous['status'] == 'held' else 0) + 1) if verification.outcome != 'verified' else 0
            self.repository.save_verification(conn, job.id, verification, attempts=attempts)
            for gate in gates:
                conn.execute('''INSERT INTO job_gate_results(job_id,name,passed,reason,checked_at) VALUES(?,?,?,?,?)
                                ON CONFLICT(job_id,name) DO UPDATE SET passed=excluded.passed,
                                reason=excluded.reason,checked_at=excluded.checked_at''',
                             (job.id, gate.name, int(gate.passed), gate.reason, verification.checked_at))
        return verification

    def _queue_outreach(self) -> bool:
        if not all((self.outreach, self.profiles, self.resumes)):
            return False
        if self.outreach.model_status() != "ready":
            return False
        profile = self.profiles.get()
        roles = [role.strip() for role in (profile.target_roles or []) if isinstance(role, str) and role.strip()]
        locations = [location.strip() for location in (profile.preferred_locations or []) if isinstance(location, str) and location.strip()]
        resume = self.resumes.most_recent() if roles else None
        if not roles or resume is None:
            return False
        candidates = []
        for job in self.repository.recent(limit=500):
            if not is_us_location(job.location):
                continue
            technology_score, _ = score_technology_role(job)
            if technology_score < 70 or not _matches_preferred_location(job, locations):
                continue
            relevance = max((_role_overlap(job.title, role) for role in roles), default=0)
            if relevance:
                candidates.append((technology_score, relevance, job.published_at or "", job.title.casefold(), job))
        for candidate in sorted(candidates, key=lambda item: item[:4], reverse=True):
            job = candidate[4]
            fingerprint = hashlib.sha256(f"outreach:{job.id}:{resume.id}".encode()).hexdigest()
            if self.outreach.create_automatic(job.id, resume.id, fingerprint) is not None:
                return True
        return False

    def _queue_portfolio(self) -> bool:
        if self.project_ideas is None or self.project_engineering is None:
            return False
        jobs = [job for job in self.repository.recent(limit=500) if is_us_location(job.location)]
        counts = []
        for name, terms in _MARKET_SKILLS:
            normalized_terms = tuple(_normalize(term) for term in terms)
            count = sum(
                1 for job in jobs
                if _contains_any(_normalize(f"{job.title} {job.description}"), normalized_terms)
            )
            if count >= 3:
                counts.append((name, count, terms[0]))
        if not counts:
            return False
        counts.sort(key=lambda row: (-row[1], next(i for i, skill in enumerate(_MARKET_SKILLS) if skill[0] == row[0])))
        selected = counts[:3]
        skills = [row[0] for row in selected]
        selected_terms = [
            _normalize(term)
            for name, _count, _slug in selected
            for skill_name, terms in _MARKET_SKILLS
            if skill_name == name
            for term in terms
        ]
        evidence = []
        for job in jobs:
            if _contains_any(_normalize(f"{job.title} {job.description}"), tuple(selected_terms)):
                evidence.append(job)
                if len(evidence) == 3:
                    break
        signal = self.project_ideas.collect(skills, limit=20)
        result = self.project_engineering.create_from_ideas(signal.items, skills)
        return result is not None


def _clean(value: object, limit: int) -> str:
    return " ".join(str(value).replace("\x00", " ").split())[:limit]


def _retry_due(record: dict) -> bool:
    if record['outcome'] != 'transient_error' or record['attempts'] >= 3 or not record['next_retry_at']:
        return False
    try:
        return datetime.fromisoformat(record['next_retry_at']) <= datetime.fromisoformat(now())
    except (ValueError, TypeError):
        return False


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9+#]+", " ", value.casefold()).strip()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    padded = f" {text} "
    return any(f" {term} " in padded for term in terms)


def _role_overlap(title: str, role: str) -> int:
    normalized_title = _normalize(title)
    normalized_role = _normalize(role)
    if not normalized_title or not normalized_role:
        return 0
    if f" {normalized_role} " in f" {normalized_title} ":
        return 100 + len(normalized_role.split())
    title_terms = set(normalized_title.split())
    return len(title_terms.intersection(normalized_role.split()))


def _matches_preferred_location(job, preferred_locations: list[str]) -> bool:
    preferences = [_normalize(item) for item in preferred_locations if isinstance(item, str) and item.strip()]
    if not preferences:
        return True
    location = _normalize(job.location)
    remote = job.remote or "remote" in location.split()
    padded_location = f" {location} "
    for preference in preferences:
        if "remote" in preference.split():
            if remote:
                return True
        elif preference in padded_location:
            return True
    return False
