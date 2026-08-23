"""SCS knowledge subsystem.

resolve_knowledge_root() is the single authority for where the private
knowledge library lives (P34-P35): it honors SCS_KNOWLEDGE_ROOT and otherwise
returns the default private root, canonicalized and safely created.
"""
from __future__ import annotations

import os
from pathlib import Path


def resolve_knowledge_root(default_root: Path | str) -> Path:
    """Resolve the ACTUAL knowledge root in use (P34).

    SCS_KNOWLEDGE_ROOT (when set) wins; otherwise the caller's default private
    root. The path is canonicalized and created safely. Never indexes a drive
    or a parent outside configured authorization.
    """
    configured = os.environ.get("SCS_KNOWLEDGE_ROOT")
    if configured:
        path = Path(configured).expanduser().resolve()
    else:
        path = Path(default_root).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path
