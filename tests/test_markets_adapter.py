from __future__ import annotations

from decimal import Decimal

from defend_markets.domain import ProvenanceStamp
from defend_markets.sports_adapter import normalize_quotes, sports_instrument_key

from tests.fakes_markets import FakeSportsReader, arb_pair


def test_sports_instrument_key_is_selection_scoped():
    assert (
        sports_instrument_key("tt-live-001", "match_winner", "player_a")
        == "sports:tt-live-001:match_winner:player_a"
    )


def test_sports_instrument_key_prefix_matches_market_level_key():
    from defend_markets.pipeline import market_instrument_key

    assert sports_instrument_key("a", "b", "c") == (
        market_instrument_key("a", "b") + ":c"
    )


def test_normalize_quotes_carries_pit_fields():
    quotes = arb_pair()
    normalized = normalize_quotes(quotes)
    assert len(normalized) == 2
    for item in normalized:
        stamp = item["provenance"]
        assert isinstance(stamp, ProvenanceStamp)
        assert stamp.observed_at is not None
        assert stamp.received_at is not None
        assert stamp.source_key in ("book-a", "book-b")


def test_normalize_quotes_includes_venue_costs_when_supplied():
    quotes = arb_pair(fees="0.002")
    normalized = normalize_quotes(quotes)
    costs = normalized[0]["costs"]
    assert costs.fees == Decimal("0.002")


def test_normalize_quotes_keeps_unknown_costs_none():
    quotes = arb_pair()
    normalized = normalize_quotes(quotes)
    assert normalized[0]["costs"] is None


def test_fake_reader_shapes_like_real_sports_db():
    reader = FakeSportsReader(quotes={("tt-live-001", "match_winner"): arb_pair()})
    venues = reader.venues()
    assert {"venue_key", "provider", "display_name", "is_active"} <= venues[0].keys()
    assert reader.tt_events()[0]["event_key"] == "tt-live-001"
    quotes = reader.latest_odds("tt-live-001", "match_winner")
    assert len(quotes) == 2
    for quote in quotes:
        assert quote.selection_id is not None
    assert reader.provider_health()["book-a"]["status"] == "HEALTHY"


def test_pit_availability_explicitly_lists_limitations():
    reader = FakeSportsReader()
    availability = reader.pit_availability()
    assert availability.has("observed_at")
    assert availability.has("received_at")
    assert not availability.has("normalization_version")