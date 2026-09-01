"""Application configuration.

Every deployment-time value arrives through the environment and is validated
here at import time, so a misconfigured container fails immediately and loudly
rather than at the first request that happens to need the missing value.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, ValidationError, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- application ---------------------------------------------------------
    APP_NAME: str = "FleetGuard AI"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # --- database ------------------------------------------------------------
    # Either set DATABASE_URL directly, or set the MYSQL_* parts and let the
    # URL be assembled. MYSQL_PASSWORD is required because a silently-empty
    # password produces a confusing access-denied much later.
    DATABASE_URL: str | None = None
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = Field(..., description="MySQL password for MYSQL_USER")
    MYSQL_DB: str = "fleetguard"
    SQL_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 3600

    # --- auth (spec 3) -------------------------------------------------------
    # When false the X-Customer-Scope header drives access; when true the JWT
    # does. Route code is identical either way - only the dependency changes.
    AUTH_ENABLED: bool = False
    JWT_SECRET: str = Field(..., description="HMAC secret for signing JWTs")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 720
    # The password the seed script hashes for all three demo users, and the one
    # /api/auth/demo-accounts hands to the login screen. It is configuration
    # rather than a constant in the seed script so that the two can never drift
    # apart, and it is only ever served while AUTH_ENABLED is false.
    DEMO_PASSWORD: str = "fleetguard"

    # --- llm (spec 7) --------------------------------------------------------
    # An OpenAI-compatible client pointed at Groq. Swapping provider is a
    # matter of changing LLM_BASE_URL and LLM_MODEL - no code change.
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.groq.com/openai/v1"
    LLM_MODEL: str = "openai/gpt-oss-120b"
    LLM_TIMEOUT_SECONDS: float = 60.0
    AGENT_MAX_TOOL_ROUNDS: int = 6
    AGENT_MAX_TOKENS: int = 2500
    # Providers charge `max_tokens` against the per-minute token allowance when
    # the request is made, not when the tokens are used. A round that only has
    # to choose a tool needs a fraction of the answer budget, and asking for the
    # full amount on every round is what exhausts a small plan mid-question.
    AGENT_TOOL_ROUND_TOKENS: int = 1200
    # Honoured by reasoning models, ignored by others. Tool selection is not a
    # hard reasoning problem; composing the final answer sometimes is.
    AGENT_TOOL_ROUND_EFFORT: str = "low"
    AGENT_ANSWER_EFFORT: str = "medium"

    # --- http ----------------------------------------------------------------
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"
    CHAT_RATE_LIMIT: str = "20/minute"

    # --- logging -------------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # --- data generation -----------------------------------------------------
    SEED: int = 20240517

    # A variable that is present but blank is the same problem as a missing
    # one, and pydantic will not catch it on a plain str field.
    @field_validator("MYSQL_PASSWORD")
    @classmethod
    def _reject_blank_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "MYSQL_PASSWORD is set but empty. An empty password surfaces "
                "much later as a confusing access-denied."
            )
        return value

    @model_validator(mode="after")
    def _check_signing_secret(self) -> "Settings":
        """A weak signing secret makes every token forgeable.

        Only enforced when AUTH_ENABLED is true, because the demo runs with the
        scope header instead and has no tokens to forge. main.py warns at
        startup when the secret is blank so it cannot be forgotten quietly.
        """
        if self.AUTH_ENABLED and len(self.JWT_SECRET.strip()) < 32:
            raise ValueError(
                "AUTH_ENABLED is true but JWT_SECRET is blank or shorter than "
                "32 characters. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return self

    @computed_field
    @property
    def auth_secret_ready(self) -> bool:
        return len(self.JWT_SECRET.strip()) >= 32

    @computed_field
    @property
    def sqlalchemy_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{quote_plus(self.MYSQL_PASSWORD)}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}?charset=utf8mb4"
        )

    @computed_field
    @property
    def server_url(self) -> str:
        """Same server, no database selected - used to CREATE DATABASE."""
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{quote_plus(self.MYSQL_PASSWORD)}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/?charset=utf8mb4"
        )

    @computed_field
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @computed_field
    @property
    def llm_configured(self) -> bool:
        return bool(self.LLM_API_KEY)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        missing = [
            ".".join(str(p) for p in err["loc"])
            for err in exc.errors()
            if err["type"] == "missing"
        ]
        invalid = [
            f"  {'.'.join(str(p) for p in err['loc']) or 'config'}: {err['msg']}"
            for err in exc.errors()
            if err["type"] != "missing"
        ]
        lines = [
            "",
            "FleetGuard could not start: configuration is incomplete.",
            f"Expected an .env file at: {BACKEND_ROOT / '.env'}",
        ]
        if missing:
            lines.append("Missing required variables: " + ", ".join(missing))
        if invalid:
            lines.append("Invalid values:")
            lines.extend(invalid)
        lines.append("Copy .env.example to .env and fill it in.")
        lines.append("")
        print("\n".join(lines), file=sys.stderr)
        raise SystemExit(1) from exc


settings = get_settings()
