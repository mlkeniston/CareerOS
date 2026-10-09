import httpx

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
