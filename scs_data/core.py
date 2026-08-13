from __future__ import annotations

import os
from pathlib import Path
import sqlite3

from defend_data.sqlite_utils import connect_sqlite
from shared_platform.application import ApplicationContext

from .config import ScsPaths
from .migrations import ScsMigrator


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


class ScsDataCore:
    def __init__(self, context: ApplicationContext) -> None:
        self.context = context
        self.paths = ScsPaths.from_context(context).ensure()
        self.conn: sqlite3.Connection = connect_sqlite(self.paths.database)
        self.schema_version = ScsMigrator(self.conn).apply()
        self._closed = False

    def __enter__(self) -> "ScsDataCore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def health(self) -> dict[str, object]:
        try:
            app = self.conn.execute(
                "SELECT application_id FROM scs_application_metadata WHERE singleton=1"
            ).fetchone()[0]
            ok = app == "scs" and self.schema_version >= 1
        except (sqlite3.Error, TypeError):
            ok = False
        return {
            "ok": ok,
            "application_id": "scs",
            "schema_version": self.schema_version,
        }

    def backup_manifest(self, destination: Path) -> dict[str, object]:
        target = Path(destination).resolve(strict=False)
        root_key = _path_key(self.paths.root)
        target_key = _path_key(target)
        try:
            inside = os.path.commonpath((root_key, target_key)) == root_key
        except ValueError:
            inside = False
        if not inside:
            raise ValueError("SCS backup destination must remain inside the SCS data root")
        return {
            "application_id": "scs",
            "schema_version": self.schema_version,
            "database": "db/scs.sqlite3",
            "destination": target.relative_to(self.paths.root).as_posix(),
        }

    def close(self) -> None:
        if self._closed:
            return
        self.conn.close()
        self._closed = True
