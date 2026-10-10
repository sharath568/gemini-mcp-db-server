"""Second and third lines of defence: every query runs in a READ ONLY transaction with a
statement timeout and a row cap, as a role that can only SELECT from a few views.

Errors from Postgres are mapped to short codes plus the layer that stopped the query, so the
audit log (and the adversarial report) can say *which* control did the work.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import decimal
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg import errors
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import Settings, get_settings


@dataclass
class QueryResult:
    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    code: str = "ok"
    layer: str = ""
    message: str = ""
    elapsed_ms: float = 0.0


_ERROR_MAP: list[tuple[type[Exception], str, str, str]] = [
    (errors.InsufficientPrivilege, "permission_denied", "db_role",
     "The database role is not allowed to read that. Call list_views to see what you can query."),
    (errors.ReadOnlySqlTransaction, "read_only", "read_only_txn",
     "The database rejected a write. This server is read-only."),
    (errors.QueryCanceled, "timeout", "statement_timeout",
     "The query ran longer than the time limit. Add filters or aggregate first."),
    (errors.UndefinedTable, "undefined_relation", "db",
     "That relation doesn't exist. Call list_views to see what you can query."),
    (errors.UndefinedColumn, "undefined_column", "db",
     "That column doesn't exist. Call describe_view to see the columns."),
    (errors.SyntaxError, "syntax_error", "db", "Postgres rejected the SQL syntax."),
]


def _jsonable(value: Any) -> Any:
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    if isinstance(value, uuid.UUID | bytes | memoryview):
        return str(value) if not isinstance(value, bytes | memoryview) else "<binary>"
    return value


class Database:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._pool: AsyncConnectionPool | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def pool(self) -> AsyncConnectionPool:
        # Opened lazily on first use: Cloud Run instances that never get a query never connect.
        # A pool belongs to one event loop; if we're called from a different loop (tests, or a
        # server restarted in-process), start a fresh pool rather than share connections across loops.
        loop = asyncio.get_running_loop()
        if self._pool is None or self._loop is not loop:
            pool = AsyncConnectionPool(
                self.settings.database_url,
                min_size=self.settings.pool_min,
                max_size=self.settings.pool_max,
                kwargs={"autocommit": True, "application_name": "mcp-db-server"},
                # If anything ever changes session state (e.g. set_config(..., false)),
                # wipe it before the connection goes back to the pool.
                reset=_reset_session,
                open=False,
            )
            await pool.open(wait=False)
            self._pool, self._loop = pool, loop
        return self._pool

    async def close(self) -> None:
        pool, self._pool = self._pool, None
        # Only close a pool from the loop that owns it; a pool from another loop just gets dropped.
        if pool is not None and self._loop is asyncio.get_running_loop():
            await pool.close()

    async def run(
        self, sql: str, row_cap: int | None = None, params: tuple | None = None, server_side: bool = True
    ) -> QueryResult:
        cap = min(row_cap or self.settings.row_cap, self.settings.row_cap)
        started = time.perf_counter()
        pool = await self.pool()
        try:
            async with pool.connection() as conn:
                async with conn.transaction():
                    # Belt and braces: the role already defaults to read-only with a timeout, but
                    # we set both explicitly so a misconfigured role can't silently drop them.
                    await conn.execute("SET TRANSACTION READ ONLY")
                    await conn.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        (str(self.settings.statement_timeout_ms),),
                    )
                    # A server-side cursor, so a wide query only ships cap+1 rows to us.
                    # (EXPLAIN can't run inside DECLARE CURSOR, hence the switch.)
                    cursor = conn.cursor(name="agent_q", row_factory=dict_row) if server_side else conn.cursor(row_factory=dict_row)
                    async with cursor as cur:
                        await cur.execute(sql, params)
                        columns = [c.name for c in cur.description or []]
                        rows = await cur.fetchmany(cap + 1)
        except tuple(e[0] for e in _ERROR_MAP) as e:  # type: ignore[misc]
            for cls, code, layer, message in _ERROR_MAP:
                if isinstance(e, cls):
                    return QueryResult(False, code=code, layer=layer, message=f"{message} ({e.diag.message_primary})",
                                       elapsed_ms=_ms(started))
            raise  # pragma: no cover
        except psycopg.Error as e:
            return QueryResult(False, code="db_error", layer="db", message=str(e).splitlines()[0],
                               elapsed_ms=_ms(started))
        truncated = len(rows) > cap
        rows = [{k: _jsonable(v) for k, v in r.items()} for r in rows[:cap]]
        return QueryResult(True, columns=columns, rows=rows, truncated=truncated, elapsed_ms=_ms(started))


async def _reset_session(conn: psycopg.AsyncConnection) -> None:
    await conn.execute("RESET ALL")


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
