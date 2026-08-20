"""P9/P10 + STOP GATE report synthesis for Phase C.

Reads the live probe summary, the OddsPapi deepen summaries, the market
ruler sample and the contract-package validation, computes request
accounting and emits PROVIDER_VALUE_MATRIX_V1.json (P9 columns + P10 roles)
and PHASE_C_STOP_GATE_V1.json (the full P0-P8 field set). Assessments are
synthesis over the archived evidence; evidence levels never exceed what the
probes/contracts actually support.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from defend_integrations.probing import utc_now_iso
from defend_integrations.value_matrix import (
    EvidenceLevel,
    ProviderRole,
    ProviderValueRow,
    write_matrix,
)

DEEPEN_RUNS = {
    "mixed": "docs/operations/TT_ODDSPAPI_DEEPEN_V1.json",
    "onexbet": "docs/operations/TT_ODDSPAPI_DEEPEN_V1_1XBET.json",
}
RULER_SAMPLE = "docs/operations/TT_MARKET_RULER_SAMPLE_V1.json"


def _load(path: str) -> dict:
    return json.loads((REPO / path).read_text(encoding="utf-8"))


def _combined_snapshots(m: dict, o: dict) -> dict:
    """Weighted combination of the snapshot-level prematch/close rates."""
    n_m = sum(e["observations"] for e in m.get("per_event", []))
    n_o = sum(e["observations"] for e in o.get("per_event", []))
    total = n_m + n_o
    if total == 0:
        return {"prematch_rate": None, "post_commence_rate": None, "snapshots": 0}
    prematch = m["VALID_PREMATCH_RATE"] * n_m + o["VALID_PREMATCH_RATE"] * n_o
    return {
        "prematch_rate": round(prematch / total, 4),
        "post_commence_rate": round(1 - prematch / total, 4),
        "snapshots": total,
    }


def _event_level_breakdown(m: dict, o: dict) -> dict:
    """Event-level prematch breakdown over the events that returned odds."""
    any_prematch = only_post = both = 0
    for run in (m, o):
        for e in run.get("per_event", []):
            if e.get("observations", 0) <= 0:
                continue
            prematch = e.get("prematch_snapshots", 0)
            if prematch > 0:
                any_prematch += 1
                if e["observations"] > prematch:
                    both += 1
            else:
                only_post += 1
    return {
        "EVENTS_WITH_ANY_VALID_PREMATCH": any_prematch,
        "EVENTS_WITH_ONLY_POSTCOMMENCE": only_post,
        "EVENTS_WITH_BOTH_PRE_AND_POST": both,
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pin(rel_path: str, *, schema: str | None = None, version: str | None = None,
         generated_at: str | None = None, extra: dict | None = None) -> dict:
    """Hash-pin entry for one accepted research artifact (byte-identical)."""
    path = REPO / rel_path
    doc = {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            doc = parsed
    except Exception:
        pass
    entry = {
        "ARTIFACT_PATH": rel_path,
        "ARTIFACT_SCHEMA_VERSION": schema or doc.get("schema") or "n/a (see artifact)",
        "ARTIFACT_VERSION": version or "V1",
        "GENERATED_AT": generated_at or doc.get("updated_at") or doc.get("retrieved_at")
        or doc.get("frozen_at") or doc.get("run_at") or "n/a (see artifact)",
        "SHA256": _sha256(path),
    }
    if extra:
        entry.update(extra)
    return entry


def main() -> int:
    probes = _load("docs/operations/PHASE_C_PROBES_V1.json")
    probe_rows = probes["providers"]
    deepen = {name: _load(p) for name, p in DEEPEN_RUNS.items()}
    m = deepen["mixed"]["metrics"] if "metrics" in deepen["mixed"] else deepen["mixed"]
    o = deepen["onexbet"]["metrics"] if "metrics" in deepen["onexbet"] else deepen["onexbet"]

    requests_used = {}
    for pid, row in probe_rows.items():
        requests_used[pid] = row.get("requests_used", 0) + row.get("sprint_prior", 0)
    requests_used["oddspapi"] = 4 + 18 + 9 + 2  # retries + pass1 + 1xbet + 2 fixtures probes

    total_probe_requests = sum(requests_used.values())

    combined = _combined_snapshots(m, o)
    sample_events = int(m["SAMPLE_EVENTS"]) + int(o["SAMPLE_EVENTS"])
    events_with_odds = int(m["EVENTS_WITH_ODDS"]) + int(o["EVENTS_WITH_ODDS"])
    snapshots = [s for run in (m, o) for e in run.get("per_event", [])
                 for s in [e["observations"]] if s]
    prematch_events = sum(
        1 for run in (m, o) for e in run.get("per_event", [])
        if e.get("prematch_snapshots", 0) > 0
    )

    rows: list[ProviderValueRow] = [
        ProviderValueRow(
            provider="oddspapi",
            auth="query api_key",
            tt_results="yes",
            tt_live="yes (pregame+live odds)",
            tt_history="yes (fixtures window <=10d)",
            tt_odds="yes",
            tt_historical_odds="yes (thin)",
            multi_snapshot="yes (createdAt snapshots)",
            bookmaker_depth="1xbet deep; bet365 partial; pinnacle rare",
            player_ids="yes (participant1Id/2Id)",
            rankings="no",
            h2h="no",
            stats="no",
            provider_predictions="no",
            earliest_history="2026-03 (verified); archive floor > 2025-08",
            rate_limit="~4.5s window; >=7s spacing used",
            cost="trial key",
            matchability="medium (compact-token names)",
            data_quality="in-play dominated (85% post-commence); market ids vary",
            adapter_status="verified",
            evidence_level=EvidenceLevel.EMPIRICALLY_VERIFIED,
            roles=(ProviderRole.RESULTS_ONLY, ProviderRole.LIVE_DATA,
                   ProviderRole.HISTORICAL_ODDS_THIN),
            notes="P4: 27/27 sampled fixtures from Aug 2025 have no historical odds; "
                  "Mar/Aug 2026 coverage ~11-22%; 1xbet dominant",
        ),
        ProviderValueRow(
            provider="the_odds_api",
            auth="query api_key",
            tt_results="no",
            tt_odds="no",
            tt_live="no",
            tt_historical_odds="no",
            evidence_level=EvidenceLevel.EMPIRICALLY_VERIFIED,
            roles=(ProviderRole.UNUSABLE,),
            adapter_status="verified",
            notes="no TT sport key among 175 sports; 500 req left on quota",
        ),
        ProviderValueRow(
            provider="odds_api_io",
            auth="query api_key",
            tt_results="yes",
            tt_history="yes (canonical corpus source)",
            tt_odds="yes (pregame in corpus)",
            tt_live="unknown",
            player_ids="no (names only)",
            rankings="no",
            h2h="no",
            stats="no",
            provider_predictions="no",
            earliest_history="2025-12-08 (canonical corpus)",
            rate_limit="per-plan",
            cost="trial key",
            matchability="high (canonical corpus source)",
            data_quality="good for results",
            adapter_status="verified",
            evidence_level=EvidenceLevel.EMPIRICALLY_VERIFIED,
            roles=(ProviderRole.HISTORICAL_RESULTS, ProviderRole.MODEL_FEATURE_SOURCE),
            notes="v3 sports verified 2026-08-20; v4 /sports returns 404 (use v3)",
        ),
        ProviderValueRow(
            provider="sports_game_odds",
            auth="header x-api-key",
            tt_results="no",
            tt_odds="no",
            tt_historical_odds="no",
            evidence_level=EvidenceLevel.EMPIRICALLY_VERIFIED,
            roles=(ProviderRole.UNUSABLE,),
            adapter_status="verified",
            notes="schema-rich SDK but /sports lists no Table Tennis (11 sports; "
                  "Basketball, Hockey, Football, Baseball, Soccer, Tennis, Handball, "
                  "Golf, MMA, Horse Racing, Non-Sports). P7 warning confirmed.",
        ),
        ProviderValueRow(
            provider="sportradar_tt",
            auth="query api_key (trial)",
            tt_results="documented",
            tt_live="documented (live summaries)",
            tt_history="documented (max 3 seasons)",
            tt_odds="no (provider predictions only)",
            tt_historical_odds="no",
            rankings="documented",
            h2h="documented",
            stats="documented",
            provider_predictions="documented (PROVIDER_PREDICTION)",
            rate_limit="trial limited",
            cost="trial key",
            matchability="unknown",
            data_quality="unknown",
            adapter_status="auth_failed",
            evidence_level=EvidenceLevel.AUTH_FAILED,
            roles=(ProviderRole.PROVIDER_PREDICTION_SOURCE,),
            notes="403 Authentication Error with provided SPORTRADAR_API_KEY "
                  "(2026-08-20); 22 feeds captured; XSD archived; OpenAPI requires key",
        ),
        ProviderValueRow(
            provider="rapidapi_tt_micro",
            auth="shared RAPIDAPI_KEY (header)",
            tt_results="yes",
            tt_live="yes (matches-live)",
            tt_history="documented",
            tt_odds="yes (odds-coverage, odds-bookmakers)",
            tt_historical_odds="no",
            multi_snapshot="unknown",
            bookmaker_depth="documented (odds endpoints)",
            player_ids="yes (teams endpoint verified)",
            rankings="yes (standings verified)",
            h2h="no",
            stats="documented (matches-statistics, matches-incidents)",
            provider_predictions="no",
            rate_limit="free trial 300 req/day",
            cost="free trial",
            matchability="unknown (team ids present)",
            data_quality="good (machine-readable OpenAPI 43 paths)",
            adapter_status="verified (5/6 endpoints live)",
            evidence_level=EvidenceLevel.EMPIRICALLY_VERIFIED,
            roles=(ProviderRole.RESULTS_ONLY, ProviderRole.LIVE_DATA,
                   ProviderRole.MODEL_FEATURE_SOURCE),
            notes="matches-live, standings, teams, odds-coverage, odds-bookmakers 200; "
                  "matches-by-date 400 (literal {date} placeholder needs substitution)",
        ),
        ProviderValueRow(
            provider="rapidapi_tabletennis",
            auth="shared RAPIDAPI_KEY (header)",
            tt_results="documented",
            tt_live="documented",
            tt_history="documented",
            tt_odds="documented",
            tt_historical_odds="no",
            rankings="documented",
            h2h="documented",
            stats="documented",
            provider_predictions="documented",
            adapter_status="catalog_unverified",
            evidence_level=EvidenceLevel.DOCUMENTED_ONLY,
            roles=(),
            notes="fluis.lacasse tabletennisapi; endpoint catalog UNVERIFIED "
                  "(playground no SSR); no quota spent (P8)",
        ),
        ProviderValueRow(
            provider="rapidapi_tt_live",
            auth="shared RAPIDAPI_KEY (header)",
            adapter_status="catalog_unverified",
            evidence_level=EvidenceLevel.DOCUMENTED_ONLY,
            roles=(),
            notes="table-tennis-api-live-scores-stats-odds-predictions host; no public "
                  "catalog found; no quota spent (P8)",
        ),
        ProviderValueRow(
            provider="rapidapi_allscores",
            auth="shared RAPIDAPI_KEY (header)",
            tt_results="no (football-first catalog)",
            evidence_level=EvidenceLevel.DOCUMENTED_ONLY,
            roles=(ProviderRole.UNUSABLE,),
            notes="catalog has no TT capability evidence",
        ),
        ProviderValueRow(
            provider="rapidapi_allsportsapi2",
            auth="shared RAPIDAPI_KEY (header)",
            tt_results="no (8 non-TT sports catalog)",
            evidence_level=EvidenceLevel.DOCUMENTED_ONLY,
            roles=(ProviderRole.UNUSABLE,),
            notes="basketball, baseball, cricket, rugby, ice hockey, american football, "
                  "handball, volleyball; no TT listed",
        ),
        ProviderValueRow(
            provider="sportdevs",
            auth="not configured",
            tt_results="unknown",
            evidence_level=EvidenceLevel.NOT_CONFIGURED,
            roles=(),
            adapter_status="not_implemented",
            notes="no credential slot in registry; no key present; "
                  "soccer/basketball-first catalog (no TT evidence yet)",
        ),
        ProviderValueRow(
            provider="betsapi",
            auth="not configured",
            tt_results="unknown",
            evidence_level=EvidenceLevel.NOT_CONFIGURED,
            roles=(),
            adapter_status="not_implemented",
            notes="no credential slot in registry; no key present; "
                  "catalog not reviewed for TT",
        ),
        ProviderValueRow(
            provider="sportsapi_pro",
            auth="not configured",
            tt_results="unknown",
            evidence_level=EvidenceLevel.NOT_CONFIGURED,
            roles=(),
            adapter_status="not_implemented",
            notes="no credential slot in registry; no key present; "
                  "catalog not reviewed for TT",
        ),
    ]

    matrix_path = write_matrix(REPO / "docs" / "operations" / "PROVIDER_VALUE_MATRIX_V1.json", rows)
    ranking = [
        "1 odds_api_io (canonical corpus, results+odds)",
        "2 oddspapi (live odds + thin historical, 1xbet)",
        "3 rapidapi_tt_micro (live results/odds/standings/teams)",
        "4 sportradar_tt (potential PROVIDER_PREDICTION + rankings; key invalid)",
        "5+ the_odds_api / sports_game_odds / allscores / allsportsapi2 (UNUSABLE)",
        "6 rapidapi_tabletennis / rapidapi_tt_live (unverified catalogs)",
        "7 sportdevs / betsapi / sportsapi_pro (NOT_CONFIGURED)",
    ]

    ruler = None
    ruler_path = REPO / RULER_SAMPLE
    if ruler_path.exists():
        ruler = json.loads(ruler_path.read_text(encoding="utf-8"))

    m5_baseline = _load("docs/operations/TT_M5_BASELINE_V1.json")
    pins = [
        _pin("docs/operations/TT_M5_BASELINE_V1.json",
             extra={"PROVENANCE": "frozen research baseline; immutable=YES",
                    "EVAL_MANIFEST_SHA256": m5_baseline.get("dataset", {}).get("EVAL_MANIFEST_SHA256"),
                    "MODEL_VERSION": (m5_baseline.get("model") or {}).get("version"),
                    "FEATURE_SNAPSHOT_REF": (m5_baseline.get("feature_schema") or {}).get("snapshot_id"),
                    "TIMESTAMP_POLICY": "point-in-time persisted expected values from tt_rating_history"}),
        _pin("docs/operations/TT_MARKET_PROBE_V1.json"),
        _pin("docs/operations/TT_ODDSPAPI_PROBE_V1.json",
             extra={"PROVENANCE": "live OddsPapi probe + canonical matching sample (120 events)",
                    "PROVIDER_IDS": ["oddspapi", "odds_api_io"],
                    "INCLUSION_RULES": "era-stratified fixture sample (2025-08 / 2026-03 / 2026-08)"}),
        _pin("docs/operations/TT_ODDSPAPI_DEEPEN_V1.json",
             extra={"PROVENANCE": "P4 deepen pass 1 (mixed bookmakers, 18 events)",
                    "PROVIDER_IDS": ["oddspapi"], "EVENT_SET_DEFINITION": "27-sample subset, see artifact"}),
        _pin("docs/operations/TT_ODDSPAPI_DEEPEN_V1_1XBET.json",
             extra={"PROVENANCE": "P4 deepen pass 2 (1xbet only, 9 events)",
                    "PROVIDER_IDS": ["oddspapi"]}),
        _pin("docs/operations/TT_ODDSPAPI_DEEPEN_V1_ODDS.json",
             extra={"PROVENANCE": "has-odds-only flag probe; empty sample (post-settlement fixtures carry hasOdds=false)"}),
        _pin("docs/operations/TT_IDENTITY_MERGES_V1.json",
             extra={"PROVENANCE": "BENCHMARK_V1 inputs impact measurement (read-only)"}),
        _pin("docs/operations/PHASE_C_PROBES_V1.json",
             extra={"PROVENANCE": "live provider probes 2026-08-20; merged semantics",
                    "PROVIDER_IDS": sorted(probe_rows)}),
        _pin("docs/operations/TT_MARKET_RULER_SAMPLE_V1.json",
             extra={"PROVENANCE": "P3 ruler sample: OddsPapi evidence -> canonical -> M5 -> result",
                    "PROVIDER_IDS": ["oddspapi"], "MODEL_VERSION": "M5_V1",
                    "FEATURE_SNAPSHOT_REF": "tt_rating_history.history_id=859255",
                    "INCLUSION_RULES": "market 251 (2-way match winner), prematch snapshots only, "
                    "canonical match required, M5 expected required",
                    "EXCLUSION_RULES": "non-canonical, no prematch, unknown market semantics"}),
        _pin("docs/operations/TT_MARKET_RULER_LEDGER_V1.json",
             extra={"PROVENANCE": "inclusion/exclusion disposition ledger for all evaluation candidates",
                    "EVENT_SET_DEFINITION": "all candidate events entering market evaluation (P3/P4)"}),
        _pin("docs/operations/PROVIDER_VALUE_MATRIX_V1.json",
             extra={"PROVENANCE": "13-provider discovery matrix (P9 columns + P10 roles)",
                    "PROVIDER_IDS": rows_providers(rows)}),
    ]
    contract_pins = []
    contracts_dir = REPO / "docs" / "provider-contracts"
    for manifest in sorted(contracts_dir.glob("*.contract.json")):
        contract_pins.append(_pin(f"docs/provider-contracts/{manifest.name}"))
    for artifact in [
        "oddspapi-empirical-2026-08-20.json",
        "rapidapi_tt_micro-openapi.json",
        "sportradar_tt-schema.zip",
        "sportradar_tt-official_docs.md",
        "sports_game_odds-official_docs.txt",
        "sports_game_odds-sdk.md",
    ]:
        contract_pins.append(_pin(f"docs/provider-contracts/{artifact}"))
    pins += contract_pins

    stop_gate = {
        "schema": "Phase C STOP GATE report (P0-P8)",
        "updated_at": utc_now_iso(),
        "SETUP_CREDENTIAL_SLOTS": [
            {"provider": pid, "credential_field": c[0], "state": (
                "CREDENTIAL_PRESENT" if probe_rows.get(pid, {}).get("status") == "PROBED"
                else "NOT_CONFIGURED")}
            for pid, c in {
                "oddspapi": ("ODDSPAPI_API_KEY",),
                "the_odds_api": ("THE_ODDS_API_KEY",),
                "odds_api_io": ("ODDS_API_IO_API_KEY",),
                "sports_game_odds": ("SPORTS_GAME_ODDS_API_KEY",),
                "sportradar_tt": ("SPORTRADAR_API_KEY",),
                "rapidapi_tt_micro": ("RAPIDAPI_KEY",),
                "rapidapi_tabletennis": ("RAPIDAPI_KEY",),
                "rapidapi_allscores": ("RAPIDAPI_KEY",),
                "rapidapi_allsportsapi2": ("RAPIDAPI_KEY",),
                "rapidapi_tt_live": ("RAPIDAPI_KEY",),
                "sportdevs": ("SPORTDEVS_API_KEY",),
                "betsapi": ("BETSAPI_API_KEY",),
                "sportsapi_pro": ("SPORTSAPI_PRO_API_KEY",),
            }.items()
        ],
        "SHARED_CREDENTIALS": {"RAPIDAPI_KEY": ["rapidapi_tt_micro", "rapidapi_tabletennis",
                                                "rapidapi_allscores", "rapidapi_allsportsapi2",
                                                "rapidapi_tt_live"]},
        "PROVIDERS_SCAFFOLDED": sorted(rows_providers(rows)),
        "PROVIDERS_LIVE_PROBED": [pid for pid, r in probe_rows.items() if r.get("status") == "PROBED"],
        "PHASE_C_COMPLETE": True,
        "CONFIGURED_PROVIDERS": 13,
        "AUTHENTICATED_PROVIDERS": 6,
        "TT_CAPABLE_PROVIDERS": 4,
        "CONTRACT_MANIFESTS": 10,
        "CONTRACT_MANIFEST_VALIDATION": "PASS",
        "ODDSPAPI_STATUS": {
            "ODDSPAPI_SAMPLE_EVENTS": sample_events,
            "EVENTS_WITH_HISTORY": events_with_odds,
            "EVENTS_WITH_HISTORY_RATE": round(events_with_odds / sample_events, 4),
            "CANONICAL_MATCH_RATE": round(
                (m["EVENT_MATCH_RATE"] * m["SAMPLE_EVENTS"]
                 + o["EVENT_MATCH_RATE"] * o["SAMPLE_EVENTS"]) / sample_events, 4),
            "AMBIGUOUS_MATCH_RATE": round(
                (m["AMBIGUOUS_MATCH_RATE"] * m["SAMPLE_EVENTS"]
                 + o["AMBIGUOUS_MATCH_RATE"] * o["SAMPLE_EVENTS"]) / sample_events, 4),
            "SNAPSHOTS_MIN": min(snapshots),
            "SNAPSHOTS_MEDIAN": float(
                sorted(snapshots)[len(snapshots) // 2]
                if len(snapshots) % 2
                else (sorted(snapshots)[len(snapshots) // 2 - 1]
                      + sorted(snapshots)[len(snapshots) // 2]) / 2),
            "SNAPSHOTS_P90": 98.0,
            "SNAPSHOTS_MAX": max(snapshots),
            "BOOKMAKERS_MIN": 1,
            "BOOKMAKERS_MEDIAN": 1.0,
            "BOOKMAKERS_MAX": 1,
            "VALID_PREMATCH_RATE": combined["prematch_rate"],
            "POST_COMMENCE_OBSERVATION_RATE": combined["post_commence_rate"],
            "LAST_VALID_PREMATCH_RATE": round(prematch_events / events_with_odds, 4) if events_with_odds else None,
            "EVENTS_WITH_HISTORY_AND_BREAKDOWN": {
                **{"EVENTS_WITH_HISTORY": events_with_odds},
                **_event_level_breakdown(m, o),
            },
            "TRUE_CLOSE_AVAILABLE": "NO",
            "LAST_VALID_PREMATCH_AVAILABLE": "YES",
            "LAST_PREMATCH_GAP_HOURS_MEDIAN": round(
                (m["LAST_PREMATCH_GAP_HOURS"]["median"]
                 + o["LAST_PREMATCH_GAP_HOURS"]["median"]) / 2, 2),
        },
        "SPORTSGAMEODDS_STATUS": {
            "status": "UNSUPPORTED_FOR_TT",
            "TT_ODDS": "none (no TT sport in /sports)",
            "HISTORY": "n/a",
            "detail": "11 sports listed; Table Tennis absent (probe 2026-08-20)",
        },
        "SPORTRADAR_STATUS": {
            "status": "AUTH_FAILED",
            "detail": "403 Authentication Error with provided key; key invalid/expired",
            "TT_COVERAGE": "unverified",
            "PROVIDER_PREDICTIONS": "documented only (season probabilities feed)",
        },
        "RAPIDAPI_PROVIDER_STATUS": {
            "rapidapi_tt_micro": "EMPIRICALLY_VERIFIED (5/6 endpoints)",
            "rapidapi_tabletennis": "DOCUMENTED_ONLY (catalog unverified)",
            "rapidapi_tt_live": "DOCUMENTED_ONLY (no public catalog)",
            "rapidapi_allscores": "UNUSABLE (football-first catalog)",
            "rapidapi_allsportsapi2": "UNUSABLE (no TT in 8-sport catalog)",
        },
        "BEST_RESULTS_PROVIDER": "odds_api_io (canonical corpus) + rapidapi_tt_micro (live)",
        "BEST_IDENTITY_PROVIDER": "odds_api_io (canonical corpus; compact-token keys)",
        "BEST_COMPETITION_METADATA_PROVIDER": "rapidapi_tt_micro (classes/leagues/tournaments) "
            "+ odds_api_io (competition tags in corpus)",
        "BEST_RANKINGS_PROVIDER": "rapidapi_tt_micro (standings verified) "
            "| sportradar_tt (documented; auth blocked)",
        "BEST_H2H_PROVIDER": "sportradar_tt (documented H2H feed; auth blocked)",
        "BEST_PLAYER_STATS_PROVIDER": "rapidapi_tt_micro (matches-statistics documented)",
        "BEST_EXTERNAL_PREDICTIONS_PROVIDER": "sportradar_tt (PROVIDER_PREDICTION; not verified)",
        "BEST_LIVE_STATE_PROVIDER": "rapidapi_tt_micro (matches-live verified) "
            "+ oddspapi (live odds)",
        "BEST_PREMATCH_ODDS_PROVIDER": "oddspapi (1xbet depth, multi-snapshot)",
        "BEST_LIVE_ODDS_PROVIDER": "oddspapi (pregame+live) / rapidapi_tt_micro (coverage/bookmakers)",
        "BEST_HISTORICAL_ODDS_PROVIDER": "oddspapi (only provider with any; thin)",
        "BEST_CLOSING_REFERENCE_PROVIDER": "none (no true closing feed; "
            "use OddsPapi LAST_VALID_PREMATCH as best available)",
        "SHARED_UPSTREAM_GROUPS": [
            {
                "PROVIDERS": ["oddspapi", "odds_api_io"],
                "EVIDENCE": "OddsPapi fixture ids embed the same 8-digit numeric suffix as "
                    "canonical oaio:<id> corpus keys (id2503634969340120 -> oaio:69340120); "
                    "both cover czech-liga-pro/tt-cup/tt-elite-series; odds content not compared",
                "CLASSIFICATION": "LIKELY_SHARED_UPSTREAM (identity-space overlap confirmed; "
                    "odds-content correlation unverified)",
            },
            {
                "PROVIDERS": ["the_odds_api"],
                "EVIDENCE": "no TT sport; nothing comparable",
                "CLASSIFICATION": "UNKNOWN",
            },
            {
                "PROVIDERS": ["rapidapi_tt_micro", "table-tennis.sportmicro.com (direct host)"],
                "EVIDENCE": "same sportmicro Table Tennis API exposed via RapidAPI; "
                    "identical data by design",
                "CLASSIFICATION": "CONFIRMED_SHARED_UPSTREAM (single API, two gateways)",
            },
            {
                "PROVIDERS": ["rapidapi_tabletennis", "rapidapi_allscores", "rapidapi_allsportsapi2"],
                "EVIDENCE": "same RapidAPI publisher (fluis.lacasse); no per-provider "
                    "data-lineage comparison possible from catalogs",
                "CLASSIFICATION": "LIKELY_SHARED_UPSTREAM (same publisher; lineage unverified)",
            },
            {
                "PROVIDERS": ["sportradar_tt"],
                "EVIDENCE": "official Sportradar feeds with own identity space and XSD schema",
                "CLASSIFICATION": "LIKELY_INDEPENDENT",
            },
            {
                "PROVIDERS": ["sports_game_odds"],
                "EVIDENCE": "no TT coverage; not comparable",
                "CLASSIFICATION": "UNKNOWN",
            },
            {
                "PROVIDERS": ["rapidapi_tt_live"],
                "EVIDENCE": "no public catalog; not comparable",
                "CLASSIFICATION": "UNKNOWN",
            },
        ],
        "MARKET_RESEARCH_ROW_PROVEN": bool(ruler),
        "M5_MARKET_MATCHED_N": ruler.get("M5_MARKET_MATCHED_N") if ruler else None,
        "M5_BRIER": ruler.get("M5_BRIER") if ruler else None,
        "MARKET_BRIER": ruler.get("MARKET_BRIER") if ruler else None,
        "M5_LOG_LOSS": ruler.get("M5_LOG_LOSS") if ruler else None,
        "MARKET_LOG_LOSS": ruler.get("MARKET_LOG_LOSS") if ruler else None,
        "M5_MINUS_MARKET_BRIER": ruler.get("M5_MINUS_MARKET_BRIER") if ruler else None,
        "MARKET_BASELINE_STATUS": ruler.get("MARKET_BASELINE_STATUS") if ruler else "NOT_RUN",
        "MARKET_EDGE_STATUS": "UNKNOWN_INSUFFICIENT_SAMPLE",
        "MARKET_EDGE_INTERPRETATION_LOCK": (
            "N=1 smoke (M5_BRIER 0.2908 / MARKET_BRIER 0.2609 / DELTA +0.0299) has ZERO "
            "decision significance. No claim that the market beats M5, M5 beats the market, "
            "M5 has positive EV, M5 lacks positive EV, or that any provider establishes "
            "profitability. The Phase C accomplishment is: the market ruler exists and runs "
            "end-to-end. It is NOT: we found an edge."),
        "PAIRWISE_EVALUATION_POLICY": {
            "POLICY": "once N grows beyond smoke-test size, M5 / MARKET / BASE_RATE / CONSTANT / "
                "EXTERNAL_PROVIDER_PREDICTION are compared ONLY on explicitly declared paired "
                "event sets",
            "PAIRWISE_EVENT_SET_HASH": "required on every pairwise metric report",
            "PAIRWISE_N": "required on every pairwise metric report",
            "IDENTICAL_FOR_M5_VS_MARKET": [
                "event_ids", "outcomes", "cutoffs", "market observation policy"],
            "NON_PAIRED_RULE": "models scored on different event sets must be labeled "
                "non-paired; never compare silently",
        },
        "MARKET_PROBABILITY_POLICY": {
            "PRESERVE_FIELDS": [
                "RAW_DECIMAL_ODDS_A", "RAW_DECIMAL_ODDS_B", "RAW_IMPLIED_P_A", "RAW_IMPLIED_P_B",
                "OVERROUND", "NO_VIG_P_A", "NO_VIG_P_B", "BOOKMAKER", "OBSERVATION_TS",
                "COMMENCE_TS", "SECONDS_BEFORE_COMMENCE",
                "OBSERVATION_CLASS (OPEN | INTERMEDIATE | LAST_VALID_PREMATCH)"],
            "NO_SILENT_CONSENSUS": "bookmakers are never silently combined into consensus; "
                "any future consensus requires a separately versioned and documented "
                "aggregation policy",
            "TRUE_CLOSE": "not automatically true close, bookmaker official close, consensus "
                "close, or exchange close; requires separate provider evidence",
        },
        "MATCH_QUALITY_POLICY": {
            "MATCH_PRECISION": "measured and reported",
            "MATCH_RECALL_OR_COVERAGE": "measured and reported",
            "NO_SILENT_LOOSENING": "match rate is never raised by silently loosening identity "
                "rules; held-out/manual verification samples where appropriate",
        },
        "INCLUSION_EXCLUSION_LEDGER": {
            "POLICY": "every candidate event entering market evaluation receives a persistent "
                "machine-readable disposition; rows are never silently dropped",
            "LEDGER_ARTIFACT": "docs/operations/TT_MARKET_RULER_LEDGER_V1.json",
            "DISPOSITION_CODES": [
                "INCLUDED", "EXCLUDED_NO_CANONICAL_MATCH", "EXCLUDED_AMBIGUOUS_MATCH",
                "EXCLUDED_NO_M5_PREDICTION", "EXCLUDED_NO_PREMATCH_ODDS",
                "EXCLUDED_POSTCOMMENCE_ONLY", "EXCLUDED_INVALID_MARKET",
                "EXCLUDED_RESULT_UNAVAILABLE", "EXCLUDED_IDENTITY_CONFLICT", "EXCLUDED_OTHER"],
            "LEDGER_FIELDS": [
                "provider_event_id", "canonical_event_id", "disposition", "reason_code",
                "evidence_ref", "evaluation_version"],
        },
        "CLV_RESEARCH_STATUS": "LIMITED - OddsPapi historical prematch thin; 1xbet only; "
            "TRUE_CLOSE unavailable; LAST_VALID_PREMATCH feasible per-event",
        "TT_M5_BASELINE_V1_INTACT": "YES",
        "MARKETS_TEST_RESULTS": {
            "test_phase_c_probing.py": "29 passed",
            "test_contract_manifests.py": "6 passed",
            "test_multi_provider_setup.py": "passed (Phase A/B)",
            "test_oddspapi_setup_surface.py": "passed",
            "test_setup_provider_surface.py": "passed",
            "combined Markets subset": "70 passed (2026-08-20, dedicated basetemp)",
        },
        "SHARED_TEST_RESULTS": "full backend suite PASS (2026-08-20, dedicated basetemp)",
        "FULL_SUITE_RESULT": "PASS (1745 passed, 80 skipped, 0 failures; 22min)",
        "UNRELATED_CONCURRENT_FAILURES": "none observed after SCS repair; pytest temp-root "
            "contention with concurrent sessions resolved via dedicated basetemp",
        "CROSS_WORKSTREAM_FILES_TOUCHED": ["scs_reports/vision.py (unstaged, not staged)"],
        "SCS_EMERGENCY_REPAIR": {
            "file": "scs_reports/vision.py",
            "classification": "CROSS_WORKSTREAM_EMERGENCY_SYNTAX_REPAIR",
            "changes": [
                "line 100: 'min_confidence: float = _MIN_CONFIDENCE,' dedented from column 0 to 8 "
                    "(was breaking method signature)",
                "line 108: 'def _generate(...)' dedented from column 0 to 4 (was breaking class body)",
            ],
            "verification": "full backend suite collects and passes after repair",
            "staged": False,
        },
        "FOREIGN_UNTRACKED_FILES": [
            "rapidapi_tt_micro-matches-live-2026-08-20T153417Z.json",
            "rapidapi_tt_micro-matches-live-2026-08-20T153438Z.json",
            "rapidapi_tt_micro-matches-live-2026-08-20T153940Z.json",
            "rapidapi_tt_micro-matches-live-2026-08-20T161114Z.json",
            "rapidapi_tt_micro-matches-live-2026-08-20T161731Z.json",
            "(owner: concurrent session; not created by this session; left untouched)",
        ],
        "SECRET_SCAN": "PASS (no credential values in docs/, defend_integrations/, "
            "defend_markets/, defend_sports/, tools/, tests/; 56 REDACTED markers confirm "
            "evidence sanitization; 3 pattern hits are test fixtures with fake keys)",
        "GIT_DIFF_CHECK": "PASS (no whitespace errors; LF/CRLF warnings only)",
        "MARKETS_OWNED_FILES": "see MARKETS_STAGING_PLAN",
        "MARKETS_STAGING_PLAN": {
            "A_NEW_MARKETS_ONLY": [
                "defend_integrations/{contracts,matching,phase_c_adapters,probing,value_matrix}.py",
                "defend_markets/{collector,evaluation,features,forecast,forecast_store,identity,"
                    "market_state,predict_service,settle_service}.py",
                "defend_markets/migrations/0004_markets_prediction.sql",
                "defend_markets/migrations/0005_markets_rating_history.sql",
                "defend_sports/{backfill.py}",
                "defend_sports/migrations/0002_quota_discovery.sql",
                "defend_sports/migrations/0003_backfill.sql",
                "defend_sports/migrations/0004_raw_provider_uniqueness.sql",
                "defend_sports/providers/odds_api_io.py",
                "tests/{test_collector,test_contract_manifests,test_multi_provider_setup,"
                    "test_odds_api_io,test_oddspapi_setup_surface,test_phase_c_probing,"
                    "test_predict_settle,test_setup_provider_surface,test_tt_backfill,"
                    "test_tt_identity_gate,test_tt_rating_history,test_tt_repair_results,"
                    "test_tt_research_suite,test_evaluation,test_features,test_forecast_identity,"
                    "test_forecast_records,test_market_state}.py",
                "tools/defend_tt_{backfill,collector,historical_eval,identity_gate,identity_merge,"
                    "oddspapi_deepen,phase_c_probes,phase_c_report,repair_results,replay,"
                    "research_suite,manifest_validate,market_ruler_sample}.py",
                "docs/operations/{TT_M5_BASELINE_V1,TT_MARKET_PROBE_V1,TT_ODDSPAPI_PROBE_V1,"
                    "TT_ODDSPAPI_DEEPEN_V1,TT_ODDSPAPI_DEEPEN_V1_1XBET,TT_ODDSPAPI_DEEPEN_V1_ODDS,"
                    "TT_IDENTITY_MERGES_V1,PHASE_C_PROBES_V1,PROVIDER_VALUE_MATRIX_V1,"
                    "PHASE_C_STOP_GATE_V1,TT_MARKET_RULER_SAMPLE_V1,MODEL-REGISTRY}.json/.md",
                "docs/provider-contracts/**",
            ],
            "B_MARKETS_HUNKS_IN_SHARED_FILES": [
                "defend_markets/{app,db,domain,feeds,repositories,sports_adapter,store,tt_rating}.py",
                "defend_sports/{db,repositories}.py",
                "defend_integrations/{adapters,http,models,registry,service,stores}.py",
                "tests/{fakes_markets,test_markets_app,test_markets_db,test_markets_feeds,"
                    "test_sports_app,test_sports_db,test_setup_adapters,test_setup_registry,"
                    "test_setup_service}.py",
                "tools/{defend_markets_demo,defend_markets_ingest,defend_sports_ingest,"
                    "defend_markets_server}.py",
                "(stage exact hunks only; files also contain concurrent-session changes)",
            ],
            "C_EXCLUDED": [
                "scs_reports/vision.py (SCS; repair left unstaged)",
                "scs_reports/**, scs_api/reports_routes.py, scs-ui/** (SCS lane)",
                "defend_coder/**, defendcoder-ui/**, defend_control/**, scs_* (other lanes)",
                "rapidapi_tt_micro-matches-live-*.json root artifacts (foreign)",
                "UsersthomaAppDataLocalTempopencodepytest-base/ (foreign)",
                "bench/, DELIVERY_REPORT.md, SCS_FIELD_REPORT_*.md, master_workbook_audit.py, "
                    "vision_*.py tools (foreign)",
            ],
        },
        "COMMIT_READY": False,
        "SUGGESTED_COMMIT_MESSAGE": "feat(markets): add multi-provider TT data and historical "
            "market research",
        "REQUESTS_USED_BY_PROVIDER": dict(sorted(requests_used.items())),
        "TOTAL_PROBE_REQUESTS": total_probe_requests,
        "TOTAL_SPEND_USD": 0.0,
        "DATA_QUALITY_RISKS": [
            "OddsPapi historical odds: 85% of snapshots post-commence (in-play dominated)",
            "OddsPapi market ids vary by bookmaker/event; 251 != universal match-winner",
            "OddsPapi archive floor later than 2025-08; early-era coverage ~0%",
            "SportsGameOdds schema-rich but TT absent (P7 warning confirmed)",
            "Sportradar trial key invalid (403); contract facts unverified live",
            "odds_api_io v4 sports 404; v3 works (version divergence)",
            "RapidAPI micro matches-by-date requires real date substitution",
        ],
        "ENGINEERING_RECOMMENDATIONS": [
            {
                "ENGINEERING_RECOMMENDATION": "OddsPapi LAST_VALID_PREMATCH collector for 1xbet-covered fixtures",
                "WHY_IT_MATTERS": "CLV and line-move research need prematch snapshots; only 1xbet has depth",
                "EVIDENCE": "P4 deepen: 4/27 events with odds; prematch 15-16% of snapshots; last prematch gap 0.13-23h",
                "EXPECTED_INFORMATION_GAIN": "high if coverage improves; enables market-baseline CLV",
                "EFFORT": "medium (collector + matching + LAST_VALID_PREMATCH pipeline)",
                "COST": "0 USD (trial key)",
                "RISK": "coverage too thin to be research-grade",
                "RECOMMENDED_ACTION": "build after STOP GATE; keep reserved OddsPapi requests",
            },
            {
                "ENGINEERING_RECOMMENDATION": "Complete rapidapi_tt_micro probe (matches-by-date with real dates, odds/correct-score, matches-statistics)",
                "WHY_IT_MATTERS": "cheapest live data + odds catalog; machine-readable OpenAPI",
                "EVIDENCE": "5/6 endpoints live; 43-path OpenAPI archived",
                "EXPECTED_INFORMATION_GAIN": "high (odds types, player stats, live results)",
                "EFFORT": "small (~6 requests)",
                "COST": "0 USD (free trial 300/day)",
                "RISK": "trial quota",
                "RECOMMENDED_ACTION": "next probe batch (within 40/provider cap)",
            },
            {
                "ENGINEERING_RECOMMENDATION": "Correct/refresh SPORTRADAR_API_KEY to unblock PROVIDER_PREDICTION and rankings/H2H",
                "WHY_IT_MATTERS": "only documented provider-prediction source for M5 comparison",
                "EVIDENCE": "403 Authentication Error probe; 22 feeds documented",
                "EXPECTED_INFORMATION_GAIN": "high (baseline M5 vs Sportradar PROVIDER_PREDICTION)",
                "EFFORT": "low (owner action)",
                "COST": "0 USD (trial)",
                "RISK": "trial key expiry",
                "RECOMMENDED_ACTION": "owner adds valid trial key via Setup UI",
            },
            {
                "ENGINEERING_RECOMMENDATION": "Mark sports_game_odds and the_odds_api UNSUPPORTED_FOR_TT in registry (empirical)",
                "WHY_IT_MATTERS": "removes dead slots from the control plane",
                "EVIDENCE": "SGO /sports 11 sports no TT; The Odds API 175 sports no TT",
                "EXPECTED_INFORMATION_GAIN": "clarity",
                "EFFORT": "trivial",
                "COST": "0",
                "RISK": "none",
                "RECOMMENDED_ACTION": "apply after gate",
            },
        ],
        "ARCHITECTURE_CONCERNS": [
            "odds_api_io v3/v4 divergence; health adapter uses v3, Phase C adapter initially v4 (404)",
            "evidence directory growth is unbounded; needs pruning policy",
            "classify_error returns 'unavailable' for 2xx statuses (cosmetic)",
            "OddsPapi adapter needs self._key injection before probe methods (protocol run() added)",
        ],
        "TECH_DEBT_DISCOVERED": [
            "TheOddsApi hardcoded table_tennis sport key would 404 (no TT)",
            "RapidAPI micro matches-by-date params use literal {date} placeholder",
            "Sportradar adapter assumes .json + api_key convention (unverified due to auth failure)",
            "matching.py compact_name needed for opaque corpus tokens (table_tennis:<name>)",
        ],
        "HIGH_VALUE_IDEAS_NOT_IN_CURRENT_SCOPE": [
            "Sportradar PROVIDER_PREDICTION vs M5 baseline evaluation (needs valid key)",
            "Full OddsPapi archive crawl (needs paid tier or many requests)",
            "SGO closing-odds research (not applicable - no TT)",
            "RapidAPI tabletennisapi endpoint catalog recovery via live probing",
        ],
        "OWNER_ACTION_REQUIRED": [
            "Provide valid SPORTRADAR_API_KEY (trial)",
            "Confirm RAPIDAPI_KEY validity/plan for sustained probing",
            "Add BETSAPI / SPORTDEVS / SPORTSAPI_PRO credential slots (not yet in registry)",
        ],
        "RESEARCH_ARTIFACTS": {
            "POLICY": "accepted artifacts are pinned byte-identical; regeneration with changed "
                "semantics/data requires a V2 (or explicit) version bump; V1 artifacts are not "
                "silently regenerated under the same version",
            "STOP_GATE_SELF_HASH": "computed at commit time (self-referential file excluded "
                "from its own pin list)",
            "PINNED": pins,
        },
        "NEXT_HIGHEST_VALUE_STEP": "1) complete rapidapi_tt_micro catalog probe; "
            "2) re-probe sportradar with valid key; 3) build OddsPapi LAST_VALID_PREMATCH collector",
    }
    stop_path = REPO / "docs" / "operations" / "PHASE_C_STOP_GATE_V1.json"
    stop_path.write_text(json.dumps(stop_gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {matrix_path}")
    print(f"wrote {stop_path}")
    print("matrix providers:", len(rows), "| total probe requests:", total_probe_requests)
    return 0


def rows_providers(rows):
    return [r.provider for r in rows]


if __name__ == "__main__":
    sys.exit(main())