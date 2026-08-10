from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import DataPaths

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class RawObject:
    sha256: str
    byte_size: int
    path: Path
    relative_path: str
    deduplicated: bool


class RawStore:
    """Content-addressed immutable blob storage."""

    def __init__(self, paths: DataPaths):
        self.paths = paths.ensure()

    @staticmethod
    def digest_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _path_for_hash(self, digest: str) -> Path:
        if not _SHA256_RE.fullmatch(digest):
            raise ValueError("Invalid SHA-256 digest")
        return self.paths.raw_blobs / digest[:2] / digest[2:4] / digest

    def put_bytes(self, data: bytes) -> RawObject:
        digest = self.digest_bytes(data)
        target = self._path_for_hash(digest)
        relative = target.relative_to(self.paths.root).as_posix()
        if target.exists():
            return RawObject(digest, len(data), target, relative, True)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(temp, "xb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink(missing_ok=True)
        return RawObject(digest, len(data), target, relative, False)

    def put_file(self, source: str | Path) -> RawObject:
        return self.put_bytes(Path(source).read_bytes())

    def get_bytes(self, digest: str) -> bytes:
        return self._path_for_hash(digest).read_bytes()

    def exists(self, digest: str) -> bool:
        return self._path_for_hash(digest).exists()
