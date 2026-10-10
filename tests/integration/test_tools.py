"""End to end through the MCP protocol (in-process client) against a real Postgres."""

import json
from contextlib import asynccontextmanager

import pytest
from mcp import Client

pytestmark = pytest.mark.asyncio


async def _call(client, name, args=None):
    r = await client.call_tool(name, args or {})
    return r.structured_content or json.loads(r.content[0].text)


@asynccontextmanager
async def connected():
    # Opened inside each test (not a yield fixture) so anyio's cancel scopes stay in one task.
    from mcp_db_server.server import db, mcp

    async with Client(mcp) as c:
        yield c
    await db.close()


async def test_lists_exactly_four_read_only_tools(seeded_db):
    async with connected() as client:
        tools = (await client.list_tools()).tools
        assert sorted(t.name for t in tools) == ["describe_view", "explain_query", "list_views", "run_query"]
        assert all(t.annotations.read_only_hint for t in tools)


async def test_list_and_describe(seeded_db):
    async with connected() as client:
        views = await _call(client, "list_views")
        assert {v["view"] for v in views["views"]} == {"customers_v", "products_v", "orders_v", "order_items_v"}
        cols = await _call(client, "describe_view", {"view": "customers_v"})
        names = [c["column"] for c in cols["columns"]]
        assert "region" in names and "email" not in names and "phone" not in names


async def test_aggregate_query(seeded_db):
    async with connected() as client:
        out = await _call(client, "run_query", {"sql": "select region, count(*) n from customers_v group by 1"})
        assert out["ok"] and out["row_count"] == 5 and sum(r["n"] for r in out["rows"]) == 500


async def test_row_cap_sets_truncated(seeded_db):
    async with connected() as client:
        out = await _call(client, "run_query", {"sql": "select * from orders_v", "max_rows": 3})
        assert out["row_count"] == 3 and out["truncated"] is True


async def test_write_is_blocked_with_actionable_error(seeded_db):
    async with connected() as client:
        out = await _call(client, "run_query", {"sql": "delete from orders_v"})
        assert out["ok"] is False and out["error"]["layer"] == "guard"


async def test_runaway_query_hits_timeout(seeded_db):
    async with connected() as client:
        sql = "select count(*) from orders_v a cross join orders_v b cross join orders_v c"
        out = await _call(client, "run_query", {"sql": sql})
        assert out["ok"] is False and out["error"]["layer"] == "statement_timeout"


async def test_prompt_injection_in_rows_is_flagged(seeded_db):
    async with connected() as client:
        out = await _call(client, "run_query", {"sql": "select customer_id, notes from customers_v where notes is not null"})
        assert out["ok"] and out["suspicious_cells"][0]["column"] == "notes"
        assert "not instructions" in out["note"]


async def test_explain_does_not_execute(seeded_db):
    async with connected() as client:
        out = await _call(client, "explain_query", {"sql": "select * from order_items_v"})
        assert out["ok"] and out["estimated_rows"] > 1000
