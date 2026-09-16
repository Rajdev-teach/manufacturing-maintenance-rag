from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.corpus import Chunk, load_corpus

TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]+")
BLOCKED_PATTERNS = ("ignore previous instructions", "reveal system prompt", "show api key", "print secrets")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "before", "belong", "can", "do", "does", "for",
    "how", "i", "in", "is", "it", "of", "on", "one", "should", "the", "their", "to", "we",
    "what", "when", "where", "which", "who", "why", "with", "yesterday"
}
EXPANSIONS = {"mtbf": ("mean", "time", "between", "failures"), "loto": ("lockout", "tagout")}


def tokenize(text: str) -> list[str]:
    output: list[str] = []
    for raw in TOKEN_RE.findall(text.lower()):
        terms = EXPANSIONS.get(raw, (raw,))
        for token in terms:
            if token in STOPWORDS:
                continue
            if token.endswith("ies") and len(token) > 4:
                token = token[:-3] + "y"
            elif token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
                token = token[:-1]
            output.append(token)
    return output


@dataclass(frozen=True)
class SearchResult:
    chunk: Chunk
    score: float


class LocalRAG:
    """Offline TF-IDF retrieval with extractive, citation-first answers."""

    def __init__(self, chunks: list[Chunk], top_k: int = 4):
        self.chunks = chunks
        self.top_k = top_k
        self.doc_tokens = [Counter(tokenize(f"{c.title} {c.title} {c.text}")) for c in chunks]
        df = Counter(token for tokens in self.doc_tokens for token in tokens)
        total = len(chunks)
        self.idf = {term: math.log((total + 1) / (freq + 1)) + 1 for term, freq in df.items()}

    @classmethod
    def from_directory(cls, directory: Path, top_k: int = 4) -> "LocalRAG":
        return cls(load_corpus(directory), top_k)

    def search(self, query: str, k: int | None = None) -> list[SearchResult]:
        query_tokens = Counter(tokenize(query))
        query_vector = {t: n * self.idf.get(t, 1.0) for t, n in query_tokens.items()}
        qnorm = math.sqrt(sum(v * v for v in query_vector.values())) or 1.0
        ranked: list[SearchResult] = []
        for chunk, tokens in zip(self.chunks, self.doc_tokens):
            vector = {t: n * self.idf.get(t, 1.0) for t, n in tokens.items()}
            norm = math.sqrt(sum(v * v for v in vector.values())) or 1.0
            score = sum(query_vector.get(t, 0) * value for t, value in vector.items()) / (qnorm * norm)
            ranked.append(SearchResult(chunk, score))
        return sorted(ranked, key=lambda item: item.score, reverse=True)[: k or self.top_k]

    def ask(self, question: str, history: list[tuple[str, str]] | None = None) -> dict:
        normalized = question.strip().lower()
        if not normalized or len(question) > 1000:
            return {"answer": "Please enter a question between 1 and 1,000 characters.", "sources": []}
        if any(pattern in normalized for pattern in BLOCKED_PATTERNS):
            return {"answer": "I can only answer questions from the maintenance knowledge base.", "sources": []}
        expanded = question
        if history and re.search(r"\b(it|that|those|they|second one|first one)\b", normalized):
            expanded = f"Previous topic: {history[-1][0]}. Follow-up: {question}"
        results = [result for result in self.search(expanded) if result.score >= 0.09]
        if not results:
            return {"answer": "I don't know based on the available maintenance documents.", "sources": []}
        query_terms = set(tokenize(expanded))
        candidates: list[tuple[int, str, Chunk]] = []
        for result in results:
            prose = " ".join(line for line in result.chunk.text.splitlines() if not line.lstrip().startswith("#"))
            for sentence in re.split(r"(?<=[.!?])\s+", prose):
                overlap = len(query_terms.intersection(tokenize(sentence)))
                if overlap:
                    candidates.append((overlap, sentence.strip(), result.chunk))
        chosen = sorted(candidates, key=lambda x: x[0], reverse=True)[:3]
        answer = " ".join(sentence for _, sentence, _ in chosen)
        sources = []
        seen = set()
        for result in results:
            chunk = result.chunk
            if chunk.source not in seen:
                sources.append({"id": chunk.chunk_id, "title": chunk.title, "source": chunk.source})
                seen.add(chunk.source)
        return {"answer": answer or "I don't know based on the available maintenance documents.", "sources": sources}
