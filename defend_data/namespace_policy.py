from __future__ import annotations

from typing import Literal

MemoryScope = Literal["global", "user", "project"]


def context_namespaces(*, user_id: str | None, project_id: str | None) -> list[str]:
    out = ["global"]
    if user_id:
        out.append(f"user:{user_id.lower()}")
    if project_id:
        out.append(f"project:{project_id.lower()}")
    return out


def resolve_public_scope(scope: MemoryScope, *, user_id: str | None, project_id: str | None) -> str:
    if scope == "global":
        return "global"
    if scope == "user":
        if not user_id:
            raise PermissionError("User-scoped memory requires a server-assigned visitor identity")
        return f"user:{user_id.lower()}"
    if scope == "project":
        if not project_id:
            raise PermissionError("Project-scoped memory requires an authorized project identity")
        return f"project:{project_id.lower()}"
    raise ValueError(f"Unsupported memory scope: {scope}")
