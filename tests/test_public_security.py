"""Check observable public API protections without attacking a live service."""
import asyncio
import json
from fastapi.testclient import TestClient
from app.main import create_app
from app.public_security import PublicDemoSecurity


def secured(monkeypatch, **options):
    monkeypatch.setenv('RAG_BACKEND', 'local')
    monkeypatch.setenv('MLFLOW_TRACKING_ENABLED', 'false')
    app = create_app(expose_docs=False)
    app.add_middleware(PublicDemoSecurity, **options)
    return TestClient(app)


def test_browser_security_headers_and_hidden_docs(monkeypatch):
    with secured(monkeypatch) as client:
        for path in ['/health', '/docs', '/redoc', '/openapi.json']:
            response = client.get(path)
            assert response.headers['x-frame-options'] == 'DENY'
            assert response.headers['x-content-type-options'] == 'nosniff'
            assert "script-src 'self'" in response.headers['content-security-policy']
            assert response.headers['cache-control'] == 'no-store'
            assert response.status_code == (200 if path == '/health' else 404)


def test_query_accepts_same_origin_and_rejects_cross_site(monkeypatch):
    with secured(monkeypatch) as client:
        query = {'question': 'What fields belong in an asset record?'}
        assert client.post('/query', json=query, headers={'Origin': 'http://testserver'}).status_code == 200
        assert client.post('/query', json=query, headers={'Origin': 'https://unrelated.example'}).status_code == 403
        assert client.post('/query', json=query, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
        assert client.post('/query', content='question=example', headers={'Content-Type': 'application/x-www-form-urlencoded'}).status_code == 415


def test_large_requests_rejected_before_json_processing(monkeypatch):
    with secured(monkeypatch) as client:
        response = client.post('/query', json={'question': 'x' * 5000})
        assert response.status_code == 413
        assert response.headers['x-content-type-options'] == 'nosniff'


def test_streamed_body_cannot_bypass_declared_length():
    called = []
    async def downstream(scope, receive, send):
        called.append(True)
    app = PublicDemoSecurity(downstream, body_limit=10)
    messages = iter([{'type': 'http.request', 'body': b'123456', 'more_body': True}, {'type': 'http.request', 'body': b'789012', 'more_body': False}])
    sent = []
    async def receive():
        return next(messages)
    async def send(message):
        sent.append(message)
    asyncio.run(app({'type': 'http', 'path': '/query', 'method': 'POST', 'headers': [(b'content-type', b'application/json')], 'client': ('127.0.0.1', 1)}, receive, send))
    assert not called
    assert sent[0]['status'] == 413


def test_rate_limit_returns_retry_after_and_recovers(monkeypatch):
    clock = [0.0]
    with secured(monkeypatch, per_client=2, clock=lambda: clock[0]) as client:
        query = {'question': 'How is MTBF calculated?'}
        assert client.post('/query', json=query).status_code == 200
        assert client.post('/query', json=query).status_code == 200
        limited = client.post('/query', json=query)
        assert limited.status_code == 429 and limited.headers['retry-after'] == '60'
        clock[0] = 61
        assert client.post('/query', json=query).status_code == 200


def test_configured_server_token_is_enforced(monkeypatch):
    monkeypatch.setenv('API_AUTH_TOKEN', 'test-only-value-that-is-at-least-24-characters')
    with secured(monkeypatch) as client:
        query = {'question': 'How is MTBF calculated?'}
        assert client.post('/query', json=query).status_code == 401
        assert client.post('/query', json=query, headers={'Authorization': 'Bearer incorrect'}).status_code == 401
        assert client.post('/query', json=query, headers={'Authorization': 'Bearer test-only-value-that-is-at-least-24-characters'}).status_code == 200
