"""The example agent wires up without credentials and sends the right headers."""

from types import SimpleNamespace

import pytest

adk = pytest.importorskip("google.adk")


def test_agent_builds_and_filters_tools(monkeypatch):
    monkeypatch.setenv("MCP_URL", "http://127.0.0.1:8080/mcp")
    from examples.db_agent import agent

    assert agent.root_agent.name == "data_analyst"
    assert agent.db_tools.tool_filter == ["list_views", "describe_view", "run_query"]


def test_local_url_sends_session_headers_without_token():
    from examples.db_agent import agent

    ctx = SimpleNamespace(session=SimpleNamespace(id="s-123"), invocation_id="inv-9")
    assert agent.mcp_headers(ctx) == {"x-agent-session-id": "s-123", "x-agent-invocation-id": "inv-9"}


def test_remote_url_adds_id_token(monkeypatch):
    from examples.db_agent import agent

    monkeypatch.setattr(agent, "MCP_URL", "https://mcp-db-server-abc.a.run.app/mcp")
    seen = {}
    monkeypatch.setattr(agent, "_id_token", lambda aud: seen.setdefault("aud", aud) and "tok")
    ctx = SimpleNamespace(session=SimpleNamespace(id="s"), invocation_id="i")
    assert agent.mcp_headers(ctx)["authorization"] == "Bearer tok"
    assert seen["aud"] == "https://mcp-db-server-abc.a.run.app"
