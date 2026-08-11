from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
from typing import Protocol

from .processes import ProcessSpec, ProcessSupervisor
from .secrets import restrict_to_current_user
from .types import VastInstance


_MAX_COMMAND_OUTPUT = 64 * 1024
_MAX_PUBLIC_KEY_BYTES = 16 * 1024
_FINGERPRINT = re.compile(r"^SHA256:[A-Za-z0-9+/]{8,}={0,2}$")
_KEY_TYPE = re.compile(r"^(?:ssh-ed25519|ecdsa-sha2-[A-Za-z0-9@._+-]+|rsa-sha2-(?:256|512))$")
_KEY_BLOB = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class _CommandRunner(Protocol):
    def __call__(
        self,
        argv: tuple[str, ...],
        *,
        stdin: bytes | None,
        timeout: float,
    ) -> CommandResult: ...


class SshTunnelError(RuntimeError):
    """A safe SSH setup failure that never reflects command output."""


class CommandCancelled(RuntimeError):
    """Raised after a bounded command has been terminated for cancellation."""


class HostFingerprintConfirmation(RuntimeError):
    def __init__(self, instance_id: int, fingerprint: str) -> None:
        super().__init__(
            f"Confirm SSH host fingerprint {fingerprint} for Vast instance {instance_id}"
        )
        self.instance_id = instance_id
        self.fingerprint = fingerprint


def run_command(
    argv: tuple[str, ...],
    *,
    stdin: bytes | None,
    timeout: float,
    cancelled: Callable[[], bool] | None = None,
) -> CommandResult:
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0 < float(timeout) <= 900
    ):
        raise ValueError("command timeout is invalid")
    if cancelled is not None and cancelled():
        raise CommandCancelled("command was cancelled")
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=(
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        ),
    )
    deadline = time.monotonic() + float(timeout)
    overflow = threading.Event()
    writer_failed = threading.Event()
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()

    def read_bounded(stream, target: bytearray) -> None:
        try:
            while chunk := stream.read1(4_096):
                remaining = _MAX_COMMAND_OUTPUT - len(target)
                if len(chunk) > remaining:
                    target.extend(chunk[: max(0, remaining)])
                    overflow.set()
                    return
                target.extend(chunk)
        except Exception:
            return

    readers = (
        threading.Thread(
            target=read_bounded,
            args=(process.stdout, stdout_buffer),
            daemon=True,
        ),
        threading.Thread(
            target=read_bounded,
            args=(process.stderr, stderr_buffer),
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()

    writer = None
    if stdin is not None:
        def write_input() -> None:
            try:
                process.stdin.write(stdin)
                process.stdin.flush()
            except Exception:
                writer_failed.set()
            finally:
                try:
                    process.stdin.close()
                except Exception:
                    pass

        writer = threading.Thread(target=write_input, daemon=True)
        writer.start()

    def terminate() -> None:
        try:
            process.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=2.0)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=2.0)
            except Exception:
                pass

    outcome: str | None = None
    while process.poll() is None:
        if overflow.is_set():
            outcome = "overflow"
            break
        if writer_failed.is_set():
            outcome = "stdin"
            break
        if cancelled is not None and cancelled():
            outcome = "cancelled"
            break
        if time.monotonic() >= deadline:
            outcome = "timeout"
            break
        time.sleep(0.02)
    if outcome is not None:
        terminate()
    for stream in (process.stdout, process.stderr):
        try:
            stream.close()
        except Exception:
            pass
    for thread in (*readers, *((writer,) if writer is not None else ())):
        thread.join(timeout=2.0)

    if outcome == "overflow" or overflow.is_set():
        raise SshTunnelError("OpenSSH command output exceeded 64 KiB")
    if outcome == "stdin" or writer_failed.is_set():
        raise SshTunnelError("OpenSSH command input failed")
    if outcome == "cancelled":
        raise CommandCancelled("command was cancelled")
    if outcome == "timeout":
        raise TimeoutError("command timed out")
    return CommandResult(
        int(process.returncode), bytes(stdout_buffer), bytes(stderr_buffer)
    )


def _trusted_openssh(name: str) -> Path:
    system_root = os.environ.get("SYSTEMROOT")
    if not system_root:
        raise SshTunnelError("Windows system directory is unavailable")
    candidate = Path(system_root) / "System32" / "OpenSSH" / name
    if not candidate.is_file():
        raise SshTunnelError(f"Required Windows OpenSSH component {name} is missing")
    return candidate


def _valid_host(host: object) -> str:
    if not isinstance(host, str) or not host or len(host) > 253:
        raise SshTunnelError("Vast.ai SSH endpoint is invalid")
    if any(character.isspace() or ord(character) < 0x21 for character in host):
        raise SshTunnelError("Vast.ai SSH endpoint is invalid")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    try:
        ascii_host = host.encode("idna").decode("ascii").rstrip(".")
    except UnicodeError:
        raise SshTunnelError("Vast.ai SSH endpoint is invalid") from None
    labels = ascii_host.split(".")
    if not all(
        label
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in labels
    ):
        raise SshTunnelError("Vast.ai SSH endpoint is invalid")
    return ascii_host


