"""Quant Director V1 foundation for DEFENDmarkets.

Supervisory-intelligence boundary above the frozen M5 champion. Provides the
orchestrator, governed read tools, research journal, champion/challenger
registry, deterministic M5 explanation, AI budget enforcement, and an
admin-only chat surface. It never writes model weights, bypasses evaluation,
places wagers, or mutates settlements.
"""

from __future__ import annotations

from defend_markets.quant.config import (
    MARKETS_RUNTIME_STATE_DEFAULT,
    MarketsRuntimeState,
    QuantDirectorSettings,
)
from defend_markets.quant.explanation import explain_m5_prediction
from defend_markets.quant.model_aliases import (
    RUNTIME_ALIAS,
    DirectorProfile,
    resolve_runtime_profile,
)
from defend_markets.quant.orchestrator import MarketsIntelligenceOrchestrator
from defend_markets.quant.store import InMemoryQuantStore, QuantStore
from defend_markets.quant.tools import GovernedMarketTools

__all__ = [
    "MARKETS_RUNTIME_STATE_DEFAULT",
    "DirectorProfile",
    "GovernedMarketTools",
    "InMemoryQuantStore",
    "MarketsIntelligenceOrchestrator",
    "MarketsRuntimeState",
    "QuantDirectorSettings",
    "QuantStore",
    "RUNTIME_ALIAS",
    "explain_m5_prediction",
    "resolve_runtime_profile",
]
