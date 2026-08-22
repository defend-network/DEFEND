"""Versioned feature registry and point-in-time feature extraction.

Every feature definition records an availability rule so challenger features
can only use information known strictly before a prediction cutoff. The M5
feature set is registered as ACTIVE; candidate features are registered by the
research layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from defend_markets.m5_live import FEATURE_NAMES as M5_FEATURE_NAMES
from defend_markets.m5_live import M5Match, M5StateBuilder

FEATURE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FeatureDefinition:
    feature_id: str
    version: int
    name: str
    description: str
    source_fields: tuple[str, ...]
    calculation: str
    available_at_rule: str
    null_behavior: str
    normalization: str
    domain: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "source_fields": list(self.source_fields),
            "calculation": self.calculation,
            "available_at_rule": self.available_at_rule,
            "null_behavior": self.null_behavior,
            "normalization": self.normalization,
            "domain": self.domain,
            "status": self.status,
        }


class FeatureRegistry:
    def __init__(self, definitions: Sequence[FeatureDefinition] = ()) -> None:
        self._by_id: dict[str, list[FeatureDefinition]] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: FeatureDefinition) -> None:
        versions = self._by_id.setdefault(definition.feature_id, [])
        if any(existing.version == definition.version for existing in versions):
            raise ValueError(f"duplicate feature version: {definition.feature_id} v{definition.version}")
        versions.append(definition)
        versions.sort(key=lambda item: item.version)

    def get(self, feature_id: str, version: int | None = None) -> FeatureDefinition | None:
        versions = self._by_id.get(feature_id, [])
        if not versions:
            return None
        if version is None:
            return versions[-1]
        for definition in versions:
            if definition.version == version:
                return definition
        return None

    def active(self) -> list[FeatureDefinition]:
        return [
            definition
            for definitions in self._by_id.values()
            for definition in definitions
            if definition.status == "ACTIVE"
        ]

    def versions(self, feature_id: str) -> list[FeatureDefinition]:
        return list(self._by_id.get(feature_id, []))


def m5_feature_registry() -> FeatureRegistry:
    definitions = [
        FeatureDefinition(
            feature_id=name,
            version=1,
            name=name,
            description=f"M5 frozen feature {name}",
            source_fields=("strictly-before state",),
            calculation="replayed state strictly before prediction timestamp",
            available_at_rule="prediction timestamp (state strictly before)",
            null_behavior="0.0 or 0.5 defaults per frozen contract",
            normalization="none",
            domain="real",
            status="ACTIVE",
        )
        for name in M5_FEATURE_NAMES
    ]
    return FeatureRegistry(definitions)


def challenger_feature_definitions() -> list[FeatureDefinition]:
    return [
        FeatureDefinition(
            feature_id="elo_diff_sq",
            version=1,
            name="elo_diff_sq",
            description="quadratic rating-difference term",
            source_fields=("elo_diff",),
            calculation="elo_diff ** 2",
            available_at_rule="prediction timestamp (derived from strictly-before elo_diff)",
            null_behavior="0.0 when elo_diff unavailable",
            normalization="none",
            domain="real",
            status="REJECTED",
        ),
        FeatureDefinition(
            feature_id="recent_form20_winrate_diff",
            version=1,
            name="recent_form20_winrate_diff",
            description="win rate over the last 20 matches, home minus away",
            source_fields=("strictly-before outcome history",),
            calculation="(wins_home_20 - wins_away_20) / 20",
            available_at_rule="prediction timestamp (strictly-before outcomes only)",
            null_behavior="0.0 when fewer than one outcome available",
            normalization="none",
            domain="real",
            status="CANDIDATE",
        ),
    ]


def extract_m5_features(builder: M5StateBuilder, home: str, away: str, ts: datetime) -> dict[str, float]:
    return builder.features(home, away, ts)


def apply_challenger_features(
    base_features: Mapping[str, float],
    feature_ids: Sequence[str],
) -> dict[str, float]:
    features = dict(base_features)
    if "elo_diff_sq" in feature_ids:
        elo_diff = float(features.get("elo_diff", 0.0))
        features["elo_diff_sq"] = elo_diff * elo_diff
    return features


def rows_to_feature_matrix(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_ids: Sequence[str],
) -> tuple[list[list[float]], list[float]]:
    builder = M5StateBuilder([])
    form20: dict[str, list[float]] = {}
    matrix: list[list[float]] = []
    targets: list[float] = []
    for row in sorted(rows, key=lambda item: (item["ts"], item["event_key"])):
        ts = datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
        home_key = str(row["home_key"])
        away_key = str(row["away_key"])
        base = builder.features(home_key, away_key, ts)
        features = apply_challenger_features(base, feature_ids)
        if "recent_form20_winrate_diff" in feature_ids:
            def _rate(key: str) -> float:
                history = form20.get(key, [])
                if not history:
                    return 0.0
                return (sum(history) / len(history)) * 2.0 - 1.0

            features["recent_form20_winrate_diff"] = _rate(home_key) - _rate(away_key)
        matrix.append([float(features[name]) for name in feature_ids])
        targets.append(float(row["actual"]))
        builder._update(
            M5Match(
                event_key=str(row["event_key"]),
                home_key=home_key,
                away_key=away_key,
                ts=ts,
                actual=float(row["actual"]),
            )
        )
        for key, actual in ((home_key, float(row["actual"])), (away_key, 1.0 - float(row["actual"]))):
            history = form20.setdefault(key, [])
            history.append(actual)
            if len(history) > 20:
                del history[0]
    return matrix, targets
