#!/usr/bin/env bash
# Run from Bash/WSL after az login and installing requirements in .venv.
set -euo pipefail
umask 077
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
for executable in az docker python3 git; do
  command -v "$executable" >/dev/null || { echo "Missing prerequisite: $executable" >&2; exit 1; }
done
: "${AZURE_SUBSCRIPTION_ID:?Export AZURE_SUBSCRIPTION_ID first}"
lab_group="${AZURE_RESOURCE_GROUP:-rajdev-rag-lab-rg}"
lab_region="${AZURE_LOCATION:-eastus2}"
lab_owner="${AZURE_OWNER:-Rajdev-teach}"
lab_base="${AZURE_BASE_NAME:-maint}"
lab_python="${AZURE_LAB_PYTHON:-.venv/bin/python}"
[[ -x "$lab_python" ]] || { echo "Create .venv and install requirements.txt first" >&2; exit 1; }
[[ "$lab_base" =~ ^[a-z][a-z0-9]{2,11}$ ]] || { echo "AZURE_BASE_NAME must be 3-12 lowercase letters/digits" >&2; exit 1; }
export AZURE_CHAT_MODEL="${AZURE_CHAT_MODEL:-gpt-4o-mini}"
export AZURE_CHAT_MODEL_VERSION="${AZURE_CHAT_MODEL_VERSION:-2024-07-18}"
export AZURE_EMBED_MODEL="${AZURE_EMBED_MODEL:-text-embedding-3-small}"
export AZURE_EMBED_MODEL_VERSION="${AZURE_EMBED_MODEL_VERSION:-1}"
export AZURE_MODEL_SKU="${AZURE_MODEL_SKU:-Standard}"
export AZURE_MODEL_CAPACITY="${AZURE_MODEL_CAPACITY:-1}"
export AZURE_LAB_IMAGE_TAG="$(git rev-parse --short=12 HEAD)"
az account set --subscription "$AZURE_SUBSCRIPTION_ID"
az account show --query '{subscription:name,id:id,tenant:tenantId}' --output table
docker info >/dev/null
az bicep build --file infra/main.bicep --outfile /dev/null
task_tmp="$(mktemp -d)"
local_container=""
cleanup_temp() {
  if [[ -n "$local_container" ]]; then docker rm -f "$local_container" >/dev/null 2>&1 || true; fi
  rm -rf "$task_tmp"
}
trap cleanup_temp EXIT

# Check the selected region/model versions before creating billable resources.
az cognitiveservices model list --location "$lab_region" --output json > "$task_tmp/models.json"
python3 - "$task_tmp/models.json" <<'PY'
import json, os, sys
catalog = json.load(open(sys.argv[1]))
if isinstance(catalog, dict):
    catalog = catalog.get('value', [])
for kind in ('CHAT', 'EMBED'):
    name = os.environ[f'AZURE_{kind}_MODEL']
    version = os.environ[f'AZURE_{kind}_MODEL_VERSION']
    matches = [entry for entry in catalog if (entry.get('model') or entry).get('name') == name
               and str((entry.get('model') or entry).get('version')) == version]
    if not matches:
        raise SystemExit(f'{name} {version} is unavailable in the selected region; choose a listed model/version')
    available_skus = {sku.get('name') for entry in matches for sku in (entry.get('skus') or (entry.get('model') or {}).get('skus') or [])}
    if available_skus and os.environ['AZURE_MODEL_SKU'] not in available_skus:
        raise SystemExit(f'{name} does not support the selected deployment SKU in this region')
print('Model catalog preflight passed. Subscription quota is still checked by Azure during deployment.')
PY

docker build --build-arg REQUIREMENTS_FILE=requirements-azure.txt \
  --build-arg "BUILD_COMMIT=$AZURE_LAB_IMAGE_TAG" -t rag-api:local .
for provider in Microsoft.CognitiveServices Microsoft.Search Microsoft.ContainerRegistry Microsoft.Web; do
  az provider register --namespace "$provider" --wait --output none
