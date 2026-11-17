"""Export only required Azure settings into a private, ignored dotenv file."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


def az(*arguments: str):
    result = subprocess.run(["az", *arguments, "--output", "json", "--only-show-errors"], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", type=Path, default=Path(".azure-lab/outputs.json"))
    parser.add_argument("--output", type=Path, default=Path(".env.azure"))
    args = parser.parse_args()
    outputs = {key: item["value"] for key, item in json.loads(args.outputs.read_text()).items()}
    group = outputs["resourceGroup"]
    values = az("webapp", "config", "appsettings", "list", "--name", outputs["appServiceName"], "--resource-group", group)
    permitted = {
        "RAG_BACKEND", "SERVICE_VERSION", "MLFLOW_TRACKING_ENABLED", "API_AUTH_TOKEN",
        "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_CHAT_DEPLOYMENT", "AZURE_OPENAI_EMBED_DEPLOYMENT",
        "AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_ADMIN_KEY", "AZURE_SEARCH_INDEX", "EMBED_DIM",
    }
    selected = {item["name"]: item["value"] for item in values if item["name"] in permitted}
    if set(selected) != permitted or any("\n" in value or "\r" in value for value in selected.values()):
        raise RuntimeError("Azure app settings are incomplete or contain unsupported line breaks")
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(args.output, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write("# Generated Azure settings. Never commit or share this file.\n")
        handle.write("\n".join(f"{name}={value}" for name, value in sorted(selected.items())) + "\n")
    print(f"Wrote {len(selected)} settings to {args.output}; secret values were not printed")


if __name__ == "__main__":
    main()
