from __future__ import annotations

from pathlib import Path

from .artifact_catalog import ArtifactCatalog
from .config import DataPaths
from .context_builder import ContextBuilder
from .conversation_store import ConversationStore
from .identity_store import IdentityStore
from .memory_manager import MemoryManager
from .memory_store import MemoryStore
from .raw_store import RawStore
from .visitor_store import VisitorStore


class DataCore:
    """Composition root for the persistent data subsystem."""

    def __init__(self, root: str | Path | None = None):
        self.paths = DataPaths.from_env(root).ensure()
        self.raw = RawStore(self.paths)
        self.catalog = ArtifactCatalog(self.paths, self.raw)
        self.conversations = ConversationStore(self.paths)
        self.visitors = VisitorStore(self.paths)
        self.identity = IdentityStore(self.paths)
        self.memory_store = MemoryStore(self.paths)
        self.memory = MemoryManager(self.memory_store)
        self.context = ContextBuilder(self.conversations, self.memory)

    def stats(self) -> dict:
        return {
            "data_root": str(self.paths.root),
            "catalog": self.catalog.stats(),
            "conversations": self.conversations.stats(),
            "visitors": self.visitors.overview(),
            "identity": self.identity.stats(),
            "memory": self.memory_store.stats(),
        }

    def health(self) -> dict:
        dbs = {
            "catalog": self.catalog.db_path,
            "conversations": self.conversations.db_path,
            "memory": self.memory_store.db_path,
            "visitors": self.visitors.db_path,
            "identity": self.identity.db_path,
        }
        return {
            "ok": all(path.exists() for path in dbs.values()),
            "data_root": str(self.paths.root),
            "paths": {
                "raw": str(self.paths.raw),
                "db": str(self.paths.db),
                "lancedb": str(self.paths.lancedb),
                "datasets": str(self.paths.datasets),
                "research_cache": str(self.paths.research_cache),
            },
            "databases": {
                name: {
                    "path": str(path),
                    "exists": path.exists(),
                    "bytes": path.stat().st_size if path.exists() else 0,
                }
                for name, path in dbs.items()
            },
            "stats": self.stats(),
        }

    def close(self) -> None:
        self.catalog.close()
        self.conversations.close()
        self.visitors.close()
        self.identity.close()
        self.memory_store.close()
