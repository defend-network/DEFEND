"""Phase D forward TT market collection + live shadow engine (P0-P5).

SHADOW ONLY. No wagering. M5 is frozen (defend_markets.m5_live).

Pipeline per cycle:
  P0  discovery   -> forward events from empirically useful providers
  P1  odds poll   -> timestamped bookmaker odds on an adaptive schedule
  P2  gate        -> observed_at vs verified commence -> observation classes
  P3  M5 live     -> frozen-M5 probability strictly before result
  P4  ruler rows  -> raw implied / overround / no-vig / disagreement
  P5  settlement  -> join verified result, incremental evaluation

Raw provider evidence is never overwritten: raw_evidence_ref always points at
the stored raw payload. Restart idempotency comes from unique natural keys in
the persistence layer (see defend_markets/migrations/0006_forward_market.sql).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Protocol

from defend_markets.m5_live import (
    FEATURE_NAMES,
    FrozenM5,
    M5Match,
    M5StateBuilder,
)

_NOW = datetime.now(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# P1 adaptive schedule (seconds-to-commence bands)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ScheduleBand:
    min_seconds: float
    label: str
    delay_seconds: float


_SCHEDULE: tuple[ScheduleBand, ...] = (
    ScheduleBand(24 * 3600.0, "LOW", 1800.0),        # >= 24h
    ScheduleBand(12 * 3600.0, "MODERATE", 600.0),    # 24h - 12h
    ScheduleBand(6 * 3600.0, "INCREASED", 300.0),    # 12h - 6h
    ScheduleBand(2 * 3600.0, "FREQUENT", 120.0),     # 6h - 2h
    ScheduleBand(30 * 60.0, "HIGH", 45.0),           # 2h - 30m
    ScheduleBand(5 * 60.0, "HIGHEST", 20.0),         # 30m - 5m
    ScheduleBand(-1.0, "COMMENCE", 10.0),            # < 5m (commence pending)
)


def poll_delay_for(seconds_to_commence: float, *, now: datetime | None = None) -> float:
    """Adaptive delay before the next odds poll for one event."""
    for band in _SCHEDULE:
        if seconds_to_commence >= band.min_seconds:
            return band.delay_seconds
    return 10.0


def schedule_label_for(seconds_to_commence: float) -> str:
    for band in _SCHEDULE:
        if seconds_to_commence >= band.min_seconds:
            return band.label
    return "COMMENCE"


# --------------------------------------------------------------------------- #
# P2 contamination gate + immutable reference classes
# --------------------------------------------------------------------------- #
OPEN = "OPEN"
INTERMEDIATE = "INTERMEDIATE"
LAST_VALID_PREMATCH = "LAST_VALID_PREMATCH"
POST_COMMENCE = "POST_COMMENCE"


def classify_observation(
    observed_at: datetime,
    commence_at: datetime,
    *,
    is_first_prematch: bool,
) -> str:
    """P2 contamination gate: observed_at >= verified commence => POST_COMMENCE
    (never used in prematch evaluation). OPEN = first prematch observation;
    everything else prematch is INTERMEDIATE. LAST_VALID_PREMATCH is assigned
    once, at commence crossing / settlement, to the latest prematch observation.
    """
    if observed_at >= commence_at:
        return POST_COMMENCE
    if is_first_prematch:
        return OPEN
    return INTERMEDIATE


def last_valid_prematch(observations: list[dict[str, Any]]) -> dict[str, Any] | None:
    prematch = [o for o in observations if o["observation_class"] != POST_COMMENCE]
    if not prematch:
        return None
    return max(prematch, key=lambda o: o["observed_at"])


# --------------------------------------------------------------------------- #
# P1 odds parsing (tolerant of verified OddsPapi shapes)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RawPrice:
    bookmaker: str
    market: str
    provider_market_id: str
    side: str
    participant_key: str
    price: float
    changed_at: datetime | None


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def parse_oddspapi_odds(
    payload: Any,
    *,
    provider_event_id: str,
    ingested_at: datetime,
) -> list[RawPrice]:
    """Normalize /v4/odds and /v4/historical-odds bookmaker payloads.

    Verified shape: {fixtureId, bookmakers: {name: {markets: {mid: {outcomes:
    {oid: {players: {key: <snapshots list | current state>}}}}}}}}. Both the
    historical list-of-snapshots form (each with createdAt) and the live
    current-state form (with changedAt or price-only) are accepted.
    """
    if not isinstance(payload, dict):
        return []
    raw: list[RawPrice] = []
    bookmakers = payload.get("bookmakers")
    if not isinstance(bookmakers, dict):
        return raw
    for bookmaker, bm_body in bookmakers.items():
        markets = bm_body.get("markets") if isinstance(bm_body, dict) else None
        if not isinstance(markets, dict):
            continue
        for market_id, market in markets.items():
            outcomes = market.get("outcomes") if isinstance(market, dict) else None
            if not isinstance(outcomes, dict):
                continue
            for outcome_id, outcome in outcomes.items():
                players = outcome.get("players") if isinstance(outcome, dict) else None
                if not isinstance(players, dict):
                    continue
                for player_key, body in players.items():
                    if isinstance(body, list):  # historical: snapshots
                        for snapshot in body:
                            if not isinstance(snapshot, dict):
                                continue
                            ts = snapshot.get("createdAt")
                            price = _num(snapshot.get("price"))
                            if price is None:
                                continue
                            raw.append(
                                RawPrice(
                                    bookmaker=str(bookmaker),
                                    market="match_winner",
                                    provider_market_id=str(market_id),
                                    side="A" if False else str(player_key),
                                    participant_key=str(player_key),
                                    price=price,
                                    changed_at=_parse_dt(ts) if isinstance(ts, str) else None,
                                )
                            )
                    elif isinstance(body, dict):  # live: current state
                        price = _num(body.get("price"))
                        if price is None:
                            continue
                        ts = body.get("changedAt")
                        raw.append(
                            RawPrice(
                                bookmaker=str(bookmaker),
                                market="match_winner",
                                provider_market_id=str(market_id),
                                side=str(player_key),
                                participant_key=str(player_key),
                                price=price,
                                changed_at=_parse_dt(ts) if isinstance(ts, str) else None,
                            )
                        )
    return raw


def _parse_dt(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# P4 market ruler math (per observation pair)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RulerRow:
    observation_id: int
    canonical_event_id: str
    observation_class: str
    observed_at: datetime
    side_a_price: float
    side_b_price: float
    raw_implied_p_a: float
    raw_implied_p_b: float
    overround: float
    no_vig_p_a: float
    no_vig_p_b: float
    m5_p_a: float
    model_market_disagreement: float
    observation_age_seconds: float
    seconds_to_commence: float


def _to_bool(value: Any) -> bool:
    return bool(value)


def build_ruler_row(
    *,
    observation_id: int,
    canonical_event_id: str,
    observation_class: str,
    price_a: float,
    price_b: float,
    m5_p_a: float,
    observed_at: datetime,
    commence_at: datetime,
    now: datetime | None = None,
) -> RulerRow:
    """One ruler row: raw implied, overround, no-vig, M5, disagreement.

    Disagreement is MODEL_MARKET_DISAGREEMENT (m5_p_a - no_vig_p_a), never
    labeled EDGE. Prices below 1.01 are treated as invalid (no-vig/overround
    undefined) and returned as None-equivalents via nan guard flags.
    """
    now = now or _now()
    pa = 1.0 / price_a if price_a >= 1.01 else float("nan")
    pb = 1.0 / price_b if price_b >= 1.01 else float("nan")
    overround = pa + pb if not (math.isnan(pa) or math.isnan(pb)) else float("nan")
    if not math.isnan(overround):
        no_vig_a = pa / overround
        no_vig_b = pb / overround
    else:
        no_vig_a = no_vig_b = float("nan")
    disagreement = m5_p_a - no_vig_a
    return RulerRow(
        observation_id=observation_id,
        canonical_event_id=canonical_event_id,
        observation_class=observation_class,
        observed_at=observed_at,
        side_a_price=price_a,
        side_b_price=price_b,
        raw_implied_p_a=_float_or_none(pa),
        raw_implied_p_b=_float_or_none(pb),
        overround=_float_or_none(overround),
        no_vig_p_a=_float_or_none(no_vig_a),
        no_vig_p_b=_float_or_none(no_vig_b),
        m5_p_a=round(float(m5_p_a), 6),
        model_market_disagreement=_float_or_none(disagreement),
        observation_age_seconds=(now - observed_at).total_seconds(),
        seconds_to_commence=(commence_at - observed_at).total_seconds(),
    )


def _float_or_none(value: float) -> float | None:
    return None if math.isnan(value) else round(float(value), 6)


# --------------------------------------------------------------------------- #
# P5 settlement + incremental evaluation
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SettlementReference:
    reference_class: str
    no_vig_p_a: float | None


def _class_row(
    ruler_rows: list[dict[str, Any]],
    class_name: str,
    *,
    prefer: str = "latest",
) -> dict[str, Any] | None:
    rows = [r for r in ruler_rows if r["observation_class"] == class_name]
    if not rows:
        return None
    if prefer == "earliest":
        return min(rows, key=lambda r: r["observed_at"])
    return max(rows, key=lambda r: r["observed_at"])


def select_reference_rows(
    ruler_rows: list[dict[str, Any]],
) -> list[SettlementReference]:
    """OPEN (earliest prematch pair), LAST_VALID_PREMATCH (latest prematch),
    and the single INTERMEDIATE pair closest to -3h before commence (or the
    last remaining prematch pair if none is near)."""
    refs: list[SettlementReference] = []
    prematch_rows = [
        r for r in ruler_rows if r["observation_class"] != POST_COMMENCE
    ]
    open_row = _class_row(ruler_rows, OPEN, prefer="earliest")
    if open_row is None and prematch_rows:
        open_row = min(prematch_rows, key=lambda r: r["observed_at"])
    if open_row is not None:
        refs.append(
            SettlementReference(OPEN, _val(open_row, "no_vig_p_a"))
        )
    last_row = _class_row(ruler_rows, LAST_VALID_PREMATCH, prefer="latest")
    if last_row is None and prematch_rows:
        last_row = max(prematch_rows, key=lambda r: r["observed_at"])
    if last_row is not None:
        refs.append(
            SettlementReference(LAST_VALID_PREMATCH, _val(last_row, "no_vig_p_a"))
        )
    interm = [
        r for r in ruler_rows
        if r["observation_class"] == INTERMEDIATE
        and r.get("observation_id") != (last_row or {}).get("observation_id")
    ]
    if interm:
        if len(interm) == 1:
            chosen = interm[0]
        else:
            chosen = min(
                interm,
                key=lambda r: abs(
                    _val(r, "seconds_to_commence", 0.0) - (-3 * 3600.0)
                ),
            )
        refs.append(
            SettlementReference(INTERMEDIATE, _val(chosen, "no_vig_p_a"))
        )
    return refs


def _val(row: dict[str, Any], key: str, default: Any = None) -> Any:
    value = row.get(key)
    return default if value is None else value


def brier(p: float, actual: float) -> float:
    return (p - actual) ** 2


def log_loss(p: float, actual: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -(actual * math.log(p) + (1 - actual) * math.log(1 - p))


@dataclass(frozen=True)
class EvaluationRow:
    canonical_event_id: str
    result_id: int
    settled_at: datetime
    reference_class: str
    m5_p_a: float
    market_no_vig_p_a: float | None
    actual: float


def build_evaluation_rows(
    *,
    canonical_event_id: str,
    result_id: int,
    settled_at: datetime,
    ruler_rows: list[dict[str, Any]],
    m5_p_a: float,
    actual: float,
) -> list[EvaluationRow]:
    refs = select_reference_rows(ruler_rows)
    rows: list[EvaluationRow] = []
    for ref in refs:
        market_p = ref.no_vig_p_a
        rows.append(
            EvaluationRow(
                canonical_event_id=canonical_event_id,
                result_id=result_id,
                settled_at=settled_at,
                reference_class=ref.reference_class,
                m5_p_a=round(float(m5_p_a), 6),
                market_no_vig_p_a=round(float(market_p), 6) if market_p is not None else None,
                actual=float(actual),
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# P5 evaluation thresholds
# --------------------------------------------------------------------------- #
REPORT_THRESHOLDS = (30, 100, 250, 500, 1000)


def evaluation_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate evaluation rows (all reference classes pooled, plus per-class).
    MARKET_EDGE_STATUS stays INSUFFICIENT_SAMPLE until N >= 100."""
    report: dict[str, Any] = {
        "n": len(rows),
        "thresholds": {str(t): None for t in REPORT_THRESHOLDS},
        "market_edge_status": (
            "INSUFFICIENT_SAMPLE" if len(rows) < 100 else "PAIRWISE_MEASURED"
        ),
    }
    for t in REPORT_THRESHOLDS:
        if len(rows) >= t:
            report["thresholds"][str(t)] = _aggregate(rows[:t])
    report["pooled"] = _aggregate(rows)
    per_class: dict[str, Any] = {}
    for class_name in (OPEN, INTERMEDIATE, LAST_VALID_PREMATCH):
        subset = [r for r in rows if r["reference_class"] == class_name]
        per_class[class_name] = _aggregate(subset)
    report["per_class"] = per_class
    return report


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    m5_brier = sum(brier(r["m5_p_a"], r["actual"]) for r in rows) / n
    m5_ll = sum(log_loss(r["m5_p_a"], r["actual"]) for r in rows) / n
    with_market = [r for r in rows if r["market_no_vig_p_a"] is not None]
    n_market = len(with_market)
    market_brier = (
        sum(brier(r["market_no_vig_p_a"], r["actual"]) for r in with_market) / n_market
        if n_market
        else None
    )
    market_ll = (
        sum(log_loss(r["market_no_vig_p_a"], r["actual"]) for r in with_market) / n_market
        if n_market
        else None
    )
    delta = (
        round(sum(
            brier(r["m5_p_a"], r["actual"]) - brier(r["market_no_vig_p_a"], r["actual"])
            for r in with_market
        ) / n_market, 6)
        if n_market
        else None
    )
    return {
        "n": n,
        "m5_brier": round(m5_brier, 6),
        "m5_log_loss": round(m5_ll, 6),
        "market_brier": round(market_brier, 6) if market_brier is not None else None,
        "market_log_loss": round(market_ll, 6) if market_ll is not None else None,
        "m5_minus_market_brier": delta,
        "market_rows": n_market,
    }


