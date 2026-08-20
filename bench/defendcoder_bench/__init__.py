"""DEFENDcoder benchmark harness (P5-P10/P12).

Runs the real CodingAgent against deterministic, self-contained task
workspaces (classes A-J) and scores the results. Two client modes:

- local scripted mode: a deterministic client drives the agent with
  scripted tool calls; runs end-to-end with the real toolkit (file
  writes, path confinement, tool results) but without a model.
- live mode: a real AgentChatClient against an OpenAI-compatible
  endpoint (reserved for owner-approved paid runs; P14).

The manifest records MODEL, AGENT, PROMPT_VERSION and TASK_CLASSES so
benchmarks remain comparable as the agent or model changes (P12).
"""

from .tasks import TASKS, TASK_CLASSES, Task

__all__ = ["TASKS", "TASK_CLASSES", "Task"]

BENCH_VERSION = "2026-08-18.v1"