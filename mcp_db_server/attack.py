"""Run the adversarial set twice: with every layer, and with the SQL guard switched off.

The second run is the honest part: it shows what the database alone (role, read-only
transaction, timeout) stops, and what *only* the parser stops.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from . import guard
from .config import get_settings
from .db import Database

CASES = Path(__file__).resolve().parent.parent / "tests" / "adversarial" / "cases.jsonl"


@dataclass
class Outcome:
    id: str
    category: str
    sql: str
    expect: str
    full_stack: str  # layer that stopped it, or "allowed"
    db_only: str     # same, with the guard switched off


def load_cases(path: Path = CASES) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def _db_layer(db: Database, sql: str) -> str:
    """Send the raw SQL straight to the database as agent_ro, bypassing the guard."""
    res = await db.run(sql, row_cap=5, server_side=False)
    if res.ok:
        return "allowed"
    if "multiple commands" in res.message:
        return "driver_protocol"  # extended query protocol accepts one statement only
    return res.layer if res.layer != "db" else f"db:{res.code}"


async def run_all(db: Database | None = None) -> list[Outcome]:
    s = get_settings()
    db = db or Database()
    out: list[Outcome] = []
    for case in load_cases():
        g = guard.check(case["sql"], s.allowed_views, s.view_schema)
        db_only = await _db_layer(db, case["sql"])
        if not g.ok:
            full = "guard"
        else:
            full = await _db_layer(db, g.sql)
        out.append(Outcome(case["id"], case["category"], case["sql"], case["expect"], full, db_only))
    return out


def summarize(results: list[Outcome]) -> dict:
    attacks = [r for r in results if r.expect == "blocked"]
    legit = [r for r in results if r.expect == "allowed"]
    return {
        "attacks": len(attacks),
        "blocked_full_stack": sum(r.full_stack != "allowed" for r in attacks),
        "blocked_db_only": sum(r.db_only != "allowed" for r in attacks),
        "only_guard_stopped": [r.id for r in attacks if r.db_only == "allowed"],
        "legit": len(legit),
        "legit_allowed": sum(r.full_stack == "allowed" for r in legit),
        "false_positives": [r.id for r in legit if r.full_stack != "allowed"],
    }


if __name__ == "__main__":  # pragma: no cover
    res = asyncio.run(run_all())
    print(json.dumps(summarize(res), indent=2))
