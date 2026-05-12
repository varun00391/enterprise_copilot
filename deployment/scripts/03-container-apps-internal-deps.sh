#!/usr/bin/env bash
# Qdrant + MinIO as internal-only Container Apps (reachable from other apps in the same environment).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

create_internal_app() {
  local name="$1"
  local image="$2"
  local target_port="$3"
  shift 3
  if az containerapp show -g "${RESOURCE_GROUP}" -n "${name}" &>/dev/null; then
    echo "    ${name} exists — skipping"
    return 0
  fi
  echo "==> Creating ${name}"
  az containerapp create \
    -g "${RESOURCE_GROUP}" \
    -n "${name}" \
    --environment "${CONTAINER_APPS_ENV}" \
    --image "${image}" \
    --ingress internal \
    --target-port "${target_port}" \
    --min-replicas 1 \
    --max-replicas 1 \
    --cpu 0.5 \
    --memory 1.0Gi \
    "$@" \
    --output none
}

create_internal_app "${CONTAINER_APP_QDRANT}" "qdrant/qdrant:latest" 6333

create_internal_app "${CONTAINER_APP_MINIO}" "minio/minio:latest" 9000 \
  --env-vars \
  "MINIO_ROOT_USER=${MINIO_ROOT_USER}" \
  "MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}"

echo ""
DOMAIN="$(get_cae_default_domain)"
echo "Internal hostnames (TLS at ingress; use https:// in app config):"
echo "  QDRANT_URL=https://${CONTAINER_APP_QDRANT}.internal.${DOMAIN}"
echo "  MINIO_ENDPOINT=${CONTAINER_APP_MINIO}.internal.${DOMAIN}"
echo "  MINIO_SECURE=true"
