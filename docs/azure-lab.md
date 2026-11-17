# End-to-End Enterprise RAG Deployment on Azure

This walkthrough maps the uploaded seven-module Emonics Azure lab to this repository. It keeps the earlier local/MLflow service runnable and adds an Azure-backed implementation under the same `/query` contract.

**Execution status:** Azure code and automation are implemented. Local tests exercise simulated Azure responses with real SDK types. A live Azure deployment, live model calls, a successful deployment workflow, deployment screenshots, and final decommissioning require Azure account access and must be recorded after they actually run. Existing local MLflow screenshots are evidence for the earlier container lab.

## Module I — Azure foundation

Use Bash in WSL, Linux, or macOS. Windows users can run this from WSL with Docker Desktop integration enabled. Install Python 3.11+, Git, Docker Engine 24+/Compose, Azure CLI, and GitHub CLI. Confirm Docker is running. Reserve local port 8001 for the Azure-backed container smoke test; the earlier Docker Compose lab uses 8000/5000.

```bash
git clone https://github.com/Rajdev-teach/manufacturing-maintenance-rag.git
cd manufacturing-maintenance-rag
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
az login
gh auth login
source infra/lab.env.example
export AZURE_SUBSCRIPTION_ID=your-actual-subscription-id
az account set --subscription "$AZURE_SUBSCRIPTION_ID"
az account show --output table
```

Implementation work is isolated on `feat/azure-migration` and submitted through a pull request. After that PR is merged, use `main` for execution and continuous deployment.

The provisioning script creates a dedicated resource group with `owner`, `cost-center`, `project`, and `environment` tags. All Azure resources use the selected `AZURE_LOCATION`. Names include a deterministic suffix for global uniqueness. An existing group must have matching project/owner tags before it can be reused.

**Resources incur charges:** the lab uses Azure OpenAI S0 with chat/embedding usage, Azure AI Search Basic, ACR Basic, and an App Service Linux B1 plan. Do not assume a free student subscription covers every service. Choose the intended subscription and complete Module VII's cleanup after saving evidence. No cloud cost or deployment is implied by committing this code.

## Module II — Azure OpenAI deployments

`infra/main.bicep` declares separate `rag-chat` and `rag-embed` deployments. Example models are `gpt-4o-mini` version `2024-07-18` and `text-embedding-3-small` version `1`. These are configurable examples, not a promise of availability in a particular subscription. Check the current model lifecycle and the subscription's regional catalog:

```bash
az cognitiveservices model list --location "$AZURE_LOCATION" --output json
az cognitiveservices usage list --location "$AZURE_LOCATION" --output table
```

`infra/provision.sh` checks the requested versions/SKU against the regional catalog before provisioning. Quota, subscription permissions, and SKU capacity are additionally enforced by Azure during deployment. Change the model/version/region variables in `infra/lab.env.example` as needed; keep a single region. `Standard` is the lab default deployment SKU; `GlobalStandard` is an explicit alternative with different processing-location implications.

The service calls **deployment names**, not base model names. `scripts/verify_azure.py` sends a chat request and an embedding request, verifies vector dimensionality, and then checks three grounded answers. It writes evidence only after successful live calls.

## Module III — Azure AI Search

`app/search_setup.py` defines the index in version control:

| Field | Purpose |
|---|---|
| `id` | Stable chunk key |
| `content` | Searchable supporting passage |
| `title`, `source` | Citation metadata; filterable |
| `corpus` | Filterable lab-corpus boundary |
| `contentVector` | HNSW/cosine vector field matching `EMBED_DIM` |

The default vector size is 1536 for the example embedding model. The index is created only if missing; incompatible existing field/dimension settings cause a clear failure instead of destructive recreation. Choose a new index name when changing the embedding model/dimensions.

`app/ingest.py` cleans/chunks the six authored Markdown documents, embeds in batches, validates every vector, checks every upload result, and upserts deterministic IDs. After all uploads succeed it removes stale IDs in the named lab corpus. Repeat ingestion after approved document changes. Rebuilding the entire corpus is not part of API startup.

```bash
DOTENV_PATH=.env.azure .venv/bin/python -m app.search_setup
DOTENV_PATH=.env.azure .venv/bin/python -m app.ingest
```

After provisioning, also inspect representative results in Azure AI Search's Search Explorer as requested by the lab. Local tests do not substitute for that portal check.

## Module IV — Refactor and local verification

`app/clients.py` owns Azure clients with finite timeouts/retries. `app/azure_rag.py` embeds each question, retrieves top-k passages from Azure AI Search, builds a context-only prompt, and calls the configured Azure chat deployment. It returns answer, cited chunk IDs, full supporting passages, and phase timings. Empty retrieval returns an explicit uncertainty response. Unexpected service errors become a sanitized HTTP 503.

`app/config.py` validates required settings at startup. Secret values are omitted from dataclass representations. `.env.example` contains names/placeholders only; `.env.azure` and private deployment output are ignored by Git and Docker. An optional query-only Search key can be used for runtime queries; index creation/ingestion requires the admin key.

The Azure deployment disables local MLflow tracking because this lab does not deploy an MLflow server. To retain tracking, point `MLFLOW_TRACKING_URI` at an accessible tracking service and set `MLFLOW_TRACKING_ENABLED=true`. Existing local Docker Compose tracking remains enabled by default.

