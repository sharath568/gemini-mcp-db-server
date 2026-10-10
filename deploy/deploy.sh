#!/usr/bin/env bash
# Deploy the MCP server to Cloud Run as a PRIVATE service, next to the AlloyDB free trial cluster
# created by vertex-alloydb-rag (same project). Nothing here bills while idle:
#   - one image build, Cloud Run with min-instances 0, two Secret Manager secrets.
#
#   PROJECT_ID=my-project ./deploy/deploy.sh
#
# Prereqs: the rag-cluster / rag-primary AlloyDB instance and the rag-database-url secret
# (admin DSN) from vertex-alloydb-rag's deploy.sh. Override CLUSTER/INSTANCE/ADMIN_SECRET if yours differ.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
NETWORK="${NETWORK:-default}"
CLUSTER="${CLUSTER:-rag-cluster}"
INSTANCE="${INSTANCE:-rag-primary}"
DB_NAME="${DB_NAME:-postgres}"
ADMIN_SECRET="${ADMIN_SECRET:-rag-database-url}"
SERVICE="${SERVICE:-mcp-db-server}"
SA_NAME="${SA_NAME:-mcp-db-runtime}"
AGENT_SA="${AGENT_SA:-agent-runtime}"   # the ADK agent's service account, granted run.invoker
AR_REPO="${AR_REPO:-gde}"
LABELS="${LABELS:-app=gemini-mcp-db-server,purpose=gde}"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE}:$(date +%Y%m%d-%H%M%S)"

gcloud config set project "$PROJECT_ID" >/dev/null
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com alloydb.googleapis.com

echo "== 1. Database address (private IP of the AlloyDB primary)"
DB_IP=$(gcloud alloydb instances describe "$INSTANCE" --cluster="$CLUSTER" --region="$REGION" \
  --format='value(ipAddress)')
echo "AlloyDB: $DB_IP"

echo "== 2. agent_ro password + DSN in Secret Manager (generated once, reused on redeploy)"
if ! gcloud secrets describe mcp-db-agent-password >/dev/null 2>&1; then
  openssl rand -base64 24 | tr -d '/+=\n' | gcloud secrets create mcp-db-agent-password --data-file=- \
    --labels="$LABELS"
fi
AGENT_PW=$(gcloud secrets versions access latest --secret=mcp-db-agent-password)
DSN="postgresql://agent_ro:${AGENT_PW}@${DB_IP}:5432/${DB_NAME}?application_name=mcp-db-server"
if gcloud secrets describe mcp-db-agent-url >/dev/null 2>&1; then
  printf '%s' "$DSN" | gcloud secrets versions add mcp-db-agent-url --data-file=- >/dev/null
else
  printf '%s' "$DSN" | gcloud secrets create mcp-db-agent-url --data-file=- --labels="$LABELS"
fi
unset AGENT_PW DSN

echo "== 3. Two service accounts: the server can read only the agent_ro DSN;"
echo "      only the one-off setup job can read the admin DSN"
SETUP_SA="mcp-db-setup@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" --display-name="MCP DB server runtime"
gcloud iam service-accounts describe "$SETUP_SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create mcp-db-setup --display-name="MCP DB one-off setup job"
gcloud secrets add-iam-policy-binding mcp-db-agent-url --member="serviceAccount:$SA" \
  --role=roles/secretmanager.secretAccessor >/dev/null
for s in "$ADMIN_SECRET" mcp-db-agent-password; do
  gcloud secrets add-iam-policy-binding "$s" --member="serviceAccount:$SETUP_SA" \
    --role=roles/secretmanager.secretAccessor >/dev/null
done

echo "== 4. Build the image once (used by the setup job and the service)"
gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$AR_REPO" --location="$REGION" --repository-format=docker \
    --labels="$LABELS"
gcloud builds submit --tag "$IMAGE" .

NET_FLAGS=(--region="$REGION" --network="$NETWORK" --subnet=default
           --vpc-egress=private-ranges-only --labels="$LABELS")

echo "== 5. Setup job: sample schema, views, agent_ro role (runs as admin, then exits)"
gcloud run jobs deploy mcp-db-setup --image="$IMAGE" "${NET_FLAGS[@]}" --service-account="$SETUP_SA" \
  --set-secrets="ADMIN_DATABASE_URL=${ADMIN_SECRET}:latest,AGENT_PASSWORD=mcp-db-agent-password:latest" \
  --command=python --args=-m,mcp_db_server.setup_db,--seed --max-retries=0
gcloud run jobs execute mcp-db-setup --region="$REGION" --wait

echo "== 6. MCP server: private, scales to zero"
gcloud run deploy "$SERVICE" --image="$IMAGE" "${NET_FLAGS[@]}" --service-account="$SA" \
  --set-secrets="DATABASE_URL=mcp-db-agent-url:latest" \
  --set-env-vars="HOST=0.0.0.0,ROW_CAP=200,STATEMENT_TIMEOUT_MS=3000,POOL_MAX=5" \
  --no-allow-unauthenticated --cpu=1 --memory=512Mi --concurrency=20 \
  --min-instances=0 --max-instances=2 --timeout=60

if gcloud iam service-accounts describe "${AGENT_SA}@${PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1; then
  gcloud run services add-iam-policy-binding "$SERVICE" --region="$REGION" \
    --member="serviceAccount:${AGENT_SA}@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role=roles/run.invoker >/dev/null
  echo "Granted run.invoker to ${AGENT_SA}"
fi

URL=$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')
cat <<MSG

Deployed (private): $URL/mcp

Try it without an LLM:
  gcloud run services proxy $SERVICE --region $REGION --port 8081 &
  python examples/smoke_client.py http://127.0.0.1:8081/mcp

Audit log:
  gcloud logging read 'resource.labels.service_name="$SERVICE" AND jsonPayload.component="mcp-db-server"' --limit 20

Done for the day? ./deploy/teardown.sh
MSG
