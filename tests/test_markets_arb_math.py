"""Arb core: N-way math, exact equalization, and known test vectors."""

from __future__ import annotations

from decimal import Decimal

import pytest

from defend_markets.arb.math import (
    NWayMathCore,
    compute_inverse_sum,
    is_pure_arb,
    solve_equalized_plan,
)


class TestTwoWayMath:
    def test_two_way_arb_vector(self):
        # Book A 2.10 / Book B 2.10 -> Q ~= 0.95238095, margin ~ 4.7619%
        result = compute_inverse_sum((Decimal("2.10"), Decimal("2.10")))
        assert result.inverse_sum == Decimal("0.9523809524")
        assert result.is_arb
        assert result.margin == Decimal("0.0476190476")

    def test_two_way_arb_stake_equalization(self):
        plan = solve_equalized_plan(Decimal("100"), (Decimal("2.10"), Decimal("2.10")))
        leg_a, leg_b = plan.legs
        assert leg_a.stake == leg_b.stake  # symmetric
        # Each leg ~= 50
        assert leg_a.stake.quantize(Decimal("0.01")) == Decimal("50.00")
        assert plan.equalized_return.quantize(Decimal("0.01")) == Decimal("105.00")
        assert plan.gross_profit.quantize(Decimal("0.01")) == Decimal("5.00")
        assert plan.is_arb

    def test_roi_is_five_percent_on_total_stake(self):
        plan = solve_equalized_plan(Decimal("100"), (Decimal("2.10"), Decimal("2.10")))
        # 105 - 100 = 5 -> 5.00% ROI
        assert (plan.gross_roi * 100).quantize(Decimal("0.0001")) == Decimal("5.0000")

    def test_two_way_no_arb(self):
        result = compute_inverse_sum((Decimal("1.90"), Decimal("1.90")))
        assert not result.is_arb
        assert result.inverse_sum > Decimal("1")


class TestThreeWayMath:
    def test_three_way_arb(self):
        # 3.0 / 3.0 / 3.0 -> Q = 1.0 (break even), need Q < 1 for arb
        result = compute_inverse_sum((Decimal("3.0"), Decimal("3.0"), Decimal("3.0")))
        assert not result.is_arb
        assert result.inverse_sum == Decimal("1.0000000000")

    def test_three_way_arb_true(self):
        result = compute_inverse_sum((Decimal("3.5"), Decimal("3.5"), Decimal("3.5")))
        assert result.is_arb
        assert result.inverse_sum < Decimal("1")

    def test_three_way_plan(self):
        plan = solve_equalized_plan(Decimal("300"), (Decimal("3.5"), Decimal("3.5"), Decimal("3.5")))
        assert len(plan.legs) == 3
        assert plan.is_arb
        # Each stake ~100, return ~350
        for leg in plan.legs:
            assert leg.stake.quantize(Decimal("0.01")) == Decimal("100.00")
            assert leg.return_.quantize(Decimal("0.01")) == Decimal("350.00")
        assert plan.equalized_return.quantize(Decimal("0.01")) == Decimal("350.00")
        assert plan.gross_profit.quantize(Decimal("0.01")) == Decimal("50.00")


class TestNWayCore:
    def test_n_way_inverse_sum(self):
        odds = (Decimal("2.10"), Decimal("2.10"), Decimal("3.0"))
        expected = Decimal("0.9523809524") + Decimal("0.3333333333")
        assert NWayMathCore.inverse_sum(odds) == expected.quantize(Decimal("0.0000000001"))

    def test_n_way_arb_detection(self):
        assert NWayMathCore.is_arb((Decimal("3.5"), Decimal("3.5"), Decimal("3.5")))
        assert NWayMathCore.is_arb((Decimal("5.0"), Decimal("5.0"), Decimal("5.0"), Decimal("5.0")))
        assert not NWayMathCore.is_arb((Decimal("2.10"), Decimal("2.10"), Decimal("3.0")))

    def test_n_way_margin(self):
        margin = NWayMathCore.margin((Decimal("2.10"), Decimal("2.10")))
        assert margin == Decimal("0.0476190476")

    def test_n_way_plan(self):
        plan = NWayMathCore.equalized_plan(Decimal("100"), (Decimal("3.5"), Decimal("3.5"), Decimal("3.5")))
        assert len(plan.legs) == 3
        assert plan.is_arb

    def test_general_n_way_arb_formula(self):
        # Verify stake_i = S * (1/O_i) / Q for arbitrary 4 outcomes, using the
        # full-precision inverse sum Q as in the solver.
        odds = (Decimal("4.0"), Decimal("5.0"), Decimal("6.0"), Decimal("7.0"))
        plan = solve_equalized_plan(Decimal("1000"), odds)
        q_full = sum((Decimal("1") / dec for dec in odds), Decimal("0"))
        for leg in plan.legs:
            expected_stake = Decimal("1000") * (Decimal("1") / leg.odds) / q_full
            assert leg.stake == expected_stake


class TestExactEqualization:
    def test_returns_equal_per_outcome(self):
        plan = solve_equalized_plan(Decimal("200"), (Decimal("2.20"), Decimal("2.40")))
        r1 = plan.legs[0].return_
        r2 = plan.legs[1].return_
        # Equalized return should be identical up to Decimal precision
        assert r1.quantize(Decimal("0.0001")) == r2.quantize(Decimal("0.0001"))

    def test_inverse_sum_less_than_one_means_arb(self):
        assert is_pure_arb((Decimal("2.10"), Decimal("2.10")))
        assert not is_pure_arb((Decimal("1.90"), Decimal("1.90")))

    def test_zero_total_stake(self):
        plan = solve_equalized_plan(Decimal("0"), (Decimal("2.10"), Decimal("2.10")))
        assert plan.total_stake == Decimal("0")
        assert plan.gross_roi == Decimal("0")

    def test_invalid_odds_rejected(self):
        with pytest.raises(ValueError):
            solve_equalized_plan(Decimal("100"), (Decimal("0.5"), Decimal("2.0")))
