"""Fresh-process canary adapter reload + non-heldout sanity inference.

This is a STRUCTURAL contract executed on the paid host (M1.9.2D). The reload
MUST run in a genuinely new Python process (never the training process). It
loads the pinned Qwen3 base + the temporary five-step adapter and runs one
tiny canary-scoped (non-heldout) sanity prompt. It never publishes, promotes,
or touches production.

In this zero-cost milestone the module exists so the reload command resolves
and the fresh-process boundary is represented structurally; the actual model
load is gated to the paid host where torch + the pinned base are present.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Qwen3 canary adapter reload sanity")
    parser.add_argument("--adapter-dir", required=True)
    parser.add_argument("--sanity-prompt", default="Reply with the single word: ready.")
    args = parser.parse_args(argv)

    adapter_dir = Path(args.adapter_dir).expanduser().resolve()
    if not adapter_dir.is_dir():
        print("RELOAD_SANITY=FAIL (adapter dir missing)", file=sys.stderr)
        return 2

    # NOTE(paid-host): load pinned Qwen3 base (9216db57...) + adapter_dir here,
    # then generate with args.sanity_prompt and verify finite/nonempty output.
    # This zero-cost module intentionally does not import torch or download
    # weights; the real load is the paid-host contract.
    print("RELOAD_SANITY=STRUCTURAL")
    print("ADAPTER_DIR=" + str(adapter_dir))
    print("SANITY_PROMPT_PRESENT=" + ("YES" if args.sanity_prompt else "NO"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
