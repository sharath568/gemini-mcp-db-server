"""Cold start and latency under concurrent agent sessions, against a deployed (or local) server.

    ID_TOKEN=$(gcloud auth print-identity-token) python tools/loadtest.py https://...run.app/mcp
    python tools/loadtest.py http://127.0.0.1:8080/mcp --sessions 20 --rounds 10

Each session is one MCP client doing what an agent does per question: list_views, describe_view,
then a join + aggregate run_query, `rounds` times. The first call is timed alone, so if the service
was scaled to zero it measures the cold start. No LLM is involved; this is the tool path only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time

from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

QUERY = (
    "select c.region, o.channel, count(*) as orders, round(sum(i.line_total), 2) as revenue "
    "from orders_v o join customers_v c using (customer_id) join order_items_v i using (order_id) "
    "group by 1, 2 order by 1, 2"
)
STEPS = [("list_views", {}), ("describe_view", {"view": "orders_v"}), ("run_query", {"sql": QUERY})]


def _headers(session_id: str) -> dict[str, str]:
    h = {"x-agent-session-id": session_id}
    if token := os.getenv("ID_TOKEN"):
        h["authorization"] = f"Bearer {token}"
    return h


async def _session(url: str, sid: str, rounds: int, out: dict[str, list[float]], errors: list[str]) -> None:
    async with create_mcp_http_client(headers=_headers(sid)) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, *_):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for _ in range(rounds):
                    for name, args in STEPS:
                        t0 = time.perf_counter()
                        r = await session.call_tool(name, args)
                        out[name].append((time.perf_counter() - t0) * 1000)
                        body = r.structured_content or json.loads(r.content[0].text)
                        if not body.get("ok"):
                            errors.append(f"{name}: {body.get('error')}")


async def _first_call(url: str) -> float:
    t0 = time.perf_counter()
    async with create_mcp_http_client(headers=_headers("loadtest-cold")) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, *_):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool("run_query", {"sql": QUERY})
    return (time.perf_counter() - t0) * 1000


def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--sessions", type=int, default=20)
    ap.add_argument("--rounds", type=int, default=10)
    a = ap.parse_args()

    first = await _first_call(a.url)
    out: dict[str, list[float]] = {name: [] for name, _ in STEPS}
    errors: list[str] = []
    t0 = time.perf_counter()
    await asyncio.gather(*(_session(a.url, f"loadtest-{i}", a.rounds, out, errors) for i in range(a.sessions)))
    wall = time.perf_counter() - t0

    calls = sum(len(v) for v in out.values())
    print(f"first call (cold if scaled to zero): {first:.0f} ms (connect + initialize + run_query)")
    print(f"{a.sessions} sessions x {a.rounds} rounds: {calls} calls in {wall:.1f} s "
          f"({calls / wall:.0f} calls/s), errors: {len(errors)}")
    print("| tool | p50 ms | p95 ms | max ms |\n|---|---|---|---|")
    for name, xs in out.items():
        print(f"| {name} | {statistics.median(xs):.0f} | {_pct(xs, 95):.0f} | {max(xs):.0f} |")
    for e in errors[:5]:
        print("error:", e)


if __name__ == "__main__":
    asyncio.run(main())
