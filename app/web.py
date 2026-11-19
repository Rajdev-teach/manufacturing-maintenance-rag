"""Browser interface for the public, offline-only maintenance demo."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


def attach_web(app: FastAPI) -> None:
    root = Path(__file__).resolve().parents[1]

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(root / "web" / "index.html")

    @app.get("/assets/{filename}", include_in_schema=False)
    def asset(filename: str):
        if filename not in {"app.js", "style.css", "mark.svg"}:
            raise HTTPException(404, "Asset not found")
        return FileResponse(root / "web" / filename)

    @app.get("/library")
    def library():
        documents = []
        for path in sorted((root / "data" / "clean").glob("*.md")):
            content = path.read_text(encoding="utf-8")
            title = next((line[2:].strip() for line in content.splitlines() if line.startswith("# ")), path.stem)
            documents.append({"source": path.name, "title": title, "content": content})
        return {"documents": documents, "mode": "curated-demo-corpus"}
