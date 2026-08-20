from __future__ import annotations

from collections.abc import Callable, Mapping
import base64
from dataclasses import dataclass
from pathlib import Path
import re
import shlex
from typing import Protocol

from .model_registry import ADAPTER_REPO
from .processes import ProcessSpec
from .settings import ControlSettings
from .ssh_tunnel import CommandResult, run_command
from .types import AdapterSpec, ModelReady, VastInstance


_MAX_STDIN_BYTES = 64 * 1024
_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
_REPOSITORY = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$"
)
_API_ENV_NAMES = frozenset(
    {
        "DEFEND_API_TOKEN",
        "DEFEND_OWNER_USER",
        "DEFEND_OWNER_PASS",
        "DEFEND_OWNER_EMAIL",
        "DEFEND_ADMIN_SESSION_HOURS",
        "DEFEND_ACCOUNT_SESSION_HOURS",
        "DEFEND_VISITOR_HMAC_KEY",
        "DEFEND_GMAIL_SMTP_USERNAME",
        "DEFEND_GMAIL_APP_PASSWORD",
        "DEFEND_GMAIL_SMTP_SECURITY",
        "DEFEND_GMAIL_SMTP_HOST",
        "DEFEND_GMAIL_SMTP_PORT",
        "DEFEND_GMAIL_SMTP_TIMEOUT",
        "DEFEND_GMAIL_SENDER",
        "TAVILY_API_KEY",
    }
)


class _CommandRunner(Protocol):
    def __call__(
        self,
        argv: tuple[str, ...],
        *,
        stdin: bytes | None,
        timeout: float,
        cancelled: Callable[[], bool] | None = None,
    ) -> CommandResult: ...


class RemoteVllmError(RuntimeError):
    """A bounded remote launch error containing no remote output or secret."""


def _endpoint(instance: VastInstance) -> tuple[str, int]:
    if not isinstance(instance, VastInstance):
        raise ValueError("instance must be a VastInstance")
    host = instance.ssh_host
    port = instance.ssh_port
    if (
        not isinstance(host, str)
        or not host
        or any(character.isspace() or ord(character) < 0x21 for character in host)
        or type(port) is not int
        or not 1 <= port <= 65_535
    ):
        raise RemoteVllmError("Vast.ai SSH endpoint is invalid")
    return host, port


def _validate_adapter(adapter: AdapterSpec) -> None:
    if not isinstance(adapter, AdapterSpec):
        raise ValueError("adapter must be an AdapterSpec")
    if (
        adapter.adapter_repo != ADAPTER_REPO
        or adapter.peft_type != "LORA"
        or not _REPOSITORY.fullmatch(adapter.base_repo)
        or not _REVISION.fullmatch(adapter.adapter_revision)
        or not _REVISION.fullmatch(adapter.base_revision)
        or type(adapter.lora_rank) is not int
        or not 1 <= adapter.lora_rank <= 512
    ):
        raise RemoteVllmError("Pinned Hugging Face adapter specification is invalid")


