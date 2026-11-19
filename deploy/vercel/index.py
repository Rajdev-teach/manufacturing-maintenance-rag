"""Vercel entrypoint: a key-free local retriever, with no remote inference logging."""

import json
import os
from pathlib import Path

os.environ["RAG_BACKEND"] = "local"
os.environ["MLFLOW_TRACKING_ENABLED"] = "false"
build_file = Path(__file__).with_name("build.json")
if build_file.exists():
    os.environ.setdefault("BUILD_COMMIT", json.loads(build_file.read_text(encoding="utf-8"))["commit"])

from app.main import create_app
from app.web import attach_web
from app.public_security import PublicDemoSecurity
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = create_app(expose_docs=False)
attach_web(app)
app.add_middleware(PublicDemoSecurity, trust_vercel_proxy=os.getenv("VERCEL") == "1")


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # Avoid reflecting user-supplied question contents in validation responses.
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]}
        for item in error.errors()
    ]})

