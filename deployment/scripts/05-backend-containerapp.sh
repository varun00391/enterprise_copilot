#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

: "${DATABASE_URL:?Run scripts/02-managed-postgres-redis.sh first}"

LOGIN="$(get_acr_login_server)"
ACR_USER="$(az acr credential show -n "${ACR_NAME}" -g "${RESOURCE_GROUP}" --query username -o tsv)"
ACR_PW="$(az acr credential show -n "${ACR_NAME}" -g "${RESOURCE_GROUP}" --query "passwords[0].value" -o tsv)"
SECRET_KEY="${APP_SECRET_KEY:?Set APP_SECRET_KEY in azure.env (long random secret)}"

DOMAIN="$(get_cae_default_domain)"
QDRANT_URL="https://${CONTAINER_APP_QDRANT}.internal.${DOMAIN}"
MINIO_EP="${CONTAINER_APP_MINIO}.internal.${DOMAIN}"

OPENAI_CHAT="${OPENAI_CHAT_MODEL:-gpt-4o}"
OPENAI_EMBED="${OPENAI_EMBEDDING_MODEL:-text-embedding-3-small}"
OPENAI_URL="${OPENAI_BASE_URL:-https://api.openai.com/v1}"
OPENAI_K="${OPENAI_API_KEY:-}"

GRAPH_FLAG="${GRAPH_RAG_ENABLED:-false}"

BASE_ENV_VARS=(
  "APP_ENV=production"
  "GRAPH_RAG_ENABLED=${GRAPH_FLAG}"
  "MINIO_BUCKET=${MINIO_BUCKET}"
  "MINIO_ACCESS_KEY=${MINIO_ROOT_USER}"
  "MINIO_SECRET_KEY=${MINIO_ROOT_PASSWORD}"
  "MINIO_ENDPOINT=${MINIO_EP}"
  "MINIO_SECURE=true"
  "QDRANT_URL=${QDRANT_URL}"
  "SECRET_KEY=${SECRET_KEY}"
  "OPENAI_BASE_URL=${OPENAI_URL}"
  "OPENAI_CHAT_MODEL=${OPENAI_CHAT}"
  "OPENAI_EMBEDDING_MODEL=${OPENAI_EMBED}"
  "CORS_ORIGINS=https://placeholder.invalid"
  "FRONTEND_PUBLIC_URL=https://placeholder.invalid"
)

if [[ -n "${OPENAI_K}" ]]; then
  BASE_ENV_VARS+=("OPENAI_API_KEY=${OPENAI_K}")
fi

COMMON_CREATE=(
  --name "${CONTAINER_APP_BACKEND}"
  --resource-group "${RESOURCE_GROUP}"
  --environment "${CONTAINER_APPS_ENV}"
  --image "${LOGIN}/${IMAGE_BACKEND}:latest"
  --ingress external
  --target-port 8000
  --min-replicas 1
  --max-replicas 3
  --cpu "2"
  --memory "4Gi"
  --registry-server "${LOGIN}"
  --registry-username "${ACR_USER}"
  --registry-password "${ACR_PW}"
)

secret_db="$(mktemp)" secret_redis="$(mktemp)"
chmod 600 "${secret_db}" "${secret_redis}"
printf '%s' "${DATABASE_URL}" >"${secret_db}"
printf '%s' "${REDIS_URL:?Run 02 script}" >"${secret_redis}"

cleanup() {
  rm -f "${secret_db}" "${secret_redis}"
}
trap cleanup EXIT

if ! az containerapp show -g "${RESOURCE_GROUP}" -n "${CONTAINER_APP_BACKEND}" &>/dev/null; then
  echo "==> Creating backend Container App ${CONTAINER_APP_BACKEND}"
  # shellcheck disable=SC2068
  az containerapp create ${COMMON_CREATE[@]} \
    --secrets "database-url=$(cat "${secret_db}")" "redis-url=$(cat "${secret_redis}")" \
    --env-vars \
      "DATABASE_URL=secretref:database-url" \
      "REDIS_URL=secretref:redis-url" \
      "${BASE_ENV_VARS[@]}" \
    --command bash \
      -c 'cd /app && alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4' \
    --output none
else
  echo "==> Updating backend image + secrets (${CONTAINER_APP_BACKEND})"
  az containerapp secret set \
    -g "${RESOURCE_GROUP}" \
    -n "${CONTAINER_APP_BACKEND}" \
    --secrets "database-url=$(cat "${secret_db}")" "redis-url=$(cat "${secret_redis}")" \
    --output none
  # shellcheck disable=SC2068
  az containerapp update \
    --name "${CONTAINER_APP_BACKEND}" \
    --resource-group "${RESOURCE_GROUP}" \
    --image "${LOGIN}/${IMAGE_BACKEND}:latest" \
    --command bash \
      -c 'cd /app && alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4' \
    --output none
fi

API_HOST="$(az containerapp show -g "${RESOURCE_GROUP}" -n "${CONTAINER_APP_BACKEND}" --query properties.configuration.ingress.fqdn -o tsv)"
echo "Backend URL: https://${API_HOST}"
