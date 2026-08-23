"""DB-backed persistent scheduler with lease-based leadership.

Jobs are claimed atomically (single leader), executed, and rescheduled
forward. Missed jobs run at most one catch-up per job then schedule forward,
so a long shutdown never produces a catch-up storm. All timestamps are UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SchedulerJob:
    job_name: str
    schedule_interval_seconds: int
    enabled: bool = True

    def initial_next_run(self) -> str:
        return utc_now_iso()


class Scheduler:
    """Lease-based scheduler over the quant store."""

    def __init__(
        self,
        store: Any,
        *,
        owner: str,
        lease_seconds: int = 120,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._owner = owner
        self._lease_seconds = lease_seconds
        self._clock = clock or utc_now

    def register(self, job: SchedulerJob) -> None:
        existing = self._store.job(job.job_name)
        next_run = existing["next_run_at"] if existing and existing.get("next_run_at") else job.initial_next_run()
        self._store.upsert_job(
            {
                "job_name": job.job_name,
                "enabled": job.enabled,
                "schedule_interval_seconds": job.schedule_interval_seconds,
                "next_run_at": next_run,
            }
        )

    def claim(self, job_name: str) -> dict[str, Any] | None:
        return self._store.claim_job(job_name, self._owner, self._lease_seconds, now=self._clock())

    def complete(self, job_name: str, *, summary: str, state_hash: str | None = None) -> None:
        job = self._store.job(job_name)
        interval = int(job["schedule_interval_seconds"]) if job else 86400
        next_run = (self._clock() + timedelta(seconds=interval)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self._store.complete_job(job_name, summary=summary, state_hash=state_hash, next_run_at=next_run)

    def fail(self, job_name: str, *, error: str) -> None:
        self._store.fail_job(job_name, error=error)

    def run_due(self, job_name: str, *, handler: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        claimed = self.claim(job_name)
        if claimed is None:
            return {"ran": False, "reason": "not due or lease held by another leader"}
        try:
            result = handler()
        except Exception as error:  # noqa: BLE001 - surfaced as FAILED job state
            self.fail(job_name, error=f"{type(error).__name__}: {error}")
            return {"ran": False, "reason": "handler failed", "error": str(error)}
        self.complete(job_name, summary=result.get("summary", ""), state_hash=result.get("state_hash"))
        return {"ran": True, "result": result}

    def status(self, job_name: str) -> dict[str, Any] | None:
        return self._store.job(job_name)
