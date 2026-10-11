"""setup_db must work when the admin is not a true superuser, as on Cloud SQL and AlloyDB.

There the admin user has CREATEROLE/CREATEDB but not SUPERUSER, and Postgres refuses any
ALTER ROLE that names SUPERUSER or REPLICATION. CI's postgres user is a real superuser, so
without this test that difference only shows up on the first cloud deploy.
"""

from __future__ import annotations

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

DB, ADMIN = "managed_sim", "managed_admin"


@pytest.fixture
def managed_admin_url(seeded_db):
    with psycopg.connect(seeded_db, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DB}")
        conn.execute(f"DROP ROLE IF EXISTS {ADMIN}")
        conn.execute(f"CREATE ROLE {ADMIN} LOGIN PASSWORD 'pw' CREATEROLE CREATEDB")
        conn.execute(f"CREATE DATABASE {DB} OWNER {ADMIN}")
        # Roles are cluster-wide and the session fixture already created agent_ro as superuser.
        # On a fresh managed instance the admin creates agent_ro itself and so administers it.
        conn.execute(f"GRANT agent_ro TO {ADMIN} WITH ADMIN OPTION")
    yield make_conninfo(seeded_db, user=ADMIN, password="pw", dbname=DB)
    with psycopg.connect(seeded_db, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DB}")
        conn.execute(f"DROP OWNED BY {ADMIN}")
        conn.execute(f"DROP ROLE IF EXISTS {ADMIN}")


def test_setup_runs_twice_as_a_managed_admin(managed_admin_url):
    from mcp_db_server.setup_db import setup

    setup(managed_admin_url, "agentpw", seed=True)
    setup(managed_admin_url, "agentpw", seed=False)  # redeploys rerun it

    agent = make_conninfo(managed_admin_url, user="agent_ro", password="agentpw")
    with psycopg.connect(agent, autocommit=True) as conn:
        assert conn.execute("select count(*) from orders_v").fetchone()[0] > 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select * from shop.customers")
    assert conninfo_to_dict(agent)["dbname"] == DB
