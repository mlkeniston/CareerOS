from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import logging
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from careeros.api import applications, autopilot, health, jobs, outreach, portfolio, profiles, settings as settings_api, tasks, workflows, workspace
from careeros.applications.service import ApplicationService
from careeros.applications.hiring_manager import HiringManagerService
from careeros.autopilot.scheduler import AutopilotScheduler
from careeros.autopilot.state import AutopilotState
from careeros.autopilot.discovery import JobDiscoveryService
from careeros.config import Settings
from careeros.db import Database
from careeros.jobs.arbeitnow import ArbeitnowSource
from careeros.jobs.boards import GreenhouseSource, LeverSource
from careeros.jobs.repository import JobRepository
from careeros.jobs.verification import EmployerPostingVerifier
from careeros.jobs.speedyapply import SpeedyApplySource
from careeros.planner.gateway import PlannerGateway
from careeros.planner.ollama import OllamaPlanner
from careeros.planner.openai import OpenAIPlanner
from careeros.portfolio.ideas import ProjectIdeaRepository, ProjectIdeaService
from careeros.portfolio.engineering import ProjectEngineeringService
from careeros.portfolio.paths import PortfolioPaths
from careeros.portfolio.qa import ProjectQAService
from careeros.portfolio.sandbox import DockerSandboxRunner
from careeros.portfolio.sources import ArxivProjectSource, GitHubProjectSource, HackerNewsProjectSource
from careeros.portfolio.service import PortfolioService
from careeros.profiles.repository import ProfileRepository, ResumeRepository
from careeros.outreach.service import OutreachService
from careeros.queue import TaskQueue
from careeros.worker import Worker


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.data_dir = Path(settings.data_dir).expanduser().resolve()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.data_dir / "careeros.sqlite3")
    db.initialize()
    queue = TaskQueue(db)
    autopilot_state = AutopilotState(db)
    autopilot_scheduler = AutopilotScheduler(db, queue)
    job_repository = JobRepository(db)
    profile_repository = ProfileRepository(db)
    resume_repository = ResumeRepository(db)
    gateway = PlannerGateway(
        planners={
            "ollama": OllamaPlanner(settings.ollama_base_url, settings.ollama_model),
            **({"openai": OpenAIPlanner(settings.openai_api_key)} if settings.openai_api_key else {}),
        },
        openai_configured=bool(settings.openai_api_key),
    )
    outreach_planner = OllamaPlanner(settings.ollama_base_url, settings.outreach_model)
    application_service = ApplicationService(db, queue, gateway, job_repository, profile_repository, resume_repository)
    hiring_manager_service = HiringManagerService(db, queue, gateway, application_service)
    application_service.hiring_manager = hiring_manager_service
    outreach_service = OutreachService(db, queue, outreach_planner, job_repository, profile_repository, resume_repository)
    portfolio_paths = PortfolioPaths(settings.data_dir)
    portfolio_service = PortfolioService(db, queue, portfolio_paths)
    sandbox_runner = DockerSandboxRunner(settings.sandbox_image)
    project_qa_service = ProjectQAService(db, queue, gateway, portfolio_service, portfolio_paths, sandbox_runner)
    project_idea_repository = ProjectIdeaRepository(db)
    def tick_autopilot() -> None:
        try:
            autopilot_scheduler.maybe_enqueue_discovery()
        except Exception as exc:
            try:
                autopilot_state.record_error(str(exc))
            except Exception:
                logging.getLogger(__name__).exception("could not persist autopilot scheduler error")
            logging.getLogger(__name__).exception("autopilot scheduler tick failed")
        else:
            autopilot_state.clear_error()

    worker = Worker(queue)
    worker.register("hiring_manager", hiring_manager_service.review_task)
    worker.register("application", application_service.handle_task)
    worker.register("application_revision", application_service.handle_revision_task)
    worker.register("outreach", outreach_service.handle_task)
    worker.register("portfolio", portfolio_service.handle_task)
    worker.register("project_qa", project_qa_service.run_task)
    discovery_worker = Worker(queue, before_claim=tick_autopilot)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        queue.recover_after_restart()
        if settings.worker_enabled:
            worker.start()
            discovery_worker.start()
        yield
        worker.stop()
        discovery_worker.stop()
        feed_client.close()
        employer_verifier.close()
        for planner in gateway.planners.values():
            client = getattr(planner, "client", None)
            close = getattr(client, "close", None)
            if callable(close):
                close()
        client = getattr(outreach_planner, "client", None)
        close = getattr(client, "close", None)
        if callable(close):
            close()

    app = FastAPI(title="CareerOS", version="0.1.0", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.queue = queue
    app.state.autopilot_state = autopilot_state
    app.state.autopilot_scheduler = autopilot_scheduler
    app.state.gateway = gateway
    app.state.outreach_planner = outreach_planner
    app.state.worker = worker
    app.state.discovery_worker = discovery_worker
    app.state.job_repository = job_repository
    app.state.profile_repository = profile_repository
    app.state.resume_repository = resume_repository
    app.state.hiring_manager_service = hiring_manager_service
    app.state.application_service = application_service
    app.state.outreach_service = outreach_service
    app.state.portfolio_service = portfolio_service
    app.state.portfolio_paths = portfolio_paths
    app.state.sandbox_runner = sandbox_runner
    app.state.project_qa_service = project_qa_service
    app.state.project_idea_repository = project_idea_repository

    feed_client = httpx.Client(timeout=httpx.Timeout(15, connect=5), headers={"User-Agent": "CareerOS/0.1"}, trust_env=False)
    job_sources = [ArbeitnowSource(client=feed_client), SpeedyApplySource(client=feed_client)]
    if settings.greenhouse_boards:
        job_sources.append(GreenhouseSource(feed_client, list(settings.greenhouse_boards)))
    if settings.lever_sites:
        job_sources.append(LeverSource(feed_client, list(settings.lever_sites)))
    app.state.job_sources = job_sources
    project_idea_sources = [
        GitHubProjectSource(client=feed_client),
        HackerNewsProjectSource(client=feed_client),
        ArxivProjectSource(client=feed_client),
    ]
    app.state.project_idea_sources = project_idea_sources
    project_idea_service = ProjectIdeaService(project_idea_sources, project_idea_repository)
    app.state.project_idea_service = project_idea_service
    project_engineering_service = ProjectEngineeringService(db, queue, gateway, portfolio_paths, portfolio_service)
    project_engineering_service.qa = project_qa_service
    app.state.project_engineering_service = project_engineering_service
    worker.register("project_engineering", project_engineering_service.handle_task)
    worker.register("project_revision", project_engineering_service.handle_revision_task)
    for kind in ("project_engineering", "project_revision", "project_qa"):
        worker.register_failure_handler(kind, project_qa_service.hold_after_task_failure)
    employer_verifier = EmployerPostingVerifier()
    application_service.posting_verifier = employer_verifier
    job_discovery_service = JobDiscoveryService(
        job_repository,
        job_sources,
        application_service,
        portfolio_service,
        profile_repository,
        resume_repository,
        outreach_service,
        verifier=employer_verifier,
        project_ideas=project_idea_service,
        project_engineering=project_engineering_service,
    )
    app.state.job_discovery_service = job_discovery_service
    discovery_worker.register("job_discovery", job_discovery_service.handle_task)

    for router in (health.router, settings_api.router, tasks.router, jobs.router, profiles.router, applications.router, outreach.router, portfolio.router, autopilot.router, workspace.router, workflows.router):
        app.include_router(router)
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static_dir / "index.html")

    return app
