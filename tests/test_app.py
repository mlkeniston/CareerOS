from careeros.config import Settings
from fastapi.testclient import TestClient
from careeros.main import create_app


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_default_settings_use_local_planner_and_loopback(tmp_path):
    settings = Settings(data_dir=tmp_path)
    assert settings.host == "127.0.0.1"
    assert settings.planner_provider == "ollama"
    assert settings.ollama_model == "qwen2.5:1.5b"


def test_board_ids_reject_path_and_query_injection(monkeypatch):
    monkeypatch.setenv("CAREEROS_GREENHOUSE_BOARDS", "acme,../escape,board?x=1, board_name")
    monkeypatch.setenv("CAREEROS_LEVER_SITES", "good-site,https://evil.example")
    settings = Settings.from_env()
    assert settings.greenhouse_boards == ("acme", "board_name")
    assert settings.lever_sites == ("good-site",)


def test_office_and_stations_are_served(client):
    page = client.get("/").text
    assert "CareerOS" in page
    assert 'id="office-map"' in page
    assert 'data-station="jobs"' in page
    assert 'data-station="resume"' in page
    assert 'data-station="portfolio"' in page


def test_autopilot_api_reports_schedule_and_persists_pause(client):
    initial = client.get("/api/autopilot")
    assert initial.status_code == 200
    assert initial.json()["enabled"] is True
    assert "last_discovery_queued_at" in initial.json()
    assert "next_discovery_at" in initial.json()

    paused = client.put("/api/autopilot", json={"enabled": False})
    assert paused.status_code == 200
    assert paused.json()["enabled"] is False
    assert client.get("/api/autopilot").json()["enabled"] is False


def test_openai_key_is_never_returned_by_settings(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, worker_enabled=False, openai_api_key="sk-local-test-secret"))
    with TestClient(app) as client:
        response = client.get("/api/settings")
        assert response.json()["openai"]["configured"] is True
        assert "sk-local-test-secret" not in response.text
