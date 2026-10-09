from __future__ import annotations

from careeros.planner.protocols import Planner, PlannerRequest, PlannerResult


class PaidUseConfirmationRequired(ValueError):
    pass


class ProviderUnavailable(RuntimeError):
    pass


class PlannerGateway:
    def __init__(self, planners: dict[str, Planner], openai_configured: bool):
        self.planners = planners
        self.openai_configured = openai_configured

    def authorize(self, provider: str, confirm_cloud: bool = False) -> None:
        if provider not in {"ollama", "openai"}:
            raise ValueError("Choose Ollama or OpenAI")
        if provider == "openai":
            if not confirm_cloud:
                raise PaidUseConfirmationRequired("Confirm paid OpenAI use before creating this task")
            if not self.openai_configured or "openai" not in self.planners:
                raise ProviderUnavailable("OpenAI is unavailable. Add OPENAI_API_KEY to the local .env file.")
        elif "ollama" not in self.planners:
            raise ProviderUnavailable("Ollama is unavailable. Check that Ollama is running.")

    def generate(self, provider: str, request: PlannerRequest, cloud_confirmed: bool = False) -> PlannerResult:
        self.authorize(provider, confirm_cloud=cloud_confirmed)
        # Provider identity is fixed per task. Errors are returned to the user with no retry or fallback.
        return self.planners[provider].generate(request)
