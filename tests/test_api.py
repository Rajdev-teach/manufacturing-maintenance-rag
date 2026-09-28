"""Exercise the real offline RAG route, its contract, and tracking failure behavior."""

from fastapi.testclient import TestClient

from app.main import create_app
from app.tracking import InferenceTracker


def test_health_info_and_grounded_query(monkeypatch):
    monkeypatch.setenv("RAG_BACKEND", "local")
    monkeypatch.setattr(InferenceTracker, "log", lambda self, **kwargs: "logged")
    with TestClient(create_app()) as client:
        assert client.get("/health").json() == {"ok": True, "backend": "local"}
        info = client.get("/info").json()
        assert info["model"] == "tf-idf-extractive-v1"
        assert info["embedding_model"] is None

        response = client.post(
            "/query", json={"question": "What are the lockout tagout steps before maintenance?", "top_k": 3}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["answer"]
        assert "verify zero-energy state" in body["answer"]
        assert any(source["source"] == "lockout_tagout.md" for source in body["sources"])
        assert len(body["sources"]) <= 3
        assert body["metadata"]["tracking_status"] == "logged"
        assert body["metadata"]["retrieval_ms"] >= 0
        assert body["metadata"]["generation_ms"] >= 0
        assert body["metadata"]["request_id"]


def test_validation_and_refusal(monkeypatch):
    monkeypatch.setenv("RAG_BACKEND", "local")
    monkeypatch.setattr(InferenceTracker, "log", lambda self, **kwargs: "logged")
    with TestClient(create_app()) as client:
        assert client.post("/query", json={"question": "   "}).status_code == 400
        assert client.post("/query", json={"question": "test", "top_k": 0}).status_code == 422
        assert client.post("/query", json={}).status_code == 422
        response = client.post("/query", json={"question": "Who won the football game?"})
        assert response.status_code == 200
        assert response.json()["sources"] == []


def test_tracking_outage_does_not_break_query(monkeypatch):
    monkeypatch.setenv("RAG_BACKEND", "local")

    def offline(*args, **kwargs):
        raise ConnectionError("tracking server down")

    monkeypatch.setattr("app.tracking.mlflow.set_experiment", offline)
    with TestClient(create_app()) as client:
        response = client.post("/query", json={"question": "How should a conveyor jam be cleared?"})
    assert response.status_code == 200
    assert response.json()["metadata"]["tracking_status"] == "unavailable"
    assert response.json()["sources"]


def test_inference_failure_has_sanitized_response(monkeypatch):
    monkeypatch.setenv("RAG_BACKEND", "local")
    with TestClient(create_app()) as client:
        def broken(*args, **kwargs):
            raise RuntimeError("internal backend details")

        monkeypatch.setattr(client.app.state.service, "ask", broken)
        response = client.post("/query", json={"question": "Why is a bearing hot?"})
    assert response.status_code == 503
    assert response.json() == {"detail": "RAG backend unavailable"}


def test_openai_adapter_reports_model_and_citations_without_network():
    from types import SimpleNamespace

    from app.service import OpenAIService

    service = OpenAIService.__new__(OpenAIService)
    service.model_name = "test-chat-model"
    document = SimpleNamespace(
        page_content="Inspect vibration and lubricant condition.",
        metadata={"chunk_id": "bearing-1", "title": "Bearing Diagnostics", "source": "bearing.md"},
    )
    service.store = SimpleNamespace(max_marginal_relevance_search=lambda *args, **kwargs: [document])
    service.llm = SimpleNamespace(invoke=lambda messages: SimpleNamespace(content="Inspect vibration [bearing-1]."))

    answer = service.ask("How do I inspect this bearing?", top_k=2)
    assert answer.sources == [{"id": "bearing-1", "title": "Bearing Diagnostics", "source": "bearing.md"}]
    assert "bearing-1" in answer.text
    assert answer.retrieval_ms >= 0 and answer.generation_ms >= 0