def _endpoint(instance: VastInstance) -> tuple[str, int]:
    if not isinstance(instance, VastInstance):
        raise ValueError("instance must be a VastInstance")
    if type(instance.instance_id) is not int or instance.instance_id <= 0:
        raise SshTunnelError("Vast.ai instance identity is invalid")
    host = _valid_host(instance.ssh_host)
    port = instance.ssh_port
    if type(port) is not int or not 1 <= port <= 65_535:
        raise SshTunnelError("Vast.ai SSH endpoint is invalid")
    return host, port


def _key_parts(line: str) -> tuple[str, str] | None:
    fields = line.strip().split()
    if len(fields) < 2:
        return None
    if _KEY_TYPE.fullmatch(fields[0]) and _KEY_BLOB.fullmatch(fields[1]):
        return fields[0], fields[1]
    if (
        len(fields) >= 3
        and _KEY_TYPE.fullmatch(fields[1])
        and _KEY_BLOB.fullmatch(fields[2])
    ):
        return fields[1], fields[2]
    return None


class SshTunnel:
    def __init__(
        self,
        supervisor: ProcessSupervisor,
        *,
        known_hosts: Path,
        key_path: Path,
        command_runner: _CommandRunner = run_command,
        acl: Callable[[Path], None] = restrict_to_current_user,
        ssh_exe: Path | None = None,
        ssh_keyscan_exe: Path | None = None,
        ssh_keygen_exe: Path | None = None,
        local_port: int = 8001,
    ) -> None:
        if type(local_port) is not int or not 1 <= local_port <= 65_535:
            raise ValueError("local SSH forward port is invalid")
        self._supervisor = supervisor
        self._known_hosts = Path(known_hosts)
        self._key_path = Path(key_path)
        self._run = command_runner
        self._acl = acl
        self._ssh_exe = ssh_exe or _trusted_openssh("ssh.exe")
        self._ssh_keyscan_exe = ssh_keyscan_exe or _trusted_openssh(
            "ssh-keyscan.exe"
        )
        self._ssh_keygen_exe = ssh_keygen_exe or _trusted_openssh(
            "ssh-keygen.exe"
        )
        self._local_port = local_port

    @property
    def key_path(self) -> Path:
        return self._key_path

    @property
    def known_hosts(self) -> Path:
        return self._known_hosts

    @property
    def ssh_exe(self) -> Path:
        return self._ssh_exe

    def ensure_identity(self) -> str:
        public_path = Path(f"{self._key_path}.pub")
        private_exists = self._key_path.is_file()
        public_exists = public_path.is_file()
        if private_exists != public_exists:
            raise SshTunnelError("Dedicated SSH identity is incomplete")
        if not private_exists:
            self._key_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                result = self._run(
                    (
                        str(self._ssh_keygen_exe),
                        "-q",
                        "-t",
                        "ed25519",
                        "-f",
                        str(self._key_path),
                        "-N",
                        "",
                        "-C",
                        "defend-control",
                    ),
                    stdin=None,
                    timeout=30.0,
                )
            except Exception as error:
                raise SshTunnelError(
                    f"Dedicated SSH identity could not be created ({type(error).__name__})"
                ) from None
            if result.returncode != 0:
                raise SshTunnelError("Dedicated SSH identity could not be created")
            if not self._key_path.is_file() or not public_path.is_file():
                raise SshTunnelError("Dedicated SSH identity was not created")
        try:
            public_bytes = public_path.read_bytes()
        except OSError as error:
            raise SshTunnelError(
                f"Dedicated SSH public key could not be read ({type(error).__name__})"
            ) from None
        if not public_bytes or len(public_bytes) > _MAX_PUBLIC_KEY_BYTES:
            raise SshTunnelError("Dedicated SSH public key is invalid")
        try:
            public_key = public_bytes.decode("ascii").strip()
        except UnicodeDecodeError:
            raise SshTunnelError("Dedicated SSH public key is invalid") from None
        if "\n" in public_key or "\r" in public_key or _key_parts(public_key) is None:
            raise SshTunnelError("Dedicated SSH public key is invalid")
        self._acl(self._key_path)
        return public_key

    def _scan(self, host: str, port: int) -> tuple[str, str]:
        try:
            scanned = self._run(
                (
                    str(self._ssh_keyscan_exe),
                    "-T",
                    "10",
                    "-t",
                    "ed25519",
                    "-p",
                    str(port),
                    host,
                ),
                stdin=None,
                timeout=15.0,
            )
        except Exception as error:
            raise SshTunnelError(
                f"SSH host key scan failed ({type(error).__name__})"
            ) from None
        if scanned.returncode != 0 or not scanned.stdout:
            raise SshTunnelError("SSH host key scan failed")
        if len(scanned.stdout) > _MAX_COMMAND_OUTPUT:
            raise SshTunnelError("SSH host key scan exceeded 64 KiB")
        try:
            lines = scanned.stdout.decode("ascii").splitlines()
        except UnicodeDecodeError:
            raise SshTunnelError("SSH host key scan was invalid") from None
        expected_marker = f"[{host}]:{port}"
        candidates = [
            line.strip()
            for line in lines
            if line.strip().split()
            and line.strip().split()[0] == expected_marker
            and _key_parts(line)
        ]
        if not candidates:
            raise SshTunnelError(
                "SSH host key scan did not match the exact endpoint"
            )
        identities = {_key_parts(line) for line in candidates}
        if len(candidates) != 1 or len(identities) != 1:
            raise SshTunnelError("SSH host key scan did not return one Ed25519 key")
        key_type, key_blob = _key_parts(candidates[0]) or (None, None)
        if key_type != "ssh-ed25519" or key_blob is None:
            raise SshTunnelError("SSH host key scan did not return one Ed25519 key")
        key_line = candidates[0]
        try:
            fingerprint_result = self._run(
                (str(self._ssh_keygen_exe), "-lf", "-", "-E", "sha256"),
                stdin=(key_line + "\n").encode("ascii"),
                timeout=10.0,
            )
        except Exception as error:
            raise SshTunnelError(
                f"SSH fingerprint calculation failed ({type(error).__name__})"
            ) from None
        if fingerprint_result.returncode != 0:
            raise SshTunnelError("SSH fingerprint calculation failed")
        try:
            output = fingerprint_result.stdout.decode("ascii").strip().split()
        except UnicodeDecodeError:
            raise SshTunnelError("SSH fingerprint calculation was invalid") from None
        fingerprint = next(
            (field for field in output if _FINGERPRINT.fullmatch(field)), None
        )
        if fingerprint is None:
            raise SshTunnelError("SSH fingerprint calculation was invalid")
        return f"{key_type} {key_blob}", fingerprint

    def _is_pinned(self, marker: str, identity: str, instance_id: int) -> bool:
        try:
            payload = self._known_hosts.read_bytes()
        except FileNotFoundError:
            return False
        except OSError as error:
            raise SshTunnelError(
                f"Dedicated known-hosts file could not be read ({type(error).__name__})"
            ) from None
        if len(payload) > _MAX_COMMAND_OUTPUT:
            raise SshTunnelError("Dedicated known-hosts file exceeds 64 KiB")
        try:
            lines = payload.decode("ascii").splitlines()
        except UnicodeDecodeError:
            raise SshTunnelError("Dedicated known-hosts file is invalid") from None
        expected = f"{marker} {identity} defend-instance-{instance_id}"
        return expected in lines

    def _pin(self, marker: str, identity: str, instance_id: int) -> None:
        existing: list[str] = []
        if self._known_hosts.exists():
            try:
                payload = self._known_hosts.read_bytes()
            except OSError as error:
                raise SshTunnelError(
                    f"Dedicated known-hosts file could not be read ({type(error).__name__})"
                ) from None
            if len(payload) > _MAX_COMMAND_OUTPUT:
                raise SshTunnelError("Dedicated known-hosts file exceeds 64 KiB")
            try:
                existing = payload.decode("ascii").splitlines()
            except UnicodeDecodeError:
                raise SshTunnelError("Dedicated known-hosts file is invalid") from None
        retained = [line for line in existing if not line.startswith(f"{marker} ")]
        retained.append(f"{marker} {identity} defend-instance-{instance_id}")
        encoded = ("\n".join(retained) + "\n").encode("ascii")
        self._known_hosts.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self._known_hosts.parent,
            prefix=f".{self._known_hosts.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self._known_hosts)
            self._acl(self._known_hosts)
        finally:
            temporary_path.unlink(missing_ok=True)

    def prepare_host(
        self,
        instance: VastInstance,
        confirm_fingerprint: str | None,
    ) -> str:
        host, port = _endpoint(instance)
        identity, fingerprint = self._scan(host, port)
        marker = f"[{host}]:{port}"
        if self._is_pinned(marker, identity, instance.instance_id):
            return fingerprint
        if confirm_fingerprint != fingerprint:
            raise HostFingerprintConfirmation(instance.instance_id, fingerprint)
        self._pin(marker, identity, instance.instance_id)
        return fingerprint

    def start(self, instance: VastInstance):
        host, port = _endpoint(instance)
        marker = f"[{host}]:{port}"
        try:
            known_hosts = self._known_hosts.read_text("ascii")
        except (OSError, UnicodeError) as error:
            raise SshTunnelError(
                f"Dedicated known-hosts file is unavailable ({type(error).__name__})"
            ) from None
        expected_suffix = f" defend-instance-{instance.instance_id}"
        if not any(
            line.startswith(f"{marker} ") and line.endswith(expected_suffix)
            for line in known_hosts.splitlines()
        ):
            raise SshTunnelError("Vast.ai SSH host is not pinned")
        spec = ProcessSpec(
            "ssh tunnel",
            (
                str(self._ssh_exe),
                "-N",
                "-L",
                f"127.0.0.1:{self._local_port}:127.0.0.1:8000",
                "-p",
                str(port),
                "-i",
                str(self._key_path),
                "-o",
                "BatchMode=yes",
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                f"UserKnownHostsFile={self._known_hosts}",
                f"root@{host}",
            ),
            self._key_path.parent,
            {},
            None,
        )
        return self._supervisor.start(spec)
