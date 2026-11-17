#!/usr/bin/env bash
# Explicitly name the dedicated lab group; never delete an arbitrary group.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
requested_group="${1:?Usage: bash infra/cleanup.sh EXACT_LAB_RESOURCE_GROUP}"
deployment_subscription="$(python3 -c "import json; print(json.load(open('.azure-lab/outputs.json'))['subscriptionId']['value'])")"
az account set --subscription "$deployment_subscription"
expected_group="$(python3 -c "import json; print(json.load(open('.azure-lab/outputs.json'))['resourceGroup']['value'])")"
[[ "$requested_group" == "$expected_group" ]] || { echo "Resource group does not match this lab's deployment record" >&2; exit 1; }
project="$(az group show --name "$expected_group" --query tags.project --output tsv)"
[[ "$project" == "manufacturing-maintenance-rag" ]] || { echo "Missing project tag; refusing deletion" >&2; exit 1; }
repository="${GITHUB_REPOSITORY:-Rajdev-teach/manufacturing-maintenance-rag}"
if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  gh variable set AZURE_DEPLOY_ENABLED --body false --repo "$repository"
else
  echo "Disable AZURE_DEPLOY_ENABLED in GitHub before cleanup; gh authentication is required" >&2
  exit 1
fi
az group delete --name "$expected_group" --yes
[[ "$(az group exists --name "$expected_group")" == "false" ]] || { echo "Deletion not finished" >&2; exit 1; }
if [[ -f .azure-lab/service-principal-app-id ]]; then
  az ad app delete --id "$(cat .azure-lab/service-principal-app-id)"
fi
for name in AZURE_CREDENTIALS ACR_LOGIN_SERVER ACR_USERNAME ACR_PASSWORD APP_SERVICE_NAME API_AUTH_TOKEN; do
  if gh secret list --repo "$repository" --json name --jq '.[].name' | grep -Fxq -- "$name"; then
    gh secret delete "$name" --repo "$repository"
  fi
done
rm -f .env.azure .azure-lab/service-principal-app-id
echo "Removed the lab resource group and its recorded Entra application; automatic deployment is disabled."
echo "Verify Azure's resource list and Cost Management for unrelated or orphaned resources."
