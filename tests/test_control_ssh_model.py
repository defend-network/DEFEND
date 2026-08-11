from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
import sys
import time

import pytest

from defend_control.ssh_tunnel import (
    CommandResult,
    CommandCancelled,
    HostFingerprintConfirmation,
    SshTunnel,
    SshTunnelError,
    run_command,
)
from defend_control.model_probe import ModelProbe, ModelProbeError, ProbeResponse
from defend_control.remote_vllm import RemoteVllmBootstrap, RemoteVllmError
from defend_control.types import AdapterSpec, ModelReady, VastInstance
from defend_control.vast import VastClient


@dataclass
class RecordedProcess:
    pid: int = 7001


class RecordingSupervisor:
    def __init__(self) -> None:
        self.specs = []

    def start(self, spec):
        self.specs.append(spec)
        return RecordedProcess()


class FakeSshCommands:
    def __init__(self, key_line: str) -> None:
        self.key_line = key_line
        self.calls: list[tuple[tuple[str, ...], bytes | None, float]] = []

    def __call__(
        self,
        argv: tuple[str, ...],
        *,
        stdin: bytes | None,
        timeout: float,
    ) -> CommandResult:
        self.calls.append((argv, stdin, timeout))
        executable = Path(argv[0]).name.casefold()
        if executable == "ssh-keyscan.exe":
            return CommandResult(0, (self.key_line + "\n").encode("ascii"), b"")
        if executable == "ssh-keygen.exe" and "-lf" in argv:
            assert stdin == (self.key_line + "\n").encode("ascii")
            return CommandResult(
                0,
                b"256 SHA256:syntheticFingerprint host (ED25519)\n",
                b"",
            )
        raise AssertionError(f"unexpected synthetic command: {argv!r}")


def running_instance() -> VastInstance:
    return VastInstance(
        instance_id=4815,
        actual_status="running",
        ssh_host="ssh.example.test",
        ssh_port=2222,
        gpu_name="A100 SXM4",
        gpu_ram_mb=81920,
        dph_total=Decimal("1.75"),
    )


def make_tunnel(tmp_path: Path):
    key_path = tmp_path / "vast_ed25519"
    key_path.write_text("synthetic private key", encoding="utf-8")
    key_path.with_suffix(".pub").write_text(
        "ssh-ed25519 AAAAC3NzaSyntheticKey defend-control\n",
        encoding="utf-8",
    )
    known_hosts = tmp_path / "known_hosts"
    commands = FakeSshCommands(
        "[ssh.example.test]:2222 ssh-ed25519 AAAAC3NzaPresentedHostKey"
    )
    supervisor = RecordingSupervisor()
    acl_paths: list[Path] = []
    tunnel = SshTunnel(
        supervisor,
        known_hosts=known_hosts,
        key_path=key_path,
        command_runner=commands,
        acl=acl_paths.append,
        ssh_exe=Path("C:/Windows/System32/OpenSSH/ssh.exe"),
        ssh_keyscan_exe=Path("C:/Windows/System32/OpenSSH/ssh-keyscan.exe"),
        ssh_keygen_exe=Path("C:/Windows/System32/OpenSSH/ssh-keygen.exe"),
    )
    return tunnel, commands, supervisor, known_hosts, key_path, acl_paths


def test_unknown_host_requires_exact_fingerprint_confirmation(tmp_path: Path):
    tunnel, _commands, _supervisor, known_hosts, _key, _acls = make_tunnel(
        tmp_path
    )

    with pytest.raises(HostFingerprintConfirmation) as pending:
        tunnel.prepare_host(running_instance(), confirm_fingerprint=None)

    assert pending.value.instance_id == 4815
    assert pending.value.fingerprint == "SHA256:syntheticFingerprint"
    assert not known_hosts.exists()

    with pytest.raises(HostFingerprintConfirmation):
        tunnel.prepare_host(
            running_instance(), confirm_fingerprint="SHA256:different"
        )
    assert not known_hosts.exists()


