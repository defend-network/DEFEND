from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from defend_coder.workspaces import (
    WorkspaceAccessError,
    WorkspaceService,
)


@dataclass(frozen=True)
class FakeWorkspace:
    workspace_id: UUID
    owner_account_id: UUID
    name: str
    workspace_root: str
    repository_url: str | None = None
    default_branch: str | None = None


class FakeRepository:
    def __init__(self, workspaces: list[FakeWorkspace]) -> None:
        self._workspaces = tuple(workspaces)

    def list_workspaces_for_owner(
        self,
        owner_account_id: UUID,
    ) -> tuple[FakeWorkspace, ...]:
        return tuple(
            workspace
            for workspace in self._workspaces
            if workspace.owner_account_id == owner_account_id
        )


def make_service(
    tmp_path: Path,
    *,
    owner_id: UUID | None = None,
):
    owner_id = owner_id or uuid4()
    workspace_id = uuid4()

    root = tmp_path / "owner" / "project"
    root.mkdir(parents=True)

    workspace = FakeWorkspace(
        workspace_id=workspace_id,
        owner_account_id=owner_id,
        name="project",
        workspace_root=str(root),
    )

    repository = FakeRepository([workspace])

    service = WorkspaceService(
        repository=repository,
        configured_root=tmp_path / "owner",
    )

    return service, owner_id, workspace_id, root


def test_resolves_normal_owned_relative_path(tmp_path):
    service, owner_id, workspace_id, root = make_service(tmp_path)

    target = root / "src" / "main.py"
    target.parent.mkdir()
    target.write_text("print('ok')", encoding="utf-8")

    resolved = service.resolve_owned_path(
        owner_id,
        workspace_id,
        "src/main.py",
    )

    assert resolved == target.resolve()


@pytest.mark.parametrize(
    "relative_path",
    [
        "../secret.txt",
        "src/../../secret.txt",
        "..",
        "src/..",
    ],
)
def test_rejects_parent_traversal(
    tmp_path,
    relative_path,
):
    service, owner_id, workspace_id, _ = make_service(tmp_path)

    with pytest.raises(
        WorkspaceAccessError,
        match="path escapes workspace",
    ):
        service.resolve_owned_path(
            owner_id,
            workspace_id,
            relative_path,
        )


@pytest.mark.parametrize(
    "relative_path",
    [
        "/etc/passwd",
        r"\Windows\System32",
        r"C:\Windows\System32",
        r"D:\other\project",
        r"\\server\share\file.txt",
    ],
)
def test_rejects_absolute_or_drive_paths(
    tmp_path,
    relative_path,
):
    service, owner_id, workspace_id, _ = make_service(tmp_path)

    with pytest.raises(
        WorkspaceAccessError,
        match="relative path required",
    ):
        service.resolve_owned_path(
            owner_id,
            workspace_id,
            relative_path,
        )


def test_rejects_workspace_owned_by_another_account(tmp_path):
    real_owner = uuid4()
    attacker = uuid4()
    workspace_id = uuid4()

    root = tmp_path / "real-owner" / "project"
    root.mkdir(parents=True)

    repository = FakeRepository(
        [
            FakeWorkspace(
                workspace_id=workspace_id,
                owner_account_id=real_owner,
                name="project",
                workspace_root=str(root),
            )
        ]
    )

    service = WorkspaceService(
        repository=repository,
        configured_root=tmp_path,
    )

    with pytest.raises(
        WorkspaceAccessError,
        match="workspace not found",
    ):
        service.resolve_owned_path(
            attacker,
            workspace_id,
            "README.md",
        )


def test_rejects_workspace_root_outside_configured_root(tmp_path):
    owner_id = uuid4()
    workspace_id = uuid4()

    configured = tmp_path / "allowed"
    configured.mkdir()

    outside = tmp_path / "outside"
    outside.mkdir()

    repository = FakeRepository(
        [
            FakeWorkspace(
                workspace_id=workspace_id,
                owner_account_id=owner_id,
                name="outside",
                workspace_root=str(outside),
            )
        ]
    )

    service = WorkspaceService(
        repository=repository,
        configured_root=configured,
    )

    with pytest.raises(
        WorkspaceAccessError,
        match="workspace root escapes configured root",
    ):
        service.resolve_owned_path(
            owner_id,
            workspace_id,
            "file.txt",
        )


def test_rejects_symlink_escape(tmp_path):
    service, owner_id, workspace_id, root = make_service(tmp_path)

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text(
        "secret",
        encoding="utf-8",
    )

    link = root / "escape"

    try:
        link.symlink_to(
            outside,
            target_is_directory=True,
        )
    except (OSError, NotImplementedError):
        pytest.skip(
            "symlink creation unavailable in this Windows environment"
        )

    with pytest.raises(
        WorkspaceAccessError,
        match="path escapes workspace",
    ):
        service.resolve_owned_path(
            owner_id,
            workspace_id,
            "escape/secret.txt",
        )


def test_rejects_symlinked_workspace_root_escape(tmp_path):
    owner_id = uuid4()
    workspace_id = uuid4()

    configured = tmp_path / "configured"
    configured.mkdir()

    outside = tmp_path / "outside"
    outside.mkdir()

    linked_root = configured / "linked"

    try:
        linked_root.symlink_to(
            outside,
            target_is_directory=True,
        )
    except (OSError, NotImplementedError):
        pytest.skip(
            "symlink creation unavailable in this Windows environment"
        )

    repository = FakeRepository(
        [
            FakeWorkspace(
                workspace_id=workspace_id,
                owner_account_id=owner_id,
                name="linked",
                workspace_root=str(linked_root),
            )
        ]
    )

    service = WorkspaceService(
        repository=repository,
        configured_root=configured,
    )

    with pytest.raises(
        WorkspaceAccessError,
        match="workspace root escapes configured root",
    ):
        service.resolve_owned_path(
            owner_id,
            workspace_id,
            "file.txt",
        )
