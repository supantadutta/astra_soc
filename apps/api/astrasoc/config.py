"""Runtime configuration.

Settings are read from environment variables (prefixed ``ASTRASOC_``) with safe
defaults chosen so the *demo* profile runs with zero external dependencies:
a local SQLite database, an in-process event bus, and the simulated LLM.

Nothing secret is ever hard-coded here. Secrets referenced by connectors and
model providers are resolved through the secret-manager interface
(:mod:`astrasoc.services.secrets`) using *references*, never plaintext values
stored in the database or shipped to the browser.
"""
from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASTRASOC_",
        env_file=(".env", "../.env", "../../.env"),
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core -------------------------------------------------------------
    environment: Literal["development", "demo", "production", "test"] = "demo"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    # A random per-process secret is fine for the demo profile. Production
    # deployments MUST set ASTRASOC_JWT_SECRET explicitly (see .env.example).
    jwt_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 3600
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 7

    # --- Datastores -------------------------------------------------------
    # SQLite keeps the demo self-contained. Point this at Postgres for
    # development/production (see docker-compose.yml).
    database_url: str = "sqlite:///./astrasoc.db"

    # Optional enterprise datastores. When unset the platform runs in a
    # degraded-but-functional mode and reports these dependencies as
    # "not configured" on the Platform Health page — it never fakes them.
    redis_url: str | None = None
    clickhouse_url: str | None = None
    neo4j_url: str | None = None
    opensearch_url: str | None = None
    kafka_brokers: str | None = None
    temporal_host: str | None = None
    opa_url: str | None = None
    vault_addr: str | None = None

    # --- Operating mode ---------------------------------------------------
    # Startup default. The authoritative, mutable mode lives in the DB
    # (SystemSetting) and is enforced by astrasoc.services.mode.
    default_mode: Literal["DEMO", "LIVE"] = "DEMO"
    allow_live_mode: bool = True  # set False to hard-lock a deployment to demo

    # --- CORS -------------------------------------------------------------
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Demo engine ------------------------------------------------------
    demo_event_interval_seconds: float = 3.0
    demo_seed_on_startup: bool = True

    # --- Rate limiting ----------------------------------------------------
    rate_limit_per_minute: int = 600

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
