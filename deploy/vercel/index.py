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

app = create_app()
attach_web(app)
