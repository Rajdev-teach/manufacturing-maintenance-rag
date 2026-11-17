"""Shared Azure OpenAI and AI Search clients with bounded retries and timeouts."""

from __future__ import annotations

import math
from dataclasses import dataclass

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from openai import AzureOpenAI

from app.azure_config import AzureSettings


@dataclass
class AzureClients:
    openai: AzureOpenAI
    search: SearchClient

    def close(self) -> None:
        self.openai.close()
        self.search.close()


def build_azure_clients(settings: AzureSettings) -> AzureClients:
    return AzureClients(
        openai=AzureOpenAI(
            azure_endpoint=settings.openai_endpoint,
            api_key=settings.openai_api_key,
            api_version=settings.api_version,
            timeout=30,
            max_retries=2,
        ),
        search=SearchClient(
            settings.search_endpoint,
            settings.index_name,
            AzureKeyCredential(settings.search_key),
            connection_timeout=5,
            read_timeout=30,
            retry_total=2,
        ),
    )


def validate_vector(vector: list[float], dimensions: int) -> list[float]:
    if len(vector) != dimensions or not all(math.isfinite(value) for value in vector):
        raise ValueError(f"Embedding must contain exactly {dimensions} finite values; check EMBED_DIM and the deployment")
    return vector
