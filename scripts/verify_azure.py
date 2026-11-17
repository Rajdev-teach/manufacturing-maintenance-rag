"""Check live Azure deployments, retrieval, generation, and the deployed API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.azure_rag import AzureService  # noqa: E402
from app.clients import build_azure_clients, validate_vector  # noqa: E402
from app.config import load_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Also verify the HTTPS App Service endpoint")
    parser.add_argument("--report", type=Path, default=ROOT / "reports/azure-live/verification.json")
    args = parser.parse_args()
    configuration = load_settings()
    settings = configuration.azure
    if settings is None:
        parser.error("Set RAG_BACKEND=azure and configure Azure credentials")
    if args.url and not args.url.startswith("https://"):
        parser.error("--url must use HTTPS")
    clients = build_azure_clients(settings)
    try:
        embedding = clients.openai.embeddings.create(
            model=settings.embed_deployment, input=["maintenance"], dimensions=settings.embedding_dimensions
        )
        validate_vector(embedding.data[0].embedding, settings.embedding_dimensions)
        ping = clients.openai.chat.completions.create(
            model=settings.chat_deployment, messages=[{"role": "user", "content": "Reply with OK"}], max_tokens=10
        )
        if not ping.choices[0].message.content:
            raise RuntimeError("Chat deployment returned no content")
        service = AzureService(settings, clients)
        examples = []
        for question in (
            "What steps verify zero energy before maintenance?",
            "How should a conveyor jam be cleared?",
            "What fields belong in an asset record?",
        ):
            answer = service.ask(question, top_k=4)
            if not answer.sources or not any(f"[{source['id']}]" in answer.text for source in answer.sources):
                raise RuntimeError("Grounded response did not include a retrieved source citation")
            examples.append({"question": question, "answer": answer.text, "sources": answer.sources})
        report = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "backend": "azure", "chat_deployment": settings.chat_deployment,
            "embedding_deployment": settings.embed_deployment,
            "embedding_dimensions": settings.embedding_dimensions, "examples": examples,
        }
        if args.url:
            base = args.url.rstrip("/")
            for path in ("/health", "/info"):
                with urlopen(base + path, timeout=60) as response:
                    body = json.load(response)
                if body.get("backend") != "azure":
                    raise RuntimeError("Live API is not running the Azure backend")
            token = configuration.api_auth_token or os.getenv("API_AUTH_TOKEN", "")
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
            request = Request(base + "/query", json.dumps({"question": examples[0]["question"]}).encode(), headers)
            with urlopen(request, timeout=120) as response:
                result = json.load(response)
            if result["metadata"]["backend"] != "azure" or not result["sources"]:
                raise RuntimeError("Live query failed Azure/citation checks")
            report.update({"url": base, "live_response": result})
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(f"PASS: Azure chat, {settings.embedding_dimensions}-dimension embeddings, and three cited answers")
        if args.url:
            print(f"PASS: deployed API {args.url}")
        print(f"Evidence saved to {args.report}")
    finally:
        clients.close()


if __name__ == "__main__":
    main()
