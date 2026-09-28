from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    root: Path
    backend: str
    chat_model: str
    embedding_model: str
    chunk_size: int = 900
    chunk_overlap: int = 120
    top_k: int = 4
    service_version: str = "1.0.0"
    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_experiment: str = "manufacturing-maintenance-rag-api"


def load_settings() -> Settings:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env", override=False)
    backend = os.getenv("RAG_BACKEND", "local").lower()
    if backend not in {"local", "openai"}:
        raise ValueError("RAG_BACKEND must be 'local' or 'openai'")
    if backend == "openai" and not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY is required for the OpenAI backend")
    return Settings(
        root=root,
        backend=backend,
        chat_model=os.getenv("CHAT_MODEL", "gpt-4o-mini"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        service_version=os.getenv("SERVICE_VERSION", "1.0.0"),
        mlflow_tracking_uri=os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"),
        mlflow_experiment=os.getenv("MLFLOW_EXPERIMENT", "manufacturing-maintenance-rag-api"),
    )
