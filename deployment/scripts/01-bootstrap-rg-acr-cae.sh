#!/usr/bin/env bash
# Creates resource group, ACR (with admin enabled for simple pulls — prefer managed identity later),
# Log Analytics workspace, and Container Apps environment.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "${SCRIPT_DIR}/_common.sh"

echo "==> Ensuring resource group ${RESOURCE_GROUP} in ${AZURE_LOCATION}"
az group create \
  --name "${RESOURCE_GROUP}" \
  --location "${AZURE_LOCATION}" \
  --output none

echo "==> Creating Azure Container Registry ${ACR_NAME}"
if ! az acr show -g "${RESOURCE_GROUP}" -n "${ACR_NAME}" &>/dev/null; then
  az acr create \
    -g "${RESOURCE_GROUP}" \
    -n "${ACR_NAME}" \
    --sku Basic \
    --admin-enabled true \
    --output none
else
  echo "    ACR exists, skipping create"
fi

echo "==> Log Analytics ${LOG_ANALYTICS_WORKSPACE}"
if ! az monitor log-analytics workspace show -g "${RESOURCE_GROUP}" -n "${LOG_ANALYTICS_WORKSPACE}" &>/dev/null; then
  az monitor log-analytics workspace create \
    -g "${RESOURCE_GROUP}" \
    -n "${LOG_ANALYTICS_WORKSPACE}" \
    -l "${AZURE_LOCATION}" \
    --output none
fi
WORKSPACE_ID="$(az monitor log-analytics workspace show \
  -g "${RESOURCE_GROUP}" \
  -n "${LOG_ANALYTICS_WORKSPACE}" \
  --query customerId -o tsv)"
WORKSPACE_SHARED_KEY="$(az monitor log-analytics workspace get-shared-keys \
  -g "${RESOURCE_GROUP}" \
  -n "${LOG_ANALYTICS_WORKSPACE}" \
  --query primarySharedKey -o tsv)"

echo "==> Container Apps environment ${CONTAINER_APPS_ENV}"
if ! az containerapp env show -g "${RESOURCE_GROUP}" -n "${CONTAINER_APPS_ENV}" &>/dev/null; then
  az containerapp env create \
    -g "${RESOURCE_GROUP}" \
    -n "${CONTAINER_APPS_ENV}" \
    -l "${AZURE_LOCATION}" \
    --logs-workspace-id "${WORKSPACE_ID}" \
    --logs-workspace-key "${WORKSPACE_SHARED_KEY}" \
    --output none
else
  echo "    Environment exists, skipping create"
fi

LOGIN_SERVER="$(get_acr_login_server)"
echo ""
echo "Bootstrap complete."
echo "  ACR login server: ${LOGIN_SERVER}"
echo "  Container Apps env domain: $(get_cae_default_domain)"
