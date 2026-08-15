"""Remote vLLM bootstrap for DEFENDcoder — plain instruct model, no LoRA.

Separated from identity RemoteVllmBootstrap which pins the chat adapter.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import base64
from pathlib import Path
import re
import shlex
from typing import Protocol

from .coder_deployment import (
    CoderDeploymentArtifact,
    is_exact_revision,
    resolve_deployment,
)
from .coder_m0 import CoderModelRef
from .ssh_tunnel import CommandResult, resolve_endpoint, run_command
from .types import VastInstance

_MAX_STDIN_BYTES = 64 * 1024
_REVISION = re.compile(r"^(main|[0-9a-f]{7,64})$")
_REPOSITORY = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$"
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


class CoderRemoteVllmError(RuntimeError):
    """Bounded remote coder launch error — no remote body or secrets."""


def _endpoint(
    instance: VastInstance, *, prefer_direct: bool = False
) -> tuple[str, int]:
    try:
        host, port, _transport = resolve_endpoint(instance, prefer_direct=prefer_direct)
    except RuntimeError:
        raise CoderRemoteVllmError("Vast.ai SSH endpoint is invalid") from None
    return host, port


def _validate_model(model: CoderModelRef) -> None:
    if not isinstance(model, CoderModelRef):
        raise ValueError("model must be a CoderModelRef")
    if not _REPOSITORY.fullmatch(model.repo_id) or not _REVISION.fullmatch(
        model.revision
    ):
        raise CoderRemoteVllmError("Coder model repository/revision is invalid")
    if type(model.max_model_len) is not int or not 1024 <= model.max_model_len <= 131072:
        raise CoderRemoteVllmError("Coder max_model_len is invalid")


def _validate_artifact(artifact: CoderDeploymentArtifact) -> None:
    if not isinstance(artifact, CoderDeploymentArtifact):
        raise ValueError("artifact must be a CoderDeploymentArtifact")
    if (
        not _REPOSITORY.fullmatch(artifact.repo_id)
        or not is_exact_revision(artifact.revision)
    ):
        raise CoderRemoteVllmError(
            "Coder deployment artifact repository/revision is invalid"
        )
    if (
        type(artifact.max_model_len) is not int
        or not 1024 <= artifact.max_model_len <= 131072
    ):
        raise CoderRemoteVllmError("Coder deployment max_model_len is invalid")
    if (
        type(artifact.tensor_parallel_size) is not int
        or not 1 <= artifact.tensor_parallel_size <= 16
    ):
        raise CoderRemoteVllmError("Coder deployment tensor_parallel_size is invalid")


class CoderRemoteVllmBootstrap:
    def __init__(
        self,
        *,
        command_runner: _CommandRunner = run_command,
        ssh_exe: Path,
        known_hosts: Path,
        key_path: Path,
    ) -> None:
        self._run = command_runner
        self._ssh_exe = Path(ssh_exe)
        self._known_hosts = Path(known_hosts)
        self._key_path = Path(key_path)

    def _argv(
        self, instance: VastInstance, *, prefer_direct: bool = False
    ) -> tuple[str, ...]:
        host, port = _endpoint(instance, prefer_direct=prefer_direct)
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
        model: CoderModelRef,
        artifact: CoderDeploymentArtifact,
        hf_token: str,
        vllm_api_key: str,
        remote_port: int,
    ) -> bytes:
        hf_encoded = base64.b64encode(hf_token.encode("utf-8")).decode("ascii")
        vllm_encoded = base64.b64encode(vllm_api_key.encode("utf-8")).decode(
            "ascii"
        )
        flag_lines: list[str] = [
            "  --host 127.0.0.1",
            f"  --port {int(remote_port)}",
            f"  --max-model-len {int(artifact.max_model_len)}",
        ]
        if artifact.enable_auto_tool_choice:
            flag_lines.append("  --enable-auto-tool-choice")
        if artifact.tool_call_parser:
            flag_lines.append(
                f"  --tool-call-parser {shlex.quote(artifact.tool_call_parser)}"
            )
        if artifact.tensor_parallel_size > 1:
            flag_lines.append(
                f"  --tensor-parallel-size {int(artifact.tensor_parallel_size)}"
            )
        flag_lines.extend(
            ("  --disable-log-requests", "  --disable-uvicorn-access-log")
        )
        flags_block = " \\\n".join(flag_lines)
        script = f"""#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
