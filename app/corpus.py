from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Chunk:
    text: str
    source: str
    title: str
    chunk_id: str


def clean_text(text: str) -> str:
    text = re.sub(r"Page\s+\d+\s+of\s+\d+", "", text, flags=re.I)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk_text(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    if size <= overlap:
        raise ValueError("chunk size must be greater than overlap")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip()
        if current and len(candidate) > size:
            chunks.append(current)
            sentences = re.split(r"(?<=[.!?])\s+", current)
            carry = sentences[-1] if sentences and len(sentences[-1]) <= overlap else ""
            current = f"{carry}\n\n{paragraph}".strip()
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def load_corpus(directory: Path, size: int = 900, overlap: int = 120) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(directory.glob("*.md")):
        text = clean_text(path.read_text(encoding="utf-8"))
        title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), path.stem)
        for index, piece in enumerate(chunk_text(text, size, overlap), start=1):
            chunks.append(Chunk(piece, path.name, title, f"{path.stem}-{index}"))
    if not chunks:
        raise ValueError(f"No Markdown documents found in {directory}")
    return chunks
