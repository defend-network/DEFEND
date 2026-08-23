from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import re
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .model_registry import ADAPTER_REPO as _ADAPTER_REPO
from .model_registry import GGUF_REPO as _GGUF_REPO
from .types import AdapterSpec


_HUB_ROOT = "https://huggingface.co"
_MAX_RESPONSE_BYTES = 64 * 1024
_TIMEOUT_SECONDS = 30.0
_REVISION = re.compile(r"^[0-9a-fA-F]{40,64}$")
_REPOSITORY = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$"
)


def _model_family(repo: str, architecture: str | None) -> str | None:
    """Return the base model family (qwen2/qwen3) from authoritative signals.

    Repository names are a hint only; the architecture class from the adapter's
    ``auto_mapping.base_model_class`` is preferred when present.
    """
    if isinstance(architecture, str) and architecture:
        lower = architecture.casefold()
        if "qwen3" in lower:
            return "qwen3"
        if "qwen2" in lower:
            return "qwen2"
    if isinstance(repo, str):
        lower = repo.casefold()
        if "qwen3" in lower:
            return "qwen3"
        if "qwen2" in lower:
            return "qwen2"
    return None


def _config_family(
    runtime_base_config: Mapping[str, object],
) -> tuple[str | None, str | None]:
    model_type = runtime_base_config.get("model_type")
    architectures = runtime_base_config.get("architectures")
    first_arch = None
    if isinstance(architectures, list) and architectures:
        first_arch = str(architectures[0])
    family = _model_family(
        str(model_type) if isinstance(model_type, str) else "",
        first_arch,
    )
    return family, first_arch


def adapter_runtime_base_compatible(
    *,
    adapter_base_repo: str,
    adapter_architecture: str | None,
    runtime_base_config: Mapping[str, object],
) -> tuple[bool, str]:
    """Fail-closed check that the adapter's declared base family and
    architecture class match the runtime base config.

    Deterministic and dependency-free so it is unit-testable with fixtures.
    """
    adapter_family = _model_family(adapter_base_repo, adapter_architecture)
    runtime_family, runtime_arch = _config_family(runtime_base_config)
    if adapter_family is None or runtime_family is None:
        return False, "unable to determine base model family"
    if adapter_family != runtime_family:
        return (
            False,
            f"adapter base is {adapter_family} but runtime base is {runtime_family}",
        )
    if runtime_arch is None:
        return False, "runtime base config has no architectures"
    adapter_arch = adapter_architecture
    if adapter_arch is not None:
        if adapter_arch.casefold() not in {
            str(entry).casefold()
            for entry in (runtime_base_config.get("architectures") or [])
        }:
            return (
                False,
                f"adapter architecture {adapter_arch} not present in runtime "
                f"base architectures",
            )
    return True, "adapter base and runtime base are compatible"


class HuggingFaceError(RuntimeError):
    """A safe Hugging Face discovery failure without response or secret data."""


@dataclass(frozen=True)
class _Response:
    status_code: int
    body: bytes


class _Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: object | None,
        timeout: float,
        max_response_bytes: int,
    ) -> _Response: ...


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self, request, file_pointer, code, message, headers, new_url
    ):
        redirected = super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )
        if redirected is None:
            return None
        old_origin = urlsplit(request.full_url)[:2]
        new_origin = urlsplit(new_url)[:2]
        if old_origin != new_origin:
            redirected.remove_header("Authorization")
        return redirected


class _UrllibTransport:
    def __init__(self) -> None:
        self._opener = build_opener(_SafeRedirectHandler())

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: object | None,
        timeout: float,
        max_response_bytes: int,
    ) -> _Response:
        payload = None
        if json is not None:
            payload = globals()["json"].dumps(
                json, separators=(",", ":")
            ).encode("utf-8")
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=timeout) as response:
                body = response.read(max_response_bytes + 1)
                status_code = int(getattr(response, "status", 200))
        except HTTPError as error:
            body = error.read(max_response_bytes + 1)
            status_code = int(error.code)
        if len(body) > max_response_bytes:
            raise ValueError("response exceeds 64 KiB")
        return _Response(status_code, body)


