"""MLflow inference logging; tracking outages do not interrupt answers."""

from __future__ import annotations

import json
import logging

import mlflow

from app.config import Settings
from app.service import Answer

logger = logging.getLogger(__name__)


class InferenceTracker:
    def __init__(self, settings: Settings):
        self.uri = settings.mlflow_tracking_uri
        self.experiment = settings.mlflow_experiment

    def log(
        self, *, request_id: str, question: str, answer: Answer, backend: str,
        model: str, version: str, top_k: int, latency_ms: float,
    ) -> str:
        try:
            mlflow.set_tracking_uri(self.uri)
            mlflow.set_experiment(self.experiment)
            with mlflow.start_run(run_name=request_id):
                mlflow.log_params({
                    "request_id": request_id,
                    "backend": backend,
                    "model": model,
                    "service_version": version,
                    "top_k": top_k,
                })
                mlflow.log_metrics({
                    "latency_ms": latency_ms,
                    "retrieval_ms": answer.retrieval_ms,
                    "generation_ms": answer.generation_ms,
                    "source_count": len(answer.sources),
                })
                mlflow.log_text(
                    json.dumps({"question": question, "answer": answer.text, "sources": answer.sources}, indent=2),
                    "interaction.json",
                )
            return "logged"
        except Exception:
            logger.warning("MLflow tracking unavailable for request %s", request_id, exc_info=True)
            return "unavailable"
