import os

import psycopg
import pytest

# Defaults match the GitHub Actions service and the local `make db` setup.
ADMIN_URL = os.environ.setdefault("ADMIN_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/shop")
os.environ.setdefault("DATABASE_URL", "postgresql://agent_ro:agentpw@localhost:5432/shop")
os.environ.setdefault("STATEMENT_TIMEOUT_MS", "1500")


def _db_up() -> bool:
    try:
        psycopg.connect(ADMIN_URL, connect_timeout=2).close()
        return True
    except psycopg.Error:
        return False


@pytest.fixture(scope="session")
def seeded_db():
    if not _db_up():
        pytest.skip("Postgres not reachable at ADMIN_DATABASE_URL (run `make db`)")
    from mcp_db_server.setup_db import setup

    setup(ADMIN_URL, "agentpw", seed=True)
    return ADMIN_URL
