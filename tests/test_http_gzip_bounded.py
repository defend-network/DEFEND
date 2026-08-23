"""M4.8.1 gzip HTTP hardening tests (P3)."""

from __future__ import annotations

import gzip
import io

from defend_integrations.http import _decompress_gzip_bounded


def _gz(data: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as f:
        f.write(data)
    return buf.getvalue()


def test_small_gzip_passes():
    payload = b'{"success":true,"data":[]}'
    out, ok = _decompress_gzip_bounded(_gz(payload), max_output_bytes=1024)
    assert ok is True
    assert out == payload


def test_multi_chunk_gzip_passes():
    payload = (b'{"data":[' + b",".join(b'{"n":%d}' % i for i in range(10000)) + b']}')
    out, ok = _decompress_gzip_bounded(_gz(payload), max_output_bytes=len(payload) + 10)
    assert ok is True
    assert out == payload


def test_gzip_exactly_at_cap_passes():
    payload = b"x" * 1000
    out, ok = _decompress_gzip_bounded(_gz(payload), max_output_bytes=1000)
    assert ok is True
    assert out == payload


def test_gzip_over_cap_fails_closed():
    payload = b"x" * 2000
    out, ok = _decompress_gzip_bounded(_gz(payload), max_output_bytes=1000)
    assert ok is False
    assert out is None


def test_malformed_gzip_fails_closed():
    out, ok = _decompress_gzip_bounded(b"\x1f\x8bnot-really-gzip", max_output_bytes=1000)
    assert ok is False
    assert out is None


def test_non_gzip_unchanged():
    payload = b'{"ok":true}'
    out, ok = _decompress_gzip_bounded(payload, max_output_bytes=1000)
    assert ok is True
    assert out == payload
