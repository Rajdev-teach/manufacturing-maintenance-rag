"""Batch embedding and idempotent corpus upload to Azure AI Search."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

from app.azure_config import AzureSettings
from app.clients import AzureClients, build_azure_clients, validate_vector
from app.corpus import load_corpus
from app.search_setup import ensure_index


def check_upload(results) -> None:
    failed = [result.key for result in results if not result.succeeded]
    if failed:
        raise RuntimeError(f"Azure Search rejected document IDs: {', '.join(failed)}")


def ingest_corpus(settings: AzureSettings, directory: Path, clients: AzureClients, batch_size: int = 16) -> dict:
    if not 1 <= batch_size <= 100:
        raise ValueError("batch_size must be between 1 and 100")
    # Load and validate before any remote writes. IDs are deterministic across runs.
    chunks = load_corpus(directory)
    active_ids = {chunk.chunk_id for chunk in chunks}
    started = time.perf_counter()
    for offset in range(0, len(chunks), batch_size):
        batch = chunks[offset:offset + batch_size]
        response = clients.openai.embeddings.create(
            model=settings.embed_deployment,
            input=[chunk.text for chunk in batch],
            dimensions=settings.embedding_dimensions,
        )
        vectors = {item.index: item.embedding for item in response.data}
        if set(vectors) != set(range(len(batch))):
            raise ValueError("Embedding response did not cover every input chunk")
        documents = [
            {"id": chunk.chunk_id, "title": chunk.title, "source": chunk.source,
             "content": chunk.text, "corpus": settings.corpus_name,
             "contentVector": validate_vector(vectors[index], settings.embedding_dimensions)}
            for index, chunk in enumerate(batch)
        ]
        check_upload(clients.search.merge_or_upload_documents(documents=documents))

    # Remove stale IDs only after all uploads succeed, and only from this lab corpus.
    previous = clients.search.search(
        search_text="*", filter=f"corpus eq '{settings.corpus_name}'", select=["id"]
    )
    stale = [{"id": hit["id"]} for hit in previous if hit["id"] not in active_ids]
    for offset in range(0, len(stale), batch_size):
        check_upload(clients.search.delete_documents(documents=stale[offset:offset + batch_size]))
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "index": settings.index_name,
        "corpus": settings.corpus_name,
        "documents": len({chunk.source for chunk in chunks}),
        "vectors_upserted": len(chunks),
        "stale_vectors_removed": len(stale),
        "embedding_dimensions": settings.embedding_dimensions,
        "duration_seconds": round(time.perf_counter() - started, 3),
    }


def main() -> None:
    from app.config import load_settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--report", type=Path, default=Path("reports/azure-live/ingestion.json"))
    args = parser.parse_args()
    configuration = load_settings()
    settings = configuration.azure
    if settings is None or not settings.search_admin_key:
        raise SystemExit("Set RAG_BACKEND=azure and AZURE_SEARCH_ADMIN_KEY before ingesting")
    ensure_index(settings)
    clients = build_azure_clients(settings)
    # A query-only runtime key may be configured; ingestion always requires the admin key.
    clients.search.close()
    clients.search = SearchClient(
        settings.search_endpoint, settings.index_name, AzureKeyCredential(settings.search_admin_key),
        connection_timeout=5, read_timeout=30, retry_total=2,
    )
    try:
        report = ingest_corpus(settings, configuration.root / "data" / "clean", clients, args.batch_size)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        clients.close()


if __name__ == "__main__":
    main()
