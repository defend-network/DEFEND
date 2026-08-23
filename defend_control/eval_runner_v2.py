"""DEFEND AI evaluator v2.3 — evaluation-episode model + strict rubric.

Fixes the M1.9.1B audit findings:

- EvalEpisode replaces the ambiguous TargetSpec. A TOOL_AGENT_TRAJECTORY episode
  stops its input prefix BEFORE the expected tool sequence, so the model is
  never handed the tool calls/results it is being scored on.
- Tool scoring uses structured actual calls (name/arguments/order), not a list
  of names; deterministic arguments are compared (canonical JSON); order is
  scored only for tool episodes; result incorporation is a tool-specific
  deterministic check (calculator -> expected numeric result, time -> expected
  date/time semantics), never a raw 40-char prefix match.
- A frozen deterministic StrictRubric (required/forbidden concepts, critical
  numerics, format, identity/tool/recovery requirements) scores direct and
  recovery episodes. A row that cannot be resolved deterministically is
  reported SEMANTIC_UNRESOLVED and excluded from the strict score; an auxiliary
  lexical overlap score is reported separately and never treated as ground
  truth.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

EVALUATOR_VERSION = "v2.3"
EVAL_DATASET_SHA = "5ee2369ea383a8590dd123fa66db8a885154a2a0bf5abc8e98c174bcdf27835a"

TOOL_EVAL_SCORING_LOGIC = "YES"
REAL_TOOL_EVAL_AGENT_LOOP = "PENDING_RUNTIME"


def tool_eval_status() -> dict:
    """Truthful tool-evaluation status: the scoring logic is implemented and
    tested, but a real model→tool→result→model agent loop is not yet wired
    (the production agent does that at eval time; the fixture is scoring only)."""
    return {
        "tool_eval_scoring_logic": TOOL_EVAL_SCORING_LOGIC,
        "real_tool_eval_agent_loop": REAL_TOOL_EVAL_AGENT_LOOP,
    }

EPISODE_DIRECT = "DIRECT_RESPONSE"
EPISODE_TOOL = "TOOL_AGENT_TRAJECTORY"
EPISODE_RECOVERY = "RECOVERY_MULTI_TURN"
EPISODE_TOOL_ONLY = "TOOL_CALL_ONLY"
EPISODE_UNSCORABLE = "UNSCORABLE_AMBIGUOUS"

_STOP = frozenset(
    "a an and the of to in on for with as by from at or is are was were be been being have has had do does did not no but so if then than that this these those it its it's we our you your they their them i me my".split()
)
_REFUSAL_MARKERS = (
    "cannot", "can't", "i cannot", "i can't", "i won't", "won't answer",
    "i'm not able", "i am not able", "as an ai", "i don't", "no comment",
    "refuse",
)


def evaluator_code_sha() -> str:
    return hashlib.sha256(Path(__file__).read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) > 2 and w not in _STOP]


def _is_refusal(output: str) -> bool:
    low = output.lower().strip()
    return any(m in low for m in _REFUSAL_MARKERS)


def _normalize_args(arguments) -> dict:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            return {}
    return dict(arguments) if isinstance(arguments, dict) else {}


def _canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


# ── Strict rubric ────────────────────────────────────────────

@dataclass
class StrictRubric:
    """Frozen deterministic behavioral rubric. Required concepts are clusters
    of accepted phrasings separated by '|'. A missing required concept is
    SEMANTIC_UNRESOLVED (never forced to FAIL); a forbidden concept or missing
    critical numeric/format is a deterministic FAIL."""

    required_concepts: list[str] = field(default_factory=list)
    forbidden_concepts: list[str] = field(default_factory=list)
    identity_requirement: str | None = None
    tool_requirement: list[str] = field(default_factory=list)
    recovery_requirement: bool = False
    format_requirement: str | None = None
    critical_numerics: list[str] = field(default_factory=list)


def score_with_rubric(output: str, rubric: StrictRubric) -> tuple[bool | None, str]:
    """Return (pass|None, detail). None == SEMANTIC_UNRESOLVED."""
    low = output.lower()
    if rubric.required_concepts and _is_refusal(output):
        return False, "refusal"
    for f in rubric.forbidden_concepts:
        if f.lower() in low:
            return False, f"forbidden:{f}"
    norm_out = re.sub(r"[^0-9a-z]", "", low)
    for n in rubric.critical_numerics:
        if re.sub(r"[^0-9a-z]", "", n.lower()) not in norm_out:
            return False, f"missing_numeric:{n}"
    for cluster in rubric.required_concepts:
        variants = [v.strip().lower() for v in cluster.split("|") if v.strip()]
        if variants and not any(v in low for v in variants):
            return None, f"unresolved_concept:{cluster}"
    if rubric.format_requirement and rubric.format_requirement.lower() not in low:
        return False, f"missing_format:{rubric.format_requirement}"
    return True, "ok"


# ── Episode model ────────────────────────────────────────────

@dataclass
class EvalEpisode:
    eval_id: str
    domain: str
    difficulty: str
    episode_type: str
    prefix_messages: list[dict]
    trigger_user_turn: str
    expected_tool_calls: list[dict] = field(default_factory=list)
    expected_tool_results: list[str] = field(default_factory=list)
    expected_final_response: str = ""
    scorable: bool = True
    ambiguity_reason: str | None = None
    source_message_indices: list[int] = field(default_factory=list)


def _assistant_indices(messages: list[dict]) -> list[int]:
    return [i for i, m in enumerate(messages) if m.get("role") == "assistant"]


def _first_tool_call_index(messages: list[dict]) -> int | None:
    for i, m in enumerate(messages):
        if m.get("role") == "assistant" and isinstance(m.get("tool_calls"), list) and m["tool_calls"]:
            return i
    return None


def _extract_tool_calls(messages: list[dict]) -> list[dict]:
    tools: list[dict] = []
    for m in messages:
        if m.get("role") == "assistant" and isinstance(m.get("tool_calls"), list):
            for call in m["tool_calls"]:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") or {}
                tools.append(
                    {
                        "name": fn.get("name"),
                        "arguments": fn.get("arguments"),
                        "order": len(tools) + 1,
                    }
                )
    return tools


def _extract_tool_results(messages: list[dict]) -> list[str]:
    return [str(m.get("content", "")) for m in messages if m.get("role") == "tool"]


def _last_user_before(messages: list[dict], index: int) -> str:
    for i in range(index - 1, -1, -1):
        if messages[i].get("role") == "user":
            return str(messages[i].get("content", ""))
    return ""


def derive_episode(row: dict) -> EvalEpisode:
    messages = list(row.get("messages", []))
    assistant = _assistant_indices(messages)
    if not assistant:
        return EvalEpisode(
            str(row.get("id")), str(row.get("domain")), str(row.get("difficulty")),
            EPISODE_UNSCORABLE, messages, "", scorable=False,
            ambiguity_reason="no assistant target",
        )

    first_tool = _first_tool_call_index(messages)
    if first_tool is not None:
        # Tool-agent episode: input stops BEFORE the expected tool sequence.
        prefix = messages[:first_tool]
        final = messages[assistant[-1]].get("content", "")
        return EvalEpisode(
            str(row.get("id")), str(row.get("domain")), str(row.get("difficulty")),
            EPISODE_TOOL, prefix, _last_user_before(messages, first_tool),
            expected_tool_calls=_extract_tool_calls(messages),
            expected_tool_results=_extract_tool_results(messages),
            expected_final_response=str(final),
            source_message_indices=list(range(len(messages))),
        )

    # No tools: direct or multi-turn recovery.
    target = assistant[-1]
    prefix = messages[:target]
    episode_type = EPISODE_DIRECT if len(assistant) == 1 else EPISODE_RECOVERY
    return EvalEpisode(
        str(row.get("id")), str(row.get("domain")), str(row.get("difficulty")),
        episode_type, prefix, _last_user_before(messages, target),
        expected_final_response=str(messages[target].get("content", "")),
        source_message_indices=list(range(len(messages))),
    )


@dataclass
class EvalModelResult:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)  # [{name, arguments, order}]


@dataclass
class EpisodeResult:
    eval_id: str
    domain: str
    difficulty: str
    episode_type: str
    strict_scorable: bool
    strict_pass: bool | None
    auxiliary_lexical_score: float | None
    tool_selection_pass: bool | None
    tool_order_pass: bool | None
    tool_arguments_pass: bool | None
    tool_result_pass: bool | None
    final_response_pass: bool | None
    semantic_resolved: bool
    latency_s: float
    error: str | None


def _lexical_overlap(episode: EvalEpisode, output: str) -> float:
    ref_words = _words(episode.expected_final_response)
    out_words = set(_words(output))
    if not ref_words:
        return 0.0
    return round(sum(1 for w in ref_words if w in out_words) / len(ref_words), 4)


def _check_result_incorporation(episode: EvalEpisode, output: str) -> bool | None:
    if not episode.expected_tool_results:
        return None
    out_digits = re.sub(r"[^0-9]", "", output)
    all_ok = True
    for call, res in zip(episode.expected_tool_calls, episode.expected_tool_results):
        name = (call.get("name") or "").lower()
        if "calculator" in name:
            digits = re.sub(r"[^0-9]", "", res)
            if digits and digits not in out_digits:
                all_ok = False
        elif "time" in name or "date" in name:
            m = re.search(r"\d{4}-\d{2}-\d{2}", res)
            if m and m.group(0) not in output:
                all_ok = False
            elif not m:
                y = re.search(r"\d{4}", res)
                if y and y.group(0) not in output:
                    all_ok = False
    return all_ok


def evaluate_episode(
    episode: EvalEpisode,
    chat: Callable[[list[dict]], EvalModelResult],
    rubric: StrictRubric | None = None,
) -> EpisodeResult:
    started = time.monotonic()
    try:
        result = chat(list(episode.prefix_messages))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        latency = round(time.monotonic() - started, 2)
        return EpisodeResult(
            episode.eval_id, episode.domain, episode.difficulty, episode.episode_type,
            strict_scorable=episode.scorable, strict_pass=None,
            auxiliary_lexical_score=None, tool_selection_pass=None,
            tool_order_pass=None, tool_arguments_pass=None, tool_result_pass=None,
            final_response_pass=None, semantic_resolved=False, latency_s=latency, error=error,
        )
    latency = round(time.monotonic() - started, 2)
    output = result.content or ""
    actual_tools = result.tool_calls or []

    if episode.episode_type == EPISODE_TOOL:
        return _score_tool_episode(episode, output, actual_tools, latency, None)

    # Direct / recovery: strict only via an explicit rubric.
    if rubric is not None:
        verdict, _detail = score_with_rubric(output, rubric)
        resolved = verdict is not None
        return EpisodeResult(
            episode.eval_id, episode.domain, episode.difficulty, episode.episode_type,
            strict_scorable=True, strict_pass=verdict,
            auxiliary_lexical_score=_lexical_overlap(episode, output),
            tool_selection_pass=None, tool_order_pass=None, tool_arguments_pass=None,
            tool_result_pass=None, final_response_pass=not _is_refusal(output),
            semantic_resolved=resolved, latency_s=latency, error=None,
        )

    # No rubric: honest SEMANTIC_UNRESOLVED, auxiliary lexical only.
    return EpisodeResult(
        episode.eval_id, episode.domain, episode.difficulty, episode.episode_type,
        strict_scorable=False, strict_pass=None,
        auxiliary_lexical_score=_lexical_overlap(episode, output),
        tool_selection_pass=None, tool_order_pass=None, tool_arguments_pass=None,
        tool_result_pass=None, final_response_pass=not _is_refusal(output),
        semantic_resolved=False, latency_s=latency, error=None,
    )


def _score_tool_episode(
    episode: EvalEpisode,
    output: str,
    actual_tools: list[dict],
    latency: float,
    error: str | None,
) -> EpisodeResult:
    expected_names = [t.get("name") for t in episode.expected_tool_calls if t.get("name")]
    actual_names = [t.get("name") for t in actual_tools if t.get("name")]

    # Selection: exact sequence of names.
    selection_pass = expected_names == actual_names
    # Order: only meaningful when more than one tool.
    order_pass = (expected_names == actual_names) if len(expected_names) > 1 else None
    # Arguments: compare deterministic expected arguments.
    args_pass = None
    for expected in episode.expected_tool_calls:
        exp_args = _normalize_args(expected.get("arguments"))
        if not exp_args:
            continue
        actual = next((t for t in actual_tools if t.get("name") == expected.get("name")), None)
        act_args = _normalize_args(actual.get("arguments")) if actual else {}
        match = _canonical_json(exp_args) == _canonical_json(act_args)
        args_pass = match if args_pass is None else (args_pass and match)

    # Result incorporation (tool-specific deterministic check).
    result_pass = _check_result_incorporation(episode, output)

    # Final response substantive.
    ref_words = _words(episode.expected_final_response)
    final_pass = (not _is_refusal(output)) if len(ref_words) >= 4 else True

    gates = [selection_pass, final_pass] + [c for c in (order_pass, args_pass, result_pass) if c is not None]
    strict_pass = all(gates)
    return EpisodeResult(
        episode.eval_id, episode.domain, episode.difficulty, episode.episode_type,
        strict_scorable=True, strict_pass=strict_pass, auxiliary_lexical_score=None,
        tool_selection_pass=selection_pass, tool_order_pass=order_pass,
        tool_arguments_pass=args_pass, tool_result_pass=result_pass,
        final_response_pass=bool(final_pass), semantic_resolved=True,
        latency_s=latency, error=error,
    )


def run_episodes(
    rows: list[dict],
    chat: Callable[[list[dict]], EvalModelResult],
    rubrics: dict[str, StrictRubric] | None = None,
) -> dict:
    rubrics = rubrics or {}
    episodes = [derive_episode(r) for r in rows]
    results = [evaluate_episode(ep, chat, rubrics.get(ep.eval_id)) for ep in episodes]
    strict = [r for r in results if r.strict_scorable]
    resolved = [r for r in strict if r.strict_pass is not None]
    unresolved = [r for r in results if r.strict_pass is None]

    def domain_score(domain: str) -> float:
        subset = [r for r in resolved if r.domain == domain]
        return round(sum(1 for r in subset if r.strict_pass) / len(subset), 4) if subset else 0.0

    return {
        "evaluator_version": EVALUATOR_VERSION,
        "evaluator_code_sha": evaluator_code_sha(),
        "eval_dataset_sha": EVAL_DATASET_SHA,
        "total_rows": len(results),
        "direct_response_rows": sum(1 for e in episodes if e.episode_type == EPISODE_DIRECT),
        "tool_agent_rows": sum(1 for e in episodes if e.episode_type == EPISODE_TOOL),
        "recovery_rows": sum(1 for e in episodes if e.episode_type == EPISODE_RECOVERY),
        "unscorable_rows": sum(1 for e in episodes if e.episode_type == EPISODE_UNSCORABLE),
        "strict_scorable_rows": len(strict),
        "strict_pass": sum(1 for r in resolved if r.strict_pass),
        "strict_pass_rate": round(sum(1 for r in resolved if r.strict_pass) / len(resolved), 4) if resolved else None,
        "semantic_unresolved_rows": len(unresolved),
        "strict_general": domain_score("general"),
        "strict_policy": domain_score("policy"),
        "strict_recovery": domain_score("recovery"),
        "results": [r.__dict__ for r in results],
    }
