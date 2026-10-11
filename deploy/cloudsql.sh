#!/usr/bin/env bash
# The cheapest private Postgres for this server: Cloud SQL shared-core, private IP only, stopped when idle.
# Use it when the AlloyDB free trial isn't available. The MCP server doesn't care which one it talks to.
#
#   PROJECT_ID=my-project ./deploy/cloudsql.sh create   # ~10 min; also stores the admin DSN secret
#   PROJECT_ID=my-project ./deploy/cloudsql.sh stop     # done for the day: only storage bills
#   PROJECT_ID=my-project ./deploy/cloudsql.sh start
#   PROJECT_ID=my-project ./deploy/cloudsql.sh delete
#
# Cost (us-central1, check current pricing): db-f1-micro about $0.0105/hour while running,
# 10 GB HDD about $0.90/month. No backups, no HA, no public IP.
# Prereq: private services access on NETWORK (a peering range for servicenetworking).
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
NETWORK="${NETWORK:-default}"
SQL_INSTANCE="${SQL_INSTANCE:-mcp-pg}"
TIER="${TIER:-db-f1-micro}"
ADMIN_SECRET="${ADMIN_SECRET:-mcp-db-admin-url}"
LABELS="${LABELS:-app=gemini-mcp-db-server,purpose=gde}"
export CLOUDSDK_CORE_PROJECT="$PROJECT_ID" CLOUDSDK_CORE_DISABLE_PROMPTS=1

case "${1:-}" in
  create)
    gcloud services enable sqladmin.googleapis.com servicenetworking.googleapis.com secretmanager.googleapis.com
    if ! gcloud sql instances describe "$SQL_INSTANCE" >/dev/null 2>&1; then
      gcloud sql instances create "$SQL_INSTANCE" --database-version=POSTGRES_16 --edition=ENTERPRISE \
        --tier="$TIER" --region="$REGION" --availability-type=zonal \
        --network="projects/$PROJECT_ID/global/networks/$NETWORK" --no-assign-ip \
        --storage-type=HDD --storage-size=10 --no-storage-auto-increase --no-backup
      # (gcloud sql has no --labels flag; tools/gcp-whats-running.sh lists Cloud SQL instances anyway)
    fi
    # New admin password on every create; it lives only in Secret Manager.
    PW=$(openssl rand -base64 24 | tr -d '/+=\n')
    gcloud sql users set-password postgres --instance="$SQL_INSTANCE" --password="$PW" >/dev/null
    IP=$(gcloud sql instances describe "$SQL_INSTANCE" --format='value(ipAddresses[0].ipAddress)')
    DSN="postgresql://postgres:${PW}@${IP}:5432/postgres"
    if gcloud secrets describe "$ADMIN_SECRET" >/dev/null 2>&1; then
      printf '%s' "$DSN" | gcloud secrets versions add "$ADMIN_SECRET" --data-file=- >/dev/null
    else
      printf '%s' "$DSN" | gcloud secrets create "$ADMIN_SECRET" --data-file=- --labels="$LABELS" >/dev/null
    fi
    unset PW DSN
    echo "Cloud SQL $SQL_INSTANCE at $IP (private). Admin DSN in secret $ADMIN_SECRET."
    ;;
  stop)   gcloud sql instances patch "$SQL_INSTANCE" --activation-policy=NEVER  >/dev/null && echo "stopped" ;;
  start)  gcloud sql instances patch "$SQL_INSTANCE" --activation-policy=ALWAYS >/dev/null && echo "started" ;;
  delete)
    gcloud sql instances delete "$SQL_INSTANCE" --quiet || true
    gcloud secrets delete "$ADMIN_SECRET" --quiet 2>/dev/null || true
    echo "deleted $SQL_INSTANCE and $ADMIN_SECRET"
    ;;
  *) echo "usage: $0 create|start|stop|delete"; exit 2 ;;
esac
