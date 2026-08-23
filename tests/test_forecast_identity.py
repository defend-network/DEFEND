from __future__ import annotations

from datetime import datetime, timezone

import pytest

from defend_markets.identity import (
    IDENTITY_AMBIGUOUS,
    IDENTITY_CONFIRMED,
    IDENTITY_NORMALIZED,
    IDENTITY_UNRESOLVED,
    IdentityService,
    normalize_participant_name,
)

from tests.fakes_markets import InMemoryForecastStore

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def make_service() -> tuple[IdentityService, InMemoryForecastStore]:
    store = InMemoryForecastStore()
    return IdentityService(store, clock=lambda: NOW), store


def test_normalize_is_deterministic_and_stable():
    a = normalize_participant_name("  André  LEBLANC  ")
    b = normalize_participant_name("andre leblanc")
    assert a == "andré leblanc"
    assert normalize_participant_name("A-É-Z!?") == "aéz"
    assert normalize_participant_name(" Player  One ") == "player one"


def test_normalize_preserves_diacritics():
    assert normalize_participant_name("Édouard") == "édouard"
    assert normalize_participant_name("EDOUARD") != "édouard"


def test_normalize_blank_returns_empty_but_resolve_rejects():
    assert normalize_participant_name("   ") == ""
    service, _ = make_service()
    with pytest.raises(ValueError):
        service.resolve("   ", provider="the_odds_api", raw_ref="evt-1")


def test_resolve_new_participant_is_normalized():
    service, store = make_service()
    row = service.resolve("Player A", provider="the_odds_api", raw_ref="evt-1")
    assert row["identity_state"] == IDENTITY_NORMALIZED
    assert row["participant_id"] is not None
    assert store.participant_by_normalized("player a")


def test_resolve_twice_keeps_same_participant_normalized_until_confirmed():
    service, _ = make_service()
    first = service.resolve("Player A", provider="the_odds_api", raw_ref="evt-1")
    second = service.resolve("Player A", provider="the_odds_api", raw_ref="evt-2")
    assert first["participant_id"] == second["participant_id"]
    assert second["identity_state"] == IDENTITY_NORMALIZED


def test_resolve_odds_and_results_names_share_identity():
    service, _ = make_service()
    odds_side = service.resolve("Alex Lebrun", provider="the_odds_api", raw_ref="evt-1")
    result_side = service.resolve("  alex lebrun ", provider="result_provider", raw_ref="res-1")
    assert odds_side["participant_id"] == result_side["participant_id"]


def test_resolve_does_not_fuzzy_merge_distinct_names():
    service, _ = make_service()
    odds_side = service.resolve("Alex Lebrun", provider="the_odds_api", raw_ref="evt-1")
    result_side = service.resolve("A. Lebrun", provider="result_provider", raw_ref="res-1")
    assert odds_side["participant_id"] != result_side["participant_id"]


def test_resolve_ambiguous_marks_all_candidates_and_blocks_prediction():
    service, store = make_service()
    store.insert_participant(
        canonical_name="Chris Jones",
        normalized_name="chris jones",
        state=IDENTITY_CONFIRMED,
        seen_at=NOW,
    )
    store.insert_participant(
        canonical_name="Chris Jones II",
        normalized_name="chris jones",
        state=IDENTITY_CONFIRMED,
        seen_at=NOW,
    )
    row = service.resolve("Chris Jones", provider="the_odds_api", raw_ref="evt-1")
    assert row["identity_state"] == IDENTITY_AMBIGUOUS
    assert not service.identity_allows_prediction(IDENTITY_AMBIGUOUS)
    assert store.participant_by_id(1)["identity_state"] == IDENTITY_AMBIGUOUS
    assert store.participant_by_id(2)["identity_state"] == IDENTITY_AMBIGUOUS


def test_confirm_explicitly():
    service, store = make_service()
    row = service.resolve("Player A", provider="the_odds_api", raw_ref="evt-1")
    confirmed = service.confirm(int(row["participant_id"]), provider="manual")
    assert confirmed["identity_state"] == IDENTITY_CONFIRMED
    assert service.identity_allows_prediction(IDENTITY_CONFIRMED)


def test_confirm_alias_merges_variant_names_to_one_participant():
    service, store = make_service()
    primary = service.resolve("Havel, Ladislav", provider="odds_api_io", raw_ref="899515")
    merged = service.confirm_alias(
        int(primary["participant_id"]),
        alias_name="Havel, Ladislav (1956)",
        provider="odds_api_io",
        raw_ref="899515",
    )
    assert merged["identity_state"] == IDENTITY_CONFIRMED
    variant = service.resolve("Havel, Ladislav (1956)", provider="odds_api_io", raw_ref="899515")
    assert variant["participant_id"] == primary["participant_id"]
    assert variant["identity_state"] == IDENTITY_CONFIRMED
    assert store.participant_by_normalized("havel ladislav 1956")


def test_confirm_alias_is_exact_and_never_fuzzy():
    service, _ = make_service()
    primary = service.resolve("Bayer, Ales", provider="odds_api_io", raw_ref="728577")
    service.confirm_alias(
        int(primary["participant_id"]),
        alias_name="Bayer, Alesh",
        provider="odds_api_io",
        raw_ref="728577",
    )
    unrelated = service.resolve("Bayer, Alex", provider="odds_api_io", raw_ref="evt-1")
    assert unrelated["participant_id"] != primary["participant_id"]
    assert unrelated["identity_state"] == IDENTITY_NORMALIZED


def test_confirm_alias_unknown_participant_raises():
    service, _ = make_service()
    with pytest.raises(KeyError):
        service.confirm_alias(9999, alias_name="Someone", provider="odds_api_io")


def test_confirm_alias_reversal_restores_fragmentation():
    service, store = make_service()
    primary = service.resolve("Havel, Ladislav", provider="odds_api_io", raw_ref="899515")
    service.confirm_alias(
        int(primary["participant_id"]),
        alias_name="Havel, Ladislav (1956)",
        provider="odds_api_io",
        raw_ref="899515",
    )
    store._aliases.pop((int(primary["participant_id"]), "havel ladislav 1956", "odds_api_io"))
    variant = service.resolve("Havel, Ladislav (1956)", provider="odds_api_io", raw_ref="899515")
    assert variant["participant_id"] != primary["participant_id"]


def test_identity_allows_prediction_gates():
    service, _ = make_service()
    assert service.identity_allows_prediction(IDENTITY_CONFIRMED)
    assert service.identity_allows_prediction(IDENTITY_NORMALIZED)
    assert not service.identity_allows_prediction(IDENTITY_AMBIGUOUS)
    assert not service.identity_allows_prediction(IDENTITY_UNRESOLVED)
    assert not service.identity_allows_prediction(None)
