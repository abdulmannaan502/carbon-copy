"""Application configuration.

Settings are read from (highest precedence first):
  1. real environment variables
  2. backend/.env
  3. <repo root>/.env
  4. the defaults below
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

import re

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

_SQLITE_PREFIX = "sqlite:///"
_LOCAL_FRONTEND_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")

DEMO_DISCLAIMER = (
    "Carbon Copy is a demonstration prototype. It uses synthetic data only, "
    "makes no medical decisions and is not clinically validated."
)
DATA_NOTICE = "Synthetic demonstration data — not for clinical use."


TWILIO_SID_PATTERN = re.compile(r"AC[0-9a-fA-F]{32}")
E164_PATTERN = re.compile(r"\+[1-9]\d{7,14}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Later files take precedence, so backend/.env overrides the root .env.
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        # A validation error must never echo a setting's value: some settings are credentials.
        hide_input_in_errors=True,
    )

    app_name: str = "Carbon Copy API"
    service_id: str = "carbon-copy-api"
    version: str = "0.1.0"
    environment: Literal["development", "test", "demo"] = "development"
    api_prefix: str = "/api/v1"

    database_url: str = "sqlite:///./carbon_copy.db"
    sql_echo: bool = False

    frontend_url: str = "http://localhost:5173"

    # "dataset": evaluate time-relative metrics at the synthetic dataset's reference time.
    clock_mode: Literal["dataset", "system"] = "dataset"

    # Learning recommendations are advisory. When true, recommendations may also carry a bounded
    # adjustment proposal (still not applied to matching or recovery). Off by default.
    learning_adjustments_enabled: bool = False

    # ---- messaging ----------------------------------------------------------------------------------
    # DEMO (default): notifications are only recorded as SIMULATED; nothing is ever sent.
    # LIVE: enables the controlled, explicitly authorised test SMS through Twilio. Credentials live in the
    # backend environment only; they are never sent to the frontend, returned by the API or logged.
    messaging_mode: Literal["DEMO", "LIVE"] = "DEMO"
    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from_number: str | None = None  # E.164, e.g. +15551230000
    twilio_status_callback_url: str | None = None  # optional, https; delivery tracking is not implemented yet
    twilio_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    # Reserved for the future Claude integration. Never commit a real key.
    claude_api_key: SecretStr | None = None

    @field_validator("messaging_mode", mode="before")
    @classmethod
    def _normalise_mode(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) and value.strip() else "DEMO"

    @field_validator("twilio_account_sid", "twilio_from_number", "twilio_status_callback_url", "twilio_auth_token", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """`.env.example` ships empty placeholders; an empty value means "not configured"."""
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _live_mode_needs_valid_credentials(self) -> "Settings":
        """Fail at startup, naming only which settings are wrong, never their values."""
        problems: list[str] = []
        if self.twilio_status_callback_url and not self.twilio_status_callback_url.startswith("https://"):
            problems.append("TWILIO_STATUS_CALLBACK_URL (must be an https URL)")
        if self.messaging_mode == "LIVE":
            if not (self.twilio_account_sid and TWILIO_SID_PATTERN.fullmatch(self.twilio_account_sid)):
                problems.append("TWILIO_ACCOUNT_SID")
            if not (self.twilio_auth_token and self.twilio_auth_token.get_secret_value()):
                problems.append("TWILIO_AUTH_TOKEN")
            if not (self.twilio_from_number and E164_PATTERN.fullmatch(self.twilio_from_number)):
                problems.append("TWILIO_FROM_NUMBER (E.164, e.g. +15551230000)")
        if problems:
            raise ValueError(f"MESSAGING_MODE={self.messaging_mode} configuration is missing or invalid: {', '.join(problems)}")
        return self

    @field_validator("database_url")
    @classmethod
    def _anchor_relative_sqlite_path(cls, value: str) -> str:
        """Resolve relative SQLite paths against backend/ so the database
        location does not depend on the directory the server is started from."""
        if not value.startswith(_SQLITE_PREFIX):
            return value
        path = value.removeprefix(_SQLITE_PREFIX)
        if path in ("", ":memory:") or Path(path).is_absolute():
            return value
        return _SQLITE_PREFIX + (BACKEND_DIR / path).resolve().as_posix()

    @property
    def cors_origins(self) -> list[str]:
        return sorted({self.frontend_url.rstrip("/"), *_LOCAL_FRONTEND_ORIGINS})


@lru_cache
def get_settings() -> Settings:
    return Settings()
