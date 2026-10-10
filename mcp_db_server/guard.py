"""First line of defence: parse the SQL and reject anything that isn't one plain SELECT over allowed views.

This layer exists to give the model fast, specific errors it can act on. It is *not* the real
security boundary. Parsers have gaps, so the database role (SELECT on views only), the read-only
transaction and the statement timeout must hold even if this module lets something through.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

# sqlglot warns when it falls back to a generic Command node; we reject those anyway.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

# Statement or clause types that must never appear anywhere in the tree, including inside CTEs
# (Postgres allows `WITH d AS (DELETE ... RETURNING *) SELECT ...`).
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
    exp.TruncateTable, exp.Command, exp.Copy, exp.Set, exp.Grant, exp.Into, exp.Lock,
    exp.Transaction, exp.Commit, exp.Rollback, exp.Use, exp.Pragma,
)

# Functions that read files, sleep, change settings, talk to other servers or touch other sessions.
DENIED_FUNCTIONS = frozenset({
    "set_config", "current_setting", "query_to_xml", "query_to_json", "table_to_xml",
    "cursor_to_xml", "dblink", "dblink_exec", "lo_import", "lo_export", "lo_get", "lo_put",
    "txid_current", "version",
})
DENIED_PREFIXES = ("pg_", "lo_", "dblink")


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    code: str = "ok"
    message: str = ""
    sql: str = ""
    relations: list[str] = field(default_factory=list)


def _reject(code: str, message: str) -> GuardResult:
    return GuardResult(ok=False, code=code, message=message)


def _function_name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    return (node.sql_name() or "").lower()


def check(sql: str, allowed_views: frozenset[str], view_schema: str = "agent_views") -> GuardResult:
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        return _reject("empty", "Send one SELECT statement.")
    if len(text) > 8000:
        return _reject("too_long", "Query is longer than 8,000 characters. Simplify it.")

    try:
        statements = [s for s in sqlglot.parse(text, read="postgres") if s is not None]
    except ParseError as e:
        return _reject("parse_error", f"Could not parse the SQL: {str(e).splitlines()[0]}")
    if len(statements) != 1:
        return _reject("multiple_statements", "Send exactly one statement. Stacked queries are not allowed.")

    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        return _reject(
            "not_select",
            f"Only SELECT is allowed (got {tree.key.upper()}). This server is read-only.",
        )

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            return _reject("forbidden_clause", f"{node.key.upper()} is not allowed. This server is read-only.")
        if isinstance(node, exp.Func):
            name = _function_name(node)
            if name in DENIED_FUNCTIONS or name.startswith(DENIED_PREFIXES):
                return _reject("function_not_allowed", f"Function {name}() is not allowed.")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    relations: list[str] = []
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        schema = (table.db or "").lower()
        if not name:  # table-valued function such as generate_series(...)
            return _reject("function_not_allowed", "Table functions are not allowed. Query the views.")
        if not schema and name in cte_names:
            continue
        if schema and schema != view_schema.lower():
            return _reject(
                "relation_not_allowed",
                f"{schema}.{name} is not available. Call list_views to see what you can query.",
            )
        if name not in allowed_views:
            return _reject(
                "relation_not_allowed",
                f"{name} is not available. Call list_views to see what you can query.",
            )
        relations.append(name)

    if not relations:
        return _reject("no_relation", "Query at least one view. Call list_views to see them.")

    return GuardResult(ok=True, sql=tree.sql(dialect="postgres"), relations=sorted(set(relations)))
