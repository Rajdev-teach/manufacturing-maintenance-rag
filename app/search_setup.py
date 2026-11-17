"""Create an HNSW index without overwriting an incompatible existing index."""

from __future__ import annotations

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration, HnswParameters, SearchField, SearchFieldDataType,
    SearchIndex, SearchableField, SimpleField, VectorSearch, VectorSearchProfile,
)

from app.azure_config import AzureSettings


def index_schema(settings: AzureSettings) -> SearchIndex:
    return SearchIndex(
        name=settings.index_name,
        fields=[
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SearchableField(name="content", type=SearchFieldDataType.String),
            SearchableField(name="title", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="source", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="corpus", type=SearchFieldDataType.String, filterable=True),
            SearchField(
                name="contentVector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=settings.embedding_dimensions,
                vector_search_profile_name="hnsw-default",
            ),
        ],
        vector_search=VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw", parameters=HnswParameters(metric="cosine"))],
            profiles=[VectorSearchProfile(name="hnsw-default", algorithm_configuration_name="hnsw")],
        ),
    )


def validate_index(index: SearchIndex, settings: AzureSettings) -> None:
    fields = {field.name: field for field in index.fields}
    expected = {field.name: field for field in index_schema(settings).fields}
    for name, wanted in expected.items():
        actual = fields.get(name)
        if actual is None or actual.type != wanted.type:
            raise ValueError(f"Index field {name} is incompatible; use a new AZURE_SEARCH_INDEX")
        for flag in ("key", "filterable", "searchable"):
            if getattr(wanted, flag, False) and not getattr(actual, flag, False):
                raise ValueError(f"Index field {name} requires {flag}; use a new AZURE_SEARCH_INDEX")
    vector = fields["contentVector"]
    if vector.vector_search_dimensions != settings.embedding_dimensions or vector.vector_search_profile_name != "hnsw-default":
        raise ValueError("Index vector settings differ from EMBED_DIM/profile; use a new AZURE_SEARCH_INDEX")


def admin_client(settings: AzureSettings) -> SearchIndexClient:
    if not settings.search_admin_key:
        raise ValueError("AZURE_SEARCH_ADMIN_KEY is required for index creation and ingestion")
    return SearchIndexClient(
        settings.search_endpoint, AzureKeyCredential(settings.search_admin_key),
        connection_timeout=5, read_timeout=30, retry_total=2,
    )


def ensure_index(settings: AzureSettings, client: SearchIndexClient | None = None) -> SearchIndex:
    owned = client is None
    client = client or admin_client(settings)
    try:
        try:
            existing = client.get_index(settings.index_name)
        except ResourceNotFoundError:
            try:
                return client.create_index(index_schema(settings))
            except ResourceExistsError:
                existing = client.get_index(settings.index_name)
        validate_index(existing, settings)
        return existing
    finally:
        if owned:
            client.close()


def main() -> None:
    from app.config import load_settings

    settings = load_settings()
    if settings.azure is None:
        raise SystemExit("Set RAG_BACKEND=azure and populate Azure settings first")
    index = ensure_index(settings.azure)
    print(f"Index ready: {index.name}; dimensions={settings.azure.embedding_dimensions}")


if __name__ == "__main__":
    main()
