import httpx
from typing import Literal

from careeros.planner.protocols import PlannerRequest, PlannerResult


class OllamaPlanner:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.Client(timeout=httpx.Timeout(120, connect=5), trust_env=False)

    def generate(self, request: PlannerRequest) -> PlannerResult:
        response = self.client.post(self.base_url + "/api/chat", json={
            "model": self.model,
            "stream": False,
            "messages": [{"role": "system", "content": request.instruction}, {"role": "user", "content": "Return only the requested result for task: " + request.task}],
        })
        response.raise_for_status()
        data = response.json()
        return PlannerResult(text=data.get("message", {}).get("content", ""))

    def health(self) -> Literal["ready", "offline", "model_missing"]:
        try:
            response = self.client.get(
                self.base_url + "/api/tags",
                timeout=httpx.Timeout(2, connect=1),
            )
            response.raise_for_status()
            data = response.json()
            models = data.get("models") if isinstance(data, dict) else None
            if not isinstance(models, list):
                return "offline"
            names = {
                value
                for item in models if isinstance(item, dict)
                for value in (item.get("name"), item.get("model"))
                if isinstance(value, str)
            }
            expected = {self.model}
            if self.model.endswith(":latest"):
                expected.add(self.model[:-7])
            elif ":" not in self.model.rsplit("/", 1)[-1]:
                expected.add(self.model + ":latest")
            return "ready" if names.intersection(expected) else "model_missing"
        except (httpx.HTTPError, ValueError, TypeError):
            return "offline"
