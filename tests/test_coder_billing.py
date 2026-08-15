"""DEFENDcoder billing domain tests — TestBillingProvider only, no Stripe, no network."""

import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from defend_control import coder_billing as billing
from defend_control.coder_billing import (
    Account,
    BillingPolicy,
    BillingProvider,
    ComputeReservation,
    CreditBalance,
    CreditGrant,
    SpendingLimit,
    TestBillingProvider,
    UsageLedgerEntry,
)


def _now() -> datetime:
    return datetime(2026, 8, 14, tzinfo=timezone.utc)


class TestBillingDomain:
    def test_account_defaults_and_tiers(self):
        account = Account(account_id="acct-1", display_name="Alice")
        assert account.tier == "COMMUNITY"
        assert account.created_at.tzinfo is not None
        heavy = Account(
            account_id="acct-2", display_name="Bob", tier="MAXIMUM"
        )
        assert heavy.tier == "MAXIMUM"

    def test_credit_balance_cannot_be_negative(self):
        with pytest.raises(ValueError):
            CreditBalance(account_id="a", credits=Decimal("-0.01"))

    def test_credit_grant_must_be_positive(self):
        with pytest.raises(ValueError):
            CreditGrant(
                grant_id="g1",
                account_id="a",
                amount=Decimal("0.00"),
                reason="test",
                granted_at=_now(),
            )

    def test_usage_ledger_entry_cannot_credit_negative_amount(self):
        with pytest.raises(ValueError):
            UsageLedgerEntry(
                entry_id="e1",
                account_id="a",
                run_id="r1",
                model_alias="defendcoder-default",
                credits_debited=Decimal("-1.00"),
                provider="vast",
                instance_id=1,
                occurred_at=_now(),
            )

    def test_spending_limit_requires_non_negative_and_valid_source(self):
        assert SpendingLimit(account_id="a", limit_credits=Decimal("0")).limit_credits == 0
        with pytest.raises(ValueError):
            SpendingLimit(account_id="a", limit_credits=Decimal("-5"))
        with pytest.raises(ValueError):
            SpendingLimit(account_id="a", limit_credits=Decimal("10"), source="OTHER")

    def test_compute_reservation_statuses(self):
        reservation = ComputeReservation(
            reservation_id="res-1",
            account_id="a",
            alias="defendcoder-default",
            instance_id=555002,
            hourly_rate=Decimal("1.10"),
            reserved_at=_now(),
            expires_at=_now() + timedelta(hours=1),
        )
        assert reservation.status == "ACTIVE"
        released = ComputeReservation(
            reservation_id="res-2",
            account_id="a",
            alias="defendcoder-heavy",
            instance_id=555003,
            hourly_rate=Decimal("2.50"),
            reserved_at=_now(),
            expires_at=_now() + timedelta(hours=1),
            status="RELEASED",
        )
        assert released.status == "RELEASED"

    def test_billing_policy_defaults(self):
        policy = BillingPolicy()
        assert policy.free_monthly_credit_allowance == Decimal("5.00")
        assert policy.cost_multiplier == Decimal("1.00")
        assert policy.max_member_spend == Decimal("100.00")
        assert policy.heavy_availability is True
        assert policy.auto_escalation_eligible is True


class TestTestBillingProvider:
    def test_grant_balance_and_usage(self):
        provider = TestBillingProvider()
        provider.apply_grant(
            CreditGrant(
                grant_id="g1",
                account_id="acct-1",
                amount=Decimal("10.00"),
                reason="monthly",
                granted_at=_now(),
            )
        )
        assert provider.balance("acct-1") == Decimal("10.00")
        provider.apply_grant(
            CreditGrant(
                grant_id="g2",
                account_id="acct-1",
                amount=Decimal("5.00"),
                reason="bonus",
                granted_at=_now(),
            )
        )
        assert provider.balance("acct-1") == Decimal("15.00")

        entry = provider.record_usage(
            UsageLedgerEntry(
                entry_id="e1",
                account_id="acct-1",
                run_id="r1",
                model_alias="defendcoder-default",
                credits_debited=Decimal("2.50"),
                provider="vast",
                instance_id=555002,
                occurred_at=_now(),
            )
        )
        assert entry.entry_id == "e1"
        assert provider.balance("acct-1") == Decimal("12.50")
        assert len(provider.ledger("acct-1")) == 1

    def test_usage_cannot_overdraw_balance(self):
        provider = TestBillingProvider()
        provider.apply_grant(
            CreditGrant(
                grant_id="g1",
                account_id="acct-1",
                amount=Decimal("1.00"),
                reason="test",
                granted_at=_now(),
            )
        )
        with pytest.raises(ValueError, match="insufficient credits"):
            provider.record_usage(
                UsageLedgerEntry(
                    entry_id="e1",
                    account_id="acct-1",
                    run_id="r1",
                    model_alias="defendcoder-default",
                    credits_debited=Decimal("5.00"),
                    provider="vast",
                    instance_id=555002,
                    occurred_at=_now(),
                )
            )
        assert provider.balance("acct-1") == Decimal("1.00")

    def test_user_limit_cannot_exceed_platform_limit(self):
        provider = TestBillingProvider()
        provider.set_platform_limit(
            SpendingLimit(
                account_id="acct-1",
                limit_credits=Decimal("100.00"),
                source="PLATFORM",
                effective_at=_now(),
            )
        )
        assert provider.set_user_limit(
            SpendingLimit(
                account_id="acct-1",
                limit_credits=Decimal("80.00"),
                source="USER",
                effective_at=_now(),
            )
        ) == Decimal("80.00")
        with pytest.raises(ValueError, match="platform limit"):
            provider.set_user_limit(
                SpendingLimit(
                    account_id="acct-1",
                    limit_credits=Decimal("150.00"),
                    source="USER",
                    effective_at=_now(),
                )
            )

    def test_reserve_and_release_compute(self):
        provider = TestBillingProvider()
        reservation = provider.reserve(
            ComputeReservation(
                reservation_id="res-1",
                account_id="acct-1",
                alias="defendcoder-default",
                instance_id=555002,
                hourly_rate=Decimal("1.10"),
                reserved_at=_now(),
                expires_at=_now() + timedelta(hours=1),
            )
        )
        assert reservation.status == "ACTIVE"
        assert provider.active_reservations("acct-1") == ["res-1"]
        released = provider.release("res-1")
        assert released.status == "RELEASED"
        assert provider.active_reservations("acct-1") == []


class TestBillingProviderContract:
    def test_billing_provider_is_a_protocol(self):
        assert issubclass(BillingProvider, object)
        assert hasattr(BillingProvider, "__protocol_attrs__") or hasattr(
            BillingProvider, "_is_protocol"
        )

    def test_test_billing_provider_is_offline(self):
        source = inspect.getsource(TestBillingProvider).casefold()
        for banned in ("urllib", "requests", "http", "socket", "stripe"):
            assert banned not in source

    def test_module_has_no_stripe_import(self):
        source = inspect.getsource(billing).casefold()
        assert "import stripe" not in source

    def test_stripe_implementation_deferred(self):
        assert not hasattr(billing, "StripeBillingProvider")
        assert not hasattr(billing, "stripe")


def test_test_billing_provider_implements_protocol_members():
    provider = TestBillingProvider()
    for member in (
        "balance",
        "apply_grant",
        "record_usage",
        "reserve",
        "release",
        "set_platform_limit",
        "set_user_limit",
    ):
        assert callable(getattr(provider, member))