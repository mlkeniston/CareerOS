import pytest
import json
import httpx

from careeros.planner.gateway import PlannerGateway, ProviderUnavailable, PaidUseConfirmationRequired
from careeros.planner.protocols import PlannerRequest, PlannerResult
from careeros.planner.openai import OpenAIPlanner


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
