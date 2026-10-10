.PHONY: db test attack serve smoke
export ADMIN_DATABASE_URL ?= postgresql://postgres:postgres@localhost:5432/shop
export AGENT_PASSWORD ?= agentpw

db:     ; docker compose up -d --wait && python -m mcp_db_server.setup_db --seed
test:   ; pytest -q
attack: ; python tools/report.py
serve:  ; python -m mcp_db_server
smoke:  ; python examples/smoke_client.py http://127.0.0.1:8080/mcp
