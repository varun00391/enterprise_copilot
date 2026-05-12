#!/usr/bin/env bash
# Deploy the nginx SPA Container App → then align backend CORS + FRONTEND_PUBLIC_URL.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

API_FQDN="$(az containerapp show -g "${RESOURCE_GROUP}" -n "${CONTAINER_APP_BACKEND}" --query properties.configuration.ingress.fqdn -o tsv)"
if [[ -z "${API_FQDN}" ]]; then
  echo "Backend app not found or has no external FQDN. Run 05-backend-containerapp.sh first."
  exit 1
fi

LOGIN="$(get_acr_login_server)"
ACR_USER="$(az acr credential show -n "${ACR_NAME}" -g "${RESOURCE_GROUP}" --query username -o tsv)"
ACR_PW="$(az acr credential show -n "${ACR_NAME}" -g "${RESOURCE_GROUP}" --query "passwords[0].value" -o tsv)"

FRONTEND_IMAGE="${LOGIN}/${IMAGE_FRONTEND}:latest"

if ! az containerapp show -g "${RESOURCE_GROUP}" -n "${CONTAINER_APP_FRONTEND}" &>/dev/null; then
  echo "==> Creating frontend Container App ${CONTAINER_APP_FRONTEND}"
  az containerapp create \
    --name "${CONTAINER_APP_FRONTEND}" \
    --resource-group "${RESOURCE_GROUP}" \
    --environment "${CONTAINER_APPS_ENV}" \
    --image "${FRONTEND_IMAGE}" \
    --ingress external \
    --target-port 80 \
    --min-replicas 1 \
    --max-replicas 3 \
    --cpu "0.5" \
    --memory "1Gi" \
    --registry-server "${LOGIN}" \
    --registry-username "${ACR_USER}" \
    --registry-password "${ACR_PW}" \
    --env-vars "BACKEND_FQDN=${API_FQDN}" \
    --output none
else
  echo "==> Updating frontend Container App (${CONTAINER_APP_FRONTEND})"
  az containerapp update \
    --name "${CONTAINER_APP_FRONTEND}" \
    --resource-group "${RESOURCE_GROUP}" \
    --image "${FRONTEND_IMAGE}" \
    --merge-env-vars "BACKEND_FQDN=${API_FQDN}" \
    --output none
fi

sleep 10
WEB_FQDN="$(az containerapp show -g "${RESOURCE_GROUP}" -n "${CONTAINER_APP_FRONTEND}" --query properties.configuration.ingress.fqdn -o tsv)"
PUBLIC_ORIGIN="https://${WEB_FQDN}"
echo ""
echo "Web URL (users open this): ${PUBLIC_ORIGIN}"

echo "==> Patching backend CORS + FRONTEND_PUBLIC_URL"
az containerapp update \
  --name "${CONTAINER_APP_BACKEND}" \
  --resource-group "${RESOURCE_GROUP}" \
  --merge-env-vars \
    "CORS_ORIGINS=${PUBLIC_ORIGIN}" \
    "FRONTEND_PUBLIC_URL=${PUBLIC_ORIGIN}" \
  --output none

echo "Deployment finished."
echo "  API ingress: https://${API_FQDN}"
echo "  SPA ingress: ${PUBLIC_ORIGIN}"
