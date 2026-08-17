from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable
from uuid import UUID

from .repositories import CoderRepository
from .workspaces import WorkspaceAccessError, WorkspaceService

_SKIPPED_DIRS = frozenset({
    ".git",
    "node_modules",
    ".next",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
})

_MAX_TOOL_OUTPUT_CHARS = 8000
_MAX_TREE_DEPTH = 3


@dataclass(frozen=True)
class ToolResult:
    content: str
    kind: str
    ok: bool = True


class ToolExecutionError(RuntimeError):
    pass


class CoderToolkit:
    """Local tool execution for the DEFENDcoder agent.

    Every file/command operation is confined to the owning user's
    workspace root via WorkspaceService.resolve_owned_path. Output is
    capped so a runaway command cannot flood the model context.
    """

    def __init__(
        self,
        *,
        repository: CoderRepository,
        configured_root: str | Path,
        log_reader: Callable[[int], str] | None = None,
    ) -> None:
        self._workspaces = WorkspaceService(
            repository=repository,
            configured_root=configured_root,
        )
        self._log_reader = log_reader

    def schema(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": (
                        "List files and directories inside the workspace. "
                        "Use this first to understand the project layout."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": (
                                    "Relative path to list; '.' for the "
                                    "workspace root."
                                ),
                                "default": ".",
                            }
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": (
                        "Read the contents of a file inside the workspace. "
                        "Long files are truncated."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": (
                                    "Relative path of the file to read."
                                ),
                            },
                            "max_chars": {
                                "type": "integer",
                                "description": (
                                    "Optional character cap for the "
                                    "returned content."
                                ),
                                "default": 12000,
                            },
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": (
                        "Create a new file or overwrite an existing file "
                        "inside the workspace with the given content."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": (
                                    "Relative path of the file to write."
                                ),
                            },
                            "content": {
                                "type": "string",
                                "description": (
                                    "Full file content to write."
                                ),
                            },
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "description": (
                        "Apply a targeted text replacement to an existing "
                        "file. Only the first occurrence of old_text is "
                        "replaced. Prefer this over write_file for "
                        "modifying existing code."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": (
                                    "Relative path of the file to edit."
                                ),
                            },
                            "old_text": {
                                "type": "string",
                                "description": (
                                    "The exact existing text to replace "
                                    "(must appear verbatim in the file)."
                                ),
                            },
                            "new_text": {
                                "type": "string",
                                "description": (
                                    "The replacement text."
                                ),
                            },
                        },
                        "required": ["path", "old_text", "new_text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": (
                        "Run a shell command inside the workspace root. "
                        "Use for builds, scaffolding, installing packages, "
                        "or any verification that is not a test run."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": (
                                    "The shell command to execute."
                                ),
                            },
                            "timeout_seconds": {
                                "type": "integer",
                                "description": (
                                    "Optional timeout; defaults to 60."
                                ),
                                "default": 60,
                            },
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_tests",
                    "description": (
                        "Run the workspace test suite. Detects the runner: "
                        "npm test for package.json projects, pytest for "
                        "Python projects, node --test for plain JS test "
                        "files. Run this after implementing or fixing code."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "git_diff",
                    "description": (
                        "Show the current uncommitted changes in the "
                        "workspace as a diff summary, or state that the "
                        "workspace is clean / not a git repository."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_logs",
                    "description": (
                        "Read the recent agent run log for this task "
                        "(tool calls, errors, and outcomes)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tail": {
                                "type": "integer",
                                "description": (
                                    "Number of recent log lines to return."
                                ),
                                "default": 100,
                            }
                        },
                    },
                },
            },
        ]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        account_id: UUID,
        workspace_id: UUID,
    ) -> ToolResult:
        try:
            handler = self._handlers().get(name)
            if handler is None:
                return ToolResult(
                    f"tool error: unknown tool {name!r}",
                    kind="log",
                    ok=False,
                )
            return handler(arguments, account_id, workspace_id)
        except ToolExecutionError as error:
            return ToolResult(
                f"tool error: {error}",
                kind=_kind_for(name),
                ok=False,
            )
        except WorkspaceAccessError as error:
            return ToolResult(
                f"tool error: {error}",
                kind="log",
                ok=False,
            )
        except (OSError, ValueError) as error:
            return ToolResult(
                f"tool error: {type(error).__name__}: {error}",
                kind=_kind_for(name),
                ok=False,
            )

    def _handlers(self) -> dict[str, Callable[..., ToolResult]]:
        return {
            "list_files": self._list_files,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "edit_file": self._edit_file,
            "run_command": self._run_command,
            "run_tests": self._run_tests,
            "git_diff": self._git_diff,
            "read_logs": self._read_logs,
        }

    def _resolve(
        self,
        account_id: UUID,
        workspace_id: UUID,
        relative_path: str,
    ) -> Path:
        return self._workspaces.resolve_owned_path(
            account_id,
            workspace_id,
            relative_path,
        )

    def _list_files(
        self,
        arguments: dict[str, Any],
        account_id: UUID,
        workspace_id: UUID,
    ) -> ToolResult:
        target = self._resolve(
            account_id,
            workspace_id,
            str(arguments.get("path") or "."),
        )
        if target.is_file():
            return ToolResult(
                f"{target.name} (file)",
                kind="file",
            )
        if not target.is_dir():
            raise ToolExecutionError(f"{target} does not exist")

        lines: list[str] = []
        for root, dirs, files in os.walk(target):
            dirs[:] = sorted(
                d
                for d in dirs
                if d not in _SKIPPED_DIRS
            )
            relative = Path(root).relative_to(target)
            depth = 0 if str(relative) == "." else len(relative.parts)
            if depth > _MAX_TREE_DEPTH:
                dirs[:] = []
                continue
            prefix = "  " * depth
            if depth == 0:
                lines.append(f"{target.name}/")
            else:
                lines.append(f"{prefix}{relative.name}/")
            for name in sorted(files):
                lines.append(f"{prefix}  {name}")
        content = "\n".join(lines) or f"{target.name}/ (empty)"
        return ToolResult(content, kind="file")

    def _read_file(
        self,
        arguments: dict[str, Any],
        account_id: UUID,
        workspace_id: UUID,
    ) -> ToolResult:
        target = self._resolve(
            account_id,
            workspace_id,
            str(arguments.get("path") or ""),
        )
        if not target.is_file():
            raise ToolExecutionError(f"{target} is not a file")
        try:
            raw = target.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            raise ToolExecutionError(
                f"could not read {target} ({type(error).__name__})"
            ) from None
        cap = int(arguments.get("max_chars") or 12000)
        cap = max(256, min(cap, 60000))
        content = raw if len(raw) <= cap else (
            raw[:cap] + f"\n...[truncated {len(raw) - cap} chars]"
        )
        return ToolResult(content, kind="file")

    def _write_file(
        self,
        arguments: dict[str, Any],
        account_id: UUID,
        workspace_id: UUID,
    ) -> ToolResult:
        target = self._resolve(
            account_id,
            workspace_id,
            str(arguments.get("path") or ""),
        )
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolExecutionError("content is required")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_dir():
            raise ToolExecutionError(f"{target} is a directory")
        target.write_text(content, encoding="utf-8")
        return ToolResult(
            f"wrote {len(content.encode('utf-8'))} bytes to {target.name}",
            kind="file",
        )

    def _edit_file(
        self,
        arguments: dict[str, Any],
        account_id: UUID,
        workspace_id: UUID,
    ) -> ToolResult:
        target = self._resolve(
            account_id,
            workspace_id,
            str(arguments.get("path") or ""),
        )
        old_text = arguments.get("old_text")
        new_text = arguments.get("new_text")
        if not isinstance(old_text, str) or not old_text:
            raise ToolExecutionError("old_text is required")
        if not isinstance(new_text, str):
            raise ToolExecutionError("new_text is required")
        if not target.is_file():
            raise ToolExecutionError(f"{target} is not a file")
        raw = target.read_text(encoding="utf-8", errors="replace")
        index = raw.find(old_text)
        if index < 0:
            raise ToolExecutionError(
                "old_text was not found in the file; read the file first "
                "and match the exact existing text"
            )
        updated = raw[:index] + new_text + raw[index + len(old_text):]
        target.write_text(updated, encoding="utf-8")
        return ToolResult(
            f"replaced first occurrence in {target.name} "
            f"({len(old_text)} -> {len(new_text)} chars)",
            kind="file",
        )

    def _run_command(
        self,
        arguments: dict[str, Any],
        account_id: UUID,
        workspace_id: UUID,
    ) -> ToolResult:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ToolExecutionError("command is required")
        workspace_root = self._resolve(
            account_id,
            workspace_id,
            ".",
        )
        if not workspace_root.is_dir():
            raise ToolExecutionError(
                f"workspace root {workspace_root} does not exist"
            )
        timeout = max(1, min(int(arguments.get("timeout_seconds") or 60), 300))
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=str(workspace_root),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise ToolExecutionError(
                f"command timed out after {timeout}s"
            ) from None
        output = _cap_output(
            completed.stdout + (completed.stderr or "")
        )
        status = f"exit code {completed.returncode}"
        return ToolResult(
            f"$ {command}\n{status}\n{output}",
            kind="terminal",
            ok=completed.returncode == 0,
        )

    def _run_tests(
        self,
        arguments: dict[str, Any],
        account_id: UUID,
        workspace_id: UUID,
    ) -> ToolResult:
        workspace_root = self._resolve(
            account_id,
            workspace_id,
            ".",
        )
        if not workspace_root.is_dir():
            raise ToolExecutionError(
                f"workspace root {workspace_root} does not exist"
            )

        command: str | None = None
        if (workspace_root / "package.json").is_file():
            command = "npm test"
        elif _has_pytest(workspace_root):
            command = "python -m pytest -q"
        elif _has_node_test_files(workspace_root):
            command = "node --test"
        else:
            return ToolResult(
                "No test runner detected in the workspace "
                "(no package.json, pytest config, or *.test.* files). "
                "Run a project check or add a test file first.",
                kind="tests",
                ok=False,
            )

        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=str(workspace_root),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            raise ToolExecutionError(
                "tests timed out after 180s"
            ) from None
        output = _cap_output(
            completed.stdout + (completed.stderr or "")
        )
        status = f"$ {command}\nexit code {completed.returncode}"
        return ToolResult(
            f"{status}\n{output}",
            kind="tests",
            ok=completed.returncode == 0,
        )

    def _git_diff(
        self,
        arguments: dict[str, Any],
        account_id: UUID,
        workspace_id: UUID,
    ) -> ToolResult:
        workspace_root = self._resolve(
            account_id,
            workspace_id,
            ".",
        )
        try:
            status = subprocess.run(
                "git status --short",
                shell=True,
                cwd=str(workspace_root),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            raise ToolExecutionError("could not run git status") from None
        if status.returncode != 0:
            return ToolResult(
                "Not a git repository. The workspace has no version "
                "control; changes cannot be shown as a diff.",
                kind="diff",
                ok=False,
            )
        short = status.stdout.strip()
        if not short:
            return ToolResult(
                "Working tree is clean; no uncommitted changes.",
                kind="diff",
            )
        try:
            diff = subprocess.run(
                "git diff --stat",
                shell=True,
                cwd=str(workspace_root),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            raise ToolExecutionError("could not run git diff") from None
        return ToolResult(
            f"git status --short:\n{short}\n\n{diff.stdout.strip()}",
            kind="diff",
        )

    def _read_logs(
        self,
        arguments: dict[str, Any],
        account_id: UUID,
        workspace_id: UUID,
    ) -> ToolResult:
        if self._log_reader is None:
            return ToolResult(
                "Run log is not available for this session.",
                kind="log",
                ok=False,
            )
        tail = max(1, min(int(arguments.get("tail") or 100), 500))
        return ToolResult(
            self._log_reader(tail),
            kind="log",
        )


def _has_pytest(root: Path) -> bool:
    for candidate in ("pytest.ini", "pyproject.toml", "setup.cfg"):
        path = root / candidate
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "pytest" in text:
                return True
    tests_dir = root / "tests"
    if tests_dir.is_dir():
        for entry in tests_dir.iterdir():
            if entry.suffix == ".py":
                return True
    return False


def _has_node_test_files(root: Path) -> bool:
    for pattern in ("*.test.js", "*.test.mjs", "*.test.cjs", "*.test.ts"):
        for entry in root.glob(pattern):
            if entry.is_file():
                return True
    tests_dir = root / "tests"
    if tests_dir.is_dir():
        for entry in tests_dir.rglob("*.test.*"):
            if entry.is_file():
                return True
    return False


def _cap_output(text: str) -> str:
    if len(text) <= _MAX_TOOL_OUTPUT_CHARS:
        return text.strip()
    return (
        text[:_MAX_TOOL_OUTPUT_CHARS]
        + f"\n...[output truncated, {len(text) - _MAX_TOOL_OUTPUT_CHARS} chars]"
    ).strip()


def _kind_for(tool_name: str) -> str:
    return {
        "run_command": "terminal",
        "run_tests": "tests",
        "git_diff": "diff",
        "list_files": "file",
        "read_file": "file",
        "write_file": "file",
        "edit_file": "file",
    }.get(tool_name, "log")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)