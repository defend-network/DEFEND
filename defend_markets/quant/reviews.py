"""Autonomous review jobs: daily lightweight and weekly deep research reviews.

Reviews are deterministic and budget-gated. A weekly review produces a
MARKET_RESEARCH_REPORT artifact. The Quant Director only proposes research; it
never promotes models, changes risk policy, or places bets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from defend_markets.quant.intelligence import QuantIntelligence, collect_monitor_data


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ReviewOutcome:
    kind: str
    started_at: str
    completed_at: str
    report: dict[str, Any]
    ran: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "report": self.report,
            "ran": self.ran,
            "reason": self.reason,
        }


class DailyReview:
    def run(self, *, tools: Any, intelligence: QuantIntelligence, data: dict[str, Any]) -> ReviewOutcome:
        started = utc_now_iso()
        monitor = intelligence.monitor(data)
        weaknesses = intelligence.find_weaknesses(data)
        report = {
            "kind": "daily",
            "model_health": monitor,
            "anomalies": [finding.to_dict() for finding in weaknesses],
            "started_at": started,
        }
        return ReviewOutcome(
            kind="daily",
            started_at=started,
            completed_at=utc_now_iso(),
            report=report,
            ran=True,
            reason="scheduled daily lightweight review",
        )


class WeeklyReview:
    def __init__(self, artifact_dir: Path | None = None) -> None:
        self._artifact_dir = artifact_dir

    def run(self, *, tools: Any, intelligence: QuantIntelligence, data: dict[str, Any]) -> ReviewOutcome:
        started = utc_now_iso()
        report = intelligence.research_report(data)
        report["kind"] = "weekly"
        report["started_at"] = started
        if self._artifact_dir is not None:
            import json

            artifact = self._artifact_dir / "TT_MARKET_RESEARCH_REPORT.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        return ReviewOutcome(
            kind="weekly",
            started_at=started,
            completed_at=utc_now_iso(),
            report=report,
            ran=True,
            reason="scheduled weekly deep research review",
        )
