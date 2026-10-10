# Changelog

## v0.1.0 (October 2026)

- Read-only MCP server (`mcp` 2.x `MCPServer`, Streamable HTTP, stateless) with four tools:
  `list_views`, `describe_view`, `run_query`, `explain_query`
- SQL guard (sqlglot): single SELECT, view allowlist, function denylist, no data-modifying CTEs,
  `SELECT INTO` or row locks
- READ ONLY transaction, per-transaction statement timeout, server-side cursor row cap,
  `RESET ALL` on pool return
- `agent_ro` role with SELECT on PII-free views only; role-level read-only and timeout defaults
- Prompt-injection flagging for text in result rows; JSON audit log with ADK session id
- 55-case adversarial suite run with and without the guard; block-rate report in CI
- Example ADK agent (`McpToolset`, `tool_filter`, ID-token header provider) with an end-to-end
  test through a real ADK Runner
- Cloud Run deploy (private, separate setup and runtime service accounts) and teardown
