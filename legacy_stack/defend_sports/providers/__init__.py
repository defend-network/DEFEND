# ==============================================================
# LEGACY / NON-CANONICAL
# ==============================================================
# STATUS: LEGACY_ACTIVE_TRANSITIONAL
# CANONICAL_OWNER: DEFENDMarkets
# CANONICAL_REPLACEMENT: defend_markets
# REMOVAL_CONDITION: Markets stops its read-only legacy-sports data relationship
# DO NOT ADD NEW FEATURES HERE.
# ==============================================================
"""DEFEND Sports provider adapters.

DS1 ships the deterministic fixture provider and a live The Odds API
provider for table-tennis events, h2h odds and scores.
"""

from legacy_stack.defend_sports.providers.base import ProviderBatch, RawProviderEvent, SportsProvider
from legacy_stack.defend_sports.providers.fixture import FixtureSportsProvider
from legacy_stack.defend_sports.providers.the_odds_api import (
    OddsApiProviderError,
    TheOddsApiSportsProvider,
)

__all__ = [
    "ProviderBatch",
    "RawProviderEvent",
    "SportsProvider",
    "FixtureSportsProvider",
    "TheOddsApiSportsProvider",
    "OddsApiProviderError",
]