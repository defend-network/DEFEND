"""Canonical DEFENDcoder system-prompt composition.

Single source of truth for the system prompt sent to the model. The
final prompt is composed from three pinned assets under
``defend_coder/prompts/``:

1. ``owner_directive.txt``     - verbatim owner directive (pinned,
   SHA-256 recorded in OWNER_DIRECTIVE_SHA256; byte-identical to the
   owner-provided source file, which is never modified).
2. ``agent_instructions.txt``  - DEFENDcoder role, engineering quality,
   agent-loop/tool usage, and security rules (audited from the original
   SYSTEM_PROMPT; all sections KEEP, none removed or rewritten in
   substance).
3. ``qwen_technical.txt``      - model-specific technical instructions
   (OpenAI function-calling format, Qwen3CoderToolParser compatibility,
   output/tool-call format).

Composition produces EXACTLY ONE system message with the owner
directive first (order of authority: owner directive > DEFENDcoder
agent behavior > model technical formatting > task/user content).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent / "prompts"

OWNER_DIRECTIVE_ASSET = "owner_directive.txt"
AGENT_INSTRUCTIONS_ASSET = "agent_instructions.txt"
QWEN_TECHNICAL_ASSET = "qwen_technical.txt"

#: Pinned SHA-256 (hex, lowercase) of the owner directive asset.
#: Source: owner-provided C:\\Users\\thoma\\Downloads\\DEFEND32B\\
#: DEFEND_coder_prompt.txt (9,106 bytes, UTF-8, no trailing newline).
#: The original file is preserved unchanged; tests enforce this hash.
OWNER_DIRECTIVE_SHA256 = (
    "78ab8899ca968efe50bee4bc57e6ee2675849be84af3e07e99c8d22826832442"
)

#: Human-visible prompt version; also recorded in benchmark manifests.
PROMPT_VERSION = "2026-08-18.v1"


def _load(name: str) -> str:
    asset = _PROMPTS_DIR / name
    if not asset.is_file():
        raise FileNotFoundError(f"missing prompt asset: {asset}")
    return asset.read_text(encoding="utf-8")


def owner_directive() -> str:
    """The verbatim owner directive (pinned asset, no modification)."""
    return _load(OWNER_DIRECTIVE_ASSET)


def agent_instructions() -> str:
    """The audited DEFENDcoder agent instructions (all KEEP)."""
    return _load(AGENT_INSTRUCTIONS_ASSET)


def qwen_technical_instructions() -> str:
    """Model-specific technical instructions (KEEP/Preserved)."""
    return _load(QWEN_TECHNICAL_ASSET)


def compose_system_prompt() -> str:
    """Compose the ONE canonical system prompt.

    Sections in order of authority; the owner directive is embedded
    verbatim and is the highest-authority section. No other system
    message is sent.
    """
    directive = owner_directive().strip("\n")
    agent = agent_instructions().strip("\n")
    technical = qwen_technical_instructions().strip("\n")
    return "\n\n".join(
        (
            "[DEFEND OWNER DIRECTIVE]",
            directive,
            agent,
            technical,
        )
    )


def system_prompt_sha256(prompt: str | None = None) -> str:
    return hashlib.sha256(
        (prompt if prompt is not None else compose_system_prompt())
        .encode("utf-8")
    ).hexdigest()


#: The canonical system prompt used by the real agent path.
SYSTEM_PROMPT = compose_system_prompt()

#: Pinned SHA-256 of the canonical composed prompt (stability check).
SYSTEM_PROMPT_SHA256 = system_prompt_sha256(SYSTEM_PROMPT)
