from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DataPaths:
    root: Path
    raw: Path
    raw_blobs: Path
    db: Path
    lancedb: Path
    datasets: Path
    research_cache: Path
    backups: Path
    exports: Path
    tmp: Path
    logs: Path

    @classmethod
    def from_env(cls, root: str | Path | None = None) -> "DataPaths":
        if root is None:
            configured = os.getenv("DEFEND_DATA_ROOT", "").strip()
            if configured:
                root_path = Path(configured)
            elif os.name == "nt":
                root_path = Path(r"C:\DEFEND_DATA")
            else:
                root_path = Path("./DEFEND_DATA").resolve()
        else:
            root_path = Path(root)
        root_path = root_path.expanduser().resolve()
        return cls(
            root=root_path,
            raw=root_path / "raw",
            raw_blobs=root_path / "raw" / "blobs",
            db=root_path / "db",
            lancedb=root_path / "lancedb",
            datasets=root_path / "datasets",
            research_cache=root_path / "research_cache",
            backups=root_path / "backups",
            exports=root_path / "exports",
            tmp=root_path / "tmp",
            logs=root_path / "logs",
        )

    def ensure(self) -> "DataPaths":
        for p in (
            self.root, self.raw, self.raw_blobs, self.db, self.lancedb,
            self.datasets, self.research_cache, self.backups, self.exports,
            self.tmp, self.logs,
        ):
            p.mkdir(parents=True, exist_ok=True)
        return self
