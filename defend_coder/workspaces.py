from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import UUID

from .repositories import CoderRepository, WorkspaceRecord


class WorkspaceAccessError(RuntimeError):
    """Public-safe workspace ownership or containment failure."""


class WorkspaceService:
    def __init__(
        self,
        *,
        repository: CoderRepository,
        configured_root: str | Path,
    ) -> None:
        self._repository = repository
        self._configured_root = Path(configured_root).resolve()

    def resolve_owned_path(
        self,
        account_id: UUID,
        workspace_id: UUID,
        relative_path: str,
    ) -> Path:
        workspace = self._get_owned_workspace(
            account_id,
            workspace_id,
        )

        workspace_root = Path(
            workspace.workspace_root
        ).resolve()

        if not _is_within(
            workspace_root,
            self._configured_root,
        ):
            raise WorkspaceAccessError(
                "workspace root escapes configured root"
            )

        normalized = _validate_relative_path(relative_path)

        target = (
            workspace_root
            if normalized == "."
            else workspace_root / normalized
        ).resolve()

        if not _is_within(
            target,
            workspace_root,
        ):
            raise WorkspaceAccessError(
                "path escapes workspace"
            )

        return target

    def _get_owned_workspace(
        self,
        account_id: UUID,
        workspace_id: UUID,
    ) -> WorkspaceRecord:
        for workspace in self._repository.list_workspaces_for_owner(
            account_id
        ):
            if workspace.workspace_id == workspace_id:
                return workspace

        raise WorkspaceAccessError("workspace not found")


def _validate_relative_path(relative_path: str) -> Path:
    if not isinstance(relative_path, str):
        raise WorkspaceAccessError(
            "relative path required"
        )

    raw = relative_path.strip()

    if not raw:
        return Path(".")

    windows = PureWindowsPath(raw)
    posix = PurePosixPath(raw.replace("\\", "/"))

    if (
        windows.is_absolute()
        or windows.drive
        or windows.root
        or posix.is_absolute()
        or raw.startswith("\\\\")
    ):
        raise WorkspaceAccessError(
            "relative path required"
        )

    raw_parts = raw.replace("\\", "/").split("/")

    if any(part == ".." for part in raw_parts):
        raise WorkspaceAccessError(
            "path escapes workspace"
        )

    return Path(*[
        part
        for part in raw_parts
        if part not in {"", "."}
    ])


def _is_within(
    candidate: Path,
    parent: Path,
) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False

    return True
