"""Every attack must be blocked by the full stack; every legit query must pass.

Also pins the honest finding: catalog reads and a few functions are stopped *only* by the guard.
If you harden the database further (see README), update EXPECTED_GUARD_ONLY.
"""

import pytest

from mcp_db_server.attack import run_all, summarize
from mcp_db_server.db import Database

pytestmark = pytest.mark.asyncio

EXPECTED_GUARD_ONLY = {"A26", "A28", "A29", "A30", "A31", "A32", "A34"}


async def test_attack_suite(seeded_db):
    db = Database()
    results = await run_all(db)
    await db.close()
    s = summarize(results)
    assert s["blocked_full_stack"] == s["attacks"], [r for r in results if r.expect == "blocked" and r.full_stack == "allowed"]
    assert s["false_positives"] == []
    assert set(s["only_guard_stopped"]) == EXPECTED_GUARD_ONLY
