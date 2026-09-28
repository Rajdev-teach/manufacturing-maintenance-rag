# Verification record

## Local execution, 2026-09-28

Environment: Python 3.12, pinned packages in `requirements.txt`, `RAG_BACKEND=local`, a local MLflow 2.17 tracking server with SQLite and proxied artifacts. No OpenAI key was used.

| Check | Observed result |
|---|---|
| Dependency resolution | `pip check`: no broken requirements after pinning SQLAlchemy 2.0.36 |
| Automated tests | 11 passed; dependency deprecation warnings from Starlette/MLflow |
| Authored retrieval/refusal evaluation | 15/15 cases passed, including three out-of-scope refusals |
| API smoke test | `/health` and `/info` responded; `/query` returned the relevant procedure and a `lockout_tagout.md` citation |
| MLflow live tracking | Query returned `tracking_status=logged`; runs contained parameters, metrics, and `interaction.json` artifacts |
| Latency probe | Three warm-up requests followed by 30 measured queries; p50/p95/p99 in `reports/latency.json` |

The first MLflow startup failed against unbounded SQLAlchemy 2.1.1. Pinning `SQLAlchemy==2.0.36` resolved that incompatibility and the live server and benchmark subsequently ran.

## Container and screenshot evidence

The local workspace does not have a Docker daemon or a browser binary. The GitHub Actions `container` job builds the image, starts API and MLflow with Docker Compose, checks the HTTP routes and MLflow metrics/artifact, and captures browser screenshots. Record the passing run and add its screenshots to `docs/screenshots/` after the workflow completes:

- `fastapi-docs.png`: the real `/docs` page
- `mlflow-runs.png`: the experiment runs table
- `mlflow-run-detail.png`: a run with parameters and metrics

Until that job passes, the Docker build and its screenshots are pending verification. Screenshots are evidence of the running local demonstration, not a claim that the service is publicly deployed.

## Scope of the measurements

The local backend is deterministic and has no external model call. Its answer time is therefore much smaller than a networked LLM's likely time. A future OpenAI-mode benchmark needs a valid key and separate cost/latency reporting. The 15 questions are authored against six short documents; their score does not establish real-world answer accuracy.
