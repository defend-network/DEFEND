from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PureWindowsPath
import uuid

from defend_data.ingest_policy import AIIngestExcluded, assert_ai_ingest_allowed


MAX_PERMANENT_FILE_BYTES = 25_000_000
MAX_PERMANENT_BATCH_FILES = 20
_ALLOWED_MEDIA = {".pdf": "pdf", ".docx": "docx"}
_TERMINAL_FILE_STATES = frozenset({"indexed", "skipped", "failed"})


class PermanentRagValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PermanentRagFile:
    name: str
    data: bytes
    content_type: str | None = None


@dataclass(frozen=True)
class ValidatedPermanentFile:
    name: str
    data: bytes
    content_type: str | None
    media_type: str
    content_hash: str
    document_id: str


@dataclass
class RagJobFile:
    name: str
    document_id: str
    status: str = "queued"
    chunks_added: int = 0
    chunks_updated: int = 0
    error: str | None = None


@dataclass(frozen=True)
class PermanentDocumentSummary:
    document_id: str
    title: str
    content_hash: str
    chunk_count: int
    embedding_model: str
    ingested_at: str
    tags: tuple[str, ...] = ()


@dataclass
class _RagJob:
    job_id: str
    requested_by: str
    created_at: str
    files: list[RagJobFile]
    validated: list[ValidatedPermanentFile] = field(repr=False)
    status: str = "queued"
    completed_at: str | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: str) -> str:
    normalized = value.replace("\\", "/")
    return Path(normalized).name or PureWindowsPath(value).name or "document"


def document_id_for(data: bytes) -> str:
    return "doc_perm_" + hashlib.sha256(data).hexdigest()[:24]


