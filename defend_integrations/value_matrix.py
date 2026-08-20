"""Provider value matrix (P9) + provider classification (P10).

Evidence levels never upgrade from documentation alone:
DOCUMENTED -> MOCK_VERIFIED -> EMPIRICALLY_VERIFIED.
Classification is role-based; a provider may hold several roles (P10).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class EvidenceLevel(str, Enum):
    EMPIRICALLY_VERIFIED = "EMPIRICALLY_VERIFIED"
    DOCUMENTED_ONLY = "DOCUMENTED_ONLY"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    AUTH_FAILED = "AUTH_FAILED"
    PLAN_REQUIRED = "PLAN_REQUIRED"
    UNSUPPORTED_FOR_TT = "UNSUPPORTED_FOR_TT"
    UNKNOWN = "UNKNOWN"


class ProviderRole(str, Enum):
    UNUSABLE = "UNUSABLE"
    RESULTS_ONLY = "RESULTS_ONLY"
    LIVE_DATA = "LIVE_DATA"
    HISTORICAL_RESULTS = "HISTORICAL_RESULTS"
    HISTORICAL_ODDS_THIN = "HISTORICAL_ODDS_THIN"
    HISTORICAL_ODDS_RESEARCH_GRADE = "HISTORICAL_ODDS_RESEARCH_GRADE"
    MODEL_FEATURE_SOURCE = "MODEL_FEATURE_SOURCE"
    PROVIDER_PREDICTION_SOURCE = "PROVIDER_PREDICTION_SOURCE"


@dataclass(frozen=True)
class ProviderValueRow:
    """One row of the live evidence-driven matrix (P9 columns)."""

    provider: str
    auth: str
    tt_results: str = "unknown"
    tt_live: str = "unknown"
    tt_history: str = "unknown"
    tt_odds: str = "unknown"
    tt_historical_odds: str = "unknown"
    multi_snapshot: str = "unknown"
    bookmaker_depth: str = "unknown"
    player_ids: str = "unknown"
    rankings: str = "unknown"
    h2h: str = "unknown"
    stats: str = "unknown"
    provider_predictions: str = "unknown"
    earliest_history: str | None = None
    rate_limit: str = "unknown"
    cost: str = "unknown"
    matchability: str = "unknown"
    data_quality: str = "unknown"
    adapter_status: str = "not_implemented"
    evidence_level: EvidenceLevel = EvidenceLevel.DOCUMENTED_ONLY
    roles: tuple[ProviderRole, ...] = ()
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "PROVIDER": self.provider,
            "AUTH": self.auth,
            "TT_RESULTS": self.tt_results,
            "TT_LIVE": self.tt_live,
            "TT_HISTORY": self.tt_history,
            "TT_ODDS": self.tt_odds,
            "TT_HISTORICAL_ODDS": self.tt_historical_odds,
            "MULTI_SNAPSHOT": self.multi_snapshot,
            "BOOKMAKER_DEPTH": self.bookmaker_depth,
            "PLAYER_IDS": self.player_ids,
            "RANKINGS": self.rankings,
            "H2H": self.h2h,
            "STATS": self.stats,
            "PROVIDER_PREDICTIONS": self.provider_predictions,
            "EARLIEST_HISTORY": self.earliest_history,
            "RATE_LIMIT": self.rate_limit,
            "COST": self.cost,
            "MATCHABILITY": self.matchability,
            "DATA_QUALITY": self.data_quality,
            "ADAPTER_STATUS": self.adapter_status,
            "EVIDENCE_LEVEL": self.evidence_level.value,
            "ROLES": [role.value for role in self.roles],
            "NOTES": self.notes,
        }


def write_matrix(path: Path, rows: list[ProviderValueRow]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema": "DEFEND provider value matrix",
        "updated_at": (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "evidence_levels": ["EMPIRICALLY_VERIFIED", "DOCUMENTED_ONLY", "NOT_CONFIGURED",
                            "AUTH_FAILED", "PLAN_REQUIRED", "UNSUPPORTED_FOR_TT", "UNKNOWN"],
        "roles": [role.value for role in ProviderRole],
        "providers": [row.to_dict() for row in rows],
    }
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def roles_csv(row: ProviderValueRow) -> str:
    return ",".join(role.value for role in row.roles) or "-"