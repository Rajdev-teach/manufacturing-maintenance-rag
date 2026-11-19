"""Public HTTP contract for the manufacturing maintenance RAG service."""

from pydantic import BaseModel, ConfigDict, Field


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(strict=True, max_length=1000, description="Maintenance question to answer")
    top_k: int = Field(default=4, strict=True, ge=1, le=10, description="Maximum retrieved chunks")


class SourceCitation(BaseModel):
    id: str
    title: str
    source: str
    content: str | None = Field(default=None, description="Retrieved supporting passage, when available")


class QueryMetadata(BaseModel):
    request_id: str
    backend: str
    model: str
    version: str
    latency_ms: float
    retrieval_ms: float
    generation_ms: float
    tracking_status: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceCitation]
    metadata: QueryMetadata


class ServiceInfo(BaseModel):
    name: str
    version: str
    backend: str
    model: str
    embedding_model: str | None
    build_commit: str = "development"