class RemoteVllmBootstrap:
    def __init__(
        self,
        *,
        command_runner: _CommandRunner = run_command,
        ssh_exe: Path,
        known_hosts: Path,
        key_path: Path,
        max_model_len: int = 8192,
    ) -> None:
        if type(max_model_len) is not int or max_model_len != 8192:
            raise ValueError("remote vLLM maximum model length must be 8192")
        self._run = command_runner
        self._ssh_exe = Path(ssh_exe)
        self._known_hosts = Path(known_hosts)
        self._key_path = Path(key_path)
        self._max_model_len = max_model_len

    def _argv(self, instance: VastInstance) -> tuple[str, ...]:
        host, port = _endpoint(instance)
        return (
            str(self._ssh_exe),
            "-p",
            str(port),
            "-i",
            str(self._key_path),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={self._known_hosts}",
            f"root@{host}",
            "bash -s",
        )

    def _script(
        self,
        adapter: AdapterSpec,
        hf_token: str,
        vllm_api_key: str,
    ) -> bytes:
        hf_encoded = base64.b64encode(hf_token.encode("utf-8")).decode("ascii")
        vllm_encoded = base64.b64encode(vllm_api_key.encode("utf-8")).decode(
            "ascii"
        )
        # Use huggingface_hub Python API — more reliable than bare `hf` CLI
        # across vllm/vllm-openai image variants.
        script = f"""#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
install -d -m 700 /workspace/defend
printf '%s' {shlex.quote(hf_encoded)} | base64 --decode > /workspace/defend/.hf_token
chmod 600 /workspace/defend/.hf_token
export HF_TOKEN="$(cat /workspace/defend/.hf_token)"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
VLLM_API_KEY="$(printf '%s' {shlex.quote(vllm_encoded)} | base64 --decode)"
export VLLM_API_KEY

python3 - <<'PY'
import os
from huggingface_hub import snapshot_download

base_repo = {adapter.base_repo!r}
base_rev = {adapter.base_revision!r}
adapter_repo = {adapter.adapter_repo!r}
adapter_rev = {adapter.adapter_revision!r}

snapshot_download(
    repo_id=base_repo,
    revision=base_rev,
    local_dir="/workspace/defend/base",
    token=os.environ.get("HF_TOKEN"),
)
snapshot_download(
    repo_id=adapter_repo,
    revision=adapter_rev,
    local_dir="/workspace/defend/adapter",
    token=os.environ.get("HF_TOKEN"),
)
print("downloads complete", flush=True)
PY

unset HF_TOKEN HUGGING_FACE_HUB_TOKEN

# Prefer `vllm` on PATH; fall back to python -m vllm if needed
if command -v vllm >/dev/null 2>&1; then
  VLLM_CMD=(vllm serve)
elif python3 -c "import vllm" >/dev/null 2>&1; then
  VLLM_CMD=(python3 -m vllm.entrypoints.openai.api_server)
else
  echo "vllm not found" >&2
  exit 127
fi

nohup "${{VLLM_CMD[@]}}" /workspace/defend/base \\
  --host 127.0.0.1 \\
  --port 8000 \\
  --enable-lora \\
  --lora-modules defend-ai=/workspace/defend/adapter \\
  --max-lora-rank {adapter.lora_rank} \\
  --max-model-len {self._max_model_len} \\
  --disable-log-requests \\
  --disable-uvicorn-access-log \\
  >/workspace/defend/vllm.log 2>&1 </dev/null &
printf '%s\\n' "$!" > /workspace/defend/vllm.pid
unset VLLM_API_KEY
"""
        try:
            encoded = script.encode("ascii")
        except UnicodeEncodeError:
            raise RemoteVllmError("Remote vLLM bootstrap input is invalid") from None
        if len(encoded) > _MAX_STDIN_BYTES:
            raise RemoteVllmError("Remote vLLM secret payload is too large")
        return encoded

    def start(
        self,
        instance: VastInstance,
        adapter: AdapterSpec,
        secrets: Mapping[str, str],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        _validate_adapter(adapter)
        if not isinstance(secrets, Mapping):
            raise RemoteVllmError("Remote vLLM required secret names are missing")
        hf_token = secrets.get("HF_TOKEN")
        vllm_api_key = secrets.get("VLLM_API_KEY")
        if (
            not isinstance(hf_token, str)
            or not hf_token
            or not isinstance(vllm_api_key, str)
            or not vllm_api_key
        ):
            raise RemoteVllmError("Remote vLLM required secret names are missing")
        if len(hf_token.encode("utf-8")) + len(vllm_api_key.encode("utf-8")) > 48 * 1024:
            raise RemoteVllmError("Remote vLLM secret payload is too large")
        if cancelled is not None and cancelled():
            raise RemoteVllmError("Remote vLLM bootstrap was cancelled")
        script = self._script(adapter, hf_token, vllm_api_key)
        try:
            result = self._run(
                self._argv(instance),
                stdin=script,
                timeout=900.0,
                cancelled=cancelled,
            )
        except Exception as error:
            raise RemoteVllmError(
                f"Remote vLLM bootstrap failed ({type(error).__name__})"
            ) from None
        if result.returncode != 0:
            raise RemoteVllmError(
                f"Remote vLLM bootstrap failed (exit {result.returncode})"
            )
        if cancelled is not None and cancelled():
            raise RemoteVllmError("Remote vLLM bootstrap was cancelled")

    def cleanup_token_file(self, instance: VastInstance) -> None:
        script = (
            b"#!/usr/bin/env bash\nset -euo pipefail\n"
            b"rm -f -- /workspace/defend/.hf_token\n"
        )
        try:
            result = self._run(self._argv(instance), stdin=script, timeout=30.0)
        except Exception as error:
            raise RemoteVllmError(
                f"Remote token cleanup failed ({type(error).__name__})"
            ) from None
        if result.returncode != 0:
            raise RemoteVllmError(
                f"Remote token cleanup failed (exit {result.returncode})"
            )


@dataclass(frozen=True)
class RemoteProcessSpecs:
    api: ProcessSpec
    web: ProcessSpec
    cloudflare: ProcessSpec


def build_remote_process_specs(
    settings: ControlSettings,
    secrets: Mapping[str, str],
    model_ready: ModelReady,
    adapter: AdapterSpec | None = None,
) -> RemoteProcessSpecs:
    if model_ready != ModelReady(
        "defend-ai", "openai_compatible", "http://127.0.0.1:8001/v1"
    ):
        raise ValueError("remote process specs require verified loopback vLLM")
    vllm_key = secrets.get("VLLM_API_KEY")
    if not isinstance(vllm_key, str) or not vllm_key:
        raise RemoteVllmError("Remote vLLM required secret names are missing")
    secret_env = {
        name: value
        for name, value in secrets.items()
        if name in _API_ENV_NAMES and isinstance(value, str) and value
    }
    adapter_env: dict[str, str] = {}
    if adapter is not None:
        _validate_adapter(adapter)
        adapter_env = {
            "DEFEND_MODEL_ADAPTER_REPO": adapter.adapter_repo,
            "DEFEND_MODEL_ADAPTER_REVISION": adapter.adapter_revision,
            "DEFEND_MODEL_BASE_REPO": adapter.base_repo,
            "DEFEND_MODEL_BASE_REVISION": adapter.base_revision,
        }
    api_env = {
        "DEFEND_MODEL_BACKEND": "openai_compatible",
        "DEFEND_MODEL": "defend-ai",
        "DEFEND_MODEL_BASE_URL": model_ready.endpoint,
        "DEFEND_MODEL_API_KEY": vllm_key,
        "DEFEND_API_PORT": "8000",
        "DEFEND_OWNER_USER": "MASSA",
        "DEFEND_OWNER_EMAIL": "chairman@defend-network.org",
        "DEFEND_ADMIN_SESSION_HOURS": "12",
        "DEFEND_ACCOUNT_SESSION_HOURS": "12",
        "DEFEND_GMAIL_SMTP_SECURITY": "ssl",
        "DEFEND_GMAIL_SMTP_HOST": "smtp.gmail.com",
        "DEFEND_GMAIL_SMTP_PORT": "465",
        "DEFEND_GMAIL_SMTP_TIMEOUT": "15",
        "DEFEND_GMAIL_SENDER": secret_env.get(
            "DEFEND_GMAIL_SMTP_USERNAME", "chairman@defend-network.org"
        ),
        "DEFEND_DATA_ROOT": str(settings.data_root),
        "DEFEND_PUBLIC_WEB_ORIGIN": settings.public_web_origin,
        "DEFEND_CORS_ORIGINS": settings.public_web_origin,
        "DEFEND_TRUST_CLOUDFLARE": "true",
        "DEFEND_COOKIE_SECURE": "true",
        **adapter_env,
        **secret_env,
    }
    repo = settings.repo_root
    return RemoteProcessSpecs(
        api=ProcessSpec(
            "api",
            (str(repo / ".venv" / "Scripts" / "python.exe"), "api_server.py"),
            repo,
            api_env,
            "http://127.0.0.1:8000/health",
        ),
        web=ProcessSpec(
            "web",
            ("npm.cmd", "run", "start"),
            repo / "defend-ui-v2",
            {"PORT": "3000", "HOSTNAME": "127.0.0.1"},
            "http://127.0.0.1:3000/",
        ),
        cloudflare=ProcessSpec(
            "cloudflare",
            (
                str(settings.cloudflared_exe),
                "tunnel",
                "--config",
                str(settings.cloudflared_config),
                "run",
                settings.cloudflared_tunnel,
            ),
            repo,
            {},
            settings.public_web_origin,
        ),
    )
