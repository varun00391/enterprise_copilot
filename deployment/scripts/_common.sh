#!/usr/bin/env bash
# shellcheck source=deployment/scripts/_common.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${DEPLOYMENT_ROOT}/.." && pwd)"

ENV_FILE="${DEPLOYMENT_ROOT}/azure.env"
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Copy deployment/azure.env.example and fill values."
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "${ENV_FILE}"
set +a

: "${AZURE_SUBSCRIPTION_ID:?Set AZURE_SUBSCRIPTION_ID in azure.env}"
: "${AZURE_LOCATION:?}"
: "${RESOURCE_GROUP:?}"
: "${ACR_NAME:?}"
: "${LOG_ANALYTICS_WORKSPACE:?}"
: "${CONTAINER_APPS_ENV:?}"
: "${CONTAINER_APP_BACKEND:?}"
: "${CONTAINER_APP_FRONTEND:?}"
: "${CONTAINER_APP_QDRANT:?}"
: "${CONTAINER_APP_MINIO:?}"
: "${POSTGRES_SERVER_NAME:?}"
: "${POSTGRES_ADMIN_USER:?}"
: "${POSTGRES_ADMIN_PASSWORD:?}"
: "${POSTGRES_DATABASE:?}"
: "${REDIS_NAME:?}"
: "${MINIO_BUCKET:?}"
: "${MINIO_ROOT_USER:?}"
: "${MINIO_ROOT_PASSWORD:?}"
: "${IMAGE_BACKEND:?}"
: "${IMAGE_FRONTEND:?}"

STATE_FILE="${DEPLOYMENT_ROOT}/.deployment-state.generated"
if [[ -f "${STATE_FILE}" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "${STATE_FILE}"
  set +a
fi

az account set --subscription "${AZURE_SUBSCRIPTION_ID}"

get_acr_login_server() {
  az acr show -g "${RESOURCE_GROUP}" -n "${ACR_NAME}" --query loginServer -o tsv
}

get_cae_default_domain() {
  az containerapp env show -g "${RESOURCE_GROUP}" -n "${CONTAINER_APPS_ENV}" \
    --query properties.defaultDomain -o tsv
}

internal_app_url() {
  local app_name="$1"
  local domain
  domain="$(get_cae_default_domain)"
  echo "https://${app_name}.internal.${domain}"
}
