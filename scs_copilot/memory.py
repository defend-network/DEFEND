"""Structured job conversation memory (M1.4, P8, P68, P44).

Per-job memory of readings (as-found/intermediate/final, timestamped, no
overwrite), answered questions, active procedures and diagnostic states, and
follow-up context so the agent never re-asks for the same reading.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


class JobConversationMemory:
    def __init__(self) -> None:
        self.turns: list[dict[str, Any]] = []
        self.readings: dict[str, list[dict[str, Any]]] = {}
        self.answered_questions: list[str] = []
        self.active_graphs: dict[str, Any] = {}

    def record_turn(self, question: str, answer: dict[str, Any],
                    answer_id: str | None = None) -> None:
        self.turns.append({"question": question, "answer_id": answer_id,
                           "created_at": datetime.now().isoformat(timespec="seconds")})

    def record_reading(self, key: str, value: Any, source: str = "field",
                       stage: str = "FIELD") -> None:
        """Store a reading with timestamp; never overwrite prior values."""
        self.readings.setdefault(key, []).append({
            "value": value, "source": source, "stage": stage,
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
        })

    def latest_reading(self, key: str) -> Any | None:
        entries = self.readings.get(key)
        return entries[-1]["value"] if entries else None

    def context_packet(self) -> dict[str, Any]:
        return {
            "readings": {k: [e for e in v] for k, v in self.readings.items()},
            "answered_questions": list(self.answered_questions[-5:]),
            "active_graphs": list(self.active_graphs),
        }
