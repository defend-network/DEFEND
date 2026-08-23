"""M4.8 resumable low-priority OddsPapi historical backfill (P16).

A checkpointed job that discovers historical TT windows, ingests fixtures and
results, and (when proven) historical odds snapshots. It resumes from the last
checkpoint, never restarts from the beginning, and never starves live/current
work — the HISTORICAL_BACKFILL job is lower priority than LIVE_ODDS,
CURRENT_EVENT, RESULT and RESULT_RECONCILIATION.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

BACKFILL_POLICY_VERSION = "HISTORICAL_BACKFILL_V1"

TASK_FIXTURES = "fixtures"
TASK_RESULTS = "results"
TASK_ODDS = "historical_odds"

# historical odds capability classification (P15)
HISTORICAL_ODDS_AVAILABLE = "HISTORICAL_ODDS_AVAILABLE"
HISTORICAL_ODDS_ENDPOINT_AVAILABLE_BUT_EMPTY = "HISTORICAL_ODDS_ENDPOINT_AVAILABLE_BUT_EMPTY"
PLAN_RESTRICTED = "PLAN_RESTRICTED"
UNSUPPORTED = "UNSUPPORTED"


class HistoricalBackfillJob:
    """Resumable historical backfill with explicit checkpoints (P16)."""

    def __init__(self, store: Any, *, provider: str = "oddspapi") -> None:
        self._store = store
        self._provider = provider

    def checkpoint(self, task: str) -> dict[str, Any] | None:
        return self._store.get_backfill_checkpoint(self._provider, task)

    def advance_checkpoint(self, task: str, cursor_value: str) -> None:
        self._store.upsert_backfill_checkpoint(self._provider, task, cursor_value=cursor_value, state="RUNNING")

    def run(self, *, ingest_fixtures: Any = None, ingest_results: Any = None,
            ingest_odds: Any = None, window_days: int = 7) -> dict[str, Any]:
        """Run one bounded backfill cycle, resuming from checkpoints.

        ``ingest_*`` are callables(provider, from_iso, to_iso) that return a
        sanitized summary. Only implemented capabilities are invoked. A cycle
        never restarts from the beginning: each task resumes at its own
        checkpoint cursor.
        """
        now = datetime.now(timezone.utc)
        out: dict[str, Any] = {}
        for task, ingest in ((TASK_FIXTURES, ingest_fixtures), (TASK_RESULTS, ingest_results), (TASK_ODDS, ingest_odds)):
            if ingest is None:
                continue
            checkpoint = self.checkpoint(task)
            cursor = checkpoint.get("cursor_value") if checkpoint else None
            # resume from checkpoint (or default to a bounded recent window)
            if cursor:
                from_iso = cursor
            else:
                from_iso = (now - timedelta(days=window_days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            to_iso = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            try:
                summary = ingest(self._provider, from_iso, to_iso)
            except Exception as error:  # noqa: BLE001
                out[task] = {"error": f"{type(error).__name__}: {error}"}
                continue
            # advance checkpoint to the end of this window (resumable)
            self.advance_checkpoint(task, to_iso)
            out[task] = summary
        return out
