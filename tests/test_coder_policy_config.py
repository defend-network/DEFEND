"""DEFENDcoder hourly-ceiling policy: CODER_MAX_HOURLY_USD config,
$4.50 default, offer selection, approval gating, $5 session budget.

No network, no billing, no Tk: recording backends + real plane/service.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from defend_control.coder_control_plane import (
    CoderControlPlane,
    CoderPolicy,
)
from defend_control.coder_m0 import (
    CODER_MAX_HOURLY_UPPER_USD,
    parse_max_hourly_budget,
)
from defend_control.products import (
    ProductsSettings,
    coder_plan_rows,
)
from defend_control.types import VastOffer

from test_coder_control_plane import RecordingBackend
from test_coder_launch_bridge import _service

_OFFER_425 = VastOffer(
    701,
    "H100 SXM 80GB",
    81920,
    Decimal("4.25"),
    Decimal("0.99"),
)
_OFFER_450 = VastOffer(
    702,
    "H100 SXM 80GB",
    81920,
    Decimal("4.50"),
    Decimal("0.99"),
)
_OFFER_451 = VastOffer(
    703,
    "H100 SXM 80GB",
    81920,
    Decimal("4.51"),
    Decimal("0.99"),
)


class TestCeilingDefault:
    def test_default_policy_ceiling_is_4_50(self):
        assert CoderPolicy().max_hourly_usd == Decimal("4.50")

    def test_default_plan_carries_configured_max_4_50(self):
        backend = RecordingBackend(offers=(_OFFER_425,))
        service, plane, _ = _service(backend)
        service.start()
        prepared = service.pending_plan()
        assert prepared.plan.max_hourly_price_usd == Decimal("4.50")
        assert prepared.plan.provider_hourly_rate == Decimal("4.25")

    def test_425_offer_qualifies_and_provisions(self):
        backend = RecordingBackend(offers=(_OFFER_425,))
        service, plane, supervisor = _service(backend)

        status = service.start()
        assert status.state == "approval_required"
        status = service.approve()

        assert status.state == "running"
        assert backend.starts == [
            ("defendcoder-heavy", 8003, Decimal("5.00"))
        ]

    def test_450_exact_boundary_qualifies(self):
        backend = RecordingBackend(offers=(_OFFER_450,))
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.approve()

        assert status.state == "running"
        assert backend.starts == [
            ("defendcoder-heavy", 8003, Decimal("5.00"))
        ]

    def test_451_offer_fails_closed_with_zero_spend(self):
        backend = RecordingBackend(offers=(_OFFER_451,))
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.approve()

        assert status.state == "failed"
        assert backend.starts == []
        assert "spend-ready" in (status.status_text or "")
        assert status.error_category == "no_qualifying_offer"


class TestConfigParsing:
    def test_env_425_is_accepted(self, monkeypatch):
        monkeypatch.setenv("CODER_MAX_HOURLY_USD", "4.25")
        settings = ProductsSettings.from_env()
        assert settings.coder_max_hourly_usd == Decimal("4.25")
        assert settings.coder_config_errors == ()

    def test_env_450_boundary_is_accepted(self, monkeypatch):
        monkeypatch.setenv("CODER_MAX_HOURLY_USD", "4.50")
        settings = ProductsSettings.from_env()
        assert settings.coder_max_hourly_usd == Decimal("4.50")

    def test_env_malformed_falls_back_to_safe_default_with_explicit_error(
        self, monkeypatch
    ):
        monkeypatch.setenv("CODER_MAX_HOURLY_USD", "not-a-number")
        settings = ProductsSettings.from_env()
        assert settings.coder_max_hourly_usd == Decimal("4.50")
        assert len(settings.coder_config_errors) == 1
        assert "CODER_MAX_HOURLY_USD" in settings.coder_config_errors[0]
        assert "safe default" in settings.coder_config_errors[0]

    def test_env_non_positive_falls_back_to_safe_default(self, monkeypatch):
        for raw in ("0", "-1"):
            monkeypatch.setenv("CODER_MAX_HOURLY_USD", raw)
            settings = ProductsSettings.from_env()
            assert settings.coder_max_hourly_usd == Decimal("4.50")
            assert len(settings.coder_config_errors) == 1

    def test_env_above_upper_bound_falls_back_to_safe_default(
        self, monkeypatch
    ):
        monkeypatch.setenv("CODER_MAX_HOURLY_USD", "999999")
        settings = ProductsSettings.from_env()
        assert settings.coder_max_hourly_usd == Decimal("4.50")
        assert len(settings.coder_config_errors) == 1
        assert "must not exceed" in settings.coder_config_errors[0]

    def test_malformed_config_never_removes_billing_protection(
        self, monkeypatch
    ):
        monkeypatch.setenv("CODER_MAX_HOURLY_USD", "garbage")
        settings = ProductsSettings.from_env()
        assert settings.coder_max_hourly_usd == Decimal("4.50")

        policy = CoderPolicy(
            max_hourly_usd=settings.coder_max_hourly_usd,
        )
        backend = RecordingBackend(offers=(_OFFER_451,))
        plane = CoderControlPlane(
            backend=backend,  # type: ignore[arg-type]
            policy=policy,
            token_provider=lambda: "hf_fake_token",
            port_available=lambda port: True,
        )
        prepared = plane.prepared_provision("defendcoder-heavy")
        with pytest.raises(ValueError, match="exceeds"):
            plane.approve(prepared)
        assert backend.starts == []

    def test_parse_max_hourly_budget_is_strict(self):
        with pytest.raises(ValueError):
            parse_max_hourly_budget(True)
        with pytest.raises(ValueError):
            parse_max_hourly_budget("NaN")
        with pytest.raises(ValueError):
            parse_max_hourly_budget("0")
        with pytest.raises(ValueError):
            parse_max_hourly_budget(
                str(CODER_MAX_HOURLY_UPPER_USD + Decimal("0.01"))
            )
        assert parse_max_hourly_budget("4.50") == Decimal("4.50")


class TestOfferSelection:
    def test_cheapest_qualifying_offer_is_chosen(self):
        offers = (
            VastOffer(601, "H100 SXM 80GB", 81920, Decimal("3.61"), Decimal("0.989")),
            VastOffer(602, "H200 SXM 141GB", 144384, Decimal("3.77"), Decimal("0.990")),
            VastOffer(603, "H100 SXM 80GB", 81920, Decimal("3.61"), Decimal("0.985")),
        )
        backend = RecordingBackend(offers=offers)
        service, plane, _ = _service(backend)

        service.start()
        prepared = service.pending_plan()

        assert prepared.offer.offer_id == 601
        assert prepared.plan.provider_hourly_rate == Decimal("3.61")

    def test_tie_break_prefers_higher_reliability_then_lower_offer_id(self):
        offers = (
            VastOffer(710, "H100 SXM 80GB", 81920, Decimal("3.61"), Decimal("0.985")),
            VastOffer(711, "H100 SXM 80GB", 81920, Decimal("3.61"), Decimal("0.990")),
            VastOffer(712, "H100 SXM 80GB", 81920, Decimal("3.61"), Decimal("0.990")),
        )
        backend = RecordingBackend(offers=offers)
        service, plane, _ = _service(backend)

        service.start()
        prepared = service.pending_plan()

        assert prepared.offer.offer_id == 711

    def test_expensive_h200_b200_cannot_outrank_cheaper_qualifying_h100(self):
        offers = (
            VastOffer(801, "H200", 141000, Decimal("4.00"), Decimal("0.995")),
            VastOffer(802, "B200", 192000, Decimal("3.90"), Decimal("0.996")),
            VastOffer(
                803,
                "H100 SXM",
                81559,
                Decimal("3.5756"),
                Decimal("0.9891"),
            ),
        )
        backend = RecordingBackend(offers=offers)
        service, plane, _ = _service(backend)

        service.start()
        prepared = service.pending_plan()

        assert prepared.offer.offer_id == 803
        assert prepared.plan.provider_hourly_rate == Decimal("3.5756")


class TestDialogAndBudget:
    def test_approval_dialog_rows_show_exact_rate_and_configured_max(self):
        backend = RecordingBackend(offers=(_OFFER_425,))
        service, plane, _ = _service(backend)

        service.start()
        rows = dict(coder_plan_rows(service.pending_plan()))

        assert rows["Exact $/hr"] == "$4.25"
        assert rows["Configured max $/hr"] == "$4.50"
        assert rows["Offer ID"] == "701"

    def test_session_budget_stays_independent_of_hourly_ceiling(self):
        backend = RecordingBackend(offers=(_OFFER_425,))
        service, plane, _ = _service(backend)

        service.start()
        prepared = service.pending_plan()

        assert prepared.plan.session_budget_usd == Decimal("5.00")
        assert prepared.plan.max_hourly_price_usd == Decimal("4.50")
        assert prepared.plan.session_budget_usd != prepared.plan.max_hourly_price_usd

        rows = dict(coder_plan_rows(prepared))
        assert rows["Session budget"] == "$5.00"
        assert rows["Configured max $/hr"] == "$4.50"

        status = service.status()
        details = dict(status.details)
        assert details["Max $/hr (ceiling)"] == "$4.50"