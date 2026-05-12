#!/usr/bin/env bash
# Build backend + SPA images remotely in ACR from this repository (runs on Azure build agents).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

cd "${REPO_ROOT}"

LOGIN="$(get_acr_login_server)"
echo "Building ${IMAGE_BACKEND} on ${LOGIN}"

az acr build \
  -g "${RESOURCE_GROUP}" \
  -r "${ACR_NAME}" \
  --image "${IMAGE_BACKEND}:latest" \
  --file backend/Dockerfile \
  backend \
  --output none

echo "Building ${IMAGE_FRONTEND} on ${LOGIN}"
az acr build \
  -g "${RESOURCE_GROUP}" \
  -r "${ACR_NAME}" \
  --image "${IMAGE_FRONTEND}:latest" \
  --file deployment/docker/frontend-acr-two-apps.Dockerfile \
  . \
  --output none

echo ""
echo "Done: ${LOGIN}/${IMAGE_BACKEND}:latest , ${LOGIN}/${IMAGE_FRONTEND}:latest"
