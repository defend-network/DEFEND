from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from defend_sports.domain import (
    CanonicalEvent,
    CanonicalMarket,
    CanonicalSelection,
    LiveObservation,
    OddsObservation,
    SourceRef,
)


def _utc(year: int = 2026, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _source() -> SourceRef:
    return SourceRef(provider="fixture", external_id="book-a")


def _odds(**overrides) -> OddsObservation:
    values = {
        "source": _source(),
        "event_external_id": "event-1",
        "market_key": "match_winner",
        "selection_key": "player-a",
        "decimal_odds": Decimal("1.95"),
        "observed_at": _utc(),
    }
    values.update(overrides)
    return OddsObservation(**values)


def _event(**overrides) -> CanonicalEvent:
    values = {
        "event_external_id": "event-1",
        "sport_key": "table_tennis",
        "league_key": "tt_wtt",
        "display_name": "Player A vs Player B",
        "scheduled_at": _utc(),
    }
    values.update(overrides)
    return CanonicalEvent(**values)


def _live(**overrides) -> LiveObservation:
    values = {
        "source": _source(),
        "event_external_id": "event-1",
        "state": {"score": {"sets": [1, 0]}},
        "observed_at": _utc(),
    }
    values.update(overrides)
    return LiveObservation(**values)


class TestSourceRef:
    def test_source_requires_nonblank_provider(self):
        with pytest.raises(ValueError, match="provider"):
            SourceRef(provider="", external_id="book-a")

    def test_source_requires_nonblank_external_id(self):
        with pytest.raises(ValueError, match="external_id"):
            SourceRef(provider="fixture", external_id="   ")


class TestOddsObservation:
    def test_decimal_odds_must_be_above_one(self):
        with pytest.raises(ValueError, match="decimal_odds"):
            _odds(decimal_odds=Decimal("1.00"))
        with pytest.raises(ValueError, match="decimal_odds"):
            _odds(decimal_odds=Decimal("0.5"))

    def test_decimal_odds_rejects_non_finite_values(self):
        with pytest.raises(ValueError, match="decimal_odds"):
            _odds(decimal_odds=Decimal("NaN"))
        with pytest.raises(ValueError, match="decimal_odds"):
            _odds(decimal_odds=Decimal("Infinity"))

    def test_decimal_odds_remains_decimal(self):
        assert isinstance(_odds(decimal_odds=Decimal("1.01")).decimal_odds, Decimal)

    def test_observed_at_must_be_timezone_aware(self):
        with pytest.raises(ValueError, match="observed_at"):
            _odds(observed_at=datetime(2026, 1, 1, 12, 0))

    def test_received_at_when_provided_must_be_timezone_aware(self):
        with pytest.raises(ValueError, match="received_at"):
            _odds(received_at=datetime(2026, 1, 1, 12, 0))
        assert _odds(received_at=_utc()).received_at == _utc()

    def test_identifiers_cannot_be_blank(self):
        with pytest.raises(ValueError, match="event_external_id"):
            _odds(event_external_id="")
        with pytest.raises(ValueError, match="market_key"):
            _odds(market_key=" ")
        with pytest.raises(ValueError, match="selection_key"):
            _odds(selection_key="")

    def test_raw_event_reference_is_optional_and_nonblank(self):
        assert _odds().raw_event_ref is None
        assert _odds(raw_event_ref="raw-1").raw_event_ref == "raw-1"
        with pytest.raises(ValueError, match="raw_event_ref"):
            _odds(raw_event_ref="  ")

    def test_models_are_immutable(self):
        observation = _odds()
        with pytest.raises(FrozenInstanceError):
            observation.decimal_odds = Decimal("2.10")

    def test_fields_are_provider_neutral_and_have_no_user_financial_state(self):
        names = {field.name for field in fields(OddsObservation)}
        assert names == {
            "source",
            "event_external_id",
            "market_key",
            "selection_key",
            "decimal_odds",
            "observed_at",
            "received_at",
            "raw_event_ref",
        }
        lower = " ".join(names).casefold()
        assert "user" not in lower
        assert "bankroll" not in lower
        assert "stake" not in lower


class TestCanonicalEvent:
    def test_identifiers_cannot_be_blank(self):
        with pytest.raises(ValueError, match="event_external_id"):
            _event(event_external_id="")
        with pytest.raises(ValueError, match="sport_key"):
            _event(sport_key="  ")
        with pytest.raises(ValueError, match="league_key"):
            _event(league_key="")

    def test_display_name_cannot_be_blank(self):
        with pytest.raises(ValueError, match="display_name"):
            _event(display_name="")

    def test_scheduled_at_must_be_timezone_aware(self):
        with pytest.raises(ValueError, match="scheduled_at"):
            _event(scheduled_at=datetime(2026, 1, 1, 12, 0))

    def test_raw_event_reference_is_optional_and_nonblank(self):
        assert _event().raw_event_ref is None
        assert _event(raw_event_ref="raw-1").raw_event_ref == "raw-1"
        with pytest.raises(ValueError, match="raw_event_ref"):
            _event(raw_event_ref="")

    def test_models_are_immutable(self):
        event = _event()
        with pytest.raises(FrozenInstanceError):
            event.display_name = "Renamed"

    def test_fields_are_provider_neutral(self):
        names = {field.name for field in fields(CanonicalEvent)}
        assert names == {
            "event_external_id",
            "sport_key",
            "league_key",
            "display_name",
            "scheduled_at",
            "raw_event_ref",
        }


class TestLiveObservation:
    def test_identifiers_cannot_be_blank(self):
        with pytest.raises(ValueError, match="event_external_id"):
            _live(event_external_id="")

    def test_state_is_required(self):
        with pytest.raises(ValueError, match="state"):
            _live(state=None)

    def test_observed_at_must_be_timezone_aware(self):
        with pytest.raises(ValueError, match="observed_at"):
            _live(observed_at=datetime(2026, 1, 1, 12, 0))

    def test_models_are_immutable(self):
        observation = _live()
        with pytest.raises(FrozenInstanceError):
            observation.state = {}

    def test_fields_are_provider_neutral_and_have_no_user_financial_state(self):
        names = {field.name for field in fields(LiveObservation)}
        assert names == {
            "source",
            "event_external_id",
            "state",
            "observed_at",
            "received_at",
            "raw_event_ref",
        }
        lower = " ".join(names).casefold()
        assert "user" not in lower
        assert "bankroll" not in lower


class TestCanonicalMarketAndSelection:
    def test_market_identifiers_cannot_be_blank(self):
        with pytest.raises(ValueError, match="event_external_id"):
            CanonicalMarket(event_external_id="", market_key="match_winner", display_name="Match Winner")
        with pytest.raises(ValueError, match="market_key"):
            CanonicalMarket(event_external_id="event-1", market_key=" ", display_name="Match Winner")

    def test_selection_identifiers_cannot_be_blank(self):
        with pytest.raises(ValueError, match="market_key"):
            CanonicalSelection(market_key="", selection_key="player-a", display_name="Player A")
        with pytest.raises(ValueError, match="selection_key"):
            CanonicalSelection(market_key="match_winner", selection_key="  ", display_name="Player A")

    def test_market_fields_are_provider_neutral(self):
        names = {field.name for field in fields(CanonicalMarket)}
        assert names == {"event_external_id", "market_key", "display_name"}

    def test_selection_fields_are_provider_neutral(self):
        names = {field.name for field in fields(CanonicalSelection)}
        assert names == {"market_key", "selection_key", "display_name"}


def test_no_domain_model_mentions_any_model_vendor_or_user_bankroll_state():
    for model in (SourceRef, CanonicalEvent, LiveObservation, CanonicalMarket, CanonicalSelection, OddsObservation):
        names = " ".join(field.name for field in fields(model)).casefold()
        assert "qwen" not in names
        assert "deepseek" not in names
        assert "huggingface" not in names
        assert "vllm" not in names
        assert "bankroll" not in names
        assert "user" not in names