`infra/azure_env.py` exports the deployed App Service settings to a mode-600 `.env.azure` without printing values. Do not paste this file into GitHub or chat. `DOTENV_PATH` loads it without executing shell contents.

```bash
DOTENV_PATH=.env.azure .venv/bin/python scripts/verify_azure.py
DOTENV_PATH=.env.azure .venv/bin/python -m uvicorn app.main:app --port 8000
```

Send queries with an `Authorization: Bearer <API_AUTH_TOKEN>` header. The provisioning script generates a random token; read it locally from your private settings file when testing Swagger's **Authorize** button.

## Modules V and VI — Container, ACR, and App Service

Run the full bootstrap from the configured, authenticated shell:

```bash
bash infra/provision.sh
```

The script validates Bicep, checks regional models, builds a non-root image, provisions the tagged services, exports private settings, creates/ingests the index, verifies live Azure model calls, and tests the Azure-backed container on localhost:8001. It then logs in to ACR, pushes an immutable Git revision tag, configures App Service, and verifies the public HTTPS endpoint. It prints the public URL and records non-secret outputs under `.azure-lab/outputs.json`.

For a manual build corresponding to Module V:

```bash
docker build --build-arg REQUIREMENTS_FILE=requirements-azure.txt \
  --build-arg BUILD_COMMIT="$(git rev-parse HEAD)" -t rag-api:local .
docker run --rm -p 127.0.0.1:8001:8000 --env-file .env.azure rag-api:local
```

`requirements-azure.txt` excludes local LangChain/FAISS dependencies from the cloud image. The default Docker build still uses `requirements.txt` for the earlier lab. App Service is configured with `WEBSITES_PORT=8000`, HTTPS, TLS 1.2+, `/health`, and externalized settings. Registry admin authentication follows the supplied lab; managed identity/OIDC is the recommended next hardening step.

If startup fails, inspect `az webapp log tail --name <app-name> --resource-group <group>`. Preserve logs privately: platform diagnostics can contain operational configuration. Do not publish keys or dump all app settings.

## Module VII — Continuous deployment, evidence, and cleanup

After a successful bootstrap, configure resource-group-scoped credentials:

```bash
bash infra/configure-github.sh
gh workflow run deploy.yml --ref main --repo Rajdev-teach/manufacturing-maintenance-rag
```

The setup script creates a service principal with Contributor limited to this lab resource group and stores its application ID locally for cleanup. It passes credentials into GitHub over stdin, using private temporary files, without printing them. It configures these secrets:

| GitHub secret | Purpose |
|---|---|
| `AZURE_CREDENTIALS` | Service principal client ID, secret, tenant, and subscription JSON |
| `ACR_LOGIN_SERVER`, `ACR_USERNAME`, `ACR_PASSWORD` | Registry authentication |
| `APP_SERVICE_NAME` | Deployment target |
| `API_AUTH_TOKEN` | Authenticated smoke test |

It also sets `AZURE_RESOURCE_GROUP` and then enables `AZURE_DEPLOY_ENABLED=true`. Until configured, the deployment job is explicitly skipped while validation still runs. A skipped deployment is not a successful Azure deployment.

The workflow runs on pushes to `main` and manual dispatch. It validates code/infrastructure, logs in, builds and pushes a SHA-tagged image, updates App Service, checks health and a grounded query, and verifies that `/info` reports the expected image build. Runs for this environment are serialized.

Successful live verification produces the `azure-deployment-evidence` Actions artifact containing the real HTTP response, an HTML rendering, a response screenshot, and the live FastAPI docs screenshot. Additional bootstrap reports live in ignored `reports/azure-live/`. Download the artifacts and retain the public URL, model/deployment names, workflow run URL, and evidence timestamp. Verify a second small commit auto-deploys; this must actually run after enabling Azure deployment.

Once evidence is saved, finish the lab's decommissioning step:

```bash
bash infra/cleanup.sh rajdev-rag-lab-rg
```

Use the exact group recorded in `.azure-lab/outputs.json` if you selected another name. The script switches to the recorded subscription, verifies the project tag, disables automatic deployment, deletes only the recorded lab group, verifies removal, deletes the recorded Entra application, and removes the deployment secrets/private dotenv file. Keep `.azure-lab/` until cleanup is complete. Check the subscription's resource list and Cost Management for orphans. An Entra application left behind by a failed SP-creation step must be reviewed/deleted separately by its exact lab display name.

## Verification boundary

Run `pytest -q` and `python scripts/evaluate.py` locally. CI additionally compiles Bicep, checks shell syntax, builds both container variants, and smoke-tests API/MLflow. These checks cover code contracts and containers. Azure quotas, permissions, real Search behavior, model availability, deployment, screenshots, a second automatic deployment, and decommissioning remain live-account checks.

## Primary references

- [Azure AI Search vector quickstart](https://learn.microsoft.com/en-us/azure/search/search-get-started-vector)
- [Azure custom-container configuration and port routing](https://learn.microsoft.com/en-us/azure/app-service/configure-custom-container)
- [Deploy containers with GitHub Actions](https://learn.microsoft.com/en-us/azure/app-service/deploy-container-github-action)
- [Regional model catalog command](https://learn.microsoft.com/en-us/cli/azure/cognitiveservices/model)
- [Azure model lifecycle and retirement](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirements)
