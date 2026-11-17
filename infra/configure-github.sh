#!/usr/bin/env bash
# Configure the lab's resource-group-scoped SP and ACR credentials without logging values.
set -euo pipefail
umask 077
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
for executable in az gh python3; do command -v "$executable" >/dev/null || { echo "Missing $executable" >&2; exit 1; }; done
gh auth status >/dev/null
deployment_subscription="$(python3 -c "import json; print(json.load(open('.azure-lab/outputs.json'))['subscriptionId']['value'])")"
az account set --subscription "$deployment_subscription"
task_tmp="$(mktemp -d)"
trap 'rm -rf "$task_tmp"' EXIT
read -r lab_group registry_name registry_server app_name < <(python3 - <<'PY'
import json
d = json.load(open('.azure-lab/outputs.json'))
print(*(d[key]['value'] for key in ('resourceGroup', 'acrName', 'acrLoginServer', 'appServiceName')))
PY
)
repository="${GITHUB_REPOSITORY:-Rajdev-teach/manufacturing-maintenance-rag}"
scope="$(az group show --name "$lab_group" --query id --output tsv)"
subscription="$(az account show --query id --output tsv)"
# Create once per lab; cleanup removes the Entra application as well as the resource group.
[[ ! -f .azure-lab/service-principal-app-id ]] || { echo "A lab SP is already recorded; rotate its credentials deliberately instead of creating another" >&2; exit 1; }
gh variable set AZURE_DEPLOY_ENABLED --body false --repo "$repository"
az ad sp create-for-rbac --name "manufacturing-rag-${app_name}" --role Contributor \
  --scopes "$scope" --years 1 --output json > "$task_tmp/sp.json"
python3 - "$task_tmp/sp.json" "$task_tmp/credentials.json" "$subscription" <<'PY'
import json, sys
from pathlib import Path
d = json.load(open(sys.argv[1]))
json.dump({'clientId': d['appId'], 'clientSecret': d['password'], 'tenantId': d['tenant'],
           'subscriptionId': sys.argv[3]}, open(sys.argv[2], 'w'))
Path('.azure-lab/service-principal-app-id').write_text(d['appId'] + '\n')
PY
gh secret set AZURE_CREDENTIALS --repo "$repository" < "$task_tmp/credentials.json"
az acr credential show --name "$registry_name" --output json > "$task_tmp/acr.json"
python3 - "$task_tmp/acr.json" "$task_tmp" <<'PY'
import json, sys
from pathlib import Path
d = json.load(open(sys.argv[1])); root = Path(sys.argv[2])
(root/'ACR_USERNAME').write_text(d['username'])
(root/'ACR_PASSWORD').write_text(d['passwords'][0]['value'])
PY
gh secret set ACR_USERNAME --repo "$repository" < "$task_tmp/ACR_USERNAME"
gh secret set ACR_PASSWORD --repo "$repository" < "$task_tmp/ACR_PASSWORD"
printf '%s' "$registry_server" | gh secret set ACR_LOGIN_SERVER --repo "$repository"
printf '%s' "$app_name" | gh secret set APP_SERVICE_NAME --repo "$repository"
az webapp config appsettings list --resource-group "$lab_group" --name "$app_name" \
  --query "[?name=='API_AUTH_TOKEN'].value | [0]" --output tsv > "$task_tmp/token"
gh secret set API_AUTH_TOKEN --repo "$repository" < "$task_tmp/token"
gh variable set AZURE_RESOURCE_GROUP --body "$lab_group" --repo "$repository"
gh variable set AZURE_DEPLOY_ENABLED --body true --repo "$repository"
echo "Deployment secrets configured; no secret values were printed."
echo "Run: gh workflow run deploy.yml --ref main --repo $repository"
