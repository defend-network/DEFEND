from __future__ import annotations

import hashlib
import ipaddress
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4
import pymupdf

import httpx

from tool_sdk import (
    DefendTool,
    ToolContext,
    ToolResult,
    ToolError,
    ToolErrorCode,
    RiskLevel,
    SideEffect,
    ToolPermission,
    DataClassification,
    SourceRef,
)
from bootstrap_models import (
    DocumentsFetchInput,
    DocumentsFetchOutput,
    DocumentMediaType,
)
from tools.documents_store import save_document, content_hash_bytes


ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}
MAX_REDIRECTS = 5


def source_id_for_url(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"src_{digest}"


def _is_private_or_forbidden_host(hostname: str) -> bool:
    if not hostname:
        return True
    host = hostname.lower().strip(".")
    if host in {"localhost"} or host.endswith(".local"):
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return True
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return True
    return False


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"Scheme not allowed: {parsed.scheme}")
    if parsed.username or parsed.password:
        raise ValueError("URLs with credentials are not allowed")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL missing hostname")
    port = parsed.port
    if port is not None and port not in ALLOWED_PORTS:
        raise ValueError(f"Port not allowed: {port}")
    if _is_private_or_forbidden_host(hostname):
        raise ValueError("Private / local / forbidden host blocked")
    return url


def detect_media_type(content_type: str | None, url: str) -> DocumentMediaType:
    ct = (content_type or "").lower()
    path = urlparse(url).path.lower()

    if "pdf" in ct or path.endswith(".pdf"):
        return DocumentMediaType.PDF
    if "word" in ct or path.endswith(".docx"):
        return DocumentMediaType.DOCX
    if "sheet" in ct or "excel" in ct or path.endswith(".xlsx"):
        return DocumentMediaType.XLSX
    if path.endswith(".xlsm"):
        return DocumentMediaType.XLSM
    if "jpeg" in ct or "jpg" in ct or path.endswith((".jpg", ".jpeg")):
        return DocumentMediaType.JPEG
    if "png" in ct or path.endswith(".png"):
        return DocumentMediaType.PNG
    return DocumentMediaType.UNKNOWN


class DocumentsFetchTool(DefendTool[DocumentsFetchInput, DocumentsFetchOutput]):
    name = "documents.fetch"
    description = "Download a document (PDF, DOCX, XLSX, image) from a public URL and store it for extraction."
    version = "1.0.0"

    input_model = DocumentsFetchInput
    output_model = DocumentsFetchOutput

    permissions = frozenset({ToolPermission.NETWORK, ToolPermission.READ_EXTERNAL})
    risk_level = RiskLevel.LOW
    side_effect = SideEffect.READ
    idempotent = True
    parallel_safe = True
    timeout_seconds = 60.0
    max_input_classification = DataClassification.PUBLIC
    max_output_classification = DataClassification.PUBLIC

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=45.0,
            headers={"User-Agent": "DEFEND-AI/1.0 (+research; respectful)"},
        )

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def execute(
        self,
        args: DocumentsFetchInput,
        context: ToolContext,
    ) -> ToolResult[DocumentsFetchOutput]:
        if self._client is None:
            await self.startup()

        try:
            current_url = validate_url(args.url)
            redirect_chain: list[str] = []
            response = None

            for _ in range(MAX_REDIRECTS + 1):
                response = await self._client.request("GET", current_url)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirect without Location header")
                    next_url = str(response.url.join(location))
                    validate_url(next_url)
                    redirect_chain.append(next_url)
                    current_url = next_url
                    continue
                break
            else:
                raise ValueError("Too many redirects")

            assert response is not None
            response.raise_for_status()

            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > args.max_bytes:
                    return ToolResult(
                        ok=False,
                        error=ToolError(
                            code=ToolErrorCode.BUDGET_EXCEEDED,
                            message=f"Document exceeded {args.max_bytes} bytes",
                            retryable=False,
                        ),
                    )
                chunks.append(chunk)

            raw = b"".join(chunks)
            final_url = str(response.url)
            content_type = response.headers.get("content-type")
            media_type = detect_media_type(content_type, final_url)

            if media_type == DocumentMediaType.UNKNOWN:
                return ToolResult(
                    ok=False,
                    error=ToolError(
                        code=ToolErrorCode.INVALID_INPUT,
                        message=f"Unsupported document type: {content_type}",
                        retryable=False,
                    ),
                )

            document_id = f"doc_{uuid4().hex[:16]}"
            source_id = source_id_for_url(final_url)
            chash = content_hash_bytes(raw)
            retrieved_at = datetime.now(timezone.utc)

            # Light metadata probes
            page_count = None
            sheet_names = None
            title = None

            if media_type == DocumentMediaType.PDF:
                try:
                    import pymupdf
                    pdf = pymupdf.open(stream=raw, filetype="pdf")
                    page_count = pdf.page_count
                    if pdf.metadata:
                        title = pdf.metadata.get("title") or None
                    pdf.close()
                except Exception:
                    pass

            if media_type in {DocumentMediaType.XLSX, DocumentMediaType.XLSM}:
                try:
                    import openpyxl
                    from io import BytesIO
                    wb = openpyxl.load_workbook(BytesIO(raw), read_only=True, data_only=True)
                    sheet_names = list(wb.sheetnames)
                    wb.close()
                except Exception:
                    pass

            meta = {
                "document_id": document_id,
                "source_id": source_id,
                "requested_url": args.url,
                "final_url": final_url,
                "source_path": urlparse(final_url).path,
                "media_type": media_type.value,
                "content_type": content_type,
                "page_count": page_count,
                "sheet_names": sheet_names,
                "title": title,
                "content_hash": chash,
                "downloaded_bytes": size,
                "retrieved_at": retrieved_at.isoformat(),
                "redirect_chain": redirect_chain,
            }
            stored_path = save_document(document_id=document_id, raw=raw, metadata=meta)

            data = DocumentsFetchOutput(
                document_id=document_id,
                source_id=source_id,
                requested_url=args.url,
                final_url=final_url,
                title=title,
                media_type=media_type,
                content_type=content_type,
                page_count=page_count,
                sheet_names=sheet_names,
                content_hash=chash,
                downloaded_bytes=size,
                retrieved_at=retrieved_at,
                stored_path=stored_path,
            )

            return ToolResult(
                ok=True,
                data=data,
                sources=[
                    SourceRef(
                        source_id=source_id,
                        url=final_url,
                        title=title,
                        retrieved_at=retrieved_at.isoformat(),
                    )
                ],
            )

        except Exception as e:
            return ToolResult(
                ok=False,
                error=ToolError(
                    code=ToolErrorCode.UPSTREAM_ERROR,
                    message=str(e),
                    retryable=True,
                ),
            )
