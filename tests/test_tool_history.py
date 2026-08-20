"""Tests for defend_coder.tool_history structural validation."""

import pytest

from defend_coder.tool_history import (
    MAX_TOOL_RESULT_CHARS,
    validate_tool_history,
)


def _assistant(call_ids=(), content="ok"):
    message = {"role": "assistant", "content": content}
    if call_ids:
        message["tool_calls"] = [
            {"id": call_id, "type": "function",
             "function": {"name": "list_files", "arguments": "{}"}}
            for call_id in call_ids
        ]
    return message


def _tool(call_id, content="result"):
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": content,
        "tool_name": "list_files",
        "tool_result": content,
        "kind": "file",
        "ok": True,
    }


def _history(*messages):
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "prompt"},
        *messages,
    ]


def test_valid_tool_history_is_valid():
    result = validate_tool_history(
        _history(
            _assistant(["call_1"]),
            _tool("call_1", "listing"),
            _assistant(["call_2", "call_3"]),
            _tool("call_2", "out"),
            _tool("call_3", "out"),
            _assistant(content="done"),
        )
    )

    assert result.valid is True
    assert result.errors == ()
    assert result.assistant_tool_calls == 3
    assert result.tool_responses == 3
    assert result.role_sequence_ok is True


def test_orphaned_tool_response_is_rejected():
    result = validate_tool_history(
        _history(
            _assistant(["call_1"]),
            _tool("call_1"),
            _tool("call_ghost", "no matching assistant call"),
        )
    )

    assert result.valid is False
    assert result.orphaned_tool_responses == 1
    assert any("call_ghost" in error for error in result.errors)


def test_duplicate_tool_call_ids_are_rejected():
    result = validate_tool_history(
        _history(
            _assistant(["call_1"]),
            _tool("call_1"),
            _assistant(["call_1"]),
            _tool("call_1"),
        )
    )

    assert result.valid is False
    assert "call_1" in result.duplicate_tool_call_ids
    assert any("repeats tool_call_id" in error for error in result.errors)


def test_missing_tool_response_is_rejected():
    result = validate_tool_history(
        _history(
            _assistant(["call_1", "call_2"]),
            _tool("call_1"),
            _assistant(content="done"),
        )
    )

    assert result.valid is False
    assert result.missing_tool_responses == ("call_2",)
    assert any("no matching tool response" in error for error in result.errors)


def test_tool_response_without_id_is_rejected():
    result = validate_tool_history(
        _history(
            _assistant(["call_1"]),
            {"role": "tool", "content": "no id"},
        )
    )

    assert result.valid is False
    assert any("missing tool_call_id" in error for error in result.errors)


def test_invalid_role_is_rejected():
    result = validate_tool_history(
        [
            {"role": "system", "content": "sys"},
            {"role": "martian", "content": "hello"},
        ]
    )

    assert result.valid is False
    assert any("invalid role" in error for error in result.errors)


def test_malformed_tool_arguments_are_rejected():
    result = validate_tool_history(
        _history(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "x", "arguments": "{"}}
                ],
                "tool_arguments": "{",
            },
            _tool("call_1"),
        )
    )

    assert result.valid is False
    assert any("malformed tool arguments" in error for error in result.errors)


def test_oversized_observation_is_warned_not_fatal():
    result = validate_tool_history(
        _history(
            _assistant(["call_1"]),
            _tool("call_1", "x" * (MAX_TOOL_RESULT_CHARS + 10)),
        )
    )

    assert result.valid is True
    assert result.oversized_observations == 1
    assert any("payload is" in warning for warning in result.warnings)


def test_empty_history_is_valid():
    result = validate_tool_history([])

    assert result.valid is True
    assert result.assistant_messages == 0