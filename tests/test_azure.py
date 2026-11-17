"""Exercise Azure contracts with real SDK models and simulated service responses.

These tests make no cloud calls and do not establish that an Azure deployment exists.
"""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceNotFoundError
from fastapi.testclient import TestClient

from app.azure_config import AzureSettings, load_azure_settings
from app.azure_rag import AzureService
from app.clients import validate_vector
from app.config import load_settings
from app.ingest import ingest_corpus
from app.main import create_app
from app.search_setup import ensure_index, index_schema, validate_index


@pytest.fixture
def azure_environment(monkeypatch):
    values = {
        'RAG_BACKEND': 'azure', 'MLFLOW_TRACKING_ENABLED': 'false',
        'AZURE_OPENAI_ENDPOINT': 'https://example.openai.azure.com',
        'AZURE_OPENAI_API_KEY': 'test-openai-secret',
        'AZURE_OPENAI_CHAT_DEPLOYMENT': 'my-chat-deployment',
        'AZURE_OPENAI_EMBED_DEPLOYMENT': 'my-embedding-deployment',
        'AZURE_SEARCH_ENDPOINT': 'https://example.search.windows.net',
        'AZURE_SEARCH_ADMIN_KEY': 'test-search-secret',
        'EMBED_DIM': '3',
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('API_AUTH_TOKEN', raising=False)
    monkeypatch.delenv('AZURE_SEARCH_QUERY_KEY', raising=False)
    return load_azure_settings()


def fake_clients(passages=None):
    state = SimpleNamespace(embedding_calls=[], search_calls=[], chat_calls=[], closed=False)

    def embed(**kwargs):
        state.embedding_calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[0.1, 0.2, 0.3])
                                     for i in range(len(kwargs['input']))])

    def search(**kwargs):
        state.search_calls.append(kwargs)
        return passages if passages is not None else [
            {'id': 'lockout_tagout-1', 'title': 'Lockout Tagout',
             'source': 'lockout_tagout.md', 'content': 'Verify the zero-energy state.'}
        ]

    def chat(**kwargs):
        state.chat_calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='Verify the zero-energy state [lockout_tagout-1].'))])

    def close():
        state.closed = True

    clients = SimpleNamespace(
        openai=SimpleNamespace(embeddings=SimpleNamespace(create=embed),
                               chat=SimpleNamespace(completions=SimpleNamespace(create=chat))),
        search=SimpleNamespace(search=search), close=close,
    )
    return clients, state


def test_configuration_requires_credentials_and_hides_secret_values(azure_environment, monkeypatch):
    settings = load_settings()
    assert settings.azure is not None and settings.azure.embedding_dimensions == 3
    assert 'test-openai-secret' not in repr(settings)
    assert 'test-search-secret' not in repr(settings)
    monkeypatch.delenv('AZURE_OPENAI_API_KEY')
    with pytest.raises(ValueError, match='AZURE_OPENAI_API_KEY'):
        load_settings()


def test_runtime_accepts_query_only_key_but_index_admin_requires_admin_key(azure_environment, monkeypatch):
    from app.search_setup import admin_client

    monkeypatch.delenv('AZURE_SEARCH_ADMIN_KEY')
    monkeypatch.setenv('AZURE_SEARCH_QUERY_KEY', 'limited-query-key')
    settings = load_azure_settings()
    assert settings.search_key == 'limited-query-key'
    with pytest.raises(ValueError, match='AZURE_SEARCH_ADMIN_KEY'):
        admin_client(settings)


@pytest.mark.parametrize('vector', [[0.1], [0.1, float('nan'), 0.3], [0.1, float('inf'), 0.3]])
def test_invalid_vectors_are_rejected(vector):
    with pytest.raises(ValueError, match='finite values'):
        validate_vector(vector, 3)


def test_existing_index_is_validated_without_overwriting(azure_environment):
    index = index_schema(azure_environment)
    fake = SimpleNamespace(get_index=lambda name: index,
                           create_index=lambda _: pytest.fail('Existing index must not be overwritten'))
    assert ensure_index(azure_environment, fake) is index
    with pytest.raises(ValueError, match='vector settings'):
        validate_index(index, replace(azure_environment, embedding_dimensions=4))


def test_missing_index_is_created_with_hnsw_and_filterable_metadata(azure_environment):
    created = []

    def missing(_):
        raise ResourceNotFoundError('missing')

    fake = SimpleNamespace(get_index=missing, create_index=lambda index: created.append(index) or index)
    index = ensure_index(azure_environment, fake)
    assert created == [index]
    assert index.vector_search.algorithms[0].kind == 'hnsw'
    fields = {field.name: field for field in index.fields}
    assert fields['contentVector'].vector_search_dimensions == 3
    assert fields['source'].filterable and fields['corpus'].filterable


def test_retrieval_uses_deployment_names_and_returns_cited_passages(azure_environment):
    clients, calls = fake_clients()
    result = AzureService(azure_environment, clients).ask('How do I verify zero energy?', top_k=2)
    assert calls.embedding_calls[0]['model'] == 'my-embedding-deployment'
    assert calls.chat_calls[0]['model'] == 'my-chat-deployment'
    assert calls.search_calls[0]['top'] == 2
    assert calls.search_calls[0]['vector_queries'][0].k_nearest_neighbors == 2
    assert calls.search_calls[0]['vector_queries'][0].fields == 'contentVector'
    assert '[lockout_tagout-1]' in calls.chat_calls[0]['messages'][0]['content']
    assert '[lockout_tagout-1]' in result.text
    assert result.sources[0]['content'] == 'Verify the zero-energy state.'
    assert result.retrieval_ms >= 0 and result.generation_ms >= 0


def test_no_passages_refuses_without_calling_chat(azure_environment):
    clients, calls = fake_clients([])
    result = AzureService(azure_environment, clients).ask('Unsupported question', 4)
    assert not result.sources and 'don\'t know' in result.text
    assert not calls.chat_calls


def test_vector_dimension_mismatch_fails_before_search(azure_environment):
    clients, calls = fake_clients()
    service = AzureService(replace(azure_environment, embedding_dimensions=4), clients)
    with pytest.raises(ValueError, match='exactly 4'):
        service.ask('Question', 4)
    assert not calls.search_calls and not calls.chat_calls


def test_ingestion_upserts_stable_ids_and_removes_only_stale_corpus_records(azure_environment, tmp_path):
    (tmp_path / 'procedure.md').write_text('# Procedure\n\nVerify isolation before maintenance.')
    clients, calls = fake_clients()
    stored = {'stale-1': {'id': 'stale-1'}}
    deletions = []

    def upload(documents):
        stored.update({document['id']: document for document in documents})
        return [SimpleNamespace(key=document['id'], succeeded=True) for document in documents]

    def search(**kwargs):
        assert kwargs['filter'] == "corpus eq 'manufacturing-maintenance-v1'"
        return list(stored.values())

    def delete(documents):
        for document in documents:
            deletions.append(document['id'])
            del stored[document['id']]
        return [SimpleNamespace(key=document['id'], succeeded=True) for document in documents]

    clients.search = SimpleNamespace(merge_or_upload_documents=upload, search=search, delete_documents=delete)
    first = ingest_corpus(azure_environment, tmp_path, clients)
    second = ingest_corpus(azure_environment, tmp_path, clients)
    assert first['vectors_upserted'] == second['vectors_upserted'] == 1
    assert len(stored) == 1 and stored['procedure-1']['contentVector'] == [0.1, 0.2, 0.3]
    assert deletions == ['stale-1'] and second['stale_vectors_removed'] == 0


def test_failed_upload_does_not_delete_existing_documents(azure_environment, tmp_path):
    (tmp_path / 'procedure.md').write_text('# Procedure\n\nVerify isolation.')
    clients, _ = fake_clients()
    clients.search = SimpleNamespace(
        merge_or_upload_documents=lambda **kwargs: [SimpleNamespace(key='procedure-1', succeeded=False)],
        search=lambda **kwargs: pytest.fail('No stale deletion after a failed upload'),
    )
    with pytest.raises(RuntimeError, match='rejected document IDs'):
        ingest_corpus(azure_environment, tmp_path, clients)


def test_azure_api_authentication_contract_and_shutdown(azure_environment, monkeypatch):
    token = 'test-bearer-token-at-least-24-characters'
    monkeypatch.setenv('API_AUTH_TOKEN', token)
    clients, calls = fake_clients()
    monkeypatch.setattr('app.azure_rag.build_azure_clients', lambda settings: clients)
    with TestClient(create_app()) as client:
        assert client.get('/health').json() == {'ok': True, 'backend': 'azure'}
        assert client.get('/info').json()['embedding_model'] == 'my-embedding-deployment'
        assert client.post('/query', json={'question': 'Verify zero energy'}).status_code == 401
        response = client.post('/query', json={'question': 'Verify zero energy'},
                               headers={'Authorization': f'Bearer {token}'})
        assert response.status_code == 200
        data = response.json()
        assert data['sources'][0]['content']
        assert data['metadata']['backend'] == 'azure'
        assert data['metadata']['tracking_status'] == 'disabled'
    assert calls.closed


def test_azure_outage_returns_sanitized_503(azure_environment, monkeypatch):
    clients, _ = fake_clients()
    clients.search.search = lambda **kwargs: (_ for _ in ()).throw(RuntimeError('sensitive backend detail'))
    monkeypatch.setattr('app.azure_rag.build_azure_clients', lambda settings: clients)
    with TestClient(create_app()) as client:
        result = client.post('/query', json={'question': 'Verify zero energy'})
    assert result.status_code == 503 and result.json() == {'detail': 'RAG backend unavailable'}
