"""Create the sample schema (optional) and the agent_ro role + views.

    ADMIN_DATABASE_URL=... AGENT_PASSWORD=... python -m mcp_db_server.setup_db [--seed]

Used by the tests, by `make db`, and by the Cloud Run setup job in deploy/deploy.sh.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import psycopg
from psycopg import sql

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def _render(text: str, agent_password: str) -> str:
    literal = sql.Literal(agent_password).as_string(None)
    return re.sub(r":agent_password\b", literal, text)


def setup(admin_url: str, agent_password: str, seed: bool) -> None:
    files = (["00_schema.sql"] if seed else []) + ["01_agent_access.sql"]
    with psycopg.connect(admin_url, autocommit=True) as conn:
        for name in files:
            conn.execute(_render((SQL_DIR / name).read_text(), agent_password))
            print(f"applied {name}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true", help="also create and load the sample shop schema")
    args = ap.parse_args()
    setup(os.environ["ADMIN_DATABASE_URL"], os.environ["AGENT_PASSWORD"], args.seed)
