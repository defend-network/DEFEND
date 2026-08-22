"""Persistent runtime mutation ownership lease.

Mutating a paid runtime (PROVISION, START, RESUME, STOP, DESTROY, REMOTE
BOOTSTRAP, vLLM restart) requires an exclusive lease keyed by
(product, provider, instance_id). A second session may READ status but may not
mutate while another valid lease is active. No foreign process is ever killed;
stale leases (dead owner PID past expiry) may be safely reacquired.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        import psutil  # type: ignore

        return psutil.pid_exists(pid)
    except Exception:
        try:
            from ctypes import wintypes
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return True


class RuntimeMutationConflict(RuntimeError):
    def __init__(self, lease: "RuntimeLease") -> None:
        super().__init__("runtime mutation lease is held by another session")
        self.lease = lease


@dataclass
class RuntimeLease:
    operation_id: str
    product_id: str
    provider: str
    instance_id: int
    owner_session_id: str
    owner_pid: int
    owner_worktree: str | None
    owner_branch: str | None
    purpose: str
    acquired_at: str
    heartbeat_at: str
    expires_at: str
    ttl_seconds: int = 3600

    @property
    def acquired_datetime(self) -> datetime:
        return datetime.fromisoformat(self.acquired_at)

    @property
    def expires_datetime(self) -> datetime:
        return datetime.fromisoformat(self.expires_at)

    def as_public_dict(self) -> dict[str, object]:
        data = asdict(self)
        return data


class RuntimeLeaseStore:
    def __init__(
        self,
        path: Path | None = None,
        is_pid_alive: Callable[[int], bool] = _is_pid_alive,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) / "DEFEND" if local_app_data else Path.cwd()
        self._path = path or (base / "runtime-lease.json")
        self._is_pid_alive = is_pid_alive
        self._clock = clock or _utcnow

    def _load(self) -> dict[str, RuntimeLease]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        leases = {}
        for key, entry in (raw.items() if isinstance(raw, dict) else {}):
            if isinstance(entry, dict):
                try:
                    leases[key] = RuntimeLease(**entry)
                except (TypeError, ValueError):
                    continue
        return leases

    def _save(self, leases: dict[str, RuntimeLease]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = __import__("tempfile").mkstemp(
            dir=self._path.parent, prefix=f".{self._path.name}.", suffix=".tmp"
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({k: asdict(v) for k, v in leases.items()}, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _key(self, product_id: str, provider: str, instance_id: int) -> str:
        return f"{product_id}|{provider}|{instance_id}"

    def acquire(
        self,
        *,
        product_id: str,
        provider: str,
        instance_id: int,
        owner_session_id: str,
        owner_pid: int,
        owner_worktree: str | None,
        owner_branch: str | None,
        purpose: str,
        ttl_seconds: int = 3600,
        renew_same_session: bool = True,
    ) -> RuntimeLease:
        leases = self._load()
        key = self._key(product_id, provider, instance_id)
        existing = leases.get(key)
        now = self._clock()
        if existing is not None:
            expired = now >= existing.expires_datetime
            owner_dead = not self._is_pid_alive(existing.owner_pid)
            if expired and owner_dead:
                del leases[key]
            elif not expired and existing.owner_session_id != owner_session_id:
                raise RuntimeMutationConflict(existing)
        expires = now + timedelta(seconds=int(ttl_seconds))
        lease = RuntimeLease(
            operation_id=str(uuid4()),
            product_id=product_id,
            provider=provider,
            instance_id=instance_id,
            owner_session_id=owner_session_id,
            owner_pid=int(owner_pid),
            owner_worktree=owner_worktree,
            owner_branch=owner_branch,
            purpose=purpose,
            acquired_at=now.isoformat(),
            heartbeat_at=now.isoformat(),
            expires_at=expires.isoformat(),
            ttl_seconds=int(ttl_seconds),
        )
        leases[key] = lease
        self._save(leases)
        return lease

    def heartbeat(
        self,
        *,
        product_id: str,
        provider: str,
        instance_id: int,
        owner_session_id: str,
        ttl_seconds: int = 3600,
    ) -> RuntimeLease | None:
        leases = self._load()
        key = self._key(product_id, provider, instance_id)
        lease = leases.get(key)
        if lease is None:
            return None
        if lease.owner_session_id != owner_session_id:
            raise RuntimeMutationConflict(lease)
        now = self._clock()
        lease.heartbeat_at = now.isoformat()
        lease.expires_at = (now + timedelta(seconds=int(ttl_seconds))).isoformat()
        leases[key] = lease
        self._save(leases)
        return lease

    def release(self, *, product_id: str, provider: str, instance_id: int, owner_session_id: str) -> bool:
        leases = self._load()
        key = self._key(product_id, provider, instance_id)
        lease = leases.get(key)
        if lease is None:
            return False
        if lease.owner_session_id != owner_session_id:
            raise RuntimeMutationConflict(lease)
        del leases[key]
        self._save(leases)
        return True

    def status(self, *, product_id: str, provider: str, instance_id: int) -> dict[str, object] | None:
        """Read-only status, allowed for any session."""
        leases = self._load()
        lease = leases.get(self._key(product_id, provider, instance_id))
        if lease is None:
            return None
        now = self._clock()
        return {
            "product_id": lease.product_id,
            "provider": lease.provider,
            "instance_id": lease.instance_id,
            "owner_session_id": lease.owner_session_id,
            "owner_worktree": lease.owner_worktree,
            "owner_branch": lease.owner_branch,
            "purpose": lease.purpose,
            "acquired_at": lease.acquired_at,
            "heartbeat_at": lease.heartbeat_at,
            "expires_at": lease.expires_at,
            "lease_age_seconds": int((now - lease.acquired_datetime).total_seconds()),
            "owner_pid_alive": self._is_pid_alive(lease.owner_pid),
            "expired": now >= lease.expires_datetime,
        }