def test_host_scan_rejects_key_line_for_a_different_endpoint(tmp_path: Path):
    tunnel, commands, _supervisor, _known_hosts, _key, _acls = make_tunnel(
        tmp_path
    )
    commands.key_line = (
        "[different.example.test]:2222 ssh-ed25519 AAAAC3NzaPresentedHostKey"
    )

    with pytest.raises(SshTunnelError, match="exact endpoint"):
        tunnel.prepare_host(running_instance(), confirm_fingerprint=None)


def test_confirmed_host_is_pinned_for_exact_endpoint_and_instance(tmp_path: Path):
    tunnel, _commands, _supervisor, known_hosts, _key, acl_paths = make_tunnel(
        tmp_path
    )

    fingerprint = tunnel.prepare_host(
        running_instance(),
        confirm_fingerprint="SHA256:syntheticFingerprint",
    )

    assert fingerprint == "SHA256:syntheticFingerprint"
    assert known_hosts.read_text("utf-8") == (
        "[ssh.example.test]:2222 ssh-ed25519 "
        "AAAAC3NzaPresentedHostKey defend-instance-4815\n"
    )
    assert acl_paths == [known_hosts]


def test_forward_uses_strict_known_hosts_loopback_and_no_secret_argv(
    tmp_path: Path,
):
    tunnel, _commands, supervisor, known_hosts, key_path, _acls = make_tunnel(
        tmp_path
    )
    tunnel.prepare_host(
        running_instance(), confirm_fingerprint="SHA256:syntheticFingerprint"
    )

    tunnel.start(running_instance())

    assert len(supervisor.specs) == 1
    spec = supervisor.specs[0]
    assert spec.name == "ssh tunnel"
    assert "-N" in spec.argv
    assert "127.0.0.1:8001:127.0.0.1:8000" in spec.argv
    assert "BatchMode=yes" in spec.argv
    assert "ExitOnForwardFailure=yes" in spec.argv
    assert "StrictHostKeyChecking=yes" in spec.argv
    assert f"UserKnownHostsFile={known_hosts}" in spec.argv
    assert str(key_path) in spec.argv
    assert spec.env == {}
    assert not any(
        "hf_" in part.casefold() or "bearer" in part.casefold()
        for part in spec.argv
    )


def test_forward_requires_pin_for_the_exact_instance(tmp_path: Path):
    tunnel, _commands, _supervisor, _known_hosts, _key_path, _acls = make_tunnel(
        tmp_path
    )
    tunnel.prepare_host(
        running_instance(), confirm_fingerprint="SHA256:syntheticFingerprint"
    )
    replacement = VastInstance(
        4816,
        "running",
        "ssh.example.test",
        2222,
        "A100 SXM4",
        81920,
        Decimal("1.75"),
    )

    with pytest.raises(SshTunnelError, match="not pinned"):
        tunnel.start(replacement)


class Response:
    def __init__(self, status_code: int, document: object) -> None:
        self.status_code = status_code
        self.body = json.dumps(document).encode("utf-8")


class QueueTransport:
    def __init__(self, responses: list[Response]) -> None:
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **options):
        self.requests.append((method, url, options))
        return self.responses.pop(0)


def test_vast_ssh_key_matches_algorithm_and_blob_not_comment():
    transport = QueueTransport(
        [
            Response(
                200,
                {
                    "ssh_keys": [
                        {
                            "id": 44,
                            "ssh_key": (
                                "ssh-ed25519 AAAAC3NzaCanonical existing-comment"
                            ),
                        }
                    ]
                },
            )
        ]
    )

    key_id = VastClient("vast_synthetic", transport=transport).ensure_account_ssh_key(
        "ssh-ed25519 AAAAC3NzaCanonical defend-control"
    )

    assert key_id == 44
    assert [method for method, _url, _options in transport.requests] == ["GET"]


def test_vast_ssh_key_create_accepts_official_nested_key_id():
    transport = QueueTransport(
        [
            Response(200, {"ssh_keys": []}),
            Response(200, {"success": True, "key": {"id": 55}}),
        ]
    )

    key_id = VastClient("vast_synthetic", transport=transport).ensure_account_ssh_key(
        "ssh-ed25519 AAAAC3NzaNested defend-control"
    )

    assert key_id == 55


