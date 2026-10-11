-- The read-only surface the agent gets. Run as an admin. Requires psql variable :agent_password
--   psql "$ADMIN_DATABASE_URL" -v agent_password="'...'" -f sql/01_agent_access.sql
-- (deploy/setup_db job runs the same statements through Python.)

CREATE SCHEMA IF NOT EXISTS agent_views;

-- Views drop PII columns. They run with the view owner's rights, so agent_ro needs no table grants.
CREATE OR REPLACE VIEW agent_views.customers_v AS
  SELECT customer_id, region, segment, signup_date, notes FROM shop.customers;

CREATE OR REPLACE VIEW agent_views.products_v AS
  SELECT product_id, name, category, unit_price FROM shop.products;

CREATE OR REPLACE VIEW agent_views.orders_v AS
  SELECT order_id, customer_id, ordered_at, status, channel FROM shop.orders;

CREATE OR REPLACE VIEW agent_views.order_items_v AS
  SELECT order_id, product_id, quantity, unit_price, quantity * unit_price AS line_total
  FROM shop.order_items;

COMMENT ON VIEW agent_views.customers_v   IS 'One row per customer. No contact details. notes is free text written by staff.';
COMMENT ON VIEW agent_views.products_v    IS 'Product catalog with list price.';
COMMENT ON VIEW agent_views.orders_v      IS 'One row per order. status: placed, shipped, delivered, cancelled. channel: web, mobile, partner.';
COMMENT ON VIEW agent_views.order_items_v IS 'Order lines. line_total = quantity * unit_price. Join to orders_v on order_id.';

-- The login role the MCP server uses.
-- SUPERUSER/REPLICATION are set only at creation: on Cloud SQL and AlloyDB the admin user is not a
-- true superuser, and Postgres 16 refuses any ALTER ROLE that names those attributes.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_ro') THEN
    CREATE ROLE agent_ro LOGIN NOSUPERUSER NOREPLICATION;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_ro' AND (rolsuper OR rolreplication OR rolbypassrls)) THEN
    RAISE EXCEPTION 'agent_ro has SUPERUSER, REPLICATION or BYPASSRLS; drop the role and rerun';
  END IF;
END $$;
ALTER ROLE agent_ro WITH LOGIN NOCREATEDB NOCREATEROLE NOINHERIT
  CONNECTION LIMIT 20 PASSWORD :agent_password;

-- Nothing by default, then exactly what it needs.
REVOKE ALL ON SCHEMA shop FROM agent_ro;
REVOKE ALL ON ALL TABLES IN SCHEMA shop FROM agent_ro;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA agent_views TO agent_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA agent_views TO agent_ro;

-- Session defaults that hold even if the server code forgets: read-only, short timeouts.
ALTER ROLE agent_ro SET default_transaction_read_only = on;
ALTER ROLE agent_ro SET statement_timeout = '5s';
ALTER ROLE agent_ro SET idle_in_transaction_session_timeout = '10s';
ALTER ROLE agent_ro SET search_path = agent_views;
