from __future__ import annotations

import hashlib
import ipaddress
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

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
from bootstrap_models import WebFetchInput, WebFetchOutput


MAX_DOWNLOAD_BYTES = 2_000_000
MAX_REDIRECTS = 5
ALLOWED_PORTS = {80, 443}
ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_MIME_PREFIXES = (
    "text/html",
    "text/plain",
    "application/json",
    "application/xml",
    "text/xml",
)


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


class WebFetchTool(DefendTool[WebFetchInput, WebFetchOutput]):
    name = "web.fetch"
    description = "Fetch a specific public URL and return cleaned text content with provenance."
    version = "1.0.0"

    input_model = WebFetchInput
    output_model = WebFetchOutput

    permissions = frozenset({ToolPermission.NETWORK, ToolPermission.READ_EXTERNAL})
    risk_level = RiskLevel.LOW
    side_effect = SideEffect.READ
    idempotent = True
    parallel_safe = True
    timeout_seconds = 25.0
    max_input_classification = DataClassification.PUBLIC
    max_output_classification = DataClassification.PUBLIC

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def startup(self) -> None:
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=20.0,
            headers={"User-Agent": "DEFEND-AI/1.0 (+research; respectful)"},
        )

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def execute(
        self,
        args: WebFetchInput,
        context: ToolContext,
    ) -> ToolResult[WebFetchOutput]:
        if self._client is None:
            await self.startup()

        try:
            current_url = validate_url(args.url)
            redirect_chain: list[str] = []
            response: httpx.Response | None = None

            for _ in range(MAX_REDIRECTS + 1):
                response = await self._client.request("GET", current_url)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirect without Location header")
                    # Resolve relative redirects
                    next_url = str(response.url.join(location))
                    validate_url(next_url)
                    redirect_chain.append(next_url)
                    current_url = next_url
                    continue
                break
            else:
                raise ValueError("Too many redirects")

            assert response is not None

            content_type = response.headers.get("content-type", "")
            mime = content_type.split(";")[0].strip().lower()

            if not any(mime.startswith(p) for p in ALLOWED_MIME_PREFIXES):
                return ToolResult(
                    ok=False,
                    error=ToolError(
                        code=ToolErrorCode.INVALID_INPUT,
                        message=f"Unsupported content type: {mime}",
                        retryable=False,
                    ),
                )

            # Stream with hard download limit
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    return ToolResult(
                        ok=False,
                        error=ToolError(
                            code=ToolErrorCode.BUDGET_EXCEEDED,
                            message=f"Response exceeded {MAX_DOWNLOAD_BYTES} bytes",
                            retryable=False,
                        ),
                    )
                chunks.append(chunk)

            raw = b"".join(chunks)
            charset = "utf-8"
            if "charset=" in content_type.lower():
                charset = content_type.lower().split("charset=")[-1].split(";")[0].strip() or "utf-8"

            try:
                text = raw.decode(charset, errors="replace")
            except Exception:
                text = raw.decode("utf-8", errors="replace")

            title = None
            if mime.startswith("text/html"):
                soup = BeautifulSoup(text, "html.parser")
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                if soup.title and soup.title.string:
                    title = soup.title.string.strip()
                text = " ".join(soup.stripped_strings)

            truncated = False
            if len(text) > args.max_chars:
                text = text[: args.max_chars]
                truncated = True

            final_url = str(response.url)
            source_id = source_id_for_url(final_url)
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            retrieved_at = datetime.now(timezone.utc)

            data = WebFetchOutput(
                source_id=source_id,
                requested_url=args.url,
                final_url=final_url,
                title=title,
                content=text,
                content_type=content_type,
                charset=charset,
                status_code=response.status_code,
                retrieved_at=retrieved_at,
                content_hash=content_hash,
                downloaded_bytes=size,
                truncated=truncated,
                redirect_chain=redirect_chain,
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