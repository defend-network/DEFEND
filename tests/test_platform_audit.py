"""Neutral platform audit log tests.

Verifies event vocabulary, redaction of known secrets, bounded persistence,
and that no secret value ever survives into an audit entry.
"""

from __future__ import annotations

import json

import pytest

from defend_control.platform_audit import (
    EVENT_CREDENTIAL_CONFIGURED,
    EVENT_CREDENTIAL_VERIFY_ATTEMPTED,
    EVENT_HEALTH_TRANSITION,
    EVENT_MANIFEST_COLLISION,
    EVENT_PLATFORM_SETTING_CHANGED,
    EVENT_PRODUCT_LAUNCHED,
    EVENT_PRODUCT_STOPPED,
    EVENT_TYPES,
    PlatformAuditEntry,
    PlatformAuditLog,
    default_audit_path,
)


def test_event_vocabulary_is_canonical():
    assert EVENT_TYPES == {
        EVENT_PRODUCT_LAUNCHED,
        EVENT_PRODUCT_STOPPED,
        EVENT_CREDENTIAL_CONFIGURED,
        EVENT_CREDENTIAL_VERIFY_ATTEMPTED,
        EVENT_MANIFEST_COLLISION,
        EVENT_HEALTH_TRANSITION,
        EVENT_PLATFORM_SETTING_CHANGED,
    }


def test_record_redacts_known_secrets(tmp_path):
    audit = PlatformAuditLog(
        tmp_path / "audit.json",
        known_secrets=("super-secret-value",),
        clock=lambda: "2026-08-23T00:00:00Z",
    )
    audit.record(
        EVENT_CREDENTIAL_CONFIGURED,
        detail="saved key super-secret-value ok",
    )
    entry = audit.snapshot()[-1]
    assert "super-secret-value" not in entry.detail
    assert "[REDACTED]" in entry.detail


def test_record_rejects_unknown_events(tmp_path):
    audit = PlatformAuditLog(tmp_path / "audit.json")
    with pytest.raises(ValueError, match="unknown platform audit event"):
        audit.record("not_an_event")


def test_audit_entries_are_bounded(tmp_path):
    audit = PlatformAuditLog(tmp_path / "audit.json", max_entries=5)
    for index in range(20):
        audit.record(EVENT_HEALTH_TRANSITION, detail=f"transition {index}")
    entries = audit.snapshot()
    assert len(entries) == 5
    assert entries[-1].detail == "transition 19"


def test_audit_persists_and_restores(tmp_path):
    path = tmp_path / "audit.json"
    audit = PlatformAuditLog(path, clock=lambda: "2026-08-23T00:00:00Z")
    audit.record(EVENT_PRODUCT_LAUNCHED, product_id="coder", detail="launched")
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["entries"][0]["event_type"] == EVENT_PRODUCT_LAUNCHED
    reloaded = PlatformAuditLog(path)
    assert reloaded.snapshot()[-1].product_id == "coder"
    assert reloaded.snapshot()[-1].detail == "launched"


def test_audit_never_records_secrets_even_in_restore(tmp_path):
    path = tmp_path / "audit.json"
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "event_type": EVENT_CREDENTIAL_CONFIGURED,
                        "occurred_at": "2026-08-23T00:00:00Z",
                        "product_id": None,
                        "detail": "stale super-secret-value",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    audit = PlatformAuditLog(path, known_secrets=("super-secret-value",))
    entry = audit.snapshot()[-1]
    assert "super-secret-value" not in entry.detail


def test_default_audit_path_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_audit_path() == tmp_path / "DEFEND" / "platform-audit.json"


def test_entry_to_dict_is_safe():
    entry = PlatformAuditEntry(
        event_type=EVENT_HEALTH_TRANSITION,
        occurred_at="2026-08-23T00:00:00Z",
        product_id="scs",
        detail="STOPPED -> RUNNING",
    )
    assert entry.to_dict()["event_type"] == EVENT_HEALTH_TRANSITION
