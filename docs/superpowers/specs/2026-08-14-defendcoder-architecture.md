# DEFENDcoder Architecture
Date: 2026-08-14
Status: BINDING (v0 implementation target)
Amendments: configurable session budget; provider_run_id/instance_id in traces; immutable completed traces; generalized branch policy

## Purpose
DEFENDcoder is the owner-only coding product of the DEFEND platform. It is not the identity chat model. It is a coding agent runtime with interchangeable models, providers, and tool adapters, orchestrated by the DEFEND Control Center.

## Non-negotiables
- Identity ≠ coder
- Agent Runtime is the product core
- Aider / OpenHands are replaceable adapters only
- Model and provider abstraction via registry + InferenceProvider
- ControlPlane owns compute orchestration
- Risk-tiered permissions (worktree is the security boundary)
- Worktree isolation from production checkouts and data roots
- Structured trace capture from day one
- RepoContextManager preferred over dumping maximum context
- Coding LoRA only after DEFEND-Bench and real traces justify it
- Reviewer loop = V2; planner sophistication = V2; automated routing = V2; training flywheel = V3

## Platform placement

```text
DEFEND Control Center
├── DEFEND        identity model, RAG/memory, public tools
├── SCS           operational/business application
└── DEFENDcoder   coding model, agent runtime, repo tools,
                  isolated workspaces, git, test/lint/terminal, policy
