"""One structured log line per tool call. On Cloud Run, stdout JSON lands in Cloud Logging with
`severity` parsed, so you can filter with jsonPayload.tool="run_query" AND jsonPayload.outcome="blocked".
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import time
from collections.abc import Mapping
from typing import Any


def caller_from_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    """Who is calling, for the log only.

    On Cloud Run with --no-allow-unauthenticated, Google's front end has already verified the ID
    token before the request reaches us, so reading the email claim without re-verifying is
    fine *for logging*. Never use it for an authorization decision in this process.
    """
    if not headers:
        return {}
    out: dict[str, str] = {}
    if sid := headers.get("x-agent-session-id"):
        out["session_id"] = sid[:128]
    if inv := headers.get("x-agent-invocation-id"):
        out["invocation_id"] = inv[:128]
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and auth.count(".") == 2:
        try:
            payload = auth.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if email := claims.get("email"):
                out["caller"] = str(email)
        except (ValueError, json.JSONDecodeError):
            pass
    return out


def log(tool: str, outcome: str, *, sql: str | None = None, **fields: Any) -> None:
    entry: dict[str, Any] = {
        "severity": "WARNING" if outcome == "blocked" else ("ERROR" if outcome == "error" else "INFO"),
        "message": f"{tool} {outcome}",
        "component": "mcp-db-server",
        "tool": tool,
        "outcome": outcome,
        "ts": round(time.time(), 3),
    }
    if sql is not None:
        entry["sql"] = sql[:2000]
        entry["sql_sha1"] = hashlib.sha1(sql.encode()).hexdigest()[:12]
    entry.update({k: v for k, v in fields.items() if v is not None})
    print(json.dumps(entry, default=str), file=sys.stdout, flush=True)