# --------------------------------------------------------------------------- #
# Forward discovery (P0) canonicalization wrapper
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ForwardFixture:
    provider: str
    provider_event_id: str
    competition: str
    player_a: str
    player_b: str
    scheduled_commence: datetime
    raw: dict[str, Any] = field(default_factory=dict)


def parse_recovered_json(body: str) -> tuple[Any, bool]:
    """Parse a possibly truncated JSON body, recovering complete prefix objects.

    Providers that cap response bodies mid-array (OddsPapi and Odds-API.io
    both hard-cap at 16384 bytes) still return a valid JSON prefix, so we cut
    at the last complete top-level element boundary and close the array.
    Returns ``(payload, recovered)`` where ``recovered`` is True when the body
    was truncated and only the complete prefix was parsed.
    """
    if not body:
        return None, False
    import json

    try:
        return json.loads(body), False
    except Exception:
        pass
    ends: list[int] = []
    depth = 0
    in_str = False
    esc = False
    for index, ch in enumerate(body):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 1 and ch == "}":
                ends.append(index)
    for index in reversed(ends):
        try:
            return json.loads(body[: index + 1] + "]"), True
        except Exception:
            continue
    return None, True


def forward_fixtures_from_oddspapi(
    payload: Any, *, ingested_at: datetime | None = None, provider: str = "oddspapi"
) -> list[ForwardFixture]:
    """Map /v4/fixtures payload to ForwardFixture (sportId 25 = table tennis)."""
    fixtures: list[ForwardFixture] = []
    if not isinstance(payload, list):
        return fixtures
    for fx in payload:
        if not isinstance(fx, dict) or fx.get("sportId") != 25:
            continue
        commence = _parse_dt(fx.get("startTime", "")) or _parse_dt(fx.get("trueStartTime", ""))
        if commence is None:
            continue
        fixtures.append(
            ForwardFixture(
                provider=provider,
                provider_event_id=str(fx.get("fixtureId", "")),
                competition=str(fx.get("tournamentName") or fx.get("tournamentSlug") or ""),
                player_a=str(fx.get("participant1Name") or ""),
                player_b=str(fx.get("participant2Name") or ""),
                scheduled_commence=commence,
                raw=fx,
            )
        )
    return fixtures