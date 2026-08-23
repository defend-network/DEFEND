from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def json_loads(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


class _LockedCursor:
    """Cursor proxy that serializes access to the shared connection."""

    def __init__(self, lock: threading.RLock, cursor: sqlite3.Cursor) -> None:
        self._lock = lock
        self._cursor = cursor

    def fetchone(self) -> Any:
        with self._lock:
            return self._cursor.fetchone()

    def fetchall(self) -> list[Any]:
        with self._lock:
            return self._cursor.fetchall()

    def fetchmany(self, size: int = 1) -> list[Any]:
        with self._lock:
            return self._cursor.fetchmany(size)

    def close(self) -> None:
        self._cursor.close()

    def __iter__(self) -> Iterator[Any]:
        def iterate() -> Iterator[Any]:
            with self._lock:
                for row in self._cursor:
                    yield row

        return iterate()

    def __next__(self) -> Any:
        with self._lock:
            return next(self._cursor)

    @property
    def description(self) -> Any:
        return self._cursor.description

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> int | None:
        return self._cursor.lastrowid

    @property
    def arraysize(self) -> int:
        return self._cursor.arraysize

    @arraysize.setter
    def arraysize(self, value: int) -> None:
        self._cursor.arraysize = value


class ThreadSafeConnection(sqlite3.Connection):
    """sqlite3.Connection whose statements are serialized with a lock.

    The SCS/FastAPI services run sync route handlers in a thread pool while
    sharing one connection; concurrent statement stepping on the same
    connection raises sqlite3.InterfaceError ("bad parameter or other API
    misuse"). Serializing execute/fetch/commit removes that race.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._op_lock = threading.RLock()

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> _LockedCursor:
        with self._op_lock:
            cursor = super().execute(sql, parameters)
        return _LockedCursor(self._op_lock, cursor)

    def executemany(self, sql: str, parameters: Sequence[Sequence[Any]]) -> _LockedCursor:
        with self._op_lock:
            cursor = super().executemany(sql, parameters)
        return _LockedCursor(self._op_lock, cursor)

    def executescript(self, sql_script: str) -> _LockedCursor:
        with self._op_lock:
            cursor = super().executescript(sql_script)
        return _LockedCursor(self._op_lock, cursor)

    def commit(self) -> None:
        with self._op_lock:
            super().commit()

    def rollback(self) -> None:
        with self._op_lock:
            super().rollback()


def connect_sqlite(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path),
        timeout=30.0,
        check_same_thread=False,
        factory=ThreadSafeConnection,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise