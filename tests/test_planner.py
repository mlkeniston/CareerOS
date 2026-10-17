import pytest
import json
import httpx

from careeros.planner.gateway import PlannerGateway, ProviderUnavailable, PaidUseConfirmationRequired
from careeros.planner.protocols import PlannerRequest, PlannerResult
from careeros.planner.openai import OpenAIPlanner
from careeros.planner.ollama import OllamaPlanner


class Spy:
    def __init__(self, result=None):
        self.calls = 0
        self.result = result or PlannerResult("ok")

    def generate(self, request):
        self.calls += 1
        return self.result


def test_explicit_provider_routing_has_no_fallback():
    local = Spy()
    cloud = Spy()
    gateway = PlannerGateway({"ollama": local, "openai": cloud}, openai_configured=True)
    gateway.generate("openai", PlannerRequest("unit", "make a plan"), cloud_confirmed=True)
    assert cloud.calls == 1
    assert local.calls == 0


def test_cloud_confirmation_is_checked_before_provider_call():
    cloud = Spy()
    gateway = PlannerGateway({"ollama": Spy(), "openai": cloud}, openai_configured=True)
    with pytest.raises(PaidUseConfirmationRequired):
        gateway.generate("openai", PlannerRequest("unit", "make a plan"), cloud_confirmed=False)
    assert cloud.calls == 0


def test_missing_cloud_key_does_not_call_provider():
    cloud = Spy()
    gateway = PlannerGateway({"ollama": Spy(), "openai": cloud}, openai_configured=False)
    with pytest.raises(ProviderUnavailable):
        gateway.authorize("openai", confirm_cloud=True)
    assert cloud.calls == 0


def test_openai_adapter_posts_only_after_invocation_to_requested_model():
    observed = []
    def handler(request):
        observed.append(request)
        return httpx.Response(200, json={"output_text": "hello"})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    planner = OpenAIPlanner("sk-test-only", client=client)
    result = planner.generate(PlannerRequest("unit task", "instructions"))
    assert result.text == "hello"
    assert len(observed) == 1
    assert str(observed[0].url) == "https://api.openai.com/v1/responses"
    body = json.loads(observed[0].content)
    assert body["model"] == "gpt-6-luna"
    assert body["max_output_tokens"] == 4000
    assert observed[0].headers["Authorization"] == "Bearer sk-test-only"
    client.close()


def test_openai_adapter_sends_requested_json_schema():
    observed = []
    schema = {"type": "object", "required": ["resume_text"]}
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: observed.append(request) or httpx.Response(200, json={"output_text": "{}"})
    ))

    OpenAIPlanner("sk-test-only", client=client).generate(
        PlannerRequest("prepare", "Return JSON.", response_schema=schema)
    )

    body = json.loads(observed[0].content)
    assert body["text"]["format"] == {
        "type": "json_schema", "name": "careeros_response", "strict": True, "schema": schema,
    }
    client.close()


def test_ollama_health_checks_tags_without_generating_text():
    observed = []

    def handler(request):
        observed.append(request)
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:1.5b"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    planner = OllamaPlanner("http://127.0.0.1:11434", "qwen2.5:1.5b")
    planner.client.close()
    planner.client = client

    assert planner.health() == "ready"
    assert len(observed) == 1
    assert observed[0].method == "GET"
    assert str(observed[0].url) == "http://127.0.0.1:11434/api/tags"
    client.close()


def test_ollama_health_reuses_a_recent_result():
    calls = []
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: calls.append(request) or httpx.Response(200, json={"models": [{"name": "qwen2.5:1.5b"}]})
    ))
    planner = OllamaPlanner("http://127.0.0.1:11434", "qwen2.5:1.5b")
    planner.client.close()
    planner.client = client

    assert planner.health() == "ready"
    assert planner.health() == "ready"
    assert len(calls) == 1
    client.close()


def test_ollama_generate_requests_json_output_for_structured_local_work():
    observed = []

    def handler(request):
        observed.append(request)
        return httpx.Response(200, json={"message": {"content": json.dumps({"ok": True})}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    planner = OllamaPlanner("http://127.0.0.1:11434", "qwen2.5:1.5b")
    planner.client.close()
    planner.client = client

    result = planner.generate(PlannerRequest("make a JSON object", "Return strict JSON."))

    body = json.loads(observed[0].content)
    assert body["format"] == "json"
    assert body["stream"] is False
    assert json.loads(result.text) == {"ok": True}
    client.close()


def test_ollama_generate_uses_requested_json_schema():
    observed = []
    schema = {"type": "object", "required": ["summary", "manifest", "files"]}

    def handler(request):
        observed.append(request)
        return httpx.Response(200, json={"message": {"content": "{}"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    planner = OllamaPlanner("http://127.0.0.1:11434", "qwen2.5:1.5b")
    planner.client.close()
    planner.client = client

    planner.generate(PlannerRequest("build a project", "Return a project bundle.", response_schema=schema))

    assert json.loads(observed[0].content)["format"] == schema
    client.close()


def test_ollama_health_distinguishes_missing_model_from_offline_server():
    missing_client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"models": []})))
    missing = OllamaPlanner("http://127.0.0.1:11434", "qwen2.5:1.5b")
    missing.client.close()
    missing.client = missing_client
    assert missing.health() == "model_missing"
    missing_client.close()

    def offline(request):
        raise httpx.ConnectError("offline", request=request)

    offline_client = httpx.Client(transport=httpx.MockTransport(offline))
    unavailable = OllamaPlanner("http://127.0.0.1:11434", "qwen2.5:1.5b")
    unavailable.client.close()
    unavailable.client = offline_client
    assert unavailable.health() == "offline"
    offline_client.close()
