"""M4.8.2 server-side Table Tennis decision board assembler (P2-P6).

One composition service owns the owner-facing board: it joins persisted Hard Rock
quote observations, provider-event mappings, participant orientation, Bet365
observations, FanDuel coverage, M5 predictions, line movement and settlement
state into a canonical board. The UI never joins provider data itself.

Rules (P3/P4/P6/P17/P18/P20):
* matched canonical ID -> canonical board identity; UNMATCHED/AMBIGUOUS/CONFLICT
  -> a unique provider-local identity (never collapse into canonical_event_id=None).
* a book contributes to no-vig consensus only with a coherent, orientation-proven,
  fresh, skew-safe, complete two-way pair.
* cross-book consensus is the mean of valid book no-vig probabilities (NOT a raw
  implied average).
* Hard Rock is the owner-facing reference price.
* deterministic actionability classification, not an LLM opinion.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from defend_markets.quant.line_movement import synchronized_snapshot, two_way_no_vig

REFERENCE_SPORTSBOOK = "hardrock_bet"

# actionability states (P4)
ACTIONABLE = "ACTIONABLE"
WATCH = "WATCH"
NO_MODEL = "NO_MODEL"
NO_COMPARISON = "NO_COMPARISON"
UNMATCHED = "UNMATCHED"
AMBIGUOUS = "AMBIGUOUS"
CONFLICT = "CONFLICT"
STALE = "STALE"
SKEW_EXCEEDED = "SKEW_EXCEEDED"
BAD_ORIENTATION = "BAD_ORIENTATION"
BAD_MARKET = "BAD_MARKET"
DEGRADED_PROVIDER = "DEGRADED_PROVIDER"
BLOCKED = "BLOCKED"


def _q(amount: Any, places: int = 6) -> str:
    if amount is None:
        return "UNKNOWN"
    try:
        return str(Decimal(str(amount)).quantize(Decimal("1").scaleb(-places), rounding=ROUND_HALF_UP))
    except Exception:
        return "UNKNOWN"


def _to_implied(decimal_odds: Any) -> str | None:
    if decimal_odds is None:
        return None
    try:
        d = Decimal(str(decimal_odds))
    except Exception:
        return None
    if d <= 1:
        return None
    return _q(Decimal("1") / d, 8)


def classify_actionability(
    *,
    has_model: bool,
    has_hardrock_pair: bool,
    hardrock_fresh: bool,
    has_bet365: bool,
    bet365_valid: bool,
    match_state: str,
    orientation: str,
    skew_ok: bool,
) -> tuple[str, list[str]]:
    """Deterministic server-side actionability classification (P4)."""
    reasons: list[str] = []
    if match_state == AMBIGUOUS:
        return AMBIGUOUS, ["ambiguous event identity; never actionable"]
    if match_state == CONFLICT:
        return CONFLICT, ["conflicting event identity; never actionable"]
    if match_state == UNMATCHED:
        return UNMATCHED, ["unmatched provider-local event"]
    if orientation in ("CONFLICT", "UNAVAILABLE"):
        return BAD_ORIENTATION, [f"orientation {orientation}"]
    if not has_hardrock_pair:
        return NO_COMPARISON, ["no Hard Rock reference pair"]
    if not hardrock_fresh:
        return STALE, ["Hard Rock reference stale"]
    if not has_model:
        return NO_MODEL, ["M5 prediction unavailable"]
    if not has_bet365:
        return NO_COMPARISON, ["no valid comparison book"]
    if not bet365_valid:
        return NO_COMPARISON, ["comparison book excluded (stale/skew)"]
    if not skew_ok:
        return SKEW_EXCEEDED, ["cross-book skew exceeded"]
    # eligible for full model + consensus view
    return ACTIONABLE, ["M5 + fresh Hard Rock + valid matched comparison"]


class LiveTTBoardService:
    """Assembles the canonical TT board from persisted real state."""

    def __init__(self, store: Any) -> None:
        self._store = store

    # ------------------------------------------------------------------ #
    # Data loading
    # ------------------------------------------------------------------ #

    def _hardrock_quotes(self) -> list[dict[str, Any]]:
        if not hasattr(self._store, "list_hardrock_quotes"):
            return []
        return self._store.list_hardrock_quotes(limit=20000)

    def _bet365_observations(self) -> list[dict[str, Any]]:
        if not hasattr(self._store, "list_bet365_observations"):
            return []
        return self._store.list_bet365_observations(limit=20000)

    def _mappings(self) -> dict[str, dict[str, Any]]:
        if not hasattr(self._store, "list_provider_event_mappings"):
            return {}
        return {str(m["native_event_id"]): m for m in self._store.list_provider_event_mappings(limit=100000)}

    def _m5_predictions(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        if not hasattr(self._store, "list_official_predictions"):
            return out
        for p in self._store.list_official_predictions(limit=100000):
            event = str(p.get("canonical_event_id") or "")
            if not event:
                continue
            model = str(p.get("model_id") or "")
            if "M5" in model.upper():
                out[event] = p
        return out

    # ------------------------------------------------------------------ #
    # Board assembly
    # ------------------------------------------------------------------ #

    def board(self, *, state: str | None = None, actionability: str | None = None,
              matched_only: bool = False, sort: str = "default", limit: int = 200) -> dict[str, Any]:
        """Assemble the canonical board (P3)."""
        hr_quotes = self._hardrock_quotes()
        bet365_obs = self._bet365_observations()
        mappings = self._mappings()
        m5 = self._m5_predictions()

        # group Hard Rock quotes by (canonical_event_id, market_family, period)
        hr_by_market: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for q in hr_quotes:
            key = (str(q.get("canonical_event_id") or ""), str(q.get("market_family") or ""), str(q.get("period") or ""))
            hr_by_market.setdefault(key, []).append(q)

        events: dict[str, dict[str, Any]] = {}
        for (canonical_event_id, family, period), quotes in hr_by_market.items():
            if family != "MATCH_WINNER_2WAY" or period != "FULL_MATCH":
                continue
            if not canonical_event_id:
                continue
            # latest per selection side (P19/P20: coherent pair = same snapshot id)
            sides: dict[str, dict[str, Any]] = {}
            for q in quotes:
                side = str(q.get("selection_side") or "")
                if side not in ("PARTICIPANT_A", "PARTICIPANT_B"):
                    continue
                existing = sides.get(side)
                if existing is None or (q.get("observed_at") or "") >= (existing.get("observed_at") or ""):
                    sides[side] = q
            if "PARTICIPANT_A" not in sides or "PARTICIPANT_B" not in sides:
                continue
            side1 = sides["PARTICIPANT_A"]
            side2 = sides["PARTICIPANT_B"]

            # participant identity (P18)
            mapping = mappings.get(str(side1.get("provider_event_id") or ""))
            participant_1 = side1.get("selection") or "UNKNOWN"
            participant_2 = side2.get("selection") or "UNKNOWN"

            # M5 (p of participant 1)
            model = m5.get(canonical_event_id)
            model_p1 = None
            if model is not None:
                model_p1 = model.get("probability_a")

            # Hard Rock no-vig (P6)
            hr_p1 = _to_implied(side1.get("decimal_odds"))
            hr_p2 = _to_implied(side2.get("decimal_odds"))
            hr_novig = None
            if hr_p1 is not None and hr_p2 is not None:
                hr_novig = two_way_no_vig(side_a_implied=hr_p1, side_b_implied=hr_p2)

            # Bet365 comparison (orientation-applied; P3 orientation applied, P5)
            bet365 = self._assemble_bet365(canonical_event_id, bet365_obs, participant_1, participant_2)

            # synchronized snapshot + skew
            snap = synchronized_snapshot(
                quotes_by_book={
                    REFERENCE_SPORTSBOOK: [side1, side2],
                    "Bet365": bet365["quotes"],
                },
                max_age_seconds=600,
                max_skew_seconds=120,
            )
            bet365_valid = "Bet365" in snap.get("included_books", [])

            # consensus (P6: mean of valid book no-vig p1)
            consensus_p1 = self._consensus(
                hr_novig,
                bet365["novig"] if bet365_valid else None,
            )

            match_state = str((mapping or {}).get("identity_mode") or "UNMATCHED")
            orientation = str((mapping or {}).get("identity_mode") or "UNAVAILABLE")
            has_model = model is not None and model_p1 is not None
            hardrock_fresh = snap.get("reference_present", False)
            actionability_state, reasons = classify_actionability(
                has_model=has_model,
                has_hardrock_pair=True,
                hardrock_fresh=hardrock_fresh,
                has_bet365=bool(bet365["quotes"]),
                bet365_valid=bet365_valid,
                match_state=match_state,
                orientation=orientation,
                skew_ok=bet365_valid,
            )

            # model edge (P6)
            edge_hr = None
            edge_hr_novig = None
            edge_consensus = None
            if model_p1 is not None:
                edge_hr = float(model_p1) - float(hr_p1) if hr_p1 is not None else None
                if hr_novig and hr_novig.get("ok"):
                    edge_hr_novig = float(model_p1) - float(hr_novig["no_vig_a"])
                if consensus_p1 is not None:
                    edge_consensus = float(model_p1) - float(consensus_p1)

            events[canonical_event_id] = {
                "canonical_event_id": canonical_event_id,
                "hardrock_provider_event_id": side1.get("provider_event_id"),
                "bet365_provider_event_id": bet365.get("provider_event_id"),
                "participant_1": participant_1,
                "participant_2": participant_2,
                "scheduled_time": None,
                "state": "LIVE" if str(side1.get("state") or "").upper() == "LIVE" else "UPCOMING",
                "cross_book_match_state": match_state,
                "orientation": orientation,
                "hardrock": {
                    "side_1": {"american": side1.get("american_odds"), "decimal": _q(side1.get("decimal_odds")), "raw_implied": hr_p1, "observed_at": side1.get("observed_at")},
                    "side_2": {"american": side2.get("american_odds"), "decimal": _q(side2.get("decimal_odds")), "raw_implied": hr_p2, "observed_at": side2.get("observed_at")},
                    "overround": hr_novig.get("overround") if hr_novig and hr_novig.get("ok") else None,
                    "no_vig_pair": {"side_1": hr_novig["no_vig_a"], "side_2": hr_novig["no_vig_b"]} if hr_novig and hr_novig.get("ok") else None,
                },
                "bet365": bet365["view"],
                "fanduel_coverage": "NO_CURRENT_TT_COVERAGE",
                "hardrock_fresh": hardrock_fresh,
                "bet365_fresh": bet365_valid,
                "observation_skew_seconds": snap.get("observed_skew_seconds"),
                "consensus_no_vig_p1": consensus_p1,
                "m5": {
                    "p1": _q(model_p1, 6) if model_p1 is not None else None,
                    "version": str(model.get("model_version") or "") if model else None,
                    "hash": (str(model.get("model_hash") or "")[:12]) if model and model.get("model_hash") else None,
                },
                "edge_hr": _q(edge_hr, 6) if edge_hr is not None else None,
                "edge_hr_no_vig": _q(edge_hr_novig, 6) if edge_hr_novig is not None else None,
                "edge_consensus": _q(edge_consensus, 6) if edge_consensus is not None else None,
                "actionability": actionability_state,
                "actionability_reasons": reasons,
            }

        result = list(events.values())

        # filters
        if state:
            result = [e for e in result if e["state"] == state.upper()]
        if actionability:
            result = [e for e in result if e["actionability"] == actionability.upper()]
        if matched_only:
            result = [e for e in result if e["cross_book_match_state"] in ("KEY_EXACT", "NAME_TIME_EXACT")]

        # deterministic ranking (P10)
        result.sort(key=lambda e: self._rank_key(e))
        if sort == "edge":
            result.sort(key=lambda e: -(abs(float(e["edge_hr"])) if e["edge_hr"] not in (None, "UNKNOWN") else 0.0))

        return {"events": result[:limit], "count": len(result[:limit]), "total": len(events)}

    def _rank_key(self, e: dict[str, Any]) -> tuple:
        order = {ACTIONABLE: 0, WATCH: 1, NO_COMPARISON: 2, NO_MODEL: 3, STALE: 4, SKEW_EXCEEDED: 5, UNMATCHED: 6, AMBIGUOUS: 7, CONFLICT: 8}
        actionability = e["actionability"]
        rank = order.get(actionability, 9)
        # LIVE before UPCOMING
        live = 0 if e["state"] == "LIVE" else 1
        # edge magnitude (descending) within actionable
        edge = abs(float(e["edge_hr"])) if e["edge_hr"] not in (None, "UNKNOWN") else 0.0
        return (rank, live, -edge)

    def _assemble_bet365(self, canonical_event_id: str, observations: list[dict[str, Any]],
                         participant_1: str, participant_2: str) -> dict[str, Any]:
        """Assemble a Bet365 comparison view with orientation applied (P3/P5)."""
        quotes = [o for o in observations if str(o.get("canonical_event_id") or "") == canonical_event_id]
        if not quotes:
            return {"quotes": [], "view": None, "novig": None, "provider_event_id": None}
        # orientation: map provider side to canonical participant
        from defend_markets.quant.event_matcher import resolve_provider_orientation

        sides: dict[str, dict[str, Any]] = {}
        for q in quotes:
            side = str(q.get("selection_side") or "")
            if side in ("PARTICIPANT_A", "PARTICIPANT_B"):
                existing = sides.get(side)
                if existing is None or (q.get("observed_at") or "") >= (existing.get("observed_at") or ""):
                    sides[side] = q
        side_a = sides.get("PARTICIPANT_A")
        side_b = sides.get("PARTICIPANT_B")
        if not side_a or not side_b:
            return {"quotes": [], "view": None, "novig": None, "provider_event_id": None}
        # orientation between Bet365 selection names and canonical participants
        _, _, orientation = resolve_provider_orientation(
            provider_participant_a=str(side_a.get("selection") or ""),
            provider_participant_b=str(side_b.get("selection") or ""),
            canonical_participant_1=participant_1,
            canonical_participant_2=participant_2,
        )
        p1 = _to_implied(side_a.get("decimal_odds") if orientation != "REVERSED" else side_b.get("decimal_odds"))
        p2 = _to_implied(side_b.get("decimal_odds") if orientation != "REVERSED" else side_a.get("decimal_odds"))
        novig = two_way_no_vig(side_a_implied=p1, side_b_implied=p2) if (p1 and p2 and orientation != "CONFLICT") else None
        view = {
            "side_1": {"decimal": _q(side_a.get("decimal_odds")), "raw_implied": p1, "observed_at": side_a.get("observed_at")},
            "side_2": {"decimal": _q(side_b.get("decimal_odds")), "raw_implied": p2, "observed_at": side_b.get("observed_at")},
            "orientation": orientation,
            "overround": novig.get("overround") if novig and novig.get("ok") else None,
            "no_vig_pair": {"side_1": novig["no_vig_a"], "side_2": novig["no_vig_b"]} if novig and novig.get("ok") else None,
        } if orientation != "CONFLICT" else None
        return {"quotes": [side_a, side_b], "view": view, "novig": novig, "provider_event_id": str(side_a.get("provider_event_id") or "")}

    def _consensus(self, hr_novig: dict[str, Any] | None, bet365_novig: dict[str, Any] | None) -> str | None:
        """Cross-book no-vig consensus = mean of valid book no-vig p1 (P6)."""
        values: list[Decimal] = []
        for novig in (hr_novig, bet365_novig):
            if novig and novig.get("ok"):
                try:
                    values.append(Decimal(str(novig["no_vig_a"])))
                except Exception:
                    pass
        if not values:
            return None
        mean = sum(values, Decimal("0")) / len(values)
        return _q(mean, 8)

    def event_detail(self, canonical_event_id: str) -> dict[str, Any] | None:
        """P7: full event detail for one canonical event."""
        board = self.board(limit=100000)
        for e in board["events"]:
            if e["canonical_event_id"] == canonical_event_id:
                return e
        return None

    def hardrock_history(self, canonical_event_id: str, *, limit: int = 50) -> dict[str, Any]:
        """P8: bounded Hard Rock quote history per canonical selection."""
        quotes = [q for q in self._hardrock_quotes() if str(q.get("canonical_event_id") or "") == canonical_event_id]
        quotes.sort(key=lambda q: str(q.get("observed_at") or ""), reverse=True)
        return {
            "canonical_event_id": canonical_event_id,
            "observations": [
                {
                    "selection_side": q.get("selection_side"),
                    "american": q.get("american_odds"),
                    "decimal": _q(q.get("decimal_odds")),
                    "observed_at": q.get("observed_at"),
                    "ladder_snapshot_id": q.get("ladder_snapshot_id"),
                }
                for q in quotes[:limit]
            ],
        }
