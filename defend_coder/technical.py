"""Provider-specific technical instruction builders (isolated).

Each provider owns ONLY its real protocol requirements. The DeepSeek builder
never mentions Qwen/vLLM/Qwen3CoderToolParser; the vLLM builder owns Qwen
tool-parser semantics; the OpenAI builder owns Responses semantics. These are
separate from the provider-neutral DEFENDcoder governance core.
"""

from __future__ import annotations

from .prompts import qwen_technical_instructions


def deepseek_technical_instructions() -> str:
    return (
        "You are called through the DeepSeek V4 Chat Completions API "
        "(https://api.deepseek.com/chat/completions). Tool use follows the "
        "OpenAI-compatible function-calling representation: the model returns "
        "tool_calls with id/type/function(name,arguments), and each tool call "
        "is answered with a tool-role message whose tool_call_id matches the "
        "call id. On thinking-mode turns the provider returns reasoning_content "
        "alongside tool calls; that field is internal continuation state and "
        "must be replayed verbatim on the assistant message in the follow-up "
        "request for the tool-call chain. Keep all file and command activity "
        "within the authorized workspace. Do not mention provider names or "
        "internals to the user unless asked about the underlying model."
    )


def openai_responses_technical_instructions() -> str:
    return (
        "You are called through the OpenAI Responses API (/v1/responses). "
        "Function/custom tools use the Responses tool shape; a tool request "
        "produces a function_call item that must be answered with a "
        "function_call_output item carrying the matching call_id. System "
        "instructions are supplied explicitly on each applicable request — a "
        "previous response id does not automatically inherit instructions. "
        "Keep all file and command activity within the authorized workspace. "
        "Do not mention provider names or internals to the user unless asked "
        "about the underlying model."
    )


def vllm_technical_instructions() -> str:
    """Qwen3-Coder-Next through the local vLLM runtime (Qwen3CoderToolParser)."""
    return qwen_technical_instructions()
