"""Application settings loaded from environment / .env file."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[REPO_ROOT / ".env", BACKEND_ROOT / ".env"],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- LLM (triage agent only) ----------------------------------------
    # Any endpoint speaking the OpenAI protocol. Gemini in the live deploy.
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_chat_model: str = "gemini-3.5-flash-lite"
    # Tried once when the primary answers 429 or 5xx. Free-tier quotas are per
    # model, so a second Lite model is a genuine second chance.
    llm_fallback_model: str = ""
    llm_timeout_seconds: float = 30.0

    # ---- Data paths ------------------------------------------------------
    data_dir: Path = REPO_ROOT / "data"
    # The build writes the platform here; the app serves a working copy so a
    # reset is a file copy, not a rebuild.
    build_db_path: Path = REPO_ROOT / "data" / "tapeline.build.duckdb"
    duckdb_path: Path = REPO_ROOT / "data" / "tapeline.duckdb"
    contracts_dir: Path = REPO_ROOT / "contracts"

    # ---- Abuse controls ---------------------------------------------------
    triage_rate_limit_per_ip: int = 8
    triage_rate_limit_global: int = 60
    replay_rate_limit_per_ip: int = 30
    rate_limit_window_seconds: float = 300.0

    # Shared secret for write endpoints. Fail closed: empty refuses writes.
    demo_write_token: str = ""

    # Stamped into the image at build time; shown by /api/meta.
    git_sha: str = ""

    cors_origins: str = "http://localhost:5241"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
