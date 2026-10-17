import httpx

from careeros.planner.protocols import PlannerRequest, PlannerResult


class OpenAIPlanner:
    """Direct Responses API adapter with no SDK retry behavior."""

    def __init__(self, api_key: str, model: str = "gpt-6-luna", client: httpx.Client | None = None):
        self.api_key = api_key
        self.model = model
        self.client = client or httpx.Client(timeout=httpx.Timeout(90, connect=10), trust_env=False)

    def generate(self, request: PlannerRequest) -> PlannerResult:
        body = {"model": self.model, "instructions": request.instruction, "input": request.task, "max_output_tokens": 4000}
        if request.response_schema:
            body["text"] = {"format": {"type": "json_schema", "name": "careeros_response", "strict": True,
                                        "schema": request.response_schema}}
        response = self.client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": "Bearer " + self.api_key},
            json=body,
        )
        response.raise_for_status()
        data = response.json()
        text = data.get("output_text")
        if text is None:
            pieces = []
            for item in data.get("output", []):
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        pieces.append(part.get("text", ""))
            text = "\n".join(pieces)
        return PlannerResult(text=text or "")
