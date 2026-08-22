"""Instrument profiles + owner inventory (M1.4, P31-P33, P26).

Once an instrument is registered, the Copilot prefers "using your registered
micromanometer + matrix probe" over generic "use an airflow meter". Manuals
may be indexed; button sequences are never invented
(INSTRUMENT_MANUAL_MISSING when absent).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class InstrumentRegistry:
    def __init__(self, store_path: Path) -> None:
        self._path = Path(store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._profiles = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._profiles, indent=2), encoding="utf-8")

    def register(self, *, manufacturer: str, model: str,
                 capabilities: str, range_: str | None = None,
                 resolution: str | None = None,
                 accuracy: str | None = None,
                 setup: str | None = None,
                 manual_source_id: str | None = None,
                 serial: str | None = None) -> dict[str, Any]:
        profile = {
            "manufacturer": manufacturer, "model": model,
            "serial": serial, "capabilities": capabilities,
            "range": range_, "resolution": resolution, "accuracy": accuracy,
            "setup": setup, "manual_source_id": manual_source_id,
            "calibration_state": None,
        }
        self._profiles[f"{manufacturer} {model}".upper()] = profile
        self._save()
        return profile

    def lookup(self, *, model: str | None = None, capability: str | None = None) -> list[dict[str, Any]]:
        matches = []
        for profile in self._profiles.values():
            if model and model.lower() in profile.get("model", "").lower():
                matches.append(profile)
            elif capability and capability.lower() in profile.get("capabilities", "").lower():
                matches.append(profile)
        return matches

    def all(self) -> list[dict[str, Any]]:
        return list(self._profiles.values())
