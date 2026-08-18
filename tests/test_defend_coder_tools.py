from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from defend_coder.repositories import WorkspaceRecord
from defend_coder.tools import CoderToolkit
from defend_coder.workspaces import WorkspaceAccessError


class FakeRepo:
    def __init__(self, workspaces):
        self._workspaces = workspaces

    def list_workspaces_for_owner(self, account_id):
        return tuple(
            workspace
            for workspace in self._workspaces
            if workspace.owner_account_id == account_id
        )


def _workspace(root, name="ws"):
    now = datetime.now(timezone.utc)
    return WorkspaceRecord(
        workspace_id=uuid4(),
        owner_account_id=uuid4(),
        name=name,
        workspace_root=str(root),
        repository_url=None,
        default_branch=None,
        created_at=now,
        updated_at=now,
    )


def _toolkit(tmp_path, workspace=None):
    configured = tmp_path / "configured"
    configured.mkdir(exist_ok=True)
    ws = workspace or _workspace(configured / "ws")
    (configured / ws.workspace_root).mkdir(parents=True, exist_ok=True)
    repo = FakeRepo([ws])
    toolkit = CoderToolkit(
        repository=repo,
        configured_root=configured,
    )
    return toolkit, ws, configured


def _run(toolkit, ws, name, arguments=None, log=None):
    return toolkit.execute(
        name,
        arguments or {},
        account_id=ws.owner_account_id,
        workspace_id=ws.workspace_id,
    )


def test_list_files_shows_tree(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)
    (tmp_path / "configured" / "ws" / "src").mkdir(parents=True)
    (tmp_path / "configured" / "ws" / "src" / "app.js").write_text(
        "// x", encoding="utf-8"
    )
    (tmp_path / "configured" / "ws" / "index.html").write_text(
        "<html></html>", encoding="utf-8"
    )

    result = _run(toolkit, ws, "list_files")

    assert result.ok
    assert result.kind == "file"
    assert "src/" in result.content
    assert "app.js" in result.content
    assert "index.html" in result.content


def test_list_files_skips_vendored_directories(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)
    root = tmp_path / "configured" / "ws"
    (root / "node_modules").mkdir(parents=True)
    (root / "node_modules" / "dep.js").write_text("x", encoding="utf-8")

    result = _run(toolkit, ws, "list_files")

    assert result.ok
    assert "node_modules" not in result.content
    assert "dep.js" not in result.content


def test_read_file_returns_contents_and_truncates(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)
    target = tmp_path / "configured" / "ws" / "notes.txt"
    target.write_text("hello world", encoding="utf-8")

    result = _run(toolkit, ws, "read_file", {"path": "notes.txt"})

    assert result.ok
    assert result.content == "hello world"

    long = "x" * 5000
    target.write_text(long, encoding="utf-8")
    result = _run(
        toolkit,
        ws,
        "read_file",
        {"path": "notes.txt", "max_chars": 1000},
    )
    assert result.ok
    assert len(result.content) < 1200
    assert "truncated" in result.content


def test_read_missing_file_returns_honest_error(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)

    result = _run(toolkit, ws, "read_file", {"path": "missing.txt"})

    assert not result.ok
    assert "not a file" in result.content


def test_write_file_creates_nested_files(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)

    result = _run(
        toolkit,
        ws,
        "write_file",
        {"path": "src/app.js", "content": "console.log(1);"},
    )

    assert result.ok
    target = tmp_path / "configured" / "ws" / "src" / "app.js"
    assert target.read_text(encoding="utf-8") == "console.log(1);"


def test_edit_file_replaces_first_occurrence(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)
    target = tmp_path / "configured" / "ws" / "app.js"
    target.write_text("a\nb\na\n", encoding="utf-8")

    result = _run(
        toolkit,
        ws,
        "edit_file",
        {"path": "app.js", "old_text": "a", "new_text": "A"},
    )

    assert result.ok
    assert target.read_text(encoding="utf-8") == "A\nb\na\n"


def test_edit_file_missing_text_is_an_error(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)
    target = tmp_path / "configured" / "ws" / "app.js"
    target.write_text("aaa", encoding="utf-8")

    result = _run(
        toolkit,
        ws,
        "edit_file",
        {"path": "app.js", "old_text": "zzz", "new_text": "x"},
    )

    assert not result.ok
    assert "not found" in result.content
    assert target.read_text(encoding="utf-8") == "aaa"


def test_run_command_executes_inside_workspace(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)

    result = _run(
        toolkit,
        ws,
        "run_command",
        {"command": "echo hello-from-agent"},
    )

    assert result.ok
    assert result.kind == "terminal"
    assert "hello-from-agent" in result.content


def test_run_command_nonzero_exit_reported_honestly(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)

    result = _run(
        toolkit,
        ws,
        "run_command",
        {"command": "python -c \"import sys; sys.exit(3)\""},
    )

    assert not result.ok
    assert "exit code 3" in result.content