def test_vast_ssh_key_lookup_skips_unrelated_or_malformed_account_keys():
    transport = QueueTransport(
        [
            Response(
                200,
                {
                    "ssh_keys": [
                        {"id": 1, "ssh_key": "not-a-key"},
                        {"id": 2, "ssh_key": "ssh-rsa AAAARsaKey comment"},
                        {
                            "id": 3,
                            "ssh_key": "ssh-ed25519 AAAAC3NzaTarget old-comment",
                        },
                    ]
                },
            )
        ]
    )

    key_id = VastClient("vast_synthetic", transport=transport).ensure_account_ssh_key(
        "ssh-ed25519 AAAAC3NzaTarget defend-control"
    )

    assert key_id == 3


def test_native_command_runner_uses_bounded_stdin_without_shell():
    result = run_command(
        (
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())",
        ),
        stdin=b"synthetic-stdin",
        timeout=5.0,
    )

    assert result == CommandResult(0, b"synthetic-stdin", b"")


def test_native_command_runner_terminates_promptly_when_cancelled():
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks >= 2

    started = time.monotonic()
    with pytest.raises(CommandCancelled):
        run_command(
            (sys.executable, "-c", "import time; time.sleep(30)"),
            stdin=None,
            timeout=10.0,
            cancelled=cancelled,
        )

    assert time.monotonic() - started < 3.0


def test_native_command_runner_terminates_on_oversized_output():
    started = time.monotonic()
    with pytest.raises(SshTunnelError, match="exceeded 64 KiB"):
        run_command(
            (
                sys.executable,
                "-c",
                "import sys,time; sys.stdout.write('x'*70000); sys.stdout.flush(); time.sleep(30)",
            ),
            stdin=None,
            timeout=10.0,
        )

    assert time.monotonic() - started < 3.0


def adapter_spec() -> AdapterSpec:
    return AdapterSpec(
        adapter_repo="Defend-network/defend-qwen-32b-lora",
        adapter_revision="a" * 40,
        base_repo="Qwen/example-32B",
        base_revision="b" * 40,
        peft_type="LORA",
    )


class RecordingRemoteCommands:
    def __init__(self, *, returncode: int = 0, stdout: bytes = b"") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.calls: list[tuple[tuple[str, ...], bytes | None, float]] = []

    def __call__(self, argv, *, stdin, timeout, cancelled=None):
        self.calls.append((argv, stdin, timeout))
        return CommandResult(self.returncode, self.stdout, b"synthetic stderr")


def make_bootstrap(tmp_path: Path, commands: RecordingRemoteCommands):
    return RemoteVllmBootstrap(
        command_runner=commands,
        ssh_exe=Path("C:/Windows/System32/OpenSSH/ssh.exe"),
        known_hosts=tmp_path / "known_hosts",
        key_path=tmp_path / "vast_ed25519",
        max_model_len=8192,
    )


def test_remote_bootstrap_sends_bounded_script_over_stdin_without_secret_argv(
    tmp_path: Path,
):
    commands = RecordingRemoteCommands()
    bootstrap = make_bootstrap(tmp_path, commands)
    secrets = {
        "HF_TOKEN": "hf_synthetic_private_value",
        "VLLM_API_KEY": "vllm_synthetic_private_value",
    }

    bootstrap.start(running_instance(), adapter_spec(), secrets)

    assert len(commands.calls) == 1
    argv, stdin, timeout = commands.calls[0]
    assert argv[-2:] == ("root@ssh.example.test", "bash -s")
    assert timeout == 900.0
    assert stdin is not None and len(stdin) <= 64 * 1024
    rendered = stdin.decode("ascii")
    assert "set +x" in rendered
    assert "umask 077" in rendered
    assert "install -d -m 700 /workspace/defend" in rendered
    assert "Qwen/example-32B" in rendered
    assert "a" * 40 in rendered
    assert "b" * 40 in rendered
    assert "--host 127.0.0.1" in rendered
    assert "--port 8000" in rendered
    assert "--enable-lora" in rendered
    assert "defend-ai=/workspace/defend/adapter" in rendered
    assert "--max-model-len 8192" in rendered
    assert "printf '%s\\n' \"$!\" > /workspace/defend/vllm.pid" in rendered
    assert "--api-key" not in rendered
    for secret in secrets.values():
        assert secret not in rendered
        assert not any(secret in part for part in argv)


