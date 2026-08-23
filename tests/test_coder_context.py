"""DEFENDcoder context engine + checkpoint compaction tests (P19/P20)."""

from __future__ import annotations

import json

import pytest

from defend_coder.context import (
    RunContext,
    TaskCheckpoint,
    build_checkpoint,
    checkpoint_to_prompt,
    compact_run_context,
    compose_checkpoint_context,
)
from defend_coder.identity import compose_system_instructions, default_identity_profile


class TestCheckpoint:
    def test_requires_objective(self):
        with pytest.raises(ValueError, match="objective"):
            build_checkpoint(objective=" ", workspace="repo")

    def test_attempts_must_be_non_negative(self):
        with pytest.raises(ValueError, match="attempts"):
            build_checkpoint(
                objective="fix", workspace="repo", attempts=-1
            )

    def test_full_checkpoint_round_trips(self):
        checkpoint = build_checkpoint(
            objective="Add login flow",
            workspace="defend",
            current_task="write auth tests",
            completed=("scaffold",),
            current_failure="test_login_flow failing",
            relevant_files=("auth.py", "test_auth.py"),
            latest_tests=("test_login_flow",),
            attempts=2,
            constraints=("no new deps",),
            next_action="fix auth.py",
            branch="feature/login",
            head="abc1234",
            dirty_files=("auth.py",),
            identity_version="1",
            model_route="deepseek-v4-flash",
            pending_approvals=("escalation:Next",),
        )
        public = json.loads(json.dumps(checkpoint.as_public_dict()))
        assert public["objective"] == "Add login flow"
        assert public["attempts"] == 2
        assert public["branch"] == "feature/login"
        assert public["model_route"] == "deepseek-v4-flash"

    def test_checkpoint_prompt_stable_order_and_fields(self):
        checkpoint = build_checkpoint(
            objective="O",
            workspace="W",
            current_task="T",
            completed=("done",),
            current_failure="F",
            relevant_files=("a.py",),
            latest_tests=("t1",),
            attempts=1,
            constraints=("c",),
            next_action="N",
            branch="b",
            head="h",
            dirty_files=("d",),
            identity_version="1",
            model_route="deepseek-v4-flash",
            pending_approvals=("p",),
        )
        text = checkpoint_to_prompt(checkpoint)
        order = [text.index(f"{field}:") for field in
                 ("OBJECTIVE", "WORKSPACE", "CURRENT_TASK", "COMPLETED",
                  "CURRENT_FAILURE", "RELEVANT_FILES", "LATEST_TESTS",
                  "ATTEMPTS", "CONSTRAINTS", "NEXT_ACTION", "BRANCH", "HEAD",
                  "DIRTY_FILES", "IDENTITY_VERSION", "MODEL_ROUTE",
                  "PENDING_APPROVALS")]
        assert order == sorted(order)

    def test_checkpoint_never_contains_reasoning_or_secrets(self):
        checkpoint = build_checkpoint(
            objective="fix",
            workspace="repo",
            current_failure="some failure",
        )
        text = checkpoint_to_prompt(checkpoint)
        assert "reasoning_content" not in text
        assert "api_key" not in text.casefold()
        assert "secret" not in text.casefold()


class TestContextCompaction:
    def test_compaction_bounds_recent_tool_results(self):
        context = RunContext(
            checkpoint=build_checkpoint(objective="o", workspace="w"),
            recent_tool_results=tuple(f"result-{i}" for i in range(10)),
            repo_map=("a", "b", "c"),
        )
        compacted = compact_run_context(
            context, max_recent_tool_results=3
        )
        assert compacted.recent_tool_results == ("result-7", "result-8", "result-9")
        assert compacted.checkpoint is context.checkpoint

    def test_compose_checkpoint_after_stable_identity_prefix(self):
        profile = default_identity_profile()
        stable = compose_system_instructions(profile)
        checkpoint = build_checkpoint(objective="fix", workspace="repo")
        dynamic = compose_checkpoint_context(checkpoint)
        combined = stable + "\n\n" + dynamic
        assert combined.index("TOOL AUTHORITY / SECURITY RULES") < combined.index(
            "[CURRENT RUN CHECKPOINT]"
        )
        assert "OBJECTIVE: fix" in dynamic


class TestRunContextText:
    def test_context_text_is_bounded_and_structured(self):
        context = RunContext(
            checkpoint=build_checkpoint(objective="o", workspace="w"),
            repo_map=("src/a.py",),
            current_diff_summary="2 files changed",
            test_state="3 passed",
            open_failures=("test_b failing",),
        )
        text = context.as_context_text()
        assert "[REPO MAP]" in text
        assert "[CURRENT DIFF]" in text
        assert "[TEST STATE]" in text
        assert "[OPEN FAILURES]" in text
        assert "reasoning" not in text
