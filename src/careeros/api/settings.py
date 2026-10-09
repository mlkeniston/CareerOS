from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from careeros.planner.gateway import ProviderUnavailable

router = APIRouter()


class SettingsInput(BaseModel):
    provider: str = Field(pattern="^(ollama|openai)$")


@router.get("/api/settings")
def get_settings(request: Request):
    settings = request.app.state.settings
    with request.app.state.db.connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='planner_provider'").fetchone()
    selected = row[0] if row else settings.planner_provider
    if selected == "openai" and not settings.openai_api_key:
        selected = "ollama"
    return {
        "provider": selected,
        "ollama": {"model": settings.ollama_model, "configured": True},
        "openai": {"model": "gpt-6-luna", "configured": bool(settings.openai_api_key), "standard_input_usd_per_million": 0.10, "standard_output_usd_per_million": 0.50, "rates_checked": date.today().isoformat(), "model_url": "https://developers.openai.com/api/docs/models/gpt-6-luna"},
    }


@router.put("/api/settings")
def update_settings(payload: SettingsInput, request: Request):
    if payload.provider == "openai" and not request.app.state.settings.openai_api_key:
        raise HTTPException(409, "Add OPENAI_API_KEY in the local .env file before selecting OpenAI")
    request.app.state.gateway.authorize(payload.provider, confirm_cloud=payload.provider == "openai")
    with request.app.state.db.connect() as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES('planner_provider',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (payload.provider,))
    return {"provider": payload.provider}
