"""Real Qwen3 chat-template masking proof (tokenizer-driven).

Produces per-token labels for the pinned Qwen3 tokenizer using the actual
``apply_chat_template`` output, then validates them with the canonical
assistant-only masking validator. The Qwen3 template renders tool responses
inside a ``<|im_start|>user`` block, so tool-result tokens are naturally
non-trainable; assistant blocks (tool-call request AND final answer) are the
trainable spans.

This is the pre-optimizer masking gate for the paid canary (Stage 7), made
locally testable now.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .training_hardening import validate_assistant_masking

_BLOCK_RE = re.compile(r"<\|im_start\|>(system|user|assistant)\n(.*?)<\|im_end\|>", re.DOTALL)


@dataclass
class MaskedExample:
    input_ids: list[int]
    labels: list[int]
    role_spans: list[tuple[str, int, int]]


def build_qwen3_masked_example(tokenizer, messages: list[dict]) -> MaskedExample:
    rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    enc = tokenizer(rendered, return_offsets_mapping=True, add_special_tokens=False)
    input_ids = enc["input_ids"]
    if hasattr(input_ids, "tolist"):
        input_ids = input_ids.tolist()
    offsets = enc["offset_mapping"]

    # char ranges of each role's CONTENT (markers excluded).
    blocks: list[tuple[str, int, int]] = []
    for match in _BLOCK_RE.finditer(rendered):
        role = match.group(1)
        blocks.append((role, match.start(2), match.end(2)))

    token_roles: list[str | None] = [None] * len(input_ids)
    for idx, (s, e) in enumerate(offsets):
        if s == 0 and e == 0:
            token_roles[idx] = "marker"
            continue
        for role, start, end in blocks:
            if start <= s < end:
                token_roles[idx] = role
                break
        if token_roles[idx] is None:
            token_roles[idx] = "marker"

    labels = [-100] * len(input_ids)
    role_spans: list[tuple[str, int, int]] = []
    idx = 0
    while idx < len(token_roles):
        role = token_roles[idx]
        if role is None or role == "marker":
            idx += 1
            continue
        end = idx
        while end < len(token_roles) and token_roles[end] == role:
            end += 1
        role_spans.append((role, idx, end))
        if role == "assistant":
            for pos in range(idx, end):
                labels[pos] = pos
        idx = end

    return MaskedExample(input_ids=input_ids, labels=labels, role_spans=role_spans)


def prepare_qwen3_training_example(tokenizer, messages: list[dict]) -> dict:
    """Canonical training example: input_ids/attention_mask/labels from the SAME
    assistant-only masking pipeline used by the tokenizer/template proof.

    Training MUST use this (never a text-only all-token-loss representation).
    """
    example = build_qwen3_masked_example(tokenizer, messages)
    return {
        "input_ids": example.input_ids,
        "attention_mask": [1] * len(example.input_ids),
        "labels": example.labels,
    }


def qwen3_masking_proof(tokenizer, messages: list[dict]) -> tuple[bool, dict]:
    example = build_qwen3_masked_example(tokenizer, messages)
    ok, failures = validate_assistant_masking(example.labels, example.role_spans)
    counts = {"system": 0, "user": 0, "assistant": 0, "marker": 0}
    for span in example.role_spans:
        counts[span[0]] = counts.get(span[0], 0) + (span[2] - span[1])
    return ok, {
        "ok": ok,
        "failures": failures,
        "token_count": len(example.input_ids),
        "role_token_counts": counts,
        "assistant_trainable": sum(1 for lab in example.labels if lab != -100),
    }
