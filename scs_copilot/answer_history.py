"""Job-private answer history store (M1.4.3, P21).

Bounded, atomic, concurrent-safe persistence of the safe rendered answer and
its verified/blocked claim refs plus tool/source/calculator execution IDs.
Never stores hidden reasoning or the model's raw unverified prose.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_MAX_HISTORY = 200


def _new_tmp_suffix() -> str:
    return uuid.uuid4().hex[:8]


def _atomic_replace(tmp: Path, path: Path) -> None:
    """Retry-tolerant atomic replace (Windows filesystems can transiently
    hold the destination handle)."""
    for attempt in range(5):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.02)

_GLOBAL_LOCKS: dict[str, threading.RLock] = {}
_GLOBAL_LOCKS_GUARD = threading.Lock()


def _shared_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _GLOBAL_LOCKS_GUARD:
        if key not in _GLOBAL_LOCKS:
            _GLOBAL_LOCKS[key] = threading.RLock()
        return _GLOBAL_LOCKS[key]


class AnswerHistoryStore:
    """Job-scoped answer history with atomic bounded writes (P21)."""

    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", job_id)
        return self._dir / f"{safe}.answers.json"

    def load(self, job_id: str) -> list[dict[str, Any]]:
        path = self._path(job_id)
        with _shared_lock(path):
            if not path.exists():
                return []
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return []

    def append(self, job_id: str, entry: dict[str, Any]) -> list[dict[str, Any]]:
        path = self._path(job_id)
        with _shared_lock(path):
            history = []
            if path.exists():
                try:
                    history = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    history = []
            history.append(entry)
            history = history[-_MAX_HISTORY:]
            tmp = path.with_name(path.name + f".{_new_tmp_suffix()}.tmp")
            tmp.write_text(json.dumps(history, indent=2, default=str),
                           encoding="utf-8")
            _atomic_replace(tmp, path)
            return history
