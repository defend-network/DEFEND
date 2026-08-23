"""M4.8.2 adaptive capture cadence tests (P13/P13A)."""

from __future__ import annotations

from defend_markets.quant.cadence import (
    MODE_BACKOFF,
    MODE_IDLE,
    MODE_IN_PLAY,
    MODE_UPCOMING,
    adaptive_cadence,
)


def test_in_play_fastest():
    c = adaptive_cadence(in_play_count=3, upcoming_count=10, has_slate=True)
    assert c["mode"] == MODE_IN_PLAY
    assert c["interval_seconds"] == 60


def test_upcoming_moderate():
    c = adaptive_cadence(in_play_count=0, upcoming_count=5, has_slate=True)
    assert c["mode"] == MODE_UPCOMING


def test_no_slate_idle():
    c = adaptive_cadence(in_play_count=0, upcoming_count=0, has_slate=False)
    assert c["mode"] == MODE_IDLE


def test_backoff_wins_over_in_play():
    c = adaptive_cadence(in_play_count=5, upcoming_count=0, has_slate=True, error_state="rate_limited")
    assert c["mode"] == MODE_BACKOFF


def test_backoff_slowest():
    backoff = adaptive_cadence(in_play_count=0, upcoming_count=0, has_slate=True, error_state="unavailable")
    in_play = adaptive_cadence(in_play_count=1, upcoming_count=0, has_slate=True)
    idle = adaptive_cadence(in_play_count=0, upcoming_count=0, has_slate=False)
    assert backoff["interval_seconds"] > in_play["interval_seconds"]
    assert idle["interval_seconds"] > in_play["interval_seconds"]
    assert backoff["interval_seconds"] >= idle["interval_seconds"]
