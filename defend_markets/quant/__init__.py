"""Quant Director foundation for DEFENDmarkets.

Supervisory-intelligence boundary above the frozen M5 champion. Provides the
orchestrator, governed read tools, research journal, champion/challenger
registry, deterministic M5 explanation, AI budget enforcement, research lab,
intelligence monitoring, and an admin-only chat surface. It never writes model
weights, bypasses evaluation, promotes models, changes risk policy, places
wagers, or mutates settlements.
"""

from __future__ import annotations

from defend_markets.quant.config import (
    MARKETS_RUNTIME_STATE_DEFAULT,
    MarketsRuntimeState,
    QuantDirectorSettings,
)
from defend_markets.quant.explanation import explain_m5_prediction
from defend_markets.quant.health import QuantDirectorHealth, QuantDirectorHealthState
from defend_markets.quant.intelligence import QuantIntelligence, WeaknessFinding, collect_monitor_data
from defend_markets.quant.model_aliases import (
    DEEP_RESEARCH_ALIAS,
    RUNTIME_ALIAS,
    SOL_ALIAS,
    DirectorProfile,
    resolve_runtime_profile,
)
from defend_markets.quant.orchestrator import MarketsIntelligenceOrchestrator
from defend_markets.quant.reviews import DailyReview, WeeklyReview
from defend_markets.quant.store import InMemoryQuantStore, QuantStore
from defend_markets.quant.tools import GovernedMarketTools

__all__ = [
    "DEEP_RESEARCH_ALIAS",
    "DailyReview",
    "DirectorProfile",
    "GovernedMarketTools",
    "InMemoryQuantStore",
    "MARKETS_RUNTIME_STATE_DEFAULT",
    "MarketsIntelligenceOrchestrator",
    "MarketsRuntimeState",
    "QuantDirectorHealth",
    "QuantDirectorHealthState",
    "QuantDirectorSettings",
    "QuantIntelligence",
    "QuantStore",
    "RUNTIME_ALIAS",
    "SOL_ALIAS",
    "WeaknessFinding",
    "WeeklyReview",
    "collect_monitor_data",
    "explain_m5_prediction",
    "resolve_runtime_profile",
]
