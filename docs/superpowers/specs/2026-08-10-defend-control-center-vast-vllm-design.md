<!-- DEFEND-AI-INGEST: EXCLUDE -->

# DEFEND Control Center and Vast.ai vLLM Design

**Date:** 2026-08-10
**Status:** Approved

## Objective

Provide one intentional Windows control surface that starts, monitors, stops, and
opens the complete DEFEND stack. The operator chooses either a Vast.ai vLLM
backend or Local Ollama at launch. The current Windows computer continues to host
FastAPI, Next.js, persistent data, and Cloudflare Tunnel; Vast.ai hosts only the
GPU model server.

This phase also makes local setup reproducible by committing complete dependency
manifests and preflight checks. It preserves a clean future migration path from
the Windows host to an always-on VPS without requiring that migration now.

## Approved decisions

- DEFEND starts only after the operator clicks **Start DEFEND**; it does not start
  automatically with Windows.
- A compact **DEFEND Control Center** exposes model selection, service status,
  Start, Stop, Restart, Open DEFEND, and bounded log views.
- Launch mode is selected explicitly each time: **Vast.ai** or **Local Ollama**.
- Local secrets are encrypted for the current Windows account with DPAPI.
- The existing Cloudflare Tunnel remains in use and continues routing the public
  web origin to Next.js on `127.0.0.1:3000`; Next.js proxies API traffic to
  FastAPI on `127.0.0.1:8000`.
- Vast.ai serves the full 32B Hugging Face base model with the private
  `Defend-network/defend-qwen-32b-lora` adapter through vLLM's OpenAI-compatible
  API on a single 80 GB A100 or H100 class GPU.
- `Defend-network/defend-qwen-32b-gguf` remains available for llama.cpp-style
  deployments but is not used by the approved vLLM path.

## Architecture

### Local Windows host

The Windows host owns:

- the Control Center and process supervisor;
- FastAPI and the identity, visitor, conversation, audit, and RAG stores;
- the Next.js frontend;
- the existing Cloudflare Tunnel;
- durable data rooted at `C:\DEFEND_DATA` unless explicitly reconfigured; and
- an optional Local Ollama fallback.

All application services bind to loopback. Cloudflare Tunnel is the only intended
public ingress. The host must remain awake, connected, and running for the public
site to remain available.

### Vast.ai model host

Vast.ai owns only the vLLM process and its downloaded Hugging Face model files.
The selected offer must provide one verified 80 GB A100/H100 class GPU, sufficient
disk space for the base model and adapter, and the required public networking.

The instance runs a pinned `vllm/vllm-openai` image with:

- the base repository read from the adapter's `adapter_config.json` after
  authenticated Hugging Face access;
- `--enable-lora`;
- a `defend` LoRA module mapped to
  `Defend-network/defend-qwen-32b-lora`;
- a stable served-model alias, `defend-ai`;
- an 8,192-token initial maximum context window;
- an API key generated and stored locally by the Control Center;
- vLLM bound inside the instance rather than exposed as an unauthenticated public
  HTTP service; and
- a Control Center-owned SSH local port forward from `127.0.0.1:8001` to the
  instance's vLLM port.

The DEFEND API uses its existing OpenAI-compatible client with
`DEFEND_MODEL_BACKEND=openai_compatible`, `DEFEND_MODEL=defend-ai`, the resolved
local `http://127.0.0.1:8001/v1` base URL, and the locally injected API key. The
SSH transport encrypts prompts and responses between the Windows host and the
Vast.ai instance.

### Control Center boundaries

The Control Center is a small Python/Tkinter Windows application so it can reuse
the repository's Python runtime and remain independently testable. It is divided
into narrow components:

- `SecretStore`: Windows DPAPI encrypt/decrypt, with no secret logging;
- `SettingsStore`: non-secret paths, ports, repository identifiers, and operator
  preferences;
- `DependencyPreflight`: Python, Node, packages, ports, data paths, Cloudflare,
  and environment validation;
- `VastProvider`: offer selection, cost confirmation, instance launch/status,
  endpoint discovery, and instance destruction;
- `SshTunnel`: dedicated-key authentication, per-instance host verification,
  local port forwarding, health, and teardown;
- `ModelProbe`: OpenAI-compatible `/v1/models` and minimal generation health;
- `ProcessSupervisor`: start, health-check, restart, and terminate local services;
- `LogBuffer`: bounded redacted stdout/stderr capture; and
- `ControlCenterUI`: mode selection, status, setup, actions, and safe prompts.

Provider and process interfaces remain independent so a future VPS deployment can
replace the local process supervisor without changing application code.

## Configuration and secret storage

Non-secret settings are stored under
`%LOCALAPPDATA%\DEFEND\control-center.json`. DPAPI-encrypted secret material is
stored separately under `%LOCALAPPDATA%\DEFEND\secrets.dpapi`, scoped to the
current Windows user.

The first-run setup collects secrets locally and never echoes them:

- Vast.ai API key;
- Hugging Face access token for the private model repositories;
- generated vLLM API key;
- DEFEND owner password;
- stable visitor HMAC key;
- Gmail SMTP username and app password; and
- any existing backend bearer secret.

Non-secret setup includes owner username/email, public web origin, data root,
Cloudflare executable/config paths, model/adapter repository identifiers, local
ports, and an operator-entered maximum Vast.ai hourly price.