def test_remote_bootstrap_rejects_missing_or_oversized_secrets_before_ssh(
    tmp_path: Path,
):
    commands = RecordingRemoteCommands()
    bootstrap = make_bootstrap(tmp_path, commands)

    with pytest.raises(RemoteVllmError, match="required secret names"):
        bootstrap.start(running_instance(), adapter_spec(), {"HF_TOKEN": "value"})
    with pytest.raises(RemoteVllmError, match="secret payload is too large"):
        bootstrap.start(
            running_instance(),
            adapter_spec(),
            {"HF_TOKEN": "x" * 40_000, "VLLM_API_KEY": "y" * 40_000},
        )

    assert commands.calls == []


def test_remote_bootstrap_failure_never_reflects_command_output_or_secret(
    tmp_path: Path,
):
    sentinel = "hf_private_provider_sentinel"
    commands = RecordingRemoteCommands(
        returncode=9, stdout=f"failed {sentinel}".encode("ascii")
    )

    with pytest.raises(RemoteVllmError) as pending:
        make_bootstrap(tmp_path, commands).start(
            running_instance(),
            adapter_spec(),
            {"HF_TOKEN": sentinel, "VLLM_API_KEY": "vllm_private"},
        )

    assert str(pending.value) == "Remote vLLM bootstrap failed (exit 9)"
    assert sentinel not in repr(pending.value)


def test_remote_bootstrap_cleanup_removes_only_temporary_token_file(
    tmp_path: Path,
):
    commands = RecordingRemoteCommands()
    bootstrap = make_bootstrap(tmp_path, commands)

    bootstrap.cleanup_token_file(running_instance())

    argv, stdin, _timeout = commands.calls[0]
    assert argv[-2:] == ("root@ssh.example.test", "bash -s")
    assert stdin == (
        b"#!/usr/bin/env bash\nset -euo pipefail\n"
        b"rm -f -- /workspace/defend/.hf_token\n"
    )


def test_remote_bootstrap_honors_cancellation_before_starting_ssh(tmp_path: Path):
    commands = RecordingRemoteCommands()
    bootstrap = make_bootstrap(tmp_path, commands)

    with pytest.raises(RemoteVllmError, match="cancelled"):
        bootstrap.start(
            running_instance(),
            adapter_spec(),
            {"HF_TOKEN": "synthetic", "VLLM_API_KEY": "synthetic"},
            cancelled=lambda: True,
        )

    assert commands.calls == []


class FakeProbeTransport:
    def __init__(self, responses: list[ProbeResponse]) -> None:
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **options):
        self.requests.append((method, url, options))
        return self.responses.pop(0)


def test_model_probe_requires_alias_then_neutral_generation():
    token = "vllm_synthetic_private"
    transport = FakeProbeTransport(
        [
            ProbeResponse(200, b'{"data":[{"id":"defend-ai"}]}'),
            ProbeResponse(
                200,
                b'{"choices":[{"message":{"content":"READY"}}]}',
            ),
        ]
    )
    probe = ModelProbe(transport=transport, monotonic=lambda: 0.0)

    ready = probe.wait_ready(
        "http://127.0.0.1:8001/v1",
        token,
        timeout_seconds=300.0,
        poll_interval_seconds=0,
    )

    assert ready == ModelReady(
        "defend-ai", "openai_compatible", "http://127.0.0.1:8001/v1"
    )
    assert [request[:2] for request in transport.requests] == [
        ("GET", "http://127.0.0.1:8001/v1/models"),
        ("POST", "http://127.0.0.1:8001/v1/chat/completions"),
    ]
    for _method, _url, options in transport.requests:
        assert options["headers"]["Authorization"] == f"Bearer {token}"
        assert token not in _url
        assert token not in json.dumps(options["json"])
    assert transport.requests[1][2]["json"] == {
        "model": "defend-ai",
        "messages": [{"role": "user", "content": "Reply with READY only"}],
        "temperature": 0,
        "max_tokens": 8,
    }
    assert token not in repr(probe)


