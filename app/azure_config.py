"""Validated Azure configuration. Secret values are excluded from representations."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith(("replace-", "your-")):
        raise ValueError(f"{name} must be configured for the Azure backend")
    return value


def endpoint(name: str) -> str:
    value = required(name).rstrip("/")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError(f"{name} must be an HTTPS service endpoint without credentials or query parameters")
    return value


@dataclass(frozen=True)
class AzureSettings:
    openai_endpoint: str
    openai_api_key: str = field(repr=False)
    chat_deployment: str
    embed_deployment: str
    search_endpoint: str
    search_key: str = field(repr=False)
    search_admin_key: str = field(default="", repr=False)
    api_version: str = "2024-10-21"
    index_name: str = "maintenance-rag"
    embedding_dimensions: int = 1536
    corpus_name: str = "manufacturing-maintenance-v1"


def load_azure_settings() -> AzureSettings:
    index = os.getenv("AZURE_SEARCH_INDEX", "maintenance-rag").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,126}[a-z0-9]", index) or "--" in index:
        raise ValueError("AZURE_SEARCH_INDEX must be a valid lowercase Azure AI Search index name")
    try:
        dimensions = int(os.getenv("EMBED_DIM", "1536"))
    except ValueError:
        raise ValueError("EMBED_DIM must be an integer") from None
    if not 1 <= dimensions <= 3072:
        raise ValueError("EMBED_DIM must be between 1 and 3072")
    admin_key = os.getenv("AZURE_SEARCH_ADMIN_KEY", "").strip()
    search_key = os.getenv("AZURE_SEARCH_QUERY_KEY", "").strip() or admin_key
    if not search_key:
        raise ValueError("AZURE_SEARCH_QUERY_KEY or AZURE_SEARCH_ADMIN_KEY must be configured")
    return AzureSettings(
        openai_endpoint=endpoint("AZURE_OPENAI_ENDPOINT"),
        openai_api_key=required("AZURE_OPENAI_API_KEY"),
        chat_deployment=required("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        embed_deployment=required("AZURE_OPENAI_EMBED_DEPLOYMENT"),
        search_endpoint=endpoint("AZURE_SEARCH_ENDPOINT"),
        search_key=search_key,
        search_admin_key=admin_key,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        index_name=index,
        embedding_dimensions=dimensions,
    )
