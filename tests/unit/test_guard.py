import pytest

from mcp_db_server.guard import check

VIEWS = frozenset({"customers_v", "products_v", "orders_v", "order_items_v"})


@pytest.mark.parametrize("sql", [
    "select region, count(*) from customers_v group by 1",
    "SELECT * FROM agent_views.orders_v",
    "with t as (select * from orders_v) select count(*) from t",
    "select * from orders_v union all select * from orders_v",
    "select * from orders_v where order_id in (select order_id from order_items_v)",
    "select * from orders_v;",
])
def test_allows_plain_selects(sql):
    r = check(sql, VIEWS)
    assert r.ok, r.message
    assert r.relations


@pytest.mark.parametrize("sql,code", [
    ("", "empty"),
    ("delete from orders_v", "not_select"),
    ("select 1; drop table orders_v", "multiple_statements"),
    ("with d as (delete from orders_v returning *) select * from d", "forbidden_clause"),
    ("select * into x from orders_v", "forbidden_clause"),
    ("select * from orders_v for update", "forbidden_clause"),
    ("select pg_sleep(5) from orders_v", "function_not_allowed"),
    ("select set_config('a','b',false) from orders_v", "function_not_allowed"),
    ("select * from generate_series(1,3)", "function_not_allowed"),
    ("select * from shop.customers", "relation_not_allowed"),
    ("select * from pg_catalog.pg_roles", "relation_not_allowed"),
    ("select * from customers", "relation_not_allowed"),
    ("select 1", "no_relation"),
    ("select * from (", "parse_error"),
])
def test_rejects_with_actionable_code(sql, code):
    r = check(sql, VIEWS)
    assert not r.ok
    assert r.code == code
    assert r.message


def test_cte_name_does_not_need_allowlisting():
    assert check("with recent as (select * from orders_v) select * from recent", VIEWS).ok


def test_cte_cannot_shadow_a_schema_qualified_table():
    assert not check("with x as (select 1) select * from shop.x", VIEWS).ok


def test_long_queries_rejected():
    assert check("select * from orders_v where " + " or ".join(["1=1"] * 3000), VIEWS).code == "too_long"
