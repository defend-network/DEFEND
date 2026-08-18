"""DEFEND Sports provider adapters.

DS1 ships the deterministic fixture provider and a live The Odds API
provider for table-tennis events, h2h odds and scores.
"""

from defend_sports.providers.base import ProviderBatch, RawProviderEvent, SportsProvider
from defend_sports.providers.fixture import FixtureSportsProvider
from defend_sports.providers.the_odds_api import (
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