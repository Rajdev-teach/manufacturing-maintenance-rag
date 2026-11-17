"""Verify a local container or live App Service without printing authorization tokens."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from dotenv import load_dotenv


def smoke(base: str, token: str, backend: str, attempts: int = 30, expected_commit: str | None = None) -> dict:
    base = base.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
        raise ValueError("Use HTTPS, or HTTP on the local loopback interface")
    for attempt in range(attempts):
        try:
            with urlopen(base + "/health", timeout=15) as response:
                health = json.load(response)
            with urlopen(base + "/info", timeout=15) as response:
                info = json.load(response)
            if (health.get("ok") and health.get("backend") == backend and info.get("backend") == backend
                    and (not expected_commit or info.get("build_commit") == expected_commit)):
                break
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            pass
        if attempt == attempts - 1:
            raise RuntimeError("API did not become healthy with the expected backend and image build")
        time.sleep(5)
    request = Request(
        base + "/query",
        json.dumps({"question": "What steps verify zero energy before maintenance?", "top_k": 4}).encode(),
        {"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urlopen(request, timeout=120) as response:
        answer = json.load(response)
    if answer["metadata"]["backend"] != backend or not answer.get("answer") or not answer.get("sources"):
        raise RuntimeError("Query did not return a grounded answer from the requested backend")
    if not any(source.get("content") for source in answer["sources"]):
        raise RuntimeError("Query omitted supporting passages")
    if backend == "azure" and not any(f"[{source['id']}]" in answer["answer"] for source in answer["sources"]):
        raise RuntimeError("Azure answer did not cite a retrieved chunk")
    return {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "url": base,
            "backend": backend, "info": info, "response": answer}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--backend", default="azure", choices=["azure", "local", "openai"])
    parser.add_argument("--attempts", type=int, default=30)
    parser.add_argument("--expected-commit")
    parser.add_argument("--output", type=Path, default=Path("reports/azure-live/live-response.json"))
    args = parser.parse_args()
    if args.attempts < 1:
        parser.error("--attempts must be positive")
    load_dotenv(os.getenv("DOTENV_PATH", ".env"), override=False)
    report = smoke(args.url, os.getenv("API_AUTH_TOKEN", ""), args.backend, args.attempts, args.expected_commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS: health, model info, grounded query and supporting passages at {args.url}")


if __name__ == "__main__":
    main()
