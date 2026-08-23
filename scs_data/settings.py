"""SCS-owned operational settings authority (M1.5C-S).

Durable owner-configurable product settings under SCS private data storage.
The browser is never the authority; the server persists and resolves settings.

Precedence for `knowledge_root`:
    persisted SCS product setting  ->  explicit environment fallback  ->  NOT_CONFIGURED
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any


class ScsSettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            data = __import__("json").loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save(self) -> None:
        with self._lock:
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(__import__("json").dumps(self._data, indent=2, default=str),
                           encoding="utf-8")
            tmp.replace(self._path)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._save()

    def knowledge_root(self) -> tuple[str | None, str]:
        """Return (root, source) where source is persisted|env|not_configured."""
        persisted = self.get("knowledge_root")
        if persisted:
            return str(persisted), "persisted"
        env = os.environ.get("SCS_KNOWLEDGE_ROOT")
        if env:
            return env, "env"
        return None, "not_configured"


def validate_knowledge_root(path: str) -> Path:
    """Normalize and validate an owner-configured knowledge root (M1.5C-S 6)."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError("knowledge root must be an existing directory")
    if not os.access(resolved, os.R_OK):
        raise ValueError("knowledge root is not readable")
    return resolved
