#!/usr/bin/env bash
# Registers an Entra App + federated credential for GitHub Actions (OIDC), grants Contributor on the RG
# and AcrPush on ACR. Re-run-safe.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

: "${GITHUB_REPO:?Set GITHUB_REPO in azure.env (owner/repo, lowercase)}"
if [[ "${GITHUB_REPO}" =~ [A-Z] ]]; then
  echo "GITHUB_REPO must be lowercase (e.g. myorg/repo-name)."
  exit 1
fi

DISPLAY_NAME="${AZURE_CI_APP_NAME:-github-actions-orgmind-deploy}"
SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
TENANT_ID="$(az account show --query tenantId -o tsv)"

CLIENT_ID="$(az ad app list --filter "displayName eq '${DISPLAY_NAME}'" --query '[0].appId' -o tsv)"

if [[ -z "${CLIENT_ID}" || "${CLIENT_ID}" == "None" ]]; then
  CLIENT_ID="$(az ad app create --display-name "${DISPLAY_NAME}" --query appId -o tsv)"
fi

APP_OBJECT_ID="$(az ad app show --id "${CLIENT_ID}" --query id -o tsv)"

if ! az ad sp show --id "${CLIENT_ID}" &>/dev/null; then
  az ad sp create --id "${CLIENT_ID}" --output none
fi

SP_OID="$(az ad sp show --id "${CLIENT_ID}" --query id -o tsv)"

RG_SCOPE="$(az group show --name "${RESOURCE_GROUP}" --query id -o tsv)"
ACR_ID="$(az acr show --name "${ACR_NAME}" --resource-group "${RESOURCE_GROUP}" --query id -o tsv)"

az role assignment create \
  --assignee-object-id "${SP_OID}" \
  --assignee-principal-type ServicePrincipal \
  --role Contributor \
  --scope "${RG_SCOPE}" \
  --output none || true

az role assignment create \
  --assignee-object-id "${SP_OID}" \
  --assignee-principal-type ServicePrincipal \
  --role AcrPush \
  --scope "${ACR_ID}" \
  --output none || true

FID_NAME="gha-main"
FID_SUBJECT="repo:${GITHUB_REPO}:ref:refs/heads/main"

FID_COUNT="$(az ad app federated-credential list \
  --id "${APP_OBJECT_ID}" \
  --query "[?name=='gha-main'] | length(@)" \
  -o tsv 2>/dev/null || echo 0)"

if [[ "${FID_COUNT:-0}" =~ ^[0-9]+$ ]] && [[ "${FID_COUNT}" -gt 0 ]]; then
  echo "Federated credential ${FID_NAME} already exists."
else
  PARAM_JSON="$(mktemp)"; chmod 600 "${PARAM_JSON}"
  trap 'rm -f "${PARAM_JSON}"' EXIT
  cat >"${PARAM_JSON}" <<EOF_JSON
{"name":"${FID_NAME}","issuer":"https://token.actions.githubusercontent.com","subject":"${FID_SUBJECT}","audiences":["api://AzureADTokenExchange"],"description":"GitHub Actions OIDC (${GITHUB_REPO} main branch)"}
EOF_JSON

  az ad app federated-credential create \
    --id "${APP_OBJECT_ID}" \
    --parameters "${PARAM_JSON}" \
    --output none

  echo "Created federated credential for ${FID_SUBJECT}"
fi

cat <<TXT

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Configure GitHub (Repository → Settings → Secrets and variables → Actions):

  Secrets → New repository secrets:
    AZURE_CLIENT_ID     = ${CLIENT_ID}
    AZURE_TENANT_ID     = ${TENANT_ID}
    AZURE_SUBSCRIPTION_ID = ${SUBSCRIPTION_ID}

  Variables → New repository variables (used by workflows/azure-container-apps-deploy.yml):
    AZURE_RESOURCE_GROUP      = ${RESOURCE_GROUP}
    AZURE_LOCATION            = ${AZURE_LOCATION}
    AZURE_ACR_NAME            = ${ACR_NAME}
    AZURE_CONTAINER_APPS_ENV   = ${CONTAINER_APPS_ENV}
    AZURE_CONTAINER_APP_BACKEND  = ${CONTAINER_APP_BACKEND}
    AZURE_CONTAINER_APP_FRONTEND = ${CONTAINER_APP_FRONTEND}
    IMAGE_BACKEND_REPO        = ${IMAGE_BACKEND}
    IMAGE_FRONTEND_REPO       = ${IMAGE_FRONTEND}

Then copy deployment/workflows/azure-container-apps-deploy.yml into .github/workflows/ (repo root), or run:
  ./deployment/scripts/install-github-workflow.sh

Deployments run on pushes to 'main'; adjust federated credential if you deploy from another branch.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TXT
