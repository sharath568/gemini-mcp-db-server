"""All settings come from environment variables, so one image runs locally and on Cloud Run."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

DEFAULT_VIEWS = "customers_v,products_v,orders_v,order_items_v"


def _csv(value: str) -> frozenset[str]:
    return frozenset(v.strip().lower() for v in value.split(",") if v.strip())


@dataclass(frozen=True)
class Settings:
    # DSN for the *agent_ro* role. On Cloud Run it comes from Secret Manager.
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "postgresql://agent_ro:agentpw@localhost:5432/shop"
        )
    )
    view_schema: str = field(default_factory=lambda: os.getenv("VIEW_SCHEMA", "agent_views"))
    allowed_views: frozenset[str] = field(
        default_factory=lambda: _csv(os.getenv("ALLOWED_VIEWS", DEFAULT_VIEWS))
    )
    row_cap: int = field(default_factory=lambda: int(os.getenv("ROW_CAP", "200")))
    statement_timeout_ms: int = field(
        default_factory=lambda: int(os.getenv("STATEMENT_TIMEOUT_MS", "3000"))
    )
    pool_min: int = field(default_factory=lambda: int(os.getenv("POOL_MIN", "0")))
    pool_max: int = field(default_factory=lambda: int(os.getenv("POOL_MAX", "5")))
    # Cloud Run sets PORT. Bind 0.0.0.0 there; 127.0.0.1 locally turns on DNS-rebinding protection.
    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8080")))


@lru_cache
def get_settings() -> Settings:
    return Settings()