def test_run_tests_detects_python_pytest(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)
    root = tmp_path / "configured" / "ws"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_smoke.py").write_text(
        "def test_ok():\n    assert True\n",
        encoding="utf-8",
    )

    result = _run(toolkit, ws, "run_tests")

    assert result.ok
    assert result.kind == "tests"
    assert "pytest" in result.content


def test_run_tests_detects_node_test(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)
    root = tmp_path / "configured" / "ws"
    (root / "smoke.test.js").write_text(
        "const test = require('node:test');\n"
        "test('ok', () => {});\n",
        encoding="utf-8",
    )

    result = _run(toolkit, ws, "run_tests")

    assert result.ok
    assert result.kind == "tests"
    assert "node --test" in result.content


def test_run_tests_without_runner_is_honest(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)

    result = _run(toolkit, ws, "run_tests")

    assert not result.ok
    assert "No test runner detected" in result.content


def test_git_diff_without_repo_is_honest(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)

    result = _run(toolkit, ws, "git_diff")

    assert not result.ok
    assert "Not a git repository" in result.content


def test_git_diff_shows_changes(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)
    root = tmp_path / "configured" / "ws"
    import subprocess

    subprocess.run(
        ["git", "init", "-q", "."],
        cwd=str(root),
        check=False,
    )
    subprocess.run(
        ["git", "config", "user.email", "agent@test"],
        cwd=str(root),
        check=False,
    )
    subprocess.run(
        ["git", "config", "user.name", "Agent"],
        cwd=str(root),
        check=False,
    )
    (root / "a.txt").write_text("v1", encoding="utf-8")
    subprocess.run(
        ["git", "add", "a.txt"],
        cwd=str(root),
        check=False,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"],
        cwd=str(root),
        check=False,
    )
    (root / "a.txt").write_text("v2", encoding="utf-8")

    result = _run(toolkit, ws, "git_diff")

    assert result.ok
    assert result.kind == "diff"
    assert "a.txt" in result.content
    assert "git status" in result.content


def test_git_diff_clean_tree_is_stated(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)
    root = tmp_path / "configured" / "ws"
    import subprocess

    subprocess.run(
        ["git", "init", "-q", "."],
        cwd=str(root),
        check=False,
    )

    result = _run(toolkit, ws, "git_diff")

    assert result.ok
    assert "clean" in result.content


def test_unknown_tool_is_honest_error(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)

    result = _run(toolkit, ws, "delete_everything")

    assert not result.ok
    assert "unknown tool" in result.content


def test_read_logs_uses_log_reader(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)
    toolkit = CoderToolkit(
        repository=FakeRepo([ws]),
        configured_root=tmp_path / "configured",
        log_reader=lambda tail: "line1\nline2",
    )

    result = _run(toolkit, ws, "read_logs", {"tail": 5})

    assert result.ok
    assert result.kind == "log"
    assert "line1" in result.content


def test_absolute_path_is_rejected(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)

    result = _run(
        toolkit,
        ws,
        "read_file",
        {"path": str(tmp_path / "outside.txt")},
    )

    assert not result.ok
    assert "relative path" in result.content or "escapes" in result.content


def test_dotdot_escape_is_rejected(tmp_path):
    toolkit, ws, _root = _toolkit(tmp_path)
    outside = tmp_path / "configured" / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    result = _run(toolkit, ws, "read_file", {"path": "../secret.txt"})

    assert not result.ok
    assert "escapes" in result.content


def test_workspace_owned_by_other_account_is_denied(tmp_path):
    configured = tmp_path / "configured"
    configured.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    owner_a = uuid4()
    owner_b = uuid4()
    ws_a = WorkspaceRecord(
        workspace_id=uuid4(),
        owner_account_id=owner_a,
        name="a",
        workspace_root=str(configured / "a"),
        repository_url=None,
        default_branch=None,
        created_at=now,
        updated_at=now,
    )
    ws_b = WorkspaceRecord(
        workspace_id=uuid4(),
        owner_account_id=owner_b,
        name="b",
        workspace_root=str(configured / "b"),
        repository_url=None,
        default_branch=None,
        created_at=now,
        updated_at=now,
    )
    (configured / "a").mkdir(parents=True, exist_ok=True)
    (configured / "b").mkdir(parents=True, exist_ok=True)
    (configured / "b" / "file.txt").write_text("data", encoding="utf-8")
    toolkit = CoderToolkit(
        repository=FakeRepo([ws_a, ws_b]),
        configured_root=configured,
    )

    result = toolkit.execute(
        "read_file",
        {"path": "file.txt"},
        account_id=owner_a,
        workspace_id=ws_b.workspace_id,
    )

    assert not result.ok
    assert "workspace not found" in result.content


def test_workspace_root_outside_configured_root_is_denied(tmp_path):
    configured = tmp_path / "configured"
    configured.mkdir(exist_ok=True)
    rogue = tmp_path / "elsewhere"
    rogue.mkdir(exist_ok=True)
    ws = _workspace(rogue)
    toolkit = CoderToolkit(
        repository=FakeRepo([ws]),
        configured_root=configured,
    )

    result = _run(toolkit, ws, "list_files")

    assert not result.ok
    assert "escapes configured root" in result.content