class PermanentRagService:
    def __init__(
        self,
        data_root: Path,
        *,
        runner: Callable[[str, str], Awaitable[object]] | None = None,
        row_source: Callable[[], list[dict]] | None = None,
        max_jobs: int = 50,
        max_file_bytes: int = MAX_PERMANENT_FILE_BYTES,
    ) -> None:
        if max_jobs <= 0 or max_file_bytes <= 0:
            raise ValueError("RAG service limits must be positive")
        self.data_root = Path(data_root)
        self.documents_root = self.data_root / "documents"
        self._runner = runner or self._run_ingest_tool
        self._row_source = row_source or self._load_permanent_rows
        self._max_jobs = max_jobs
        self._max_file_bytes = max_file_bytes
        self._jobs: OrderedDict[str, _RagJob] = OrderedDict()

    def validate_file(self, item: PermanentRagFile) -> ValidatedPermanentFile:
        name = _safe_name(item.name)
        extension = Path(name).suffix.lower()
        media_type = _ALLOWED_MEDIA.get(extension)
        if media_type is None:
            raise PermanentRagValidationError("Permanent RAG accepts PDF and DOCX files only")
        if not item.data:
            raise PermanentRagValidationError(f"{name} is empty")
        if len(item.data) > self._max_file_bytes:
            raise PermanentRagValidationError(f"{name} exceeds the 25 MB file limit")
        try:
            assert_ai_ingest_allowed(filename=name, content_prefix=item.data[:4096])
        except AIIngestExcluded as error:
            raise PermanentRagValidationError(str(error)) from None
        content_hash = hashlib.sha256(item.data).hexdigest()
        return ValidatedPermanentFile(
            name=name,
            data=item.data,
            content_type=item.content_type,
            media_type=media_type,
            content_hash=content_hash,
            document_id=document_id_for(item.data),
        )

    async def create_job(
        self,
        files: Sequence[PermanentRagFile],
        *,
        requested_by: str,
    ) -> dict:
        if not files:
            raise PermanentRagValidationError("Choose at least one PDF or DOCX file")
        if len(files) > MAX_PERMANENT_BATCH_FILES:
            raise PermanentRagValidationError("Permanent RAG accepts at most 20 files per batch")
        validated = [self.validate_file(item) for item in files]
        job = _RagJob(
            job_id="ragjob_" + uuid.uuid4().hex[:20],
            requested_by=requested_by,
            created_at=_now(),
            files=[RagJobFile(item.name, item.document_id) for item in validated],
            validated=validated,
        )
        self._evict_completed_jobs()
        self._jobs[job.job_id] = job
        job.task = asyncio.create_task(self._run_job(job))
        return self._snapshot(job)

    def get_job(self, job_id: str) -> dict | None:
        job = self._jobs.get(job_id)
        return self._snapshot(job) if job is not None else None

    async def wait(self, job_id: str) -> dict:
        job = self._jobs[job_id]
        if job.task is not None:
            await job.task
        return self._snapshot(job)

    async def _run_job(self, job: _RagJob) -> None:
        job.status = "running"
        for validated, state in zip(job.validated, job.files):
            if self._document_is_indexed(validated.document_id, validated.content_hash):
                state.status = "skipped"
                continue
            try:
                state.status = "extracting"
                self._save_document(validated)
                state.status = "embedding"
                result = await self._runner(validated.document_id, job.requested_by)
                ok, chunks_added, chunks_updated, error = self._normalize_result(result)
                if not ok:
                    raise RuntimeError(error or "Document ingestion failed")
                state.chunks_added = chunks_added
                state.chunks_updated = chunks_updated
                state.status = "indexed"
            except Exception as error:
                state.status = "failed"
                state.error = self._safe_error(error)
        job.status = "complete"
        job.completed_at = _now()

    def list_documents(self) -> list[dict]:
        grouped: dict[str, dict] = {}
        for row in self._row_source():
            document_id = str(row.get("document_id") or "")
            if not document_id:
                continue
            current = grouped.setdefault(
                document_id,
                {
                    "document_id": document_id,
                    "title": self._title_for(document_id),
                    "content_hash": str(row.get("content_hash") or ""),
                    "chunk_count": 0,
                    "embedding_model": str(row.get("embedding_model") or ""),
                    "ingested_at": str(row.get("ingested_at") or ""),
                    "tags": set(),
                },
            )
            current["chunk_count"] += 1
            ingested_at = str(row.get("ingested_at") or "")
            if ingested_at > current["ingested_at"]:
                current["ingested_at"] = ingested_at
            current["tags"].update(
                tag.strip() for tag in str(row.get("tags") or "").split(",") if tag.strip()
            )
        return [
            {**item, "tags": sorted(item["tags"])}
            for item in sorted(grouped.values(), key=lambda value: value["ingested_at"], reverse=True)
        ]

    def _save_document(self, item: ValidatedPermanentFile) -> None:
        directory = self.documents_root / item.document_id
        directory.mkdir(parents=True, exist_ok=True)
        metadata = {
            "document_id": item.document_id,
            "source_id": f"permanent:{item.document_id}",
            "source_path": item.name,
            "media_type": item.media_type,
            "content_type": item.content_type,
            "title": item.name,
            "content_hash": item.content_hash,
            "downloaded_bytes": len(item.data),
            "scope": "permanent",
            "ingested_at": _now(),
        }
        (directory / "original.bin").write_bytes(item.data)
        (directory / "meta.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    async def _run_ingest_tool(self, document_id: str, requested_by: str) -> object:
        from bootstrap_models import RagIngestInput
        from tool_sdk import ToolContext
        from tools.rag_ingest import RagIngestTool

        return await RagIngestTool().execute(
            RagIngestInput(document_id=document_id),
            ToolContext(
                request_id="req_" + uuid.uuid4().hex,
                trace_id="trace_" + uuid.uuid4().hex,
                user_id=requested_by,
            ),
        )

    def _load_permanent_rows(self) -> list[dict]:
        try:
            from rag_store import get_or_create_table

            return get_or_create_table("permanent").search().limit(50_000).to_list()
        except Exception:
            return []

    def _document_is_indexed(self, document_id: str, content_hash: str) -> bool:
        return any(
            str(row.get("document_id")) == document_id
            and str(row.get("content_hash")) == content_hash
            for row in self._row_source()
        )

    def _title_for(self, document_id: str) -> str:
        path = self.documents_root / document_id / "meta.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return str(value.get("title") or document_id)
        except Exception:
            return document_id

    def _evict_completed_jobs(self) -> None:
        while len(self._jobs) >= self._max_jobs:
            removable = next(
                (key for key, value in self._jobs.items() if value.status == "complete"),
                None,
            )
            if removable is None:
                raise PermanentRagValidationError("Too many RAG jobs are currently active")
            del self._jobs[removable]

    @staticmethod
    def _normalize_result(result: object) -> tuple[bool, int, int, str | None]:
        if isinstance(result, dict):
            return (
                bool(result.get("ok", True)),
                int(result.get("chunks_added", 0)),
                int(result.get("chunks_updated", 0)),
                str(result.get("error")) if result.get("error") else None,
            )
        ok = bool(getattr(result, "ok", False))
        data = getattr(result, "data", None)
        error = getattr(result, "error", None)
        return (
            ok,
            int(getattr(data, "chunks_added", 0) or 0),
            int(getattr(data, "chunks_updated", 0) or 0),
            str(getattr(error, "message", "")) or None,
        )

    @staticmethod
    def _safe_error(error: Exception) -> str:
        message = str(error).strip()
        return (message[:300] if message else type(error).__name__).replace("\r", " ").replace("\n", " ")

    @staticmethod
    def _snapshot(job: _RagJob) -> dict:
        indexed = sum(item.status == "indexed" for item in job.files)
        skipped = sum(item.status == "skipped" for item in job.files)
        failed = sum(item.status == "failed" for item in job.files)
        return {
            "job_id": job.job_id,
            "status": job.status,
            "created_at": job.created_at,
            "completed_at": job.completed_at,
            "total": len(job.files),
            "indexed": indexed,
            "skipped": skipped,
            "failed": failed,
            "files": [asdict(item) for item in job.files],
        }