def test_model_probe_retries_unready_models_and_never_posts_early():
    transport = FakeProbeTransport(
        [
            ProbeResponse(200, b'{"data":[]}'),
            ProbeResponse(503, b'{"error":"still loading"}'),
            ProbeResponse(200, b'{"data":[{"id":"defend-ai"}]}'),
            ProbeResponse(200, b'{"choices":[{"message":{"content":"OK"}}]}'),
        ]
    )
    sleeps = []
    probe = ModelProbe(
        transport=transport,
        monotonic=lambda: 0.0,
        sleep=sleeps.append,
    )

    probe.wait_ready(
        "http://127.0.0.1:8001/v1",
        "vllm_synthetic",
        timeout_seconds=300.0,
        poll_interval_seconds=0.25,
    )

    assert [method for method, _url, _options in transport.requests] == [
        "GET",
        "GET",
        "GET",
        "POST",
    ]
    assert sleeps == [0.25, 0.25]


def test_model_probe_rejects_non_loopback_and_safe_generation_failure():
    probe = ModelProbe(transport=FakeProbeTransport([]))
    with pytest.raises(ValueError, match="loopback"):
        probe.wait_ready("https://public.example/v1", "synthetic")

    sentinel = "private_generation_response_sentinel"
    transport = FakeProbeTransport(
        [
            ProbeResponse(200, b'{"data":[{"id":"defend-ai"}]}'),
            ProbeResponse(
                200,
                json.dumps(
                    {"choices": [{"message": {"content": ""}}], "detail": sentinel}
                ).encode("utf-8"),
            ),
        ]
    )
    with pytest.raises(ModelProbeError) as pending:
        ModelProbe(transport=transport, monotonic=lambda: 0.0).wait_ready(
            "http://127.0.0.1:8001/v1", "vllm_synthetic"
        )

    assert str(pending.value) == "vLLM generation probe did not return content"
    assert sentinel not in repr(pending.value)


class MutableClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class DeadlineProbeTransport(FakeProbeTransport):
    def __init__(self, clock: MutableClock):
        super().__init__([ProbeResponse(200, b'{"data":[{"id":"defend-ai"}]}')])
        self.clock = clock

    def request(self, method, url, **options):
        result = super().request(method, url, **options)
        self.clock.value = 300.0
        return result


def test_model_probe_rejects_response_that_crosses_absolute_deadline():
    clock = MutableClock()
    transport = DeadlineProbeTransport(clock)

    with pytest.raises(ModelProbeError, match="timed out after 300 seconds"):
        ModelProbe(transport=transport, monotonic=clock).wait_ready(
            "http://127.0.0.1:8001/v1", "synthetic"
        )

    assert len(transport.requests) == 1


class GenerationDeadlineTransport(FakeProbeTransport):
    def __init__(self, clock: MutableClock):
        super().__init__(
            [
                ProbeResponse(200, b'{"data":[{"id":"defend-ai"}]}'),
                ProbeResponse(
                    200,
                    b'{"choices":[{"message":{"content":"READY"}}]}',
                ),
            ]
        )
        self.clock = clock

    def request(self, method, url, **options):
        result = super().request(method, url, **options)
        if method == "POST":
            self.clock.value = 300.0
        return result


def test_model_probe_rejects_generation_that_crosses_absolute_deadline():
    clock = MutableClock()
    transport = GenerationDeadlineTransport(clock)

    with pytest.raises(ModelProbeError, match="timed out after 300 seconds"):
        ModelProbe(transport=transport, monotonic=clock).wait_ready(
            "http://127.0.0.1:8001/v1", "synthetic"
        )

    assert len(transport.requests) == 2