done
if [[ "$(az group exists --name "$lab_group")" == "true" ]]; then
  existing_project="$(az group show --name "$lab_group" --query tags.project --output tsv)"
  existing_owner="$(az group show --name "$lab_group" --query tags.owner --output tsv)"
  [[ "$existing_project" == "manufacturing-maintenance-rag" && "$existing_owner" == "$lab_owner" ]] || {
    echo "Refusing to reuse a resource group without this project's owner tags" >&2; exit 1;
  }
fi
az group create --name "$lab_group" --location "$lab_region" \
  --tags "owner=$lab_owner" "cost-center=${AZURE_COST_CENTER:-learning}" project=manufacturing-maintenance-rag environment=lab --output none
export AZURE_LAB_API_TOKEN="${API_AUTH_TOKEN:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')}"
export AZURE_LAB_BASE="$lab_base" AZURE_LAB_REGION="$lab_region" AZURE_LAB_OWNER="$lab_owner"
export AZURE_LAB_COST_CENTER="${AZURE_COST_CENTER:-learning}"
python3 - "$task_tmp/parameters.json" <<'PY'
import json, os, sys
values = {
    'baseName': os.environ['AZURE_LAB_BASE'], 'location': os.environ['AZURE_LAB_REGION'],
    'owner': os.environ['AZURE_LAB_OWNER'], 'costCenter': os.environ['AZURE_LAB_COST_CENTER'],
    'chatModel': os.environ['AZURE_CHAT_MODEL'], 'chatModelVersion': os.environ['AZURE_CHAT_MODEL_VERSION'],
    'embeddingModel': os.environ['AZURE_EMBED_MODEL'], 'embeddingModelVersion': os.environ['AZURE_EMBED_MODEL_VERSION'],
    'modelSku': os.environ['AZURE_MODEL_SKU'], 'modelCapacity': int(os.environ['AZURE_MODEL_CAPACITY']),
    'imageTag': os.environ['AZURE_LAB_IMAGE_TAG'], 'apiAuthToken': os.environ['AZURE_LAB_API_TOKEN'],
}
json.dump({'parameters': {k: {'value': v} for k, v in values.items()}}, open(sys.argv[1], 'w'))
PY
mkdir -p .azure-lab
az deployment group create --resource-group "$lab_group" --name azure-rag-lab \
  --template-file infra/main.bicep --parameters "@$task_tmp/parameters.json" \
  --query properties.outputs --output json > .azure-lab/outputs.json
unset AZURE_LAB_API_TOKEN
python3 infra/azure_env.py
DOTENV_PATH="$repo_root/.env.azure" "$lab_python" -m app.ingest
DOTENV_PATH="$repo_root/.env.azure" "$lab_python" scripts/verify_azure.py

# The local Azure-backed container must pass before publishing its image.
local_container="$(docker run --rm -d -p 127.0.0.1:8001:8000 --env-file .env.azure rag-api:local)"
DOTENV_PATH="$repo_root/.env.azure" "$lab_python" scripts/smoke_deployment.py \
  --url http://127.0.0.1:8001 --output reports/azure-live/local-container.json
docker rm -f "$local_container" >/dev/null
local_container=""
read -r registry_name registry_server app_name public_url < <(python3 - <<'PY'
import json
d = json.load(open('.azure-lab/outputs.json'))
print(*(d[key]['value'] for key in ('acrName', 'acrLoginServer', 'appServiceName', 'publicUrl')))
PY
)
az acr login --name "$registry_name" --output none
image="$registry_server/rag-api:$AZURE_LAB_IMAGE_TAG"
docker tag rag-api:local "$image"
docker push "$image"
az webapp config container set --resource-group "$lab_group" --name "$app_name" \
  --container-image-name "$image" --container-registry-url "https://$registry_server" --output none
az webapp restart --resource-group "$lab_group" --name "$app_name" --output none
DOTENV_PATH="$repo_root/.env.azure" "$lab_python" scripts/smoke_deployment.py --url "$public_url" --expected-commit "$AZURE_LAB_IMAGE_TAG"
DOTENV_PATH="$repo_root/.env.azure" "$lab_python" scripts/verify_azure.py --url "$public_url"
echo "Azure deployment verified: $public_url"
echo "Next: bash infra/configure-github.sh; retain evidence, then follow the cleanup instructions."
