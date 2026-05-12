#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/../.." && pwd)"
mkdir -p "${REPO}/.github/workflows"
cp "${HERE}/../workflows/azure-container-apps-deploy.yml" "${REPO}/.github/workflows/azure-container-apps-deploy.yml"
echo "Installed ${REPO}/.github/workflows/azure-container-apps-deploy.yml"
