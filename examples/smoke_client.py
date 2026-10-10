"""Call the deployed (or local) server without any LLM. Good first check after a deploy.

    # local
    python examples/smoke_client.py http://127.0.0.1:8080/mcp
    # Cloud Run, through an authenticated local proxy (no token handling needed):
    gcloud run services proxy mcp-db-server --region us-central1 --port 8081
    python examples/smoke_client.py http://127.0.0.1:8081/mcp
    # Cloud Run directly, with your own ID token:
    ID_TOKEN=$(gcloud auth print-identity-token) python examples/smoke_client.py https://...run.app/mcp
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client


async def main(url: str) -> None:
    headers = {"x-agent-session-id": "smoke-test"}
    if token := os.getenv("ID_TOKEN"):
        headers["authorization"] = f"Bearer {token}"
    async with create_mcp_http_client(headers=headers) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, *_):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print("tools:", [t.name for t in tools.tools])
                for name, args in [
                    ("list_views", {}),
                    ("run_query", {"sql": "select region, count(*) as customers from customers_v group by 1 order by 1"}),
                    ("run_query", {"sql": "drop table shop.orders"}),
                ]:
                    r = await session.call_tool(name, args)
                    body = r.structured_content or json.loads(r.content[0].text)
                    print(f"\n{name} {args}\n", json.dumps(body, indent=2)[:600])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080/mcp"))
