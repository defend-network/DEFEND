"""DEFENDmarkets benchmark demo (Demo A-E).

Runs against the real provisioned database and real external providers.
Every number printed is a real value; anything not available is stated
honestly.

    Demo A  Provider matrix: feed status, records ingested, latency.
    Demo B  One real TT matchup through the full decision pipeline.
    Demo C  Journal: latest decision record with thesis and model fields.
    Demo D  Disciplined abstention: tt_elo_arb without model history.
    Demo E  TT activation (after THE_ODDS_API_KEY): feeds, fixture,
            implied P, model P, edge, journal, deliberate abstention.

Usage:
    python tools/defend_markets_demo.py --demo a
    python tools/defend_markets_demo.py --demo e
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from defend_markets.config import MarketsSettings
from defend_markets.db import MarketsDatabase
from defend_markets.feeds import FeedService, build_default_feed_providers, odds_api_key, participant_key
from defend_markets.models import build_default_models, build_default_reasoners
from defend_markets.pipeline import DecisionPipeline
from defend_markets.repositories import MarketsRepository
from defend_markets.store import PostgresMarketsStore
from defend_markets.strategies import build_default_registry


def _dependencies():
    settings = MarketsSettings.from_env()
    database = MarketsDatabase(settings.database_url)
    database.migrate()
    with database.connect() as connection:
        with connection.transaction():
            MarketsRepository().seed_defaults(connection)
    store = PostgresMarketsStore(database, MarketsRepository())
    return settings, database, store


def demo_a(store: PostgresMarketsStore) -> None:
    print("=" * 72)
    print("DEMO A - Provider matrix (live probes + persisted records)")
    print("=" * 72)
    service = FeedService(store, build_default_feed_providers())
    results = service.poll_all()
    print(f"{'provider':24s} {'status':12s} {'records':>8s} {'tt':>4s} {'latency':>8s} error")
    for result in results.values():
        print(
            f"{result.provider_id:24s} {result.status:12s} "
            f"{result.record_count:8d} {len(result.tt_results):4d} "
            f"{(str(result.latency_ms) + 'ms') if result.latency_ms is not None else '-':>8s} "
            f"{result.error or '-'}"
        )
    counts = store.counts()
    print(f"\npersisted: provider_feeds={counts.get('provider_feeds')} "
          f"records={counts.get('market_feed_records')} "
          f"tt_results={counts.get('tt_match_results')}")


def demo_b(database: MarketsDatabase, store: PostgresMarketsStore) -> None:
    print("=" * 72)
    print("DEMO B - One real TT matchup through the decision pipeline")
    print("=" * 72)
    sports_url = os.environ.get("SPORTS_DATABASE_URL", "").strip()
    if not sports_url:
        print("no SPORTS_DATABASE_URL configured; the odds source is not attached.")
        print("without a live odds source the pipeline has NO_ELIGIBLE_DATA (honest).")
        return
    from defend_markets.journal import DecisionJournal
    from defend_markets.sports_adapter import PostgresSportsDataReader
    from defend_sports.db import SportsDatabase

    reader = PostgresSportsDataReader(SportsDatabase(sports_url))
    journal = DecisionJournal(database, MarketsRepository())
    events = reader.tt_events()
    if not events:
        print("the sports database holds no table-tennis events right now.")
        print("pipeline outcome below is for tt-live-001 (absent -> NO_ELIGIBLE_DATA).")
        event_key = "tt-live-001"
    else:
        event_key = str(events[0]["event_key"])
        print(f"using first real event: {event_key}")
    pipeline = DecisionPipeline(
        reader=reader,
        registry=build_default_registry(),
        store=store,
        journal=journal,
        models=build_default_models(),
        reasoners=build_default_reasoners(),
    )
    outcome = pipeline.evaluate_sports(
        event_key=event_key,
        market_key="match_winner",
        strategy_key="tt_elo_arb",
    )
    decision = outcome.decision
    print(f"decision_type={decision.decision_type.value}")
    print(f"reason_codes={[code.value for code in decision.reason_codes]}")
    print(f"model_version={decision.model_version}")
    print(f"model_probability={decision.model_probability}")
    print(f"thesis={decision.thesis}")
    print("(the evaluation was journaled to market_decisions, visible in Demo C)")


def demo_c(database: MarketsDatabase, store: PostgresMarketsStore) -> None:
    print("=" * 72)
    print("DEMO C - Journal (latest persisted decision records)")
    print("=" * 72)
    decisions = store.catalog_decisions(limit=5)
    if not decisions:
        print("no decision records persisted yet (run the pipeline via the server).")
        return
    for decision in decisions:
        print(f"- {decision.get('decision_type')} {decision.get('strategy_key')} "
              f"edge={decision.get('estimated_edge')} "
              f"model={decision.get('model_version')} "
              f"p={decision.get('model_probability')} "
              f"thesis={(decision.get('thesis') or '')[:110]}")


def demo_d(store: PostgresMarketsStore) -> None:
    print("=" * 72)
    print("DEMO D - Disciplined abstention (tt_elo_arb model gate)")
    print("=" * 72)
    history = store.catalog_tt_results()
    print(f"persisted tt_match_results: {len(history)}")
    if len(history) < 2:
        print("insufficient history: the gate MUST abstain with "
              "INSUFFICIENT_MODEL_HISTORY - that abstention is the demo.")
        print("(inject real results via the_odds_api_tt feed with THE_ODDS_API_KEY set)")
        return
    from defend_markets.tt_rating import TTEloModel

    model = TTEloModel.from_history_rows(history)
    names = sorted(model.profiles())
    if len(names) < 2:
        print("only one rated player; gate abstains.")
        return
    evaluation = model.evaluate(names[0], names[1])
    print(f"players: {names[0]} ({evaluation.home_games} games) vs "
          f"{names[1]} ({evaluation.away_games} games)")
    print(f"model available={evaluation.available}")
    print(f"p_home={evaluation.p_home} calibration_bucket={evaluation.calibration_bucket}")
    if evaluation.available:
        print("gate PASSES: an OPPORTUNITY is possible once an arb edge exists.")
    else:
        print(f"gate ABSTAINS: {evaluation.reason}")


def demo_e(database: MarketsDatabase, store: PostgresMarketsStore) -> None:
    print("=" * 72)
    print("DEMO E - TT activation: feeds, fixture, implied P, model P, edge, journal")
    print("=" * 72)
    api_key = odds_api_key()
    if not api_key:
        print("the_odds_api UNCONFIGURED missing THE_ODDS_API_KEY")
        print("enter it in Setup & Integrations -> The Odds API -> THE_ODDS_API_KEY")
        print("(or set the THE_ODDS_API_KEY environment variable) then re-run --demo e.")
        return

    results = FeedService(store, build_default_feed_providers()).poll("the_odds_api_tt")
    print(f"results feed: {results.status} records={results.record_count} "
          f"tt_results={len(results.tt_results)} error={results.error or '-'}")

    sports_url = os.environ.get("SPORTS_DATABASE_URL", "").strip()
    if not sports_url:
        print("odds feed: SPORTS_DATABASE_URL not configured; skipping the odds side.")
        print("results above still persist tt_match_results for the Elo model.")
        return
    from defend_sports.db import SportsDatabase
    from defend_sports.ingestion import IngestionService
    from defend_sports.providers.the_odds_api import (
        OddsApiProviderError,
        TheOddsApiSportsProvider,
    )

    sports_db = SportsDatabase(sports_url)
    sports_db.migrate()
    try:
        batch = TheOddsApiSportsProvider(api_key=api_key).poll()
    except OddsApiProviderError as error:
        print(f"odds feed: UNAVAILABLE {error.detail}")
        return
    if not batch.raw_events:
        print("odds feed: HEALTHY but no live table-tennis events right now")
    else:
        ingested = IngestionService(sports_db).ingest(batch)
        print(f"odds feed: {ingested.health} events={ingested.events} "
              f"odds={ingested.odds_snapshots} live={ingested.live_observations}")

    from defend_markets.journal import DecisionJournal
    from defend_markets.sports_adapter import PostgresSportsDataReader
    from defend_markets.tt_rating import TTEloModel

    reader = PostgresSportsDataReader(sports_db)
    events = reader.tt_events()
    if not events:
        print("no table-tennis events persisted; the odds side reported above.")
        return
    event = events[0]
    event_key = str(event["event_key"])
    print(f"\nfixture: {event.get('display_name')} ({event_key}) "
          f"league={event.get('league_key')}")
    quotes = reader.latest_odds(event_key, "match_winner")
    if not quotes:
        print("  quotes: none persisted for this fixture yet")
        return
    implied_rows = []
    for quote in quotes:
        decimal = quote.decimal_odds
        if decimal is None or decimal <= 0:
            continue
        implied = 1 / decimal
        implied_rows.append((quote.selection_key, decimal, implied))
        print(f"  {quote.selection_key:8s} decimal={decimal} implied_p={implied:.4f}")
    print(f"  market implied sum (overround): {sum(row[2] for row in implied_rows):.4f}")
    print(f"  gross arbitrage edge: {1 - sum(row[2] for row in implied_rows):.4f}")

    history = store.catalog_tt_results()
    print(f"\nmodel history: tt_match_results={len(history)}")
    model = TTEloModel.from_history_rows(history)
    try:
        names = reader.tt_event_participants(event_key)
    except AttributeError:
        names = []
    league = str(event.get("league_key") or "table_tennis")
    if len(names) >= 2:
        home_key = participant_key(league, names[0])
        away_key = participant_key(league, names[1])
    else:
        home_key = implied_rows[0][0] if implied_rows else None
        away_key = implied_rows[1][0] if len(implied_rows) > 1 else None
    print(f"  evaluating model on: {home_key} vs {away_key}")
    evaluation = model.evaluate(home_key, away_key) if home_key and away_key else None
    if evaluation is not None:
        print(f"  model available={evaluation.available}")
        print(f"  model P home={evaluation.p_home} games {evaluation.home_games} vs {evaluation.away_games}")
        if evaluation.available:
            print(f"  calibration_bucket={evaluation.calibration_bucket}")
        else:
            print(f"  model ABSTAINS: {evaluation.reason} (deliberate abstention)")

    pipeline = DecisionPipeline(
        reader=reader,
        registry=build_default_registry(),
        store=store,
        journal=DecisionJournal(database, MarketsRepository()),
        models=build_default_models(),
        reasoners=build_default_reasoners(),
    )
    outcome = pipeline.evaluate_sports(
        event_key=event_key,
        market_key="match_winner",
        strategy_key="tt_elo_arb",
    )
    decision = outcome.decision
    strategy = outcome.strategy
    print(f"\ndecision_type={decision.decision_type.value}")
    print(f"reason_codes={[code.value for code in decision.reason_codes]}")
    print(f"gross_edge={strategy.gross_edge if strategy else None} "
          f"cost={strategy.costs.total() if strategy else None}")
    print(f"model_version={decision.model_version} model_probability={decision.model_probability}")
    print(f"thesis={decision.thesis}")
    print("(the decision was journaled to market_decisions, visible in Demo C)")


def main() -> None:
    parser = argparse.ArgumentParser(description="DEFENDmarkets benchmark demo")
    parser.add_argument("--demo", action="append", choices=("a", "b", "c", "d", "e"), required=True)
    args = parser.parse_args()

    settings, database, store = _dependencies()
    print(f"database={settings.database_url.split('@')[-1]}")
    for demo in sorted(set(args.demo)):
        if demo == "a":
            demo_a(store)
        elif demo == "b":
            demo_b(database, store)
        elif demo == "c":
            demo_c(database, store)
        elif demo == "d":
            demo_d(store)
        elif demo == "e":
            demo_e(database, store)


if __name__ == "__main__":
    main()