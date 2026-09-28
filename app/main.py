"""Typed FastAPI entrypoint for the containerized RAG service."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request

from app.config import load_settings
from app.schemas import QueryMetadata, QueryRequest, QueryResponse, ServiceInfo
from app.service import create_service
from app.tracking import InferenceTracker

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = load_settings()
        app.state.settings = settings
        app.state.service = create_service(settings)
        app.state.tracker = InferenceTracker(settings)
        logger.info("RAG service ready: backend=%s, version=%s", settings.backend, settings.service_version)
        yield

    app = FastAPI(
        title="Manufacturing Maintenance RAG API",
        version=os.getenv("SERVICE_VERSION", "1.0.0"),
        description="Grounded maintenance answers with source citations and MLflow inference tracking.",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health(request: Request) -> dict[str, str | bool]:
        return {"ok": True, "backend": request.app.state.settings.backend}

    @app.get("/info", response_model=ServiceInfo)
    def info(request: Request) -> ServiceInfo:
        settings = request.app.state.settings
        return ServiceInfo(
            name="manufacturing-maintenance-rag-api",
            version=settings.service_version,
            backend=settings.backend,
            model=request.app.state.service.model_name,
            embedding_model=settings.embedding_model if settings.backend == "openai" else None,
        )

    @app.post("/query", response_model=QueryResponse)
    def query(payload: QueryRequest, request: Request) -> QueryResponse:
        if not payload.question.strip():
            raise HTTPException(status_code=400, detail="Question must not be empty")

        started = time.perf_counter()
        request_id = str(uuid4())
        settings = request.app.state.settings
        service = request.app.state.service
        try:
            answer = service.ask(payload.question.strip(), payload.top_k)
        except Exception:
            logger.exception("RAG inference failed for request %s", request_id)
            raise HTTPException(status_code=503, detail="RAG backend unavailable") from None

        latency_ms = (time.perf_counter() - started) * 1000
        tracking_status = request.app.state.tracker.log(
            request_id=request_id,
            question=payload.question.strip(),
            answer=answer,
            backend=settings.backend,
            model=service.model_name,
            version=settings.service_version,
            top_k=payload.top_k,
            latency_ms=latency_ms,
        )
        return QueryResponse(
            answer=answer.text,
            sources=answer.sources,
            metadata=QueryMetadata(
                request_id=request_id,
                backend=settings.backend,
                model=service.model_name,
                version=settings.service_version,
                latency_ms=round(latency_ms, 3),
                retrieval_ms=round(answer.retrieval_ms, 3),
                generation_ms=round(answer.generation_ms, 3),
                tracking_status=tracking_status,
            ),
        )

    return app


app = create_app()
