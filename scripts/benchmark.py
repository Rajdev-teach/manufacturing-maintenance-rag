"""Warm up the API, probe latency, and summarize matching MLflow inference runs."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from mlflow.tracking import MlflowClient

QUESTIONS = (
    "What are the lockout tagout steps before maintenance?",
    "How should a conveyor jam be cleared?",
    "What checks help diagnose bearing vibration?",
)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 3)


def summary(values: list[float]) -> dict[str, float]:
    return {"p50": percentile(values, 0.50), "p95": percentile(values, 0.95), "p99": percentile(values, 0.99)}


def send_query(base_url: str, question: str) -> tuple[float, dict]:
    data = json.dumps({"question": question}).encode()
    request = Request(f"{base_url.rstrip('/')}/query", data=data, headers={"Content-Type": "application/json"})
    start = time.perf_counter()
    with urlopen(request, timeout=60) as response:
        body = json.load(response)
    return (time.perf_counter() - start) * 1000, body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--tracking-uri", default=os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
    parser.add_argument("--experiment", default=os.getenv("MLFLOW_EXPERIMENT", "manufacturing-maintenance-rag-api"))
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("reports/latency.json"))
    args = parser.parse_args()
    if args.count < 2 or args.warmup < 0:
        parser.error("--count must be at least 2 and --warmup cannot be negative")

    for index in range(args.warmup):
        send_query(args.url, QUESTIONS[index % len(QUESTIONS)])

    client_ms: list[float] = []
    request_ids: set[str] = set()
    last_metadata: dict = {}
    for index in range(args.count):
        elapsed, body = send_query(args.url, QUESTIONS[index % len(QUESTIONS)])
        last_metadata = body["metadata"]
        if last_metadata["tracking_status"] != "logged":
            raise RuntimeError("MLflow is unavailable; cannot report MLflow run statistics")
        request_ids.add(last_metadata["request_id"])
        client_ms.append(elapsed)

    tracking = MlflowClient(tracking_uri=args.tracking_uri)
    experiment = tracking.get_experiment_by_name(args.experiment)
    if experiment is None:
        raise RuntimeError(f"MLflow experiment {args.experiment!r} was not found")
    runs = tracking.search_runs([experiment.experiment_id], max_results=1000)
    matches = [run for run in runs if run.data.params.get("request_id") in request_ids]
    if len(matches) != args.count:
        raise RuntimeError(f"Expected {args.count} MLflow runs; found {len(matches)}")

    phase_metrics = {
        key: [float(run.data.metrics[key]) for run in matches]
        for key in ("latency_ms", "retrieval_ms", "generation_ms")
    }
    dominant = max(("retrieval_ms", "generation_ms"), key=lambda key: statistics.mean(phase_metrics[key]))
    result = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "backend": last_metadata["backend"],
        "model": last_metadata["model"],
        "version": last_metadata["version"],
        "warmup_count": args.warmup,
        "measured_count": args.count,
        "unit": "milliseconds",
        "client_latency": summary(client_ms),
        "mlflow_metrics": {key: summary(values) for key, values in phase_metrics.items()},
        "dominant_phase_by_mean": dominant,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
