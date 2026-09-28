# Manufacturing Maintenance RAG API — Containerized ML Microservice with MLflow

A source-citing question-answering service for a small, curated manufacturing maintenance corpus. This repository implements the Emonics AI Lab: a typed FastAPI interface, MLflow inference tracking, a non-root Docker image, functional and latency verification, and documented architecture/UML diagrams.

The default `local` backend is fully offline: TF-IDF retrieval plus an extractive answer. The optional `openai` backend builds an OpenAI embedding/FAISS index once at startup and generates answers with a chat model. The two modes are labeled in every response and MLflow run; results from one mode should not be presented as results from the other.

## Architecture

The request flows through validation, a selected RAG backend, a best-effort MLflow tracking helper, and a typed response. The service stays available if tracking goes down. See the [system flowchart and UML sequence, activity, and class diagrams](docs/architecture.md).

The six source documents live in `data/clean/`; `data/manifest.csv` lists their titles, owners, and dates. The API exposes chunk ID, title, and source filename with each answer.

## Prerequisites

- Python 3.10+ for local development (Docker uses Python 3.11)
- Docker Engine 24+ with Docker Compose v2 for the container workflow
- Free local ports 8000 (API) and 5000 (MLflow)
- About 4 GB of disk space for dependencies and images
- An OpenAI API key **only** for `RAG_BACKEND=openai`

## Run end to end with Docker

```bash
git clone https://github.com/Rajdev-teach/manufacturing-maintenance-rag.git
cd manufacturing-maintenance-rag
docker compose up --build -d --wait
```

Open the [FastAPI docs](http://127.0.0.1:8000/docs) and [MLflow UI](http://127.0.0.1:5000). The default mode is `local`, so no key is needed. Both published ports bind to your computer's loopback interface.

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/info
curl --fail -X POST http://127.0.0.1:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"What are the lockout tagout steps before maintenance?","top_k":3}'
```

`POST /query` returns `answer`, `sources`, and `metadata` with the request ID, actual backend/model/version, retrieval and generation times, total inference time, and `tracking_status`. `top_k` must be 1–10. A blank question returns HTTP 400; invalid JSON fields return 422. If inference fails, the API returns a sanitized HTTP 503. An MLflow outage leaves the answer available and changes `tracking_status` to `unavailable`.

On Windows PowerShell, use `Invoke-RestMethod` rather than the PowerShell `curl` alias:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/query -ContentType 'application/json' -Body '{"question":"How should a conveyor jam be cleared?"}'
```

After several queries, select the `manufacturing-maintenance-rag-api` experiment in MLflow. Each request logs `backend`, `model`, `service_version`, `top_k`, and `request_id` as parameters; `latency_ms`, `retrieval_ms`, `generation_ms`, and `source_count` as metrics; and a JSON interaction artifact. Stop the stack with `docker compose down`. The `mlflow-data` volume retains runs; `docker compose down -v` removes that volume.

### Optional OpenAI/FAISS mode

Copy `.env.example` to `.env`, set `RAG_BACKEND=openai`, and replace the example `OPENAI_API_KEY` value with your key. Then run `docker compose up --build -d --wait`. Do not commit `.env`. Startup builds the embedding index once; the corpus is intentionally small. The API is stateless, while the original local CLI still supports follow-up history.

## Run locally without Docker

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start MLflow in one terminal from the repository root:

```bash
mlflow server --backend-store-uri sqlite:///mlflow.db \
  --artifacts-destination ./mlartifacts --host 127.0.0.1 --port 5000
```

Start the API in another terminal (activate the same environment first):

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The API defaults to `MLFLOW_TRACKING_URI=http://localhost:5000`. For other environments, set `MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT`, `RAG_BACKEND`, `CHAT_MODEL`, `EMBEDDING_MODEL`, and `SERVICE_VERSION` as needed. `OPENAI_API_KEY` is required only in OpenAI mode. Local `.env` is loaded without overriding variables already supplied by the environment. No secrets or generated indices are committed.

## Verify and measure

```bash
pytest -q
python scripts/evaluate.py
python scripts/benchmark.py --warmup 3 --count 30
```

The evaluation checks retrieval and refusal behavior against 15 authored cases. The benchmark first warms up the service, measures client response times, then matches the measured request IDs to MLflow runs to calculate p50, p95, and p99 for total inference, retrieval, and generation. Its JSON output is saved to `reports/latency.json`. These results depend on the backend, hardware, server load, and sample size. The client time also includes HTTP and MLflow logging overhead.

| Measurement | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|
| Client request | 36.607 | 49.495 | 55.884 |
| MLflow inference | 0.267 | 0.306 | 0.349 |
| MLflow retrieval | 0.174 | 0.225 | 0.260 |
| MLflow generation | 0.061 | 0.069 | 0.070 |

Measured on 2026-09-28 using the local backend, Python 3.12, three warm-up calls, and 30 measured queries. See [`reports/latency.json`](reports/latency.json) for the machine-readable record. The reported inference metric stops before MLflow logging, so client and inference values measure different spans.

GitHub Actions runs tests, the authored evaluation, a Docker Compose build, and an API/MLflow smoke test. The [verification record and live screenshots](docs/verification.md) show what actually ran.

## Reflection

- **Dominant latency:** Retrieval dominated the measured local inference phase by mean time. Client requests took much longer than the in-process RAG calculation because HTTP handling and synchronous MLflow logging are included in client timing. The offline result does not predict OpenAI embedding or LLM latency; measure that configuration separately.
- **More signals before deployment:** Track retrieval relevance, citation support, answer refusal rate, token use, cost, error rate, corpus version, and user feedback. Avoid storing sensitive queries in MLflow without a retention policy.
- **Next hardening layer:** Add authentication, authorization, TLS, secrets management, approved document versioning, redaction, rate limits, and a production tracking database. Validate on real, permissioned maintenance data with human review.

## Repository layout

```text
app/main.py            FastAPI routes and startup lifespan
app/schemas.py         Request, response, and metadata schemas
app/service.py         Offline and OpenAI RAG adapters
app/tracking.py        Best-effort MLflow run logging
app/local_rag.py       Offline retriever and extractive answer
app/openai_rag.py      Existing history-aware LangChain chain
app/cli.py             Offline interactive CLI
data/clean/            Curated source documents
data/manifest.csv      Source ownership metadata
evaluation/            Authored evaluation questions
scripts/benchmark.py  Client and MLflow latency probe
scripts/evaluate.py   Retrieval/refusal evaluation
docs/                 Diagrams and verification evidence
Dockerfile            Pinned dependency install, non-root API image
compose.yaml          Local API and MLflow stack
```

This educational service does not replace site procedures, manufacturer instructions, or qualified safety judgment. The corpus and benchmark are small demonstrations, not a production accuracy claim.
