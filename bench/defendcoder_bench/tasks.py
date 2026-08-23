"""Benchmark task workspace fixtures.

Tasks are deterministic: the fixture files are materialized into a
temporary workspace before each run and the expected outcomes are
checked by content, not by hash, so small formatting differences in the
agent's output do not produce false negatives.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Task:
    id: str
    task_class: str
    title: str
    prompt: str
    files: dict[str, str] = field(default_factory=dict)
    expected: dict[str, list[str]] = field(default_factory=dict)
    forbidden: tuple[str, ...] = ()
    inspect_required: tuple[str, ...] = ()
    max_steps: int = 8
    script: list[dict[str, Any]] = field(default_factory=list)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def materialize_workspace(root: Path, files: dict[str, str]) -> dict[str, str]:
    """Write the fixture files and return relpath -> sha256 of originals."""
    root = Path(root).resolve()
    original_hashes: dict[str, str] = {}
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        original_hashes[relative] = _hash(content)
    return original_hashes


def workspace_hashes(root: Path, relative_paths: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in relative_paths:
        target = root / relative
        if target.is_file():
            result[relative] = _hash(
                target.read_text(encoding="utf-8")
            )
    return result


def cleanup_workspace(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


A_SCRATCH = Task(
    id="a_scratch_fibonacci",
    task_class="A",
    title="Scratch implementation from spec",
    prompt=(
        "Create a new Python module fib.py in this workspace that defines "
        "a function nth_fib(n) returning the n-th Fibonacci number "
        "(0-indexed, nth_fib(0) == 0, nth_fib(1) == 1). "
        "Keep the module self-contained with no imports beyond the "
        "standard library."
    ),
    expected={"fib.py": ["def nth_fib", "return"]},
    max_steps=6,
    script=[
        {"tool": "list_files", "arguments": {"path": "."}},
        {
            "tool": "write_file",
            "arguments": {
                "path": "fib.py",
                "content": (
                    "def nth_fib(n):\n"
                    "    if n < 0:\n"
                    "        raise ValueError('n must be non-negative')\n"
                    "    a, b = 0, 1\n"
                    "    for _ in range(n):\n"
                    "        a, b = b, a + b\n"
                    "    return a\n"
                ),
            },
        },
        {
            "text": (
                "Created fib.py with nth_fib(n) implementing the "
                "0-indexed Fibonacci sequence. I verified the base cases "
                "by reading the module back."
            )
        },
    ],
)

B_FIX_FAILING_TESTS = Task(
    id="b_fix_failing_tests",
    task_class="B",
    title="Fix failing tests",
    prompt=(
        "The test suite in this workspace is failing. Run the tests, "
        "find the bug in app.py, fix the smallest possible change, and "
        "re-run the tests until they pass."
    ),
    files={
        "app.py": (
            "def add(a, b):\n"
            "    return a - b\n"
        ),
        "test_app.py": (
            "from app import add\n\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n"
            "    assert add(-1, 1) == 0\n"
        ),
    },
    expected={"app.py": ["a + b"]},
    max_steps=8,
    script=[
        {
            "tool": "run_command",
            "arguments": {
                "command": "python -B -m pytest --basetemp .pytest_tmp",
                "timeout_seconds": 60,
            },
            "expect_error": True,
        },
        {"tool": "read_file", "arguments": {"path": "app.py"}},
        {
            "tool": "edit_file",
            "arguments": {
                "path": "app.py",
                "old_text": "    return a - b",
                "new_text": "    return a + b",
            },
        },
        {
            "tool": "run_command",
            "arguments": {
                "command": "python -B -m pytest --basetemp .pytest_tmp",
                "timeout_seconds": 60,
            },
        },
        {"text": "Fixed the bug in app.py; the test suite now passes."},
    ],
)

C_BUG_REPRO = Task(
    id="c_bug_repro_steps",
    task_class="C",
    title="Bug fix from reproduction steps",
    prompt=(
        "Reproduce and fix this bug: calculator.py's convert_temperature "
        "returns 32.0 for convert_temperature(100, 'C', 'F') instead of "
        "212.0, so Fahrenheit conversions are wrong by 180. Find the "
        "defect and fix it. Do not change the public function signature."
    ),
    files={
        "calculator.py": (
            "def convert_temperature(value, from_unit, to_unit):\n"
            "    if from_unit == 'C' and to_unit == 'F':\n"
            "        return value * 9 / 5\n"
            "    if from_unit == 'F' and to_unit == 'C':\n"
            "        return (value - 32) * 5 / 9\n"
            "    return value\n"
        ),
        "notes.txt": (
            "# Conversion notes\n"
            "Handle C->F, F->C, and passthrough.\n"
        ),
    },
    expected={"calculator.py": ["+ 32"]},
    forbidden=("notes.txt",),
    max_steps=8,
    script=[
        {"tool": "read_file", "arguments": {"path": "calculator.py"}},
        {
            "tool": "edit_file",
            "arguments": {
                "path": "calculator.py",
                "old_text": "        return value * 9 / 5",
                "new_text": "        return value * 9 / 5 + 32",
            },
        },
        {"text": "Fixed the missing +32 offset in the C-to-F branch."},
    ],
)

D_TARGETED_EDIT = Task(
    id="d_targeted_config_edit",
    task_class="D",
    title="Targeted edit of existing code",
    prompt=(
        "The service config.json has the port set to 8080. Change ONLY "
        "the port value to 9090 and leave every other key untouched, "
        "including the comments in notes.txt."
    ),
    files={
        "config.json": (
            "{\n"
            "  \"server\": {\n"
            "    \"host\": \"127.0.0.1\",\n"
            "    \"port\": 8080\n"
            "  },\n"
            "  \"log_level\": \"info\"\n"
            "}\n"
        ),
        "notes.txt": (
            "# Deployment notes\n"
            "The API listens on the port in config.json.\n"
        ),
    },
    expected={"config.json": ['"port": 9090']},
    forbidden=("notes.txt",),
    max_steps=8,
    script=[
        {"tool": "read_file", "arguments": {"path": "config.json"}},
        {
            "tool": "write_file",
            "arguments": {
                "path": "config.json",
                "content": (
                    "{\n"
                    "  \"server\": {\n"
                    "    \"host\": \"127.0.0.1\",\n"
                    "    \"port\": 9090\n"
                    "  },\n"
                    "  \"log_level\": \"info\"\n"
                    "}\n"
                ),
            },
        },
        {"text": "Updated the port to 9090; nothing else changed."},
    ],
)

E_REFACTOR = Task(
    id="e_refactor_rename",
    task_class="E",
    title="Refactor without behavior change",
    prompt=(
        "Refactor utils.py: rename the function old_name to "
        "compute_total and update its single docstring reference. "
        "Behavior and output must stay identical."
    ),
    files={
        "utils.py": (
            "def old_name(items):\n"
            "    \"\"\"Sum the items using the legacy name.\"\"\"\n"
            "    return sum(items)\n"
        ),
    },
    expected={"utils.py": ["def compute_total"]},
    max_steps=6,
    script=[
        {"tool": "read_file", "arguments": {"path": "utils.py"}},
        {
            "tool": "write_file",
            "arguments": {
                "path": "utils.py",
                "content": (
                    "def compute_total(items):\n"
                    "    \"\"\"Sum the items using the legacy name.\"\"\"\n"
                    "    return sum(items)\n"
                ),
            },
        },
        {"text": "Renamed old_name to compute_total; behavior unchanged."},
    ],
)

F_DOCS = Task(
    id="f_docs_readme",
    task_class="F",
    title="Documentation update",
    prompt=(
        "Add a '## Usage' section to README.md with a one-line example "
        "command. Keep the existing title and description intact."
    ),
    files={
        "README.md": (
            "# sample\n"
            "A tiny sample project used to demonstrate the agent.\n"
        ),
        "docs/notes.txt": (
            "# Project notes\n"
            "Internal notes; do not touch.\n"
        ),
    },
    expected={"README.md": ["## Usage"]},
    forbidden=("docs/notes.txt",),
    max_steps=6,
    script=[
        {"tool": "read_file", "arguments": {"path": "README.md"}},
        {
            "tool": "edit_file",
            "arguments": {
                "path": "README.md",
                "old_text": "# sample\nA tiny sample project used to demonstrate the agent.",
                "new_text": (
                    "# sample\n"
                    "A tiny sample project used to demonstrate the agent.\n\n"
                    "## Usage\n"
                    "```\n"
                    "python app.py\n"
                    "```"
                ),
            },
        },
        {"text": "Added the Usage section with an example command."},
    ],
)

G_UTILITY = Task(
    id="g_utility_script",
    task_class="G",
    title="Small utility script",
    prompt=(
        "Create count_lines.py: a script that reads the file path given "
        "as its first command-line argument and prints the number of "
        "lines in that file to stdout."
    ),
    expected={"count_lines.py": ["sys.argv", "print"]},
    max_steps=6,
    script=[
        {"tool": "list_files", "arguments": {"path": "."}},
        {
            "tool": "write_file",
            "arguments": {
                "path": "count_lines.py",
                "content": (
                    "import sys\n\n\n"
                    "def main():\n"
                    "    path = sys.argv[1]\n"
                    "    with open(path, encoding='utf-8') as handle:\n"
                    "        print(sum(1 for _ in handle))\n\n\n"
                    "if __name__ == '__main__':\n"
                    "    main()\n"
                ),
            },
        },
        {
            "text": "Created count_lines.py; it prints the line count of "
            "the file given as the first argument."
        },
    ],
)

H_CONFIG = Task(
    id="h_ci_config",
    task_class="H",
    title="Configuration file change",
    prompt=(
        "Update ci.yml: add a 'lint' job that runs on ubuntu-latest "
        "with a single step that executes 'python -m flake8'. Preserve "
        "the existing build job exactly."
    ),
    files={
        "ci.yml": (
            "jobs:\n"
            "  build:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: python -m pytest\n"
        ),
        "README.md": "# ci\nCI pipeline config.\n",
    },
    expected={"ci.yml": ["lint", "python -m flake8"]},
    forbidden=("README.md",),
    max_steps=6,
    script=[
        {"tool": "read_file", "arguments": {"path": "ci.yml"}},
        {
            "tool": "edit_file",
            "arguments": {
                "path": "ci.yml",
                "old_text": "      - run: python -m pytest",
                "new_text": (
                    "      - run: python -m pytest\n"
                    "  lint:\n"
                    "    runs-on: ubuntu-latest\n"
                    "    steps:\n"
                    "      - run: python -m flake8"
                ),
            },
        },
        {"text": "Added the lint job with flake8; build job preserved."},
    ],
)

I_INSPECT = Task(
    id="i_inspect_report",
    task_class="I",
    title="Inspection and report only",
    prompt=(
        "Inspect this workspace and report which file contains the "
        "marker line 'DEPLOY_TARGET=blue'. Make NO changes to any file."
    ),
    files={
        "app.py": "VERSION = 3\n",
        "config/local.env": "DEPLOY_TARGET=blue\n",
        "README.md": "# project\n",
    },
    inspect_required=("config/local.env",),
    expected={"config/local.env": ["DEPLOY_TARGET=blue"]},
    max_steps=6,
    script=[
        {"tool": "list_files", "arguments": {"path": "."}},
        {"tool": "read_file", "arguments": {"path": "app.py"}},
        {"tool": "read_file", "arguments": {"path": "config/local.env"}},
        {"tool": "read_file", "arguments": {"path": "README.md"}},
        {
            "text": (
                "The marker 'DEPLOY_TARGET=blue' is in config/local.env. "
                "No files were modified."
            )
        },
    ],
)

J_MULTI_FILE = Task(
    id="j_multi_file_dashboard",
    task_class="J",
    title="Multi-file feature assembly",
    prompt=(
        "Build a minimal web dashboard in this workspace: index.html "
        "that links style.css and app.js, a style.css with a body "
        "background rule, and an app.js that updates the page heading "
        "text. All three files must reference each other consistently."
    ),
    expected={
        "index.html": ["style.css", "app.js"],
        "style.css": ["background"],
        "app.js": ["heading"],
    },
    max_steps=10,
    script=[
        {"tool": "list_files", "arguments": {"path": "."}},
        {
            "tool": "write_file",
            "arguments": {
                "path": "index.html",
                "content": (
                    "<!DOCTYPE html>\n"
                    "<html><head>\n"
                    "  <link rel=\"stylesheet\" href=\"style.css\">\n"
                    "  <script src=\"app.js\"></script>\n"
                    "</head><body>\n"
                    "  <h1 id=\"heading\">Dashboard</h1>\n"
                    "</body></html>\n"
                ),
            },
        },
        {
            "tool": "write_file",
            "arguments": {
                "path": "style.css",
                "content": "body { background: #f4f4f4; }\n",
            },
        },
        {
            "tool": "write_file",
            "arguments": {
                "path": "app.js",
                "content": (
                    "const heading = document.getElementById('heading');\n"
                    "if (heading) { heading.textContent = 'Live'; }\n"
                ),
            },
        },
        {
            "text": "Built the three-file dashboard with consistent links."
        },
    ],
)

TASKS: tuple[Task, ...] = (
    A_SCRATCH,
    B_FIX_FAILING_TESTS,
    C_BUG_REPRO,
    D_TARGETED_EDIT,
    E_REFACTOR,
    F_DOCS,
    G_UTILITY,
    H_CONFIG,
    I_INSPECT,
    J_MULTI_FILE,
)

TASK_CLASSES: dict[str, str] = {
    task.id: task.task_class for task in TASKS
}