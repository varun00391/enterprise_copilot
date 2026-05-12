# Azure deployment — Container Apps + ACR + Postgres + Redis

This folder provisions a production-style footprint for OrgMind:

- **Azure Container Registry (ACR)** — builds Docker images *on Azure* (`az acr build`).
- **Azure Container Apps** — scales to zero capable “serverless” containers (consumption billing).
  - Two public apps: FastAPI backend + nginx SPA (`deployment/docker/frontend-acr-two-apps.Dockerfile`).
  - Internal apps: **Qdrant** (vectors) + **MinIO** (S3-compatible object storage).
- **Azure Database for PostgreSQL Flexible Server** + **Azure Cache for Redis**.

Graph RAG (Neo4j) is left off by default (`GRAPH_RAG_ENABLED=false`). Add Neo4j later or enable Graph manually.

Security note: scripts open Postgres to broad IP ranges so Container Apps egress can reach the database without VNet injection. Replace with **private endpoints + Integrated VNet** before production workloads.

---

## Prerequisites

Install [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) and extensions:

```bash
az upgrade
az extension add --name containerapp --upgrade
az login
```

Register providers once per subscription:

```bash
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az provider register --namespace Microsoft.DBforPostgreSQL
az provider register --namespace Microsoft.Cache
```

---

## 1. Configure secrets locally

From the repo root:

```bash
cp deployment/azure.env.example deployment/azure.env
```

Edit `deployment/azure.env` — set globally unique names (`ACR_NAME`, `POSTGRES_SERVER_NAME`, `REDIS_NAME`, …), passwords, **`APP_SECRET_KEY`**, **`OPENAI_API_KEY`**, and optional OAuth keys you already use locally.

Ensure `deployment/azure.env` stays private (globbed in `.gitignore`).

---

## 2. Run numbered scripts from your laptop

Scripts load `deployment/azure.env` automatically.

```bash
chmod +x deployment/scripts/*.sh
./deployment/scripts/01-bootstrap-rg-acr-cae.sh
./deployment/scripts/02-managed-postgres-redis.sh          # writes deployment/.deployment-state.generated
./deployment/scripts/03-container-apps-internal-deps.sh   # qdrant + minio internal
./deployment/scripts/04-acr-build.sh                    # queues remote builds on ACR
./deployment/scripts/05-backend-containerapp.sh
./deployment/scripts/06-frontend-containerapp.sh       # SPA URL + patches backend CORS
```

Open the SPA URL printed at the end. API docs: `https://<backend-fqdn>/api/docs`.

---

## 3. Automate pushes with GitHub Actions

1. Set `GITHUB_REPO` in `deployment/azure.env` (e.g. `my-org/enterprise_copilot`).
2. Run `./deployment/scripts/07-github-actions-identity.sh`.
3. Add the emitted **Secrets** (client id / tenant id / subscription id).
4. Add the printed **repository Variables** (`AZURE_*`, image repo names — without tags).
5. Install the workflow (GitHub only runs workflows under `.github/workflows/`):

   ```bash
   ./deployment/scripts/install-github-workflow.sh
   ```

6. Push to `main`; the workflow runs `az acr build` twice, pushes tags `:latest`, and updates both Container Apps. Adjust the federated credential in `07` if you branch from something other than `main`.

---

## Layout

| Path | Purpose |
|------|---------|
| `azure.env.example` | Template copied to ignored `azure.env`. |
| `scripts/_common.sh` | Shared env loader + helpers. |
| `scripts/01–07` | One-time / occasional Azure provisioning. |
| `scripts/install-github-workflow.sh` | Copies workflow into `.github/workflows/`. |
| `docker/frontend-acr-two-apps.Dockerfile` | SPA image; nginx terminates TLS proxy to HTTPS backend ingress. |
| `docker/default.confACA.template` + `nginx-frontend-acr-render.sh` | Builds nginx.conf with injected backend hostname. |
| `workflows/azure-container-apps-deploy.yml` | Canonical workflow file (installed by script above). |

After changing infrastructure names or regions, re-run relevant scripts — they skip resources that already exist where possible.
