# Changelog

## v0.1.1 (October 2026)

- Fix: `agent_ro` setup failed on Cloud SQL and AlloyDB, where the admin is not a true superuser
  (Postgres 16 rejects `ALTER ROLE ... NOSUPERUSER/NOREPLICATION` from non-superusers). Attributes are
  now set at `CREATE ROLE` and verified; new test runs setup as a CREATEROLE-only admin.
- `deploy/cloudsql.sh`: shared-core Cloud SQL Postgres on a private IP, with start/stop/delete;
  `deploy.sh` takes `SQL_INSTANCE`; `teardown.sh` stops it
- `tools/loadtest.py`: cold start plus p50/p95 per tool under concurrent MCP sessions
- Deploy scripts never stop at gcloud prompts

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