class HuggingFaceClient:
    def __init__(self, *, transport: _Transport | None = None) -> None:
        self._transport = transport or _UrllibTransport()

    def __repr__(self) -> str:
        return "HuggingFaceClient()"

    def resolve_adapter(self, repo: str, token: str) -> AdapterSpec:
        if repo != _ADAPTER_REPO:
            raise ValueError("only the configured DEFEND LoRA adapter is supported")
        if not isinstance(token, str) or not token:
            raise ValueError("Hugging Face token must be a non-empty string")

        adapter_metadata = self._get_json(
            f"{_HUB_ROOT}/api/models/{repo}/revision/main", token
        )
        adapter_revision = self._require_revision(
            adapter_metadata.get("sha") if isinstance(adapter_metadata, Mapping) else None,
            "adapter",
        )
        config = self._get_json(
            f"{_HUB_ROOT}/{repo}/resolve/{adapter_revision}/adapter_config.json",
            token,
        )
        if not isinstance(config, Mapping):
            raise HuggingFaceError("Hugging Face adapter configuration is invalid")
        if config.get("peft_type") != "LORA":
            raise HuggingFaceError("Hugging Face adapter must use LORA")
        lora_rank = config.get("r")
        if type(lora_rank) is not int or not 1 <= lora_rank <= 512:
            raise HuggingFaceError(
                "Hugging Face adapter LoRA rank must be an integer from 1 to 512"
            )
        base_repo = config.get("base_model_name_or_path")
        if (
            not isinstance(base_repo, str)
            or not _REPOSITORY.fullmatch(base_repo)
            or base_repo == _GGUF_REPO
        ):
            raise HuggingFaceError("Hugging Face base repository is invalid")

        configured_revision = config.get("revision")
        if configured_revision is None:
            base_metadata = self._get_json(
                f"{_HUB_ROOT}/api/models/{base_repo}/revision/main", token
            )
            configured_revision = (
                base_metadata.get("sha")
                if isinstance(base_metadata, Mapping)
                else None
            )
        base_revision = self._require_revision(configured_revision, "base")

        auto_mapping = config.get("auto_mapping")
        base_architecture = None
        if isinstance(auto_mapping, Mapping):
            candidate = auto_mapping.get("base_model_class")
            if isinstance(candidate, str) and candidate:
                base_architecture = candidate

        return AdapterSpec(
            adapter_repo=repo,
            adapter_revision=adapter_revision,
            base_repo=base_repo,
            base_revision=base_revision,
            peft_type="LORA",
            lora_rank=lora_rank,
            base_architecture=base_architecture,
        )

    def verify_deployment_compatibility(self, adapter: AdapterSpec, token: str) -> None:
        """Fail closed if the adapter's declared base is incompatible with the
        runtime base config (e.g. Qwen2.5 adapter against a Qwen3 runtime)."""
        if not isinstance(token, str) or not token:
            raise HuggingFaceError("Hugging Face token must be a non-empty string")
        base_config = self._get_json(
            f"{_HUB_ROOT}/{adapter.base_repo}/resolve/{adapter.base_revision}/config.json",
            token,
        )
        if not isinstance(base_config, Mapping):
            raise HuggingFaceError("Hugging Face base configuration is invalid")
        ok, reason = adapter_runtime_base_compatible(
            adapter_base_repo=adapter.base_repo,
            adapter_architecture=adapter.base_architecture,
            runtime_base_config=base_config,
        )
        if not ok:
            raise HuggingFaceError(f"DEFEND adapter/runtime base mismatch: {reason}")

    @staticmethod
    def _require_revision(value: object, subject: str) -> str:
        if not isinstance(value, str) or not _REVISION.fullmatch(value):
            raise HuggingFaceError(
                f"Hugging Face {subject} revision is not an immutable SHA"
            )
        return value.lower()

    def _get_json(self, url: str, token: str) -> object:
        try:
            response = self._transport.request(
                "GET",
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                json=None,
                timeout=_TIMEOUT_SECONDS,
                max_response_bytes=_MAX_RESPONSE_BYTES,
            )
        except Exception as error:
            raise HuggingFaceError(
                f"Hugging Face request failed ({type(error).__name__})"
            ) from None
        if response.status_code < 200 or response.status_code >= 300:
            raise HuggingFaceError(
                f"Hugging Face request failed (status {response.status_code})"
            )
        if len(response.body) > _MAX_RESPONSE_BYTES:
            raise HuggingFaceError("Hugging Face response exceeds 64 KiB")
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HuggingFaceError(
                f"Hugging Face response is invalid ({type(error).__name__})"
            ) from None
