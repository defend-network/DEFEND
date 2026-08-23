"""Tests for the TT research suite helpers (offline, deterministic).

Includes the metric-integrity regression tests required by the owner
audit: constant-0.5 Brier == 0.25 exactly, log-loss == ln(2), label
domain firewall (no actual outside {0,1}), row-order invariance,
pairwise event-set equality, calibration artifact equality, blocked
bootstrap determinism.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

_TOOL = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "defend_tt_research_suite.py"
)


def _load():
    loader = importlib.machinery.SourceFileLoader("tt_research_suite", str(_TOOL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def suite():
    return _load()


def _rows(ps, ys):
    return [{"p": float(p), "actual": float(y)} for p, y in zip(ps, ys)]


def test_sigmoid_boundaries_and_monotonic(suite):
    assert suite._sigmoid(0) == 0.5
    assert suite._sigmoid(-1000) < 1e-9
    assert suite._sigmoid(1000) > 1 - 1e-9
    assert suite._sigmoid(1) > suite._sigmoid(-1)


def test_aggregate_brier_log_loss_accuracy(suite):
    rows = _rows([0.8, 0.8, 0.5], [1.0, 0.0, 1.0])
    agg = suite._aggregate(rows)
    assert agg["n"] == 3
    assert abs(agg["brier"] - (0.04 + 0.64 + 0.25) / 3) < 1e-9
    expected_ll = (
        -math.log(0.8) - math.log(0.2) - math.log(0.5)
    ) / 3
    assert abs(agg["log_loss"] - expected_ll) < 1e-6
    assert abs(agg["accuracy"] - 1 / 3) < 1e-6  # p=0.5 tie is never counted


def test_aggregate_empty(suite):
    assert suite._aggregate([]) == {"n": 0}


def test_fit_ridge_recovers_separable_signal(suite):
    rng = np.random.default_rng(7)
    x = rng.normal(size=(400, 2))
    y = (x[:, 0] > 0).astype(float)
    w = suite._fit_ridge(x, y, lam=0.1)
    preds = 1.0 / (1.0 + np.exp(-(w[0] + x @ w[1:])))
    assert (((preds > 0.5) == (x[:, 0] > 0)).mean()) >= 0.99  # near-perfect recovery
    assert abs(w[2]) < 1.0  # noise feature stays small


def test_calibration_bucket_edges(suite):
    bounds = [b for _, b in suite._BUCKETS]
    assert bounds == [0.55, 0.60, 0.65, 0.70, 0.80, 1.01]
    for p, expected in ((0.50, "0.50-0.55"), (0.5499, "0.50-0.55"),
                        (0.55, "0.55-0.60"), (0.60, "0.60-0.65"),
                        (0.65, "0.65-0.70"), (0.70, "0.70-0.80"),
                        (0.7999, "0.70-0.80"), (0.80, "0.80+")):
        bucket = None
        for label, upper in suite._BUCKETS:
            if p < upper:
                bucket = label
                break
        assert bucket == expected, p


def test_bucket_for_includes_below_half(suite):
    assert suite._bucket_for(0.30) == "<0.50"
    assert suite._bucket_for(0.4999) == "<0.50"
    assert suite._bucket_for(0.50) == "0.50-0.55"
    assert suite._bucket_for(0.9999) == "0.80+"


def test_glicko_probability_symmetry(suite):
    glicko = suite.Glicko()
    p_ab = glicko.probability("a", "b")
    p_ba = glicko.probability("b", "a")
    assert abs(p_ab + p_ba - 1.0) < 1e-9


def test_recency_elo_uses_only_recent_results(suite):
    recency = suite.RecencyElo(3)
    base = recency.rating("p")
    assert base == suite._INITIAL_RATING
    recency.record("p", __import__("datetime").datetime(2026, 1, 1), "x", 1.0)
    assert recency.rating("p") != base
    assert len(recency.history["p"]) == 1


# ---------------------------------------------------------- TEST A-F
def test_A_constant_half_brier_exactly_0_25(suite):
    rng = np.random.default_rng(99)
    ys = rng.integers(0, 2, size=100).astype(float)
    rows = _rows([0.5] * 100, ys)
    agg = suite._aggregate(rows)
    assert agg["brier"] == 0.25  # exact within float representation
    assert abs(agg["brier"] - 0.25) < 1e-12
    assert agg["accuracy"] == "NOT_APPLICABLE"


def test_B_all_y1_p1_brier_zero(suite):
    rows = _rows([1.0] * 10, [1.0] * 10)
    assert suite._aggregate(rows)["brier"] == 0.0


def test_C_all_y0_p0_brier_zero(suite):
    rows = _rows([0.0] * 10, [0.0] * 10)
    assert suite._aggregate(rows)["brier"] == 0.0


def test_D_all_y1_p0_brier_one(suite):
    rows = _rows([0.0] * 10, [1.0] * 10)
    assert suite._aggregate(rows)["brier"] == 1.0


def test_E_hand_calculated_vector(suite):
    ps = [0.8, 0.6, 0.5, 0.9, 0.2]
    ys = [1.0, 0.0, 1.0, 1.0, 0.0]
    expected = sum((p - y) ** 2 for p, y in zip(ps, ys)) / 5
    assert abs(suite._aggregate(_rows(ps, ys))["brier_exact"] - expected) < 1e-12
    expected_ll = sum(
        -math.log(p) if y > 0.5 else -math.log(1 - p)
        for p, y in zip(ps, ys)
    ) / 5
    assert abs(suite._aggregate(_rows(ps, ys))["log_loss_exact"] - expected_ll) < 1e-12


def test_F_row_order_invariance(suite):
    rows = _rows([0.9, 0.1, 0.7, 0.3, 0.55, 0.45], [1, 0, 1, 0, 1, 0])
    a = suite._aggregate(rows)
    b = suite._aggregate(list(reversed(rows)))
    assert a == b


# ---------------------------------------------------------- log-loss sanity
def test_constant_half_log_loss_is_ln2(suite):
    rng = np.random.default_rng(7)
    ys = rng.integers(0, 2, size=100).astype(float)
    agg = suite._aggregate(_rows([0.5] * 100, ys))
    assert abs(agg["log_loss_exact"] - math.log(2.0)) < 1e-15


def test_log_loss_clipping_preserves_ordinary_values(suite):
    assert abs(suite._log_loss(0.5, 1.0) - math.log(2.0)) < 1e-15
    assert abs(suite._log_loss(0.3, 0.0) + math.log(0.7)) < 1e-15
    assert suite._log_loss(1e-12, 1.0) < 1e6  # clipped, finite
    assert suite._log_loss(1.0 - 1e-12, 0.0) < 1e6


# ---------------------------------------------------------- label domain
def test_label_domain_rejects_0_5(suite):
    rows = _rows([0.5, 0.5], [1.0, 0.5])
    with pytest.raises(ValueError):
        suite._aggregate(rows)


def test_label_domain_rejects_out_of_range(suite):
    with pytest.raises(ValueError):
        suite._aggregate(_rows([0.5], [2.0]))
    with pytest.raises(ValueError):
        suite._aggregate(_rows([0.5], [-1.0]))


# ---------------------------------------------------------- pairwise integrity
def _pred_map(keys, ps, ys):
    return {
        k: {"event_key": k, "p": float(p), "actual": float(y)}
        for k, p, y in zip(keys, ps, ys)
    }


def test_paired_delta_same_sets(suite):
    keys = ["e1", "e2", "e3"]
    a = _pred_map(keys, [0.5, 0.5, 0.5], [1, 0, 1])
    b = _pred_map(keys, [0.6, 0.4, 0.7], [1, 0, 1])
    d = suite._paired_delta_rows(a, b, "brier")
    assert abs(sum(d) - sum((0.5 - y) ** 2 - (q - y) ** 2 for q, y in zip([0.6, 0.4, 0.7], [1, 0, 1]))) < 1e-12
    _, _, n, only_a, only_b = suite._common_rows(a, b)
    assert n == 3 and not only_a and not only_b


def test_paired_delta_rejects_mismatched_sets(suite):
    a = _pred_map(["e1", "e2"], [0.5, 0.5], [1, 0])
    b = _pred_map(["e1"], [0.6], [1])
    with pytest.raises(ValueError):
        suite._paired_delta_rows(a, b, "brier")


# ---------------------------------------------------------- bootstrap
def test_blocked_bootstrap_deterministic(suite):
    rng = np.random.default_rng(3)
    deltas = rng.normal(loc=-0.001, scale=0.05, size=400).tolist()
    block_ids = [f"d{i % 40}" for i in range(400)]
    a = suite._blocked_bootstrap_ci(deltas, block_ids, n_iter=500, seed=20260818)
    b = suite._blocked_bootstrap_ci(deltas, block_ids, n_iter=500, seed=20260818)
    assert a == b
    assert a["95ci_low"] <= a["mean_delta"] <= a["95ci_high"]


def test_blocked_bootstrap_seed_sensitivity(suite):
    rng = np.random.default_rng(3)
    deltas = rng.normal(loc=-0.001, scale=0.05, size=400).tolist()
    block_ids = [f"d{i % 40}" for i in range(400)]
    a = suite._blocked_bootstrap_ci(deltas, block_ids, n_iter=500, seed=1)
    b = suite._blocked_bootstrap_ci(deltas, block_ids, n_iter=500, seed=2)
    assert a["95ci_low"] != b["95ci_low"] or a["95ci_high"] != b["95ci_high"]


# ---------------------------------------------------------- calibration
def test_calibration_insufficient_sample_flag(suite):
    preds = {}
    for i in range(10):
        preds[f"e{i}"] = {"p": 0.52, "actual": 1.0}
    for i in range(10):
        preds[f"f{i}"] = {"p": 0.52, "actual": 0.0}
    rows, wace, extreme = suite._calibration_table(preds)
    bucket = rows[0]
    assert bucket["bucket"] == "0.50-0.55"
    assert bucket["status"] == "INSUFFICIENT_SAMPLE"
    assert wace is None  # no populated bucket reaches min_n


def test_calibration_weighted_ace_over_populated(suite):
    preds = {}
    for i in range(40):
        preds[f"e{i}"] = {"p": 0.52, "actual": 1.0}
    for i in range(40):
        preds[f"f{i}"] = {"p": 0.52, "actual": 0.0}
    rows, wace, _ = suite._calibration_table(preds)
    assert rows[0]["status"] == "OK"
    assert wace == pytest.approx(0.02, abs=1e-4)


def test_calibration_uses_exact_prediction_map(suite):
    preds = {"e1": {"p": 0.9, "actual": 1.0}, "e2": {"p": 0.9, "actual": 0.0}}
    rows, _, extreme = suite._calibration_table(preds)
    assert any(r["bucket"] == "0.80+" for r in rows)
    assert extreme["0.80+"]["n"] == 2
    assert extreme["0.80+"]["status"] == "INSUFFICIENT_SAMPLE"


# ---------------------------------------------------------- manifests
def test_manifest_hash_deterministic(suite):
    m1 = {"windows": [{"window_id": "W00", "eval_event_ids_sha256": "abc"}]}
    m2 = {"windows": [{"window_id": "W00", "eval_event_ids_sha256": "abc"}]}
    assert suite._sha256_hex(m1) == suite._sha256_hex(m2)


def test_event_set_hash_order_sensitive_deterministic(suite):
    h1 = suite._event_set_hash(["a", "b", "c"])
    h2 = suite._event_set_hash(["a", "b", "c"])
    h3 = suite._event_set_hash(["a", "c", "b"])
    assert h1 == h2
    assert h1 != h3
