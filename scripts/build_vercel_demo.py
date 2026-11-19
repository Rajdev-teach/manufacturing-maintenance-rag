"""Package the actual local Python backend and browser UI for Vercel Drop.

Run from any directory: python scripts/build_vercel_demo.py
The output is deliberately separate from the full Docker/MLflow deployment.
"""

import argparse
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "vercel-dist"
MODULES = (
    "__init__.py", "main.py", "config.py", "azure_config.py", "service.py",
    "schemas.py", "tracking.py", "corpus.py", "local_rag.py", "web.py", "public_security.py",
)


def build(commit: str):
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    (OUTPUT / "app").mkdir(parents=True)
    for name in MODULES:
        shutil.copyfile(ROOT / "app" / name, OUTPUT / "app" / name)
    shutil.copytree(ROOT / "data" / "clean", OUTPUT / "data" / "clean")
    shutil.copytree(ROOT / "web", OUTPUT / "web")
    (OUTPUT / "public" / "assets").mkdir(parents=True)
    for name in ("app.js", "style.css", "mark.svg"):
        shutil.copyfile(ROOT / "web" / name, OUTPUT / "public" / "assets" / name)
    for source in (ROOT / "deploy" / "vercel").iterdir():
        if source.is_file():
            shutil.copyfile(source, OUTPUT / source.name)
    (OUTPUT / "build.json").write_text(json.dumps({"commit": commit}), encoding="utf-8")
    print(f"Vercel package: {OUTPUT} ({sum(p.is_file() for p in OUTPUT.rglob('*'))} files)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default=os.getenv("GITHUB_SHA", "development"))
    build(parser.parse_args().commit)

