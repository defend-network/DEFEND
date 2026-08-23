"""Structural validation of the OpenAI-compatible tool-call message history.

The agent persists every run message (roles, tool calls, tool results) to
coder_run_messages. This module validates that a run's history is a legal
tool-call sequence: every tool response matches a preceding assistant
tool_call, ids are unique, roles are ordered, and no payload is
accidentally oversized.

Used for diagnostics (e.g. the live smoke sixth-call stall) and as a
guarantee that malformed histories are detected locally without a GPU.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
from typing import Any, Mapping
from uuid import UUID

from .runs import RunsRepository

MAX_TOOL_RESULT_CHARS = 100_000

_VALID_ROLES = frozenset({"system", "user", "assistant", "tool", "log"})

_OBSERVATION_ROLES = frozenset({"tool", "log"})


@dataclass(frozen=True)
class ToolHistoryValidation:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    assistant_messages: int = 0
    assistant_tool_calls: int = 0
    tool_responses: int = 0
    orphaned_tool_responses: int = 0
    duplicate_tool_call_ids: tuple[str, ...] = ()
    missing_tool_responses: tuple[str, ...] = ()
    role_sequence_ok: bool = True
    max_tool_result_chars: int = 0
    oversized_observations: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "assistant_messages": self.assistant_messages,
            "assistant_tool_calls": self.assistant_tool_calls,
            "tool_responses": self.tool_responses,
            "orphaned_tool_responses": self.orphaned_tool_responses,
            "duplicate_tool_call_ids": list(self.duplicate_tool_call_ids),
            "missing_tool_responses": list(self.missing_tool_responses),
            "role_sequence_ok": self.role_sequence_ok,
            "max_tool_result_chars": self.max_tool_result_chars,
            "oversized_observations": self.oversized_observations,
        }


def _role_of(message: Mapping[str, Any]) -> str:
    role = str(message.get("role") or "")
    return role.strip().lower()


def _content_of(message: Mapping[str, Any]) -> str:
    value = message.get("content")
    return value if isinstance(value, str) else ""


def _tool_call_ids(message: Mapping[str, Any]) -> list[str]:
    raw = message.get("tool_calls")
    if not isinstance(raw, list):
        # Persisted assistant rows store the full tool_calls payload in the
        # tool_arguments JSONB column (the sink passes fields["tool_calls"]).
        raw = message.get("tool_arguments")
    if isinstance(raw, list):
        ids: list[str] = []
        for call in raw:
            if isinstance(call, Mapping):
                call_id = call.get("id")
                if isinstance(call_id, str) and call_id:
                    ids.append(call_id)
        return ids
    return []


def _arguments_are_valid(message: Mapping[str, Any]) -> bool:
    raw = message.get("tool_arguments")
    if raw is None:
        return True
    if isinstance(raw, (dict, list)):
        return True
    if isinstance(raw, str):
        try:
            json.loads(raw)
        except ValueError:
            return False
        return True
    return False


def validate_tool_history(messages: Sequence[Mapping[str, Any]]) -> ToolHistoryValidation:
    """Validate an ordered message sequence against tool-call invariants."""
    errors: list[str] = []
    warnings: list[str] = []
    assistant_tool_calls = 0
    tool_responses = 0
    orphaned = 0
    oversized = 0
    max_result_chars = 0
    assistant_messages = 0
    role_sequence_ok = True

    declared_ids: list[str] = []
    id_counter: Counter[str] = Counter()
    open_ids: set[str] = set()
    responded_ids: set[str] = set()

    for index, message in enumerate(messages):
        role = _role_of(message)
        if role not in _VALID_ROLES:
            errors.append(
                f"message[{index}] has invalid role {role!r} "
                f"(expected one of {sorted(_VALID_ROLES)})"
            )
            role_sequence_ok = False
            continue

        if role == "assistant":
            assistant_messages += 1
            ids = _tool_call_ids(message)
            for call_id in ids:
                assistant_tool_calls += 1
                id_counter[call_id] += 1
                if id_counter[call_id] > 1:
                    errors.append(
                        f"assistant message[{index}] repeats tool_call_id "
                        f"{call_id!r}"
                    )
                    role_sequence_ok = False
                declared_ids.append(call_id)
                open_ids.add(call_id)
            if ids and not _arguments_are_valid(message):
                errors.append(
                    f"assistant message[{index}] has malformed tool arguments"
                )
                role_sequence_ok = False
        elif role == "tool":
            tool_responses += 1
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or not call_id:
                errors.append(
                    f"tool message[{index}] is missing tool_call_id"
                )
                orphaned += 1
                role_sequence_ok = False
                continue
            if call_id in responded_ids or call_id not in declared_ids:
                errors.append(
                    f"tool message[{index}] has no matching open assistant "
                    f"tool_call {call_id!r}"
                )
                orphaned += 1
                role_sequence_ok = False
                continue
            open_ids.discard(call_id)
            responded_ids.add(call_id)
            result = _content_of(message) or str(message.get("tool_result") or "")
            max_result_chars = max(max_result_chars, len(result))
            if len(result) > MAX_TOOL_RESULT_CHARS:
                oversized += 1
                warnings.append(
                    f"tool message[{index}] payload is {len(result)} chars "
                    f"(> {MAX_TOOL_RESULT_CHARS})"
                )
        elif role in _OBSERVATION_ROLES:
            content = _content_of(message)
            max_result_chars = max(max_result_chars, len(content))
            if len(content) > MAX_TOOL_RESULT_CHARS:
                oversized += 1
                warnings.append(
                    f"{role} message[{index}] payload is {len(content)} chars "
                    f"(> {MAX_TOOL_RESULT_CHARS})"
                )
        prior_role = role

    missing = [call_id for call_id in open_ids if call_id not in responded_ids]
    if missing:
        for call_id in missing:
            errors.append(
                f"assistant tool_call {call_id!r} has no matching tool response"
            )
        role_sequence_ok = False

    duplicates = tuple(
        call_id for call_id, count in id_counter.items() if count > 1
    )
    valid = not errors and role_sequence_ok
    return ToolHistoryValidation(
        valid=valid,
        errors=tuple(errors),
        warnings=tuple(warnings),
        assistant_messages=assistant_messages,
        assistant_tool_calls=assistant_tool_calls,
        tool_responses=tool_responses,
        orphaned_tool_responses=orphaned,
        duplicate_tool_call_ids=duplicates,
        missing_tool_responses=tuple(missing),
        role_sequence_ok=role_sequence_ok,
        max_tool_result_chars=max_result_chars,
        oversized_observations=oversized,
    )


def validate_persisted_run(
    repository: RunsRepository, run_id: UUID | str
) -> ToolHistoryValidation:
    """Load a persisted run's messages and validate them."""
    parsed = run_id if isinstance(run_id, UUID) else UUID(str(run_id))
    records = repository.messages_for_run(parsed)
    messages = [
        {
            "role": record.role,
            "content": record.content,
            "tool_call_id": record.tool_call_id,
            "tool_name": record.tool_name,
            "tool_arguments": record.tool_arguments,
            "tool_result": record.tool_result,
            "kind": record.kind,
            "ok": record.ok,
        }
        for record in records
    ]
    return validate_tool_history(messages)