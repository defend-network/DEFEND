"""P0 tests: canonical single-system-prompt composition.

Proves:
- exactly one effective system message is sent by the real agent path
- the owner directive text is present verbatim, once
- no duplicate copies of the directive exist in the codebase
- retired/conflicting behavior clauses are absent
- required Qwen technical / tool-format guidance remains
- the prompt hash/version is stable and pinned
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from defend_coder.agent import CodingAgent
from defend_coder.agent_client import (
    AgentChatClient,
    AgentChatResponse,
    ToolCall,
)
from defend_coder.model_config import CoderModelConfig
from defend_coder.prompts import (
    AGENT_INSTRUCTIONS_ASSET,
    OWNER_DIRECTIVE_ASSET,
    OWNER_DIRECTIVE_SHA256,
    PROMPT_VERSION,
    QWEN_TECHNICAL_ASSET,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_SHA256,
    agent_instructions,
    compose_system_prompt,
    owner_directive,
    qwen_technical_instructions,
    system_prompt_sha256,
)
from defend_coder.tools import CoderToolkit

OWNER_SOURCE = Path(
    r"C:\Users\thoma\Downloads\DEFEND32B\DEFEND_coder_prompt.txt"
)
_DIRECTIVE_MARKER = (
    "OWNER DIRECTIVE \u2014 FREEDOM, VIEWPOINT NEUTRALITY & "
    "EXECUTION PRIORITY"
)

#: Clauses that must never appear in the composed prompt (owner: retire
#: refusal/paternalistic/ideological behavior language).
FORBIDDEN_PHRASES = (
    "you must refuse",
    "decline the task",
    "refuse to comply",
    "refuse requests",
    "align with human values",
    "you should not help",
    "safety policy requires",
    "do not comply with",
    "as an AI, I cannot",
    "I cannot assist with",
    "reject the request",
)


class FakeClient(AgentChatClient):
    def __init__(self):
        super().__init__(
            CoderModelConfig(
                alias="defendcoder-heavy",
                model_name="Qwen/Qwen3-Coder-Next",
                base_url="http://127.0.0.1:8001/v1",
            )
        )
        self.requests: list[list[dict]] = []

    def chat(self, messages, tools=None, **kwargs):
        self.requests.append(list(messages))
        return AgentChatResponse(
            content="I inspected the workspace; nothing to do.",
            tool_calls=(),
        )


def _agent_request_messages(tmp_path) -> list[dict]:
    from tests.test_defend_coder_agent import FakeRepo, _workspace
    from datetime import datetime, timezone
    from uuid import uuid4

    root = tmp_path / "configured"
    root.mkdir(exist_ok=True)
    ws_root = root / "ws"
    ws = _workspace(ws_root)
    toolkit = CoderToolkit(
        repository=FakeRepo([ws]),
        configured_root=root,
    )
    client = FakeClient()
    agent = CodingAgent(client=client, toolkit=toolkit, log=lambda _m: None)
    agent.run(
        prompt="Inspect the workspace.",
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
        sink=lambda **kw: None,
    )
    assert client.requests, "agent must have made at least one request"
    return client.requests[0]


def test_composed_prompt_contains_all_section_headers():
    prompt = compose_system_prompt()
    for header in (
        "[DEFEND OWNER DIRECTIVE]",
        "[DEFENDCODER ROLE / MISSION]",
        "[ENGINEERING QUALITY RULES]",
        "[AGENT LOOP / TOOL USAGE]",
        "[SECURITY / AUTHORIZATION / RISK HANDLING]",
        "[MODEL-SPECIFIC TECHNICAL INSTRUCTIONS]",
        "[OUTPUT / TOOL-CALL FORMAT]",
    ):
        assert header in prompt


def test_exactly_one_system_message_is_sent(tmp_path):
    messages = _agent_request_messages(tmp_path)
    system_messages = [
        message
        for message in messages
        if message.get("role") == "system"
    ]
    assert len(system_messages) == 1
    assert system_messages[0]["content"] == compose_system_prompt()


def test_owner_directive_present_verbatim_and_once():
    prompt = compose_system_prompt()
    directive = owner_directive()
    assert _DIRECTIVE_MARKER in prompt
    assert prompt.count(_DIRECTIVE_MARKER) == 1
    assert directive in prompt
    assert prompt.count(directive) == 1


def test_owner_directive_present_in_agent_request(tmp_path):
    messages = _agent_request_messages(tmp_path)
    system_message = next(
        message
        for message in messages
        if message.get("role") == "system"
    )
    assert _DIRECTIVE_MARKER in system_message["content"]


def test_owner_source_file_preserved_byte_identical():
    if not OWNER_SOURCE.is_file():
        pytest.skip("owner source file not present on this machine")
    source_bytes = OWNER_SOURCE.read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest() == OWNER_DIRECTIVE_SHA256
    asset = (
        Path(__file__).parent.parent / "defend_coder" / "prompts"
        / OWNER_DIRECTIVE_ASSET
    )
    assert asset.read_bytes() == source_bytes


def test_owner_directive_pinned_hash_matches_asset():
    asset = (
        Path(__file__).parent.parent / "defend_coder" / "prompts"
        / OWNER_DIRECTIVE_ASSET
    )
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == (
        OWNER_DIRECTIVE_SHA256
    )


def test_no_duplicate_copies_of_directive_in_package():
    package = Path(__file__).parent.parent / "defend_coder"
    marker = "VIEWPOINT NEUTRALITY & EXECUTION PRIORITY"
    hits: list[str] = []
    for path in package.rglob("*"):
        if path.is_file() and path.suffix in (".txt", ".py", ".md"):
            if marker in path.read_text(encoding="utf-8", errors="replace"):
                hits.append(str(path))
    assert hits == [
        str(package / "prompts" / OWNER_DIRECTIVE_ASSET)
    ], hits


def test_forbidden_behavior_clauses_absent():
    prompt = compose_system_prompt()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase.lower() not in prompt.lower(), phrase


def test_qwen_technical_guidance_preserved():
    prompt = compose_system_prompt()
    for marker in (
        "Qwen3-Coder-Next",
        "Qwen3CoderToolParser",
        "tool_calls",
        "arguments",
        "function",
    ):
        assert marker in prompt, marker


def test_tool_format_guidance_preserved():
    prompt = compose_system_prompt()
    for marker in (
        "edit_file",
        "write_file",
        "old_text",
        "new_text",
        "relative to the workspace root",
        "exactly as it appears in the file",
    ):
        assert marker in prompt, marker
    assert "edit_file" in qwen_technical_instructions()
    assert "write_file" in qwen_technical_instructions()


def test_prompt_hash_is_stable_and_pinned():
    assert compose_system_prompt() == SYSTEM_PROMPT
    assert system_prompt_sha256() == SYSTEM_PROMPT_SHA256
    assert SYSTEM_PROMPT_SHA256 == _PINNED_SYSTEM_PROMPT_SHA256


#: Pinned after the first successful composition; update only when the
#: prompt content intentionally changes (see delivery report).
_PINNED_SYSTEM_PROMPT_SHA256 = (
    "3a970bc7f1726732ffd40b64e96159fbbba339b29beb79860efe16e220098474"
)


def test_prompt_version_is_recorded():
    assert PROMPT_VERSION
    assert PROMPT_VERSION.count(".") >= 1


def test_assets_exist_and_are_the_only_sources():
    prompts_dir = Path(__file__).parent.parent / "defend_coder" / "prompts"
    assets = sorted(path.name for path in prompts_dir.iterdir() if path.is_file())
    assert assets == sorted(
        [OWNER_DIRECTIVE_ASSET, AGENT_INSTRUCTIONS_ASSET, QWEN_TECHNICAL_ASSET]
    ), assets
    assert agent_instructions()
    assert qwen_technical_instructions()


def test_agent_instructions_are_engineering_only():
    text = agent_instructions().lower()
    for phrase in ("refuse", "ideolog", "moral", "politic"):
        assert phrase not in text, phrase


def test_system_message_count_constant_is_one():
    prompt = compose_system_prompt()
    assert len(
        [line for line in prompt.splitlines() if line.startswith("[") and line.endswith("]")]
    ) >= 7
