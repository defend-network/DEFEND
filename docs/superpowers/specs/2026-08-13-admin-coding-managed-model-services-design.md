Exit code: 0
Wall time: 0.6 seconds
Output:
# Admin Coding and Managed Model Services Design

## Objective

Evolve DEFEND into a permissioned AI runtime with interchangeable services. Public users retain the primary DEFEND assistant. Owners gain a separate coding workspace. Retrieval embeddings become a managed service instead of an undocumented local Ollama dependency.

## Phased delivery

1. Add an explicit embedding-provider abstraction and managed vLLM embedding service.
2. Add an owner-only Coding Workspace with isolated worktrees and read-only repository tools.
3. Add reviewed patches, bounded structured commands, tests, local Git operations, and explicit draft-PR publishing.
4. Benchmark the official coding model and consider a coding LoRA only if evaluation proves it useful.
5. Build the canonical Person, screening, applicant, and membership domain as a separate program.

Public chat must remain operational after every phase.

## Model-service architecture

Use one sufficiently capable Vast instance with isolated localhost services and SSH tunnels:

- primary chat vLLM on remote `8000`, mapped to local `8001`;
- Qwen embedding vLLM on remote `8002`, mapped to a new local loopback port;
- coding vLLM on remote `8003`, mapped separately and started on demand.

Each service has a distinct credential and served-model alias. Cloudflare never exposes model ports. Because exact simultaneous residency depends on model size, quantization, KV cache, and GPU, the launcher never assumes all services fit. Coding can pause/replace chat only through an explicit, visible owner action and must report Vast billing state.

## Managed RAG embeddings

Implement `EmbeddingClient` providers for OpenAI-compatible vLLM, explicit local Ollama fallback, and deterministic tests. Configure provider, endpoint, model, dimension, timeout, and credential separately.

Start with `Qwen/Qwen3-Embedding-0.6B` at 1024 dimensions. Build a retrieval evaluation set before considering 4B/8B. A model or dimension change creates a new index generation and requires re-embedding; incompatible vectors never share a table.

RAG ingestion checks readiness before accepting a batch. The Admin panel displays provider/model status and clear remediation.

## Owner-only Coding Workspace

Coding tools are absent from public registries, prompts, routes, and navigation. A dedicated router/service requires `owner` initially; future delegation uses an explicit `coding_operator` permission.

`WorkspaceManager` creates disposable Git worktrees or clones beneath a configured coding root. Every workspace records an opaque ID, repository/revision, owner, resolved root, lifecycle, expiry, budgets, and append-only audit events. Path traversal, junction/symlink escapes, alternate data streams, device paths, the production checkout, `C:\DEFEND_DATA`, and other workspaces are rejected.

Initial tools:

- `repo.list`
- `repo.read`
- `repo.search`
- `repo.diff`
- `test.discover`

Reviewed second-stage tools:

- `repo.apply_patch` with path/diff limits
- `terminal.exec` using structured argument arrays, allowlists, timeouts, output caps, and workspace-only working directories
- `test.run` using registered project commands
- `git.status`, `git.diff`, and local `git.commit`
- a separate explicit push/draft-PR action

There is no arbitrary shell-string endpoint. Destructive operations, credential changes, unrestricted networking, and external writes remain unavailable.

Each agent run has step, time, token, command, changed-file, and diff-size budgets. It stops on completion, cancellation, exhaustion, repeated identical failures, or required approval. Writes and commands require owner review initially. GitHub publication always remains explicit.

The Admin UI shows service readiness, workspace creation, task input, proposed actions, approval controls, bounded events, file diffs, tests, commit/PR actions, cancellation, and disposal.

## Training strategy

Train the primary DEFEND LoRA on stable behavior: voice, tool selection, structured reports, policy, and workflows. Keep changing facts in RAG and sensitive member/screening data in permission-checked databases.

Begin coding with the official Qwen3-Coder instruct model. Build `DEFEND-Bench` from real repository tasks and grade requirements, tests, regressions, unrelated edits, tool calls, runtime, and cost. Compare the same tasks with Qwen Code. Train a coding LoRA only when traces show recurring deficiencies that prompting, tools, and context retrieval do not solve.

Replace the hard-coded 8192-token limit with validated model profiles. Long context complements repository search; it does not replace file maps, symbols, dependency/search results, diffs, and selected ranges.

## Person and membership boundary

Background Check cases eventually reference one canonical `Person`. Applicant and Member are lifecycle relationships rather than duplicate records. Screening, applications, interviews, notes, tasks, documents, communications, status history, and audit events retain separate permissions and retention.

Screening tools provide attributable evidence for human review and never approve, deny, discipline, rank, or infer protected characteristics. Social-media and voter-status providers require jurisdiction-specific permissible-purpose rules, terms review, minimization, retention controls, and legal review before activation.

## Failure handling and acceptance

- Missing embeddings block ingestion, not chat.
- Coding failures stop only coding runs.
- Failed model transitions restore the prior service when possible.
- Cancellation terminates child commands and preserves audit/diff state.
- Unprovable workspace containment quarantines the workspace.
- Model aliases, dimensions, and index generations are validated before switching traffic.

Tests cover provider selection/readiness, vector generations, owner authorization, public-registry separation, containment, commands, budgets, cancellation, audit redaction, UI authorization and approvals, Windows repeated starts/stops, Vast localhost ports/credentials/tunnels, service transitions, rollback, full backend/frontend suites, and the production build.

## First-plan non-goals

- training/publishing a LoRA
- autonomous GitHub pushes or merges
- arbitrary shell access
- guaranteed simultaneous residency for unknown model profiles
- live court, sanctions, social, voter, or commercial screening providers
- automatic membership decisions
- the complete Membership CRM

