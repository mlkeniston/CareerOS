from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    data_dir: Path = Path("data")
    host: str = "127.0.0.1"
    port: int = 8000
    worker_enabled: bool = True
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:1.5b"
    outreach_model: str = "qwen3.5:2b-q4_K_M"
    planner_provider: str = "ollama"
    openai_api_key: str | None = None
    greenhouse_boards: tuple[str, ...] = ()
    lever_sites: tuple[str, ...] = ()
    sandbox_image: str = "careeros-sandbox:1"

    @classmethod
    def from_env(cls) -> "Settings":
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        host = os.getenv("CAREEROS_HOST", "127.0.0.1")
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("CareerOS binds to loopback only; use 127.0.0.1, localhost, or ::1")
        provider = os.getenv("CAREEROS_PLANNER_PROVIDER", "ollama").strip().lower()
        if provider not in {"ollama", "openai"}:
            raise ValueError("CAREEROS_PLANNER_PROVIDER must be ollama or openai")
        return cls(
            data_dir=Path(os.getenv("CAREEROS_DATA_DIR", "data")).expanduser(),
            host=host,
            port=int(os.getenv("CAREEROS_PORT", "8000")),
            worker_enabled=os.getenv("CAREEROS_WORKER_ENABLED", "true").lower() not in {"0", "false", "no"},
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b"),
            outreach_model=os.getenv("CAREEROS_OUTREACH_MODEL", "qwen3.5:2b-q4_K_M"),
            planner_provider=provider,
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            greenhouse_boards=_csv_ids(os.getenv("CAREEROS_GREENHOUSE_BOARDS", "")),
            lever_sites=_csv_ids(os.getenv("CAREEROS_LEVER_SITES", "")),
            sandbox_image=os.getenv("CAREEROS_SANDBOX_IMAGE", "careeros-sandbox:1"),
        )


def _csv_ids(value: str) -> tuple[str, ...]:
    ids = (part.strip() for part in value.split(","))
    return tuple(part for part in ids if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", part))[:30]
