"""A real ADK Runner drives the example agent against the real server over Streamable HTTP.

The LLM is scripted (no credentials, no cost): turn 1 asks for run_query, turn 2 answers with
what the tool returned. Everything between the model and Postgres is the real code path:
McpToolset -> HTTP -> MCPServer -> guard -> read-only txn -> agent_ro.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from typing import AsyncGenerator

import pytest

adk = pytest.importorskip("google.adk")

import uvicorn  # noqa: E402
from google.adk.models import BaseLlm  # noqa: E402
from google.adk.models.llm_request import LlmRequest  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

pytestmark = pytest.mark.asyncio


class ScriptedLlm(BaseLlm):
    """Calls run_query with a fixed SQL, then echoes the tool result as the answer."""

    sql: str = ""
    seen: list = []

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        last = llm_request.contents[-1].parts[-1]
        if last.function_response is None:
            call = types.FunctionCall(name="run_query", args={"sql": self.sql})
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]))
        else:
            self.seen.append(last.function_response.response)
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="done")]))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_url(seeded_db):
    from mcp_db_server.server import build_app

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(build_app(), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(5)


async def _ask(server_url: str, sql: str) -> dict:
    from google.adk.tools.mcp_tool import McpToolset
    from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

    from examples.db_agent import agent as example

    model = ScriptedLlm(model="scripted", sql=sql, seen=[])
    toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=server_url, timeout=30),
        tool_filter=["list_views", "describe_view", "run_query"],
        header_provider=example.mcp_headers,
    )
    root = example.root_agent.clone(update={"model": model, "tools": [toolset]})
    runner = InMemoryRunner(agent=root, app_name="t")
    session = await runner.session_service.create_session(app_name="t", user_id="u")
    msg = types.Content(role="user", parts=[types.Part(text="question")])
    async for _ in runner.run_async(user_id="u", session_id=session.id, new_message=msg):
        pass
    await toolset.close()
    result = model.seen[0]
    # ADK wraps MCP results; structured content may arrive as text JSON
    if "structuredContent" in result:
        return result["structuredContent"]
    if "content" in result:
        return json.loads(result["content"][0]["text"])
    return result


async def test_agent_answers_through_mcp(server_url, capfd):
    out = await _ask(server_url, "select channel, count(*) as n from orders_v group by 1 order by 1")
    assert out["ok"] is True
    assert [r["channel"] for r in out["rows"]] == ["mobile", "partner", "web"]
    # the server's audit line carries the ADK session id sent by the header provider
    await asyncio.sleep(0.1)
    logs = [json.loads(l) for l in capfd.readouterr().out.splitlines() if l.startswith("{")]
    assert any(l.get("tool") == "run_query" and l.get("session_id") for l in logs)


async def test_agent_write_attempt_is_blocked(server_url):
    out = await _ask(server_url, "delete from orders_v")
    assert out["ok"] is False and out["error"]["layer"] == "guard"
