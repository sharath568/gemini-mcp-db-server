#!/usr/bin/env bash
# Remove everything deploy.sh created. Leaves the AlloyDB cluster (owned by vertex-alloydb-rag).
set -uo pipefail
PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-mcp-db-server}"
AR_REPO="${AR_REPO:-gde}"
gcloud config set project "$PROJECT_ID" >/dev/null

gcloud run services delete "$SERVICE" --region="$REGION" --quiet 2>/dev/null || true
gcloud run jobs delete mcp-db-setup --region="$REGION" --quiet 2>/dev/null || true
gcloud secrets delete mcp-db-agent-url --quiet 2>/dev/null || true
gcloud secrets delete mcp-db-agent-password --quiet 2>/dev/null || true
gcloud artifacts docker images delete "${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE}" \
  --delete-tags --quiet 2>/dev/null || true
echo "Removed $SERVICE, its setup job, secrets and images."
echo "The agent_ro role and agent_views schema stay in the database (free). Drop them with:"
echo "  DROP SCHEMA agent_views CASCADE; DROP ROLE agent_ro;"