Secrets are injected only into child-process environments or provider requests.
They are excluded from Git, frontend variables, process command lines where the
underlying tool supports environment injection, logs, audit events, crash output,
and screenshots. DPAPI protects local files at rest but does not protect an
already-compromised signed-in Windows account; this limitation is stated in the
setup UI. Local secret files receive a current-user-only Windows ACL. Vast.ai SSH
uses a dedicated key rather than the user's general-purpose GitHub key.

## Startup flow

`Start DEFEND.cmd` launches the Control Center through the repository virtual
environment. A first-run bootstrap command creates or repairs that environment
and performs `npm.cmd ci` before the Control Center is launched.

When **Start** is pressed:

1. Acquire a single-instance lock and refuse duplicate supervisors.
2. Load and decrypt configuration, then validate required values without printing
   them.
3. Verify data directories, dependency manifests, ports 3000/8000, and the
   invitation-transport rollout gate.
4. For **Local Ollama**, verify Ollama and the configured local model.
5. For **Vast.ai**:
   - read and validate the private adapter configuration;
   - reuse a healthy known instance when possible;
   - otherwise show an eligible 80 GB offer and exact hourly price, and require
     confirmation before creating the billable instance;
   - launch vLLM, establish the SSH local port forward, verify the instance host
     fingerprint on first connection and pin it for that instance, then poll
     bounded status/readiness checks; and
   - refuse to start DEFEND chat traffic unless the served model and LoRA alias
     are verified.
6. Start FastAPI and wait for `/health`.
7. Start Next.js in production mode and wait for its local health response.
8. Reuse a healthy existing Cloudflare Tunnel or start the configured named
   tunnel, then verify the public web and API paths.
9. Mark the stack ready and enable **Open DEFEND**.

Partial failures trigger reverse-order cleanup for processes started during that
attempt. The Control Center leaves persistent data untouched.

## Stop, restart, and cost safety

**Stop local services** terminates only processes owned by the Control Center in
reverse dependency order. It does not kill unrelated Python, Node, Ollama, or
Cloudflare processes.

When Vast.ai is active, the UI separately offers **Stop services and destroy Vast
instance**. It shows the instance identifier and billing consequence and requires
explicit confirmation before the external destructive action. The ordinary local
stop action warns when a billable instance remains active.

Restart preserves the selected mode and reuses a healthy Vast.ai instance. If the
instance is missing or unhealthy, replacement requires a fresh price confirmation.

## Dependency and update reliability

The repository gains:

- a committed Python runtime dependency manifest covering FastAPI, Uvicorn,
  HTTP/document/RAG/search support, multipart uploads, and all registered tools;
- a reproducible development/test dependency manifest;
- the existing committed `package-lock.json`, installed with `npm.cmd ci`;
- a bootstrap/preflight command that reports all missing prerequisites in one
  pass instead of failing through successive imports; and
- startup documentation using only configuration names and safe procedures.

The Control Center may display whether the local branch is behind GitHub, but it
does not silently pull, merge, overwrite local changes, or deploy unreviewed code.
Updating remains an explicit separate action with clean-worktree and backup
checks.

## Error handling and observability

- Statuses are explicit: stopped, validating, provisioning, starting, ready,
  degraded, stopping, and failed.
- Every failure names the component and a safe corrective action.
- Polling has bounded timeouts and cancellation.
- Local logs use size/entry bounds and recursive secret-shaped redaction.
- Provider responses are reduced to identifiers, state, GPU, price, and safe
  diagnostics; authorization headers and response bodies are not logged.
- The vLLM HTTP port is not treated as safe public ingress; model traffic passes
  through the owned SSH tunnel and the local API calls only loopback.
- A model outage degrades chat but does not corrupt identity or telemetry data.
- The launcher never reports ready until local health, model readiness, and public
  routing checks all pass.

## Testing and acceptance

Automated tests cover:

- DPAPI abstraction behavior and failure handling without real production
  secrets;
- settings validation and secret redaction;
- dependency and port preflight aggregation;
- process ownership, duplicate-start prevention, ordered cleanup, and restart;
- Vast.ai request construction through a fake provider, price confirmation,
  timeout, cancellation, and destruction confirmation;
- adapter base-model discovery and LoRA launch configuration;
- SSH host verification, tunnel loss, local-port collision, and teardown;
- OpenAI-compatible readiness and generation probes;
- local Ollama mode;
- existing backend and frontend regression suites; and
- Python compilation, TypeScript checking, and Next.js production build.

Final manual acceptance uses one real, explicitly approved Vast.ai instance:

1. Enter secrets only through the local setup UI.
2. Select Vast.ai and confirm the displayed offer price.
3. Start the stack and verify all status indicators become ready.
4. Open `https://ai.defend-network.org` and complete one ordinary chat exchange.
5. Verify the response came from the `defend` LoRA alias without secrets appearing
   in browser, application, audit, or Control Center logs.
6. Stop local services, destroy the Vast.ai instance, and verify billing-active
   state is cleared.

## Non-goals

This phase does not move persistent services to a VPS, start DEFEND automatically
with Windows, train or alter the LoRA, convert the GGUF model, implement silent
GitHub auto-deployment, or choose/purchase GPU capacity without explicit operator
confirmation.

## Migration path

The future VPS migration moves FastAPI, Next.js, persistent stores, and
Cloudflare Tunnel behind the same environment/configuration contract. The Vast.ai
vLLM provider and model alias remain unchanged. The local Control Center then
becomes a development and emergency-fallback supervisor rather than the primary
production host.
