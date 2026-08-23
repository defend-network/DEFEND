"""M4.7 canonical odds feed and sports arb scanner (P24-P32).

The arb core consumes immutable :class:`ArbQuote` objects. The
:class:`CanonicalOddsFeed` is the provider-neutral adapter that maps live
canonical market observations (tt_market_observations) onto ArbQuote using the
existing M4.6 market-truth orientation and freshness systems. Odds-API.io is
one provider adapter; the arb engine never depends on a provider HTTP payload.

The :class:`SportsArbScanner` is scheduler-owned: it reads current compatible
quotes from >=2 books, chooses the best compatible price per outcome, evaluates
Arb Core, and persists immutable opportunities.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from defend_markets.arb.models import (
    ArbQuote,
    EventState,
    MarketFamily,
    SelectionSide,
)
from defend_markets.quant.market import FULL_MATCH, MATCH_WINNER, SPREAD, TOTAL, parse_dt

ARB_FEED_POLICY_VERSION = "CANONICAL_ODDS_FEED_V1"
ARB_SCAN_POLICY_VERSION = "SPORTS_ARB_SCAN_V1"

# P28: fail-closed. Until the canonical observation storage preserves exact
# period and line, production arb scanning is restricted to MATCH_WINNER_2WAY.
ARB_ALLOWED_FAMILIES = (MarketFamily.MATCH_WINNER_2WAY,)


def _market_family(market: str) -> MarketFamily | None:
    normalized = str(market or "").strip().casefold()
    if normalized in ("match_winner", "ml", "moneyline", "money line", "h2h", "1x2"):
        return MarketFamily.MATCH_WINNER_2WAY
    if normalized in ("spread", "handicap"):
        return MarketFamily.SPREAD
    if normalized in ("total", "totals", "over under"):
        return MarketFamily.TOTAL
    return None


def _selection_side(side: str) -> SelectionSide | None:
    normalized = str(side or "").strip().upper()
    mapping = {
        "A": SelectionSide.PARTICIPANT_A,
        "PARTICIPANT_A": SelectionSide.PARTICIPANT_A,
        "B": SelectionSide.PARTICIPANT_B,
        "PARTICIPANT_B": SelectionSide.PARTICIPANT_B,
        "DRAW": SelectionSide.DRAW,
        "OVER": SelectionSide.OVER,
        "UNDER": SelectionSide.UNDER,
    }
    return mapping.get(normalized)


def _event_state(state: str | None) -> EventState:
    normalized = str(state or "").strip().upper()
    mapping = {
        "UPCOMING": EventState.PRE_MATCH,
        "LIVE": EventState.LIVE,
        "SETTLED": EventState.CLOSED,
        "CANCELLED": EventState.CANCELLED,
    }
    return mapping.get(normalized, EventState.PRE_MATCH)


def observation_to_arb_quote(
    row: dict[str, Any],
    *,
    participant_a: str,
    participant_b: str,
    event_state: str | None = None,
) -> ArbQuote | None:
    """Convert one canonical market observation into an immutable ArbQuote.

    Market identity is exact: only supported families with a resolvable side
    are converted. Unknown stays unknown (no fabricated values).
    """
    market = str(row.get("market") or "")
    family = _market_family(market)
    if family is None:
        return None
    side = _selection_side(str(row.get("side") or ""))
    if side is None:
        return None
    try:
        odds = Decimal(str(row.get("price")))
    except Exception:  # noqa: BLE001 - non-decimal price is invalid evidence
        return None
    if not odds.is_finite() or odds <= Decimal("1"):
        return None
    period = str(row.get("period") or FULL_MATCH)
    line = None
    if family in (MarketFamily.SPREAD, MarketFamily.TOTAL):
        # P27/P28: SPREAD/TOTAL require an exact line. If the canonical
        # observation storage does not preserve the line, fail closed and do
        # NOT fabricate line=None (which would treat different totals/spreads
        # as compatible).
        raw_line = row.get("line")
        if raw_line is None:
            return None
        try:
            line = Decimal(str(raw_line))
        except Exception:  # noqa: BLE001
            return None
    event_id = str(row.get("canonical_event_id") or "")
    if not event_id:
        return None
    return ArbQuote(
        quote_id=str(row.get("observation_id") or f"obs-{event_id}-{side.value}"),
        canonical_event_id=event_id,
        provider_event_id=str(row.get("provider_event_id")) if row.get("provider_event_id") else None,
        bookmaker=str(row.get("bookmaker") or ""),
        sport="table-tennis",
        competition=str(row.get("competition")) if row.get("competition") else None,
        participant_a=participant_a,
        participant_b=participant_b,
        commence_time=parse_dt(row.get("scheduled_commence")),
        market_family=family,
        period=period,
        selection=str(row.get("participant_key") or (participant_a if side is SelectionSide.PARTICIPANT_A else participant_b)),
        selection_side=side,
        line=line,
        decimal_odds=odds,
        observed_at=parse_dt(row.get("observed_at")),
        provider_updated_at=parse_dt(row.get("provider_updated_at")),
        received_at=parse_dt(row.get("received_at")),
        event_state=_event_state(event_state),
        currency="USD",
        source_ref=str(row.get("raw_evidence_ref")) if row.get("raw_evidence_ref") else None,
    )


class CanonicalOddsFeed:
    """Provider-neutral feed: canonical observations -> ArbQuote."""

    def __init__(self, database: Any, *, policy_version: str = ARB_FEED_POLICY_VERSION) -> None:
        self._database = database
        self.policy_version = policy_version

    def quotes_for_events(self, canonical_event_ids: list[str] | None = None) -> list[ArbQuote]:
        """Load current canonical quotes from tt_market_observations.

        Only OPEN / LAST_VALID_PREMATCH observations from the latest poll
        contribute; a quote is the newest observation per
        (canonical_event_id, bookmaker, market, side).
        """
        with self._database.connect() as connection, connection.cursor() as cursor:
            params: list[Any] = []
            sql = (
                "SELECT o.observation_id, o.canonical_event_id, o.provider_event_id, o.bookmaker, "
                "o.market, o.side, o.participant_key, o.price, o.observed_at, o.scheduled_commence, "
                "o.raw_evidence_ref, f.player_a_key, f.player_b_key, f.state "
                "FROM tt_market_observations o "
                "JOIN tt_forward_events f ON f.canonical_event_id = o.canonical_event_id "
                "WHERE o.observation_class IN ('OPEN', 'INTERMEDIATE', 'LAST_VALID_PREMATCH') "
            )
            if canonical_event_ids:
                placeholders = ",".join("%s" for _ in canonical_event_ids)
                sql += f" AND o.canonical_event_id IN ({placeholders})"
                params.extend(canonical_event_ids)
            sql += " ORDER BY o.observed_at ASC"
            cursor.execute(sql, params)
            rows = [
                dict(
                    zip(
                        (
                            "observation_id", "canonical_event_id", "provider_event_id", "bookmaker", "market",
                            "side", "participant_key", "price", "observed_at", "scheduled_commence",
                            "raw_evidence_ref", "player_a_key", "player_b_key", "state",
                        ),
                        row,
                    )
                )
                for row in cursor.fetchall()
            ]
        # newest observation per (event, book, market, side)
        latest: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for row in rows:
            key = (str(row["canonical_event_id"]), str(row["bookmaker"]), str(row["market"]), str(row["side"]))
            current = latest.get(key)
            if current is None or (parse_dt(row["observed_at"]) or datetime.min.replace(tzinfo=timezone.utc)) >= (parse_dt(current["observed_at"]) or datetime.min.replace(tzinfo=timezone.utc)):
                latest[key] = row
        quotes: list[ArbQuote] = []
        for row in latest.values():
            quote = observation_to_arb_quote(
                row,
                participant_a=str(row.get("player_a_key") or ""),
                participant_b=str(row.get("player_b_key") or ""),
                event_state=row.get("state"),
            )
            if quote is not None:
                quotes.append(quote)
        return quotes


class SportsArbScanner:
    """Scheduler-owned arb scanner (P30).

    Groups current compatible quotes by canonical market key, builds the best
    price per outcome with Arb Core, and persists material results. Rejection
    telemetry is aggregated, not spammed.
    """

    def __init__(
        self,
        database: Any,
        store: Any,
        feed: CanonicalOddsFeed | None = None,
        *,
        total_stake: Decimal = Decimal("1000"),
        policy_version: str = ARB_SCAN_POLICY_VERSION,
    ) -> None:
        self._database = database
        self._store = store
        self._feed = feed or CanonicalOddsFeed(database)
        self._total_stake = total_stake
        self.policy_version = policy_version

    def scan(self, *, canonical_event_ids: list[str] | None = None) -> dict[str, Any]:
        from defend_markets.arb.identity import CanonicalMarketKey
        from defend_markets.arb.models import ArbSettings
        from defend_markets.arb.opportunity import build_opportunity, classify
        from defend_markets.arb.risk import SettlementCompatibility, SettlementStatus
        from defend_markets.arb.search import best_price_candidate

        quotes = self._feed.quotes_for_events(canonical_event_ids)
        result = best_price_candidate(tuple(quotes))
        funnel = {
            "quote_sets_examined": 0,
            "mathematical_arbs": 0,
            "paper_actionable": 0,
            "rejected_market_mismatch": 0,
            "rejected_line_mismatch": 0,
            "rejected_period_mismatch": 0,
            "rejected_stale": 0,
            "rejected_time_delta": 0,
            "rejected_settlement_unknown": 0,
            "rejected_stake_constraint": 0,
            "rejected_bankroll": 0,
            "expired": 0,
        }
        stored = 0
        if result.error:
            return {"funnel": funnel, "stored": 0, "error": result.error}

        settings = ArbSettings(policy_version=self.policy_version)
        settlement = SettlementCompatibility(status=SettlementStatus.UNKNOWN)
        for candidate in result.candidates:
            funnel["quote_sets_examined"] += 1
            if not candidate.complete:
                funnel["rejected_market_mismatch"] += 1
                continue
            # P28: fail-closed to MATCH_WINNER_2WAY only.
            families = {q.market_family for q in candidate.source_quotes}
            if any(f not in ARB_ALLOWED_FAMILIES for f in families):
                funnel["rejected_market_mismatch"] += 1
                continue
            # P29: cross-book arb requires >=2 distinct bookmakers; two outcomes
            # from the same bookmaker are not cross-book evidence.
            books = {q.bookmaker for q in candidate.source_quotes}
            if len(books) < 2:
                funnel["rejected_market_mismatch"] += 1
                continue
            from defend_markets.arb.compatibility import check_market_compatibility
            from defend_markets.arb.freshness import FreshnessPolicy, evaluate_freshness

            compatibility = check_market_compatibility(
                candidate.source_quotes,
                max_quote_age_seconds=settings.max_quote_age_seconds,
                pre_match_only=settings.pre_match_only,
            )
            if not compatibility.compatible:
                code = compatibility.result.value
                if "PERIOD" in code:
                    funnel["rejected_period_mismatch"] += 1
                elif "LINE" in code:
                    funnel["rejected_line_mismatch"] += 1
                else:
                    funnel["rejected_market_mismatch"] += 1
                continue
            freshness = evaluate_freshness(
                candidate.source_quotes,
                FreshnessPolicy(
                    max_quote_age_seconds=settings.max_quote_age_seconds,
                    max_cross_book_delta_seconds=settings.max_cross_book_delta_seconds,
                    pre_match_only=settings.pre_match_only,
                ),
            )
            if not freshness.ok:
                if freshness.stale_quotes:
                    funnel["rejected_stale"] += 1
                else:
                    funnel["rejected_time_delta"] += 1
                continue
            try:
                opportunity = build_opportunity(
                    candidate.source_quotes,
                    total_stake=self._total_stake,
                    settings=settings,
                    settlement=settlement,
                )
            except ValueError:
                funnel["rejected_market_mismatch"] += 1
                continue
            if opportunity.classification.value in ("MATHEMATICAL_ARB", "EXECUTABLE_ARB"):
                funnel["mathematical_arbs"] += 1
            if opportunity.classification.value == "EXECUTABLE_ARB":
                funnel["paper_actionable"] += 1
            if opportunity.classification.value == "NO_ARB" and opportunity.raw_margin > 0:
                continue  # no material signal; skip persistence
            # persist immutable snapshot
            fingerprint = opportunity.opportunity_id
            stored_row = self._store.insert_arb_opportunity(self._opportunity_row(opportunity))
            if stored_row:
                stored += 1
                # P31: paper-arb creation path — record a PAPER_ARB ticket for
                # a validated mathematical/executable opportunity.
                if opportunity.classification.value in ("MATHEMATICAL_ARB", "EXECUTABLE_ARB"):
                    self._record_paper_ticket(opportunity)

        # expire ACTIVE opportunities that are past expires_at
        for opp in self._store.list_arb_opportunities(limit=5000, status="ACTIVE"):
            expires_at = opp.get("expires_at")
            if expires_at and (parse_dt(expires_at) or datetime.max.replace(tzinfo=timezone.utc)) < datetime.now(timezone.utc):
                self._store.expire_arb_opportunity(str(opp["opportunity_id"]), expired_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
                funnel["expired"] += 1

        return {
            "funnel": funnel,
            "stored": stored,
            "quotes": len(quotes),
            "summary": f"arb scan: {funnel['quote_sets_examined']} sets, {funnel['mathematical_arbs']} math arbs, {stored} persisted",
        }

    def _record_paper_ticket(self, opportunity: Any) -> None:
        """P31: record an immutable PAPER_ARB ticket for a validated opportunity."""
        from defend_markets.quant.paper_arb import PaperArbStore

        PaperArbStore(self._store).record_ticket(opportunity)

    def _record_verification(self, opportunity: Any, *, still_valid: bool) -> None:
        """P30: append a survival verification observation (never mutate snapshot)."""
        now = datetime.now(timezone.utc)
        self._store.insert_arb_verification(
            {
                "opportunity_id": opportunity.opportunity_id,
                "verified_at": now.isoformat().replace("+00:00", "Z"),
                "still_valid": still_valid,
                "quote_age_seconds": opportunity.quote_age_by_leg,
                "cross_book_delta_seconds": opportunity.cross_book_time_delta,
                "classification": opportunity.classification.value,
            }
        )

    def _opportunity_row(self, opportunity: Any) -> dict[str, Any]:
        return {
            "opportunity_id": opportunity.opportunity_id,
            "fingerprint": opportunity.opportunity_id,
            "canonical_event_id": opportunity.canonical_event_id,
            "canonical_market_key": opportunity.canonical_market_key,
            "detected_at": opportunity.detected_at.isoformat().replace("+00:00", "Z") if opportunity.detected_at else None,
            "first_seen_at": opportunity.detected_at.isoformat().replace("+00:00", "Z") if opportunity.detected_at else None,
            "last_verified_at": opportunity.last_verified_at.isoformat().replace("+00:00", "Z") if opportunity.last_verified_at else None,
            "expires_at": opportunity.expires_at.isoformat().replace("+00:00", "Z") if opportunity.expires_at else None,
            "bookmakers": [q.bookmaker for q in opportunity.quotes],
            "quote_ids": [q.quote_id for q in opportunity.quotes],
            "odds": [str(q.decimal_odds) for q in opportunity.quotes],
            "inverse_sum": str(opportunity.inverse_sum),
            "raw_margin": str(opportunity.raw_margin),
            "stake_plan": [
                {
                    "bookmaker": leg.bookmaker,
                    "quote_id": leg.quote_id,
                    "selection": leg.selection,
                    "selection_side": leg.selection_side,
                    "odds": str(leg.odds),
                    "stake": str(leg.stake),
                    "return": str(leg.return_),
                }
                for leg in opportunity.stake_plan
            ],
            "worst_case_profit": float(opportunity.worst_case_profit),
            "worst_case_roi": float(opportunity.worst_case_roi),
            "freshness_state": opportunity.freshness_state,
            "cross_book_time_delta": opportunity.cross_book_time_delta,
            "settlement_compatibility": "UNKNOWN",
            "classification": opportunity.classification.value,
            "risk_flags": [f.value for f in opportunity.risk_flags],
            "policy_version": opportunity.policy_version,
            "status": "ACTIVE",
        }
