from __future__ import annotations
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from typing import Literal



# ─────────────────────────────────────────────
# Memory
# ─────────────────────────────────────────────

class RagQueryInput(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    project_id: str | None = None
    document_ids: list[str] | None = None
    limit: int = Field(default=8, ge=1, le=30)
    mode: Literal["hybrid", "semantic", "lexical"] = "semantic"
    scope: Literal["permanent", "research", "session"] = "permanent"


class RagHit(BaseModel):
    chunk_id: str
    document_id: str
    source_id: str | None = None
    text: str
    page: int | None = None
    start_offset: int | None = None
    end_offset: int | None = None

    # optional diagnostics
    vector_score: float | None = None      # raw vector distance/score
    lexical_score: float | None = None     # raw BM25/FTS score
    relevance_score: float = 0.0           # within-mode ranking score
    score_method: str = "vector_distance"  # "vector_distance" | "bm25" | "rrf"

    content_hash: str = ""


class RagQueryOutput(BaseModel):
    hits: list[RagHit]
    embedding_model: str
    mode: str

class RagIngestInput(BaseModel):
    document_id: str
    project_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class RagIngestOutput(BaseModel):
    document_id: str
    chunks_added: int
    chunks_updated: int
    chunks_skipped: int
    embedding_model: str
    content_hash: str

class EvidenceItem(BaseModel):
    evidence_id: str
    source_id: str
    claim_supported: str
    excerpt: str
    page: int | None = None
    url: str | None = None
    title: str | None = None
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class ResearchPacket(BaseModel):
    objective: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

class MemoryType(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROJECT = "project"
    DECISION = "decision"
    PREFERENCE = "preference"


class MemoryRecord(BaseModel):
    memory_id: str
    content: str
    memory_type: MemoryType
    project_id: str | None = None
    similarity_score: float | None = Field(default=None, ge=0, le=1)
    importance: float = Field(default=0.5, ge=0, le=1)
    created_at: datetime
    source_ref: str | None = None


class MemorySearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=8, ge=1, le=50)
    project_id: str | None = None
    memory_types: set[MemoryType] | None = None


class MemorySearchOutput(BaseModel):
    results: list[MemoryRecord]
    total_candidates: int | None = None


class MemoryProposalInput(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    memory_type: MemoryType
    project_id: str | None = None
    rationale: str | None = None


class MemoryAction(str, Enum):
    IGNORED = "ignored"
    QUEUED = "queued"
    MERGED = "merged"
    STORED = "stored"


class MemoryProposalOutput(BaseModel):
    proposal_id: str
    accepted: bool
    action: MemoryAction
    memory_id: str | None = None


# ─────────────────────────────────────────────
# Documents
# ─────────────────────────────────────────────

class DocumentHit(BaseModel):
    document_id: str
    title: str | None = None
    snippet: str
    score: float
    page: int | None = None
    chunk_id: str | None = None
    source_id: str | None = None


class DocumentsSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=6, ge=1, le=30)
    project_id: str | None = None


class DocumentsSearchOutput(BaseModel):
    results: list[DocumentHit]


class DocumentsReadInput(BaseModel):
    document_id: str
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    cursor: str | None = None
    max_chars: int = Field(default=12_000, ge=100, le=100_000)


class DocumentsReadOutput(BaseModel):
    document_id: str
    title: str | None = None
    content: str
    start_offset: int | None = None
    end_offset: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    truncated: bool = False
    next_cursor: str | None = None


# ─────────────────────────────────────────────
# Web
# ─────────────────────────────────────────────

class SearchFreshness(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class WebSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=8, ge=1, le=20)
    freshness: SearchFreshness | None = None
    region: str = "us-en"
    domain: str | None = None


class WebSearchResult(BaseModel):
    source_id: str
    title: str
    url: str
    snippet: str | None = None
    publisher: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    score: float | None = None
    domain: str | None = None
    media_type_hint: str | None = None  # "pdf" | "html" | "unknown"
    rank: int | None = None


class WebSearchOutput(BaseModel):
    results: list[WebSearchResult]


class WebFetchInput(BaseModel):
    url: str = Field(min_length=1, max_length=4096)
    max_chars: int = Field(default=20_000, ge=500, le=100_000)


class WebFetchOutput(BaseModel):
    source_id: str
    requested_url: str
    final_url: str
    title: str | None = None
    content: str
    content_type: str | None = None
    charset: str | None = None
    status_code: int
    retrieved_at: datetime
    content_hash: str
    downloaded_bytes: int
    truncated: bool = False
    redirect_chain: list[str] = Field(default_factory=list)

# ─────────────────────────────────────────────
# Documents
# ─────────────────────────────────────────────

class DocumentsSearchInput(BaseModel):
    document_id: str
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=5, ge=1, le=20)
    mode: Literal["hybrid", "semantic", "lexical"] = "hybrid"
    scope: Literal["permanent", "research", "session"] = "permanent"


class DocumentsSearchOutput(BaseModel):
    document_id: str
    hits: list[RagHit]
    mode: str

class DocumentMediaType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    XLSM = "xlsm"
    JPEG = "jpeg"
    PNG = "png"
    TXT = "txt"
    MD = "md"
    CSV = "csv"
    UNKNOWN = "unknown"


class DocumentsFetchInput(BaseModel):
    url: str = Field(min_length=1, max_length=4096)
    max_bytes: int = Field(default=15_000_000, ge=10_000, le=50_000_000)


class DocumentsFetchOutput(BaseModel):
    document_id: str
    source_id: str
    requested_url: str
    final_url: str
    title: str | None = None
    media_type: DocumentMediaType
    content_type: str | None = None
    page_count: int | None = None
    sheet_names: list[str] | None = None
    content_hash: str
    downloaded_bytes: int
    retrieved_at: datetime
    stored_path: str


class DocumentsReadInput(BaseModel):
    document_id: str
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    sheet_name: str | None = None
    max_chars: int = Field(default=20_000, ge=500, le=200_000)


class DocumentsReadOutput(BaseModel):
    document_id: str
    media_type: DocumentMediaType
    title: str | None = None
    content: str
    page_start: int | None = None
    page_end: int | None = None
    sheet_name: str | None = None
    truncated: bool = False
    extracted_chars: int


# ─────────────────────────────────────────────
# Calculator + Time
# ─────────────────────────────────────────────

class CalculatorInput(BaseModel):
    expression: str = Field(min_length=1, max_length=512)


class CalculatorOutput(BaseModel):
    expression: str
    exact: str | None = None
    approximate: float | None = None
    display: str
    warnings: list[str] = Field(default_factory=list)


class TimeNowInput(BaseModel):
    timezone: str = Field(default="UTC", min_length=1, max_length=128)


class TimeNowOutput(BaseModel):
    iso: str
    unix: float
    timezone: str