install -d -m 700 /workspace/defendcoder
printf '%s' {shlex.quote(hf_encoded)} | base64 --decode > /workspace/defendcoder/.hf_token
chmod 600 /workspace/defendcoder/.hf_token
export HF_TOKEN="$(cat /workspace/defendcoder/.hf_token)"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
VLLM_API_KEY="$(printf '%s' {shlex.quote(vllm_encoded)} | base64 --decode)"
export VLLM_API_KEY

python3 - <<'PY'
import os
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id={artifact.repo_id!r},
    revision={artifact.revision!r},
    local_dir="/workspace/defendcoder/model",
    token=os.environ.get("HF_TOKEN"),
)
print("coder download complete", flush=True)
PY

unset HF_TOKEN HUGGING_FACE_HUB_TOKEN

if command -v vllm >/dev/null 2>&1; then
  VLLM_CMD=(vllm serve)
elif python3 -c "import vllm" >/dev/null 2>&1; then
  VLLM_CMD=(python3 -m vllm.entrypoints.openai.api_server)
else
  echo "vllm not found" >&2
  exit 127
fi

nohup "${{VLLM_CMD[@]}}" /workspace/defendcoder/model \\
{flags_block} \\
  >/workspace/defendcoder/vllm.log 2>&1 </dev/null &
printf '%s\\n' "$!" > /workspace/defendcoder/vllm.pid
unset VLLM_API_KEY
rm -f -- /workspace/defendcoder/.hf_token
"""
        try:
            encoded = script.encode("ascii")
        except UnicodeEncodeError:
            raise CoderRemoteVllmError("Remote coder bootstrap input is invalid") from None
        if len(encoded) > _MAX_STDIN_BYTES:
            raise CoderRemoteVllmError("Remote coder secret payload is too large")
        return encoded

    def start(
        self,
        instance: VastInstance,
        model: CoderModelRef,
        secrets: Mapping[str, str],
        *,
        remote_port: int = 8000,
        artifact: CoderDeploymentArtifact | None = None,
        prefer_direct: bool = False,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        _validate_model(model)
        if artifact is None:
            artifact = resolve_deployment(model.alias)
        _validate_artifact(artifact)
        if type(remote_port) is not int or not 1 <= remote_port <= 65_535:
            raise CoderRemoteVllmError("Remote coder port is invalid")
        hf_token = secrets.get("HF_TOKEN")
        vllm_api_key = secrets.get("CODER_VLLM_API_KEY") or secrets.get("VLLM_API_KEY")
        if (
            not isinstance(hf_token, str)
            or not hf_token
            or not isinstance(vllm_api_key, str)
            or not vllm_api_key
        ):
            raise CoderRemoteVllmError("Remote coder required secret names are missing")
        if cancelled is not None and cancelled():
            raise CoderRemoteVllmError("Remote coder bootstrap was cancelled")
        script = self._script(model, artifact, hf_token, vllm_api_key, remote_port)
        try:
            result = self._run(
                self._argv(instance, prefer_direct=prefer_direct),
                stdin=script,
                timeout=900.0,
                cancelled=cancelled,
            )
        except Exception as error:
            raise CoderRemoteVllmError(
                f"Remote coder bootstrap failed ({type(error).__name__})"
            ) from None
        if result.returncode != 0:
            raise CoderRemoteVllmError(
                f"Remote coder bootstrap failed (exit {result.returncode})"
            )
