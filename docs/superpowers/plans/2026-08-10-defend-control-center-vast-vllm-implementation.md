<!-- DEFEND-AI-INGEST: EXCLUDE -->

# DEFEND Control Center and Vast.ai vLLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Build a one-click Windows Control Center that reproducibly starts DEFEND against either Local Ollama or a securely tunneled Vast.ai vLLM instance serving the private DEFEND LoRA.

**Architecture:** A focused defend_control Python package owns encrypted settings, preflight validation, provider calls, SSH transport, process supervision, and orchestration. A thin Tkinter UI consumes those interfaces; FastAPI, Next.js, Cloudflare Tunnel, and the existing model clients remain separate child services.

**Tech Stack:** Python 3.14, Tkinter, Windows DPAPI/ACL APIs, httpx, OpenSSH, FastAPI/Uvicorn, Next.js 14/Node 24, Vast.ai REST API, Hugging Face Hub HTTP API, vLLM OpenAI-compatible server, pytest, Vitest.

## Global Constraints

- DEFEND does not start automatically. It starts only after the operator clicks Start DEFEND; do not create a Windows auto-start entry.
- Offer Vast.ai and Local Ollama as an explicit choice every launch.
- Keep FastAPI on 127.0.0.1:8000, Next.js on 127.0.0.1:3000, and the local SSH model forward on 127.0.0.1:8001.
- Continue using C:\DEFEND_DATA by default and the existing Cloudflare configuration under the current Windows profile.
- Use the private adapter repository Defend-network/defend-qwen-32b-lora and served LoRA alias defend-ai.
- Preserve Defend-network/defend-qwen-32b-gguf, but do not download, convert, or serve it in the approved vLLM path.
- Discover and pin the base repository/revision from the adapter configuration; never guess the base model.
- Use a single verified on-demand A100/H100-class offer with at least 80,000 MB GPU RAM and an operator-entered hourly-price ceiling.
- Use vllm/vllm-openai:v0.10.0, max model length 8192, and a 160 GB initial instance disk.
- Require an exact price confirmation before creating a billable Vast.ai instance and a separate destructive confirmation before destroying it.
- Send model traffic only through a Control Center-owned SSH local forward; do not expose or consume an unauthenticated public vLLM HTTP port.
- Store secrets only in a current-user DPAPI blob with a current-user-only ACL. Never put secrets in Git, frontend variables, command lines, logs, audit metadata, or screenshots.
- Do not silently pull, merge, overwrite local files, change PowerShell execution policy, or run npm audit fix --force.
- Mark every developer operations document with DEFEND-AI-INGEST: EXCLUDE and keep docs/superpowers excluded by the existing ingestion policy.
- Do not execute a real Vast.ai rental or destructive API request in automated tests.

---

## File map

- Create requirements-runtime.txt: pinned direct Python runtime dependencies.
- Create requirements-dev.txt: runtime plus test dependencies.
- Create Bootstrap-DEFEND.ps1: reproducible local install/build and desktop shortcut.
- Create Start-DEFEND.cmd: execution-policy-independent Control Center entrypoint.
- Replace start_api.ps1: secret-free compatibility wrapper.
- Create defend_control/types.py: immutable service, model, offer, instance, and status types.
- Create defend_control/settings.py: immutable ControlSettings and non-secret JSON validation.
- Create defend_control/secrets.py: DPAPI backend, encrypted secret file, and ACL enforcement.
- Create defend_control/redaction.py: bounded secret-shaped log redaction.
- Create defend_control/preflight.py: aggregate prerequisite and rollout validation.
- Create defend_control/windows_job.py: owned Windows Job Object boundary.
- Create defend_control/processes.py: child-process lifecycle and bounded logs.
- Create defend_control/health.py: local/public HTTP and port health probes.
- Create defend_control/local_model.py: Ollama readiness contract.
- Create defend_control/huggingface.py: private adapter metadata and immutable revision discovery.
- Create defend_control/vast.py: official Vast.ai offer and instance lifecycle client.
- Create defend_control/remote_vllm.py: secret-safe remote model download and launch.
- Create defend_control/ssh_tunnel.py: host-key pinning and local forwarding.
- Create defend_control/model_probe.py: vLLM model and generation readiness.
- Create defend_control/orchestrator.py: ordered start/stop/restart state machine.
- Create defend_control/controller.py: UI-safe commands, confirmations, and state projection.
- Create defend_control/ui.py: Tkinter Control Center.
- Create tools/defend_control_center.py: application entrypoint.
- Create tests/test_runtime_dependencies.py.
- Create tests/test_control_settings_secrets.py.
- Create tests/test_control_preflight.py.
- Create tests/test_control_processes.py.
- Create tests/test_control_local.py.
- Create tests/test_control_huggingface_vast.py.
- Create tests/test_control_ssh_model.py.
- Create tests/test_control_orchestrator.py.
- Create tests/test_control_controller.py.
- Modify start_api.TXT and RUN_DEFEND.txt with secret-free operating procedures.

### Task 1: Make setup reproducible and remove tracked launch secrets

**Files:**
- Create: requirements-runtime.txt
- Create: requirements-dev.txt
- Create: Bootstrap-DEFEND.ps1
- Create: Start-DEFEND.cmd
- Modify: start_api.ps1
- Test: tests/test_runtime_dependencies.py

**Interfaces:**
- Produces: Bootstrap-DEFEND.ps1 -Repair, which creates/repairs .venv, installs pinned Python dependencies, runs npm.cmd ci, builds Next.js, and creates a desktop shortcut.
- Produces: Start-DEFEND.cmd, which invokes .venv\Scripts\pythonw.exe -m tools.defend_control_center.
- Produces: a runtime import smoke test used by preflight.

- [ ] **Step 1: Write the failing dependency-manifest test**

~~~python
from pathlib import Path

RUNTIME_IMPORTS = {
    "bs4": "beautifulsoup4",
    "ddgs": "ddgs",
    "fastapi": "fastapi",
    "httpx": "httpx",
    "lancedb": "lancedb",
    "openpyxl": "openpyxl",
    "pdfplumber": "pdfplumber",
    "PIL": "pillow",
    "pymupdf": "pymupdf",
    "uvicorn": "uvicorn",
    "yaml": "pyyaml",
}

def test_runtime_manifest_covers_registered_tool_imports():
    text = Path("requirements-runtime.txt").read_text("utf-8").casefold()
    missing = sorted(package for package in RUNTIME_IMPORTS.values() if package not in text)
    assert missing == []

def test_legacy_start_script_contains_no_literal_key_assignment():
    text = Path("start_api.ps1").read_text("utf-8")
    assert "tvly-" not in text
    assert "DEFEND_OWNER_PASS=" not in text
~~~

- [ ] **Step 2: Run the focused test and verify RED**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_runtime_dependencies.py -v
~~~

Expected: FAIL because requirements-runtime.txt does not exist and start_api.ps1 still contains a literal credential.

- [ ] **Step 3: Add pinned direct dependency manifests**

requirements-runtime.txt must contain exactly these direct runtime requirements:

~~~text
beautifulsoup4==4.15.0
ddgs==9.14.4
fastapi==0.141.1
httpx==0.28.1
lancedb==0.37.1
openpyxl==3.1.5
pdfplumber==0.11.10
pillow==12.3.0
pydantic==2.13.4
pymupdf==1.28.2
python-docx==1.2.0
python-multipart==0.0.32
pyyaml==6.0.3
uvicorn[standard]==0.52.1
~~~

requirements-dev.txt must contain:

~~~text
-r requirements-runtime.txt
pytest==9.1.1
~~~

- [ ] **Step 4: Implement the bootstrap and secret-free entrypoints**

Bootstrap-DEFEND.ps1 must resolve paths relative to itself, use npm.cmd, and stop on every nonzero command:

~~~powershell
param([switch]$Repair)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    py -3.14 -m venv (Join-Path $repo ".venv")
}
& $venvPython -m pip install --requirement (Join-Path $repo "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed" }
& npm.cmd ci --prefix (Join-Path $repo "defend-ui-v2")
if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed" }
& npm.cmd run build --prefix (Join-Path $repo "defend-ui-v2")
if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed" }
~~~

Start-DEFEND.cmd must be:

~~~bat
@echo off
set "DEFEND_REPO=%~dp0"
"%DEFEND_REPO%.venv\Scripts\pythonw.exe" -m tools.defend_control_center
~~~

Bootstrap-DEFEND.ps1 must also create or refresh a desktop shortcut:

~~~powershell
$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $desktop "Start DEFEND.lnk"))
$shortcut.TargetPath = Join-Path $repo "Start-DEFEND.cmd"
$shortcut.WorkingDirectory = $repo
$shortcut.Save()
~~~

Replace start_api.ps1 with a compatibility wrapper that invokes Start-DEFEND.cmd and contains no key values or old Downloads paths. Keep %LOCALAPPDATA%\DEFEND out of .gitignore because it is outside the repository.

- [ ] **Step 5: Run bootstrap contract and import tests**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_runtime_dependencies.py -v
.\.venv\Scripts\python.exe -c "import api_server, registry, rag_store; print('RUNTIME_IMPORTS_OK')"
git diff --check
~~~

Expected: focused tests PASS, import prints RUNTIME_IMPORTS_OK, diff check exits 0.

- [ ] **Step 6: Commit Task 1**

~~~powershell
git add requirements-runtime.txt requirements-dev.txt Bootstrap-DEFEND.ps1 Start-DEFEND.cmd start_api.ps1 tests/test_runtime_dependencies.py
git commit -m "Make DEFEND startup dependencies reproducible"
~~~

### Task 2: Add validated settings, DPAPI secrets, and redacted logs

**Files:**
- Create: defend_control/__init__.py
- Create: defend_control/types.py
- Create: defend_control/settings.py
- Create: defend_control/secrets.py
- Create: defend_control/redaction.py
- Test: tests/test_control_settings_secrets.py

**Interfaces:**
- Produces: ModelMode = Literal["vast", "ollama"].
- Produces: ControlSettings.from_mapping(raw: Mapping[str, object]) -> ControlSettings.
- Produces: JsonSettingsStore.load() and save(settings).
- Produces: SecretBackend.protect(data: bytes) -> bytes and unprotect(data: bytes) -> bytes.
- Produces: DpapiSecretStore.load() -> dict[str, str] and save(values: Mapping[str, str]) -> None.
- Produces: redact_text(value: str, known_secrets: Iterable[str]) -> str.

- [ ] **Step 1: Write RED tests for validation and encrypted persistence**

~~~python
from pathlib import Path
import json
import sys
import pytest

from defend_control.settings import ControlSettings
from defend_control.secrets import DpapiSecretStore
from defend_control.redaction import redact_text

class ReversingBackend:
    def protect(self, data: bytes) -> bytes:
        return data[::-1]
    def unprotect(self, data: bytes) -> bytes:
        return data[::-1]

def valid_settings(tmp_path: Path) -> dict[str, object]:
    return {
        "repo_root": str(tmp_path),
        "data_root": r"C:\DEFEND_DATA",
        "public_web_origin": "https://ai.defend-network.org",
        "cloudflared_exe": r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
        "cloudflared_config": r"C:\Users\operator\.cloudflared\config.yml",
        "cloudflared_tunnel": "defend-ai",
        "adapter_repo": "Defend-network/defend-qwen-32b-lora",
        "local_model": "defend-ai:latest",
        "vast_max_hourly": "3.00",
    }

def test_rejects_non_https_public_origin(tmp_path):
    raw = valid_settings(tmp_path)
    raw["public_web_origin"] = "http://public.example"
    with pytest.raises(ValueError, match="HTTPS"):
        ControlSettings.from_mapping(raw)

def test_secret_store_never_writes_plaintext(tmp_path):
    path = tmp_path / "secrets.dpapi"
    store = DpapiSecretStore(path, backend=ReversingBackend(), acl=lambda _: None)
    store.save({"HF_TOKEN": "hf_private_value"})
    assert b"hf_private_value" not in path.read_bytes()
    assert store.load()["HF_TOKEN"] == "hf_private_value"

@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_real_dpapi_round_trip_is_current_user_scoped(tmp_path):
    path = tmp_path / "real-secrets.dpapi"
    store = DpapiSecretStore(path)
    store.save({"DEFEND_OWNER_PASS": "temporary-test-value"})
    assert store.load() == {"DEFEND_OWNER_PASS": "temporary-test-value"}
    assert b"temporary-test-value" not in path.read_bytes()

def test_redacts_known_and_secret_shaped_values():
    raw = "Authorization: Bearer hf_private_value password=visible"
    cleaned = redact_text(raw, ["hf_private_value"])
    assert "hf_private_value" not in cleaned
    assert "visible" not in cleaned
~~~

- [ ] **Step 2: Run tests and verify RED**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_control_settings_secrets.py -v
~~~

Expected: FAIL because defend_control does not exist.

- [ ] **Step 3: Implement immutable shared types and settings validation**

types.py must define ModelMode and ServiceState. settings.py must define
ControlSettings:

~~~python
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

@dataclass(frozen=True)
class ControlSettings:
    repo_root: Path
    data_root: Path
    public_web_origin: str
    cloudflared_exe: Path
    cloudflared_config: Path
    cloudflared_tunnel: str
    adapter_repo: str
    local_model: str
    vast_max_hourly: Decimal
    api_port: int = 8000
    web_port: int = 3000
    model_port: int = 8001
    vllm_image: str = "vllm/vllm-openai:v0.10.0"
    vllm_disk_gb: int = 160
    max_model_len: int = 8192
~~~

ControlSettings.from_mapping must require an absolute existing repo root, HTTPS public origin, ports in 1..65535 with no duplicates, adapter_repo exactly Defend-network/defend-qwen-32b-lora, positive price cap, and no unknown keys.

- [ ] **Step 4: Implement native DPAPI and current-user ACL**

secrets.py must wrap CryptProtectData/CryptUnprotectData behind SecretBackend. Serialize a versioned UTF-8 JSON object, protect bytes before opening the destination, write through a same-directory temporary file, fsync, replace atomically, and apply an ACL limited to the current user SID. Reject empty decryptions, unknown versions, non-string values, payloads over 64 KiB, and all non-Windows use with a clear unsupported-platform error.

The production constructor is:

~~~python
class DpapiSecretStore:
    def __init__(
        self,
        path: Path,
        *,
        backend: SecretBackend | None = None,
        acl: Callable[[Path], None] = restrict_to_current_user,
    ) -> None: ...

    def save(self, values: Mapping[str, str]) -> None: ...
    def load(self) -> dict[str, str]: ...
~~~

- [ ] **Step 5: Implement bounded recursive redaction**

redact_text must replace exact known secret values and case-insensitive assignments/headers whose key contains token, password, secret, cookie, authorization, api_key, or app_password. Cap input at 64 KiB and output at 16 KiB.

- [ ] **Step 6: Run focused tests and commit**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_control_settings_secrets.py -v
.\.venv\Scripts\python.exe -m compileall -q defend_control
git diff --check
~~~

Expected: PASS.

Commit:

~~~powershell
git add defend_control tests/test_control_settings_secrets.py
git commit -m "Protect DEFEND control center settings"
~~~

### Task 3: Aggregate preflight and own local processes safely

**Files:**
- Create: defend_control/preflight.py
- Create: defend_control/windows_job.py
- Create: defend_control/processes.py
- Create: defend_control/health.py
- Test: tests/test_control_preflight.py
- Test: tests/test_control_processes.py

**Interfaces:**
- Consumes: ControlSettings, ModelMode, DpapiSecretStore, redact_text.
- Produces: CheckResult(name: str, ok: bool, detail: str, remediation: str | None).
- Produces: PreflightRunner.run(mode, settings, secrets) -> tuple[CheckResult, ...].
- Produces: ProcessSpec(name, argv, cwd, env, health_url).
- Produces: ProcessSupervisor.start(spec), stop(name), stop_all(), snapshot().
- Produces: probe_http(url, timeout_seconds) -> HealthResult.

- [ ] **Step 1: Write RED preflight aggregation tests**

~~~python
def test_preflight_returns_every_failure_without_short_circuit(tmp_path):
    runner = PreflightRunner(
        command_exists=lambda name: name not in {"ssh.exe", "cloudflared.exe"},
        port_available=lambda port: port != 8000,
        writable=lambda path: False,
        invitation_check=lambda: CheckResult("invitations", False, "blocked", "Run rollout reissue"),
    )
    results = runner.run("vast", settings(tmp_path), complete_secrets())
    failed = {result.name for result in results if not result.ok}
    assert {"ssh.exe", "cloudflared.exe", "port:8000", "data-root", "invitations"} <= failed

def test_preflight_reports_secret_names_only(tmp_path):
    results = PreflightRunner.for_test(missing_secrets={"HF_TOKEN"}).run(
        "vast", settings(tmp_path), {}
    )
    rendered = "\n".join(result.detail for result in results)
    assert "HF_TOKEN" in rendered
    assert "Bearer " not in rendered
~~~

- [ ] **Step 2: Run preflight tests and verify RED**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_control_preflight.py -v
~~~

Expected: FAIL because PreflightRunner does not exist.

- [ ] **Step 3: Implement aggregate preflight checks**

Check Python 3.14+, node 22+, npm.cmd, git, ssh.exe, cloudflared executable/config, required import modules, writable data/settings/log paths, ports 3000/8000/8001, required secret names for the selected mode, Next .next build output, and the real invitation rollout check. Return every result in one pass; do not mutate, install, bind ports, or create provider resources during preflight.

- [ ] **Step 4: Write RED process-ownership and log-bound tests**

~~~python
def test_stop_all_terminates_only_owned_handles(fake_popen, fake_job):
    supervisor = ProcessSupervisor(job=fake_job, popen=fake_popen)
    api = supervisor.start(ProcessSpec("api", ("python", "api_server.py"), ROOT, {}, None))
    supervisor.observe_external("cloudflare", pid=999)
    supervisor.stop_all()
    assert api.terminate_called
    assert 999 not in fake_job.terminated_pids

def test_log_buffer_redacts_and_bounds_entries():
    logs = LogBuffer(max_entries=2, max_line_chars=80, known_secrets=["hf_secret"])
    logs.append("api", "token=hf_secret")
    logs.append("api", "safe-2")
    logs.append("api", "safe-3")
    assert len(logs.snapshot()) == 2
    assert "hf_secret" not in repr(logs.snapshot())
~~~

- [ ] **Step 5: Implement Windows Job Object and process supervisor**

Create one Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. Assign only Popen handles created by the supervisor. Use CREATE_NEW_PROCESS_GROUP, stdin DEVNULL, text-mode stdout/stderr reader threads, and child environments built from an explicit allowlisted parent plus injected settings. Secrets may appear only in the environment mapping, never argv.

External processes discovered through health/port checks are recorded as external and never attached to the Job Object or terminated.

- [ ] **Step 6: Implement bounded health probes**

HealthResult must expose ok, status_code, latency_ms, and safe error_type only. probe_http must reject non-loopback HTTP except the configured HTTPS public origin, cap response reads at 64 KiB, and never include response bodies in errors.

- [ ] **Step 7: Run focused tests and commit**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_control_preflight.py tests/test_control_processes.py -v
.\.venv\Scripts\python.exe -m compileall -q defend_control
git diff --check
~~~

Expected: PASS.

Commit:

~~~powershell
git add defend_control/preflight.py defend_control/windows_job.py defend_control/processes.py defend_control/health.py tests/test_control_preflight.py tests/test_control_processes.py
git commit -m "Supervise local DEFEND services safely"
~~~

### Task 4: Deliver Local Ollama mode and the Control Center shell

**Files:**
- Create: defend_control/local_model.py
- Create: defend_control/orchestrator.py
- Create: defend_control/controller.py
- Create: defend_control/ui.py
- Create: tools/defend_control_center.py
- Modify: tools/__init__.py if import packaging requires it
- Test: tests/test_control_local.py
- Test: tests/test_control_orchestrator.py
- Test: tests/test_control_controller.py

**Interfaces:**
- Consumes: settings, secrets, PreflightRunner, ProcessSupervisor, probe_http.
- Produces: ModelReady(model: str, backend: str, endpoint: str).
- Produces: LocalOllamaBackend.verify(model: str) -> ModelReady.
- Produces: StackOrchestrator.start(mode), stop_local(), restart(), snapshot().
- Produces: ControlController commands returning UIState without blocking Tk's event loop.
- Produces: run_control_center() application entrypoint.

Task 4 must add this immutable type to defend_control/types.py:

~~~python
@dataclass(frozen=True)
class ModelReady:
    model: str
    backend: str
    endpoint: str
~~~

- [ ] **Step 1: Write RED local-mode orchestration tests**

~~~python
def test_local_start_orders_model_api_web_tunnel(fake_dependencies):
    orchestrator = StackOrchestrator(**fake_dependencies)
    orchestrator.start("ollama")
    assert fake_dependencies.events == [
        "preflight:ollama",
        "ollama:verify",
        "api:start", "api:healthy",
        "web:start", "web:healthy",
        "tunnel:reuse-or-start", "public:healthy",
    ]
    assert orchestrator.snapshot().state == "ready"

def test_failed_web_health_rolls_back_only_new_processes(fake_dependencies):
    fake_dependencies.web_health.ok = False
    with pytest.raises(StartFailed, match="frontend"):
        StackOrchestrator(**fake_dependencies).start("ollama")
    assert fake_dependencies.stopped == ["web", "api"]
    assert "external-cloudflare" not in fake_dependencies.stopped
~~~

- [ ] **Step 2: Run local orchestration tests and verify RED**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_control_local.py tests/test_control_orchestrator.py -v
~~~

Expected: FAIL because the local backend/orchestrator do not exist.

- [ ] **Step 3: Implement LocalOllamaBackend and local process specifications**

Verify GET http://127.0.0.1:11434/api/tags contains the configured model. Build the API child environment with DEFEND_MODEL_BACKEND=ollama, DEFEND_MODEL, owner settings/secrets, visitor HMAC key, Gmail values, Cloudflare trust, secure cookies, public origin, CORS origins, and data root.

Use these local commands:

~~~python
api = ProcessSpec(
    "api",
    (str(repo / ".venv/Scripts/python.exe"), "api_server.py"),
    repo,
    api_env,
    "http://127.0.0.1:8000/health",
)
web = ProcessSpec(
    "web",
    ("npm.cmd", "run", "start"),
    repo / "defend-ui-v2",
    {"PORT": "3000", "HOSTNAME": "127.0.0.1"},
    "http://127.0.0.1:3000/health",
)
~~~

Reuse a healthy Cloudflare process. Otherwise start the configured named tunnel using executable/config/tunnel name only; do not pass a tunnel token in argv.

- [ ] **Step 4: Implement the ordered orchestrator state machine**

All state transitions occur under one lock. Start runs in a worker thread, checks cancellation between every component, records which resources were created during the attempt, and rolls those resources back in reverse order. Restart is stop_local followed by start with the last explicit mode. Duplicate start returns AlreadyRunning.

- [ ] **Step 5: Write RED controller tests**

~~~python
def test_controller_never_blocks_ui_thread(fake_orchestrator, executor):
    controller = ControlController(fake_orchestrator, executor=executor)
    controller.start("ollama")
    assert executor.submitted == [("start", "ollama")]

def test_destroy_requires_exact_instance_confirmation(fake_orchestrator):
    controller = ControlController(fake_orchestrator, executor=InlineExecutor())
    with pytest.raises(ConfirmationRequired):
        controller.stop_and_destroy_vast(confirmed_instance_id=None)
~~~

- [ ] **Step 6: Implement Tkinter Control Center**

The window contains:

- a Vast.ai / Local Ollama radio choice;
- Start, Stop Local, Restart, Open DEFEND, Setup, and Stop + Destroy Vast buttons;
- component rows for model, SSH tunnel, API, frontend, and Cloudflare;
- current Vast GPU, instance ID, and exact hourly price when applicable;
- a bounded read-only log panel; and
- modal setup/confirmation dialogs.

Tk callbacks submit controller work to a single executor and poll immutable UIState with root.after. Closing the window while services run asks whether to leave them running or stop local services. It never destroys a Vast instance from a window-close action.

- [ ] **Step 7: Run local/UI tests and commit**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_control_local.py tests/test_control_orchestrator.py tests/test_control_controller.py -v
.\.venv\Scripts\python.exe -m compileall -q defend_control tools
git diff --check
~~~

Expected: PASS.

Commit:

~~~powershell
git add defend_control tools/defend_control_center.py tests/test_control_local.py tests/test_control_orchestrator.py tests/test_control_controller.py
git commit -m "Add the DEFEND Windows control center"
~~~

### Task 5: Implement immutable Hugging Face discovery and Vast.ai lifecycle

**Files:**
- Create: defend_control/huggingface.py
- Create: defend_control/vast.py
- Test: tests/test_control_huggingface_vast.py

**Interfaces:**
- Produces: HuggingFaceClient.resolve_adapter(repo, token) -> AdapterSpec.
- Produces: AdapterSpec(adapter_repo, adapter_revision, base_repo, base_revision, peft_type).
- Produces: LaunchSpec(image, disk_gb, runtype, label) with LaunchSpec.default().
- Produces: VastClient.search_offers(max_hourly) -> tuple[VastOffer, ...].
- Produces: VastClient.create_instance(offer, launch) -> VastInstance.
- Produces: VastClient.show_instance(id), set_state(id, state), destroy_instance(id).
- Produces: VastClient.ensure_account_ssh_key(public_key) -> int.

Task 5 must add these immutable types to defend_control/types.py:

~~~python
@dataclass(frozen=True)
class AdapterSpec:
    adapter_repo: str
    adapter_revision: str
    base_repo: str
    base_revision: str
    peft_type: str

@dataclass(frozen=True)
class LaunchSpec:
    image: str
    disk_gb: int
    runtype: str
    label: str

    @classmethod
    def default(cls) -> "LaunchSpec":
        return cls("vllm/vllm-openai:v0.10.0", 160, "ssh_direct", "defend-vllm")

@dataclass(frozen=True)
class VastOffer:
    offer_id: int
    gpu_name: str
    gpu_ram_mb: int
    dph_total: Decimal
    reliability: Decimal

@dataclass(frozen=True)
class VastInstance:
    instance_id: int
    actual_status: str | None
    ssh_host: str | None
    ssh_port: int | None
    gpu_name: str
    gpu_ram_mb: int
    dph_total: Decimal
~~~

- [ ] **Step 1: Write RED immutable-adapter tests**

~~~python
def test_resolve_adapter_pins_both_revisions(fake_http):
    fake_http.add_response(
        url="https://huggingface.co/api/models/Defend-network/defend-qwen-32b-lora/revision/main",
        json={"sha": "adapter-sha"},
    )
    fake_http.add_response(
        url="https://huggingface.co/Defend-network/defend-qwen-32b-lora/resolve/adapter-sha/adapter_config.json",
        json={
            "peft_type": "LORA",
            "base_model_name_or_path": "Qwen/example-32B",
            "revision": "base-sha",
        },
    )
    spec = client.resolve_adapter("Defend-network/defend-qwen-32b-lora", "hf_secret")
    assert spec.adapter_revision == "adapter-sha"
    assert spec.base_repo == "Qwen/example-32B"
    assert spec.base_revision == "base-sha"
~~~

- [ ] **Step 2: Run Hugging Face tests and verify RED**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_control_huggingface_vast.py -k huggingface -v
~~~

Expected: FAIL because HuggingFaceClient does not exist.

- [ ] **Step 3: Implement safe adapter discovery**

Use Authorization: Bearer only in request headers. Require a 40-64 hexadecimal Hub revision SHA, peft_type LORA, a nonempty organization/repository base model, and an explicit base revision. If adapter_config has no base revision, resolve the base repository's main revision through the Hub API and pin that SHA. Do not log headers or response bodies.

- [ ] **Step 4: Write RED Vast offer/lifecycle tests**

~~~python
def test_offer_search_is_verified_on_demand_single_80gb_and_capped(fake_http):
    client = VastClient("vast_secret", transport=fake_http)
    client.search_offers(Decimal("2.50"))
    request = fake_http.last_request
    assert request.method == "POST"
    assert request.url.path == "/api/v0/bundles"
    assert request.json["type"] == "on-demand"
    assert request.json["verified"] == {"eq": True}
    assert request.json["rentable"] == {"eq": True}
    assert request.json["rented"] == {"eq": False}
    assert request.json["num_gpus"] == {"eq": 1}
    assert request.json["gpu_ram"] == {"gte": 80000}
    assert request.json["dph_total"] == {"lte": 2.5}

def test_create_has_no_hf_or_vllm_secret(fake_http, offer):
    client.create_instance(offer, LaunchSpec.default())
    body = fake_http.last_request.json
    serialized = json.dumps(body)
    assert "HF_TOKEN" not in serialized
    assert "API_KEY" not in serialized
    assert body == {
        "image": "vllm/vllm-openai:v0.10.0",
        "disk": 160,
        "runtype": "ssh_direct",
        "target_state": "running",
        "cancel_unavail": True,
        "label": "defend-vllm",
    }
~~~

- [ ] **Step 5: Implement official Vast.ai REST contracts**

Use:

- POST https://console.vast.ai/api/v0/bundles for search;
- PUT https://console.vast.ai/api/v0/asks/{offer_id}/ for creation;
- GET https://console.vast.ai/api/v0/instances/{instance_id}/ for status;
- PUT https://console.vast.ai/api/v0/instances/{instance_id} with state running/stopped; and
- DELETE https://console.vast.ai/api/v0/instances/{instance_id}/ for destruction;
- GET https://console.vast.ai/api/v0/ssh to find the dedicated public key; and
- POST https://console.vast.ai/api/v0/ssh with {"ssh_key": public_key} only when it is absent.

Every request uses Authorization: Bearer in the header, a 30-second network timeout, bounded 429 retry with jitter, and a 64 KiB response cap. Search returns at most 20 offers sorted by dph_total ascending and locally revalidates GPU RAM, GPU count, verification, rentable state, on-demand state, and price cap before displaying an offer.

- [ ] **Step 6: Add provisioning-state and billing tests**

Cover null/loading/running, terminal exited/unknown/offline, five-minute timeout, offer-rented race, stopped-instance disk-charge warning, exact instance-ID destruction confirmation, and destruction success/failure. Failure strings expose status/error type only.

- [ ] **Step 7: Run focused tests and commit**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_control_huggingface_vast.py -v
.\.venv\Scripts\python.exe -m compileall -q defend_control
git diff --check
~~~

Expected: PASS.

Commit:

~~~powershell
git add defend_control/huggingface.py defend_control/vast.py tests/test_control_huggingface_vast.py
git commit -m "Integrate Vast model provisioning"
~~~

### Task 6: Secure the remote model and integrate Vast mode

**Files:**
- Create: defend_control/ssh_tunnel.py
- Create: defend_control/remote_vllm.py
- Create: defend_control/model_probe.py
- Modify: defend_control/orchestrator.py
- Modify: defend_control/controller.py
- Modify: defend_control/ui.py
- Test: tests/test_control_ssh_model.py
- Modify: tests/test_control_orchestrator.py
- Modify: tests/test_control_controller.py

**Interfaces:**
- Consumes: AdapterSpec, VastOffer, VastInstance, SecretStore, ProcessSupervisor.
- Produces: SshTunnel.prepare_host(instance, confirm_fingerprint) and start(instance).
- Produces: RemoteVllmBootstrap.start(instance, adapter, secrets).
- Produces: ModelProbe.wait_ready(base_url, api_key, model="defend-ai").
- Extends: StackOrchestrator.start("vast") and destroy_vast(confirmed_instance_id).

- [ ] **Step 1: Write RED SSH pinning and forwarding tests**

~~~python
def test_unknown_host_requires_fingerprint_confirmation(fake_ssh):
    tunnel = SshTunnel(fake_ssh, known_hosts=KNOWN_HOSTS, key_path=KEY)
    with pytest.raises(HostFingerprintConfirmation) as pending:
        tunnel.prepare_host(instance, confirm_fingerprint=None)
    assert pending.value.fingerprint.startswith("SHA256:")

def test_forward_uses_strict_known_hosts_and_loopback(fake_ssh, confirmed_tunnel):
    confirmed_tunnel.start(instance)
    argv = fake_ssh.last_argv
    assert "-N" in argv
    assert "127.0.0.1:8001:127.0.0.1:8000" in argv
    assert "StrictHostKeyChecking=yes" in argv
    assert "ExitOnForwardFailure=yes" in argv
    assert not any("hf_" in part or "Bearer" in part for part in argv)
~~~

- [ ] **Step 2: Run SSH/model tests and verify RED**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_control_ssh_model.py -v
~~~

Expected: FAIL because SshTunnel and ModelProbe do not exist.

- [ ] **Step 3: Implement dedicated SSH identity and host pinning**

Generate an Ed25519 key at %LOCALAPPDATA%\DEFEND\ssh\vast_ed25519 with ssh-keygen if absent. Apply the current-user-only ACL. Register only its public key with Vast during first-run setup. Obtain the presented host key with ssh-keyscan, calculate the SHA256 fingerprint with ssh-keygen, require UI confirmation, and then append only the exact host/port key to the dedicated known_hosts file. Strict checking is mandatory after confirmation.

Start the owned forward with:

~~~text
ssh.exe -N
  -L 127.0.0.1:8001:127.0.0.1:8000
  -p SSH_PORT
  -i VAST_IDENTITY
  -o BatchMode=yes
  -o ExitOnForwardFailure=yes
  -o StrictHostKeyChecking=yes
  -o UserKnownHostsFile=DEFEND_KNOWN_HOSTS
  root@SSH_HOST
~~~

- [ ] **Step 4: Implement remote vLLM bootstrap without secret argv**

Send a bounded shell script and encrypted-at-transport secret payload over SSH stdin. The remote script creates /workspace/defend with mode 700, downloads the pinned base and adapter snapshots, writes no token to logs, starts vLLM under nohup, and records only the PID.

The resulting launch command is structurally:

~~~text
vllm serve /workspace/defend/base
  --host 127.0.0.1
  --port 8000
  --api-key ENV_VLLM_API_KEY
  --enable-lora
  --lora-modules defend-ai=/workspace/defend/adapter
  --max-model-len 8192
~~~

After /v1/models is ready, securely remove the temporary remote token file. The running instance remains ephemeral and is destroyed by the final cost-safe stop path.

- [ ] **Step 5: Implement model readiness and minimal generation probe**

GET http://127.0.0.1:8001/v1/models with the bearer key and require model id defend-ai. Then POST /v1/chat/completions with model defend-ai, temperature 0, max_tokens 8, and the neutral prompt Reply with READY only. Require a nonempty assistant content field; do not log the response.

- [ ] **Step 6: Write RED integrated Vast orchestration tests**

~~~python
def test_vast_start_requires_price_then_fingerprint(fake_dependencies):
    orchestrator = StackOrchestrator(**fake_dependencies)
    with pytest.raises(PriceConfirmationRequired):
        orchestrator.start("vast")
    orchestrator.confirm_offer(fake_dependencies.offer.offer_id, fake_dependencies.offer.dph_total)
    with pytest.raises(HostFingerprintConfirmation):
        orchestrator.start("vast")
    orchestrator.confirm_fingerprint(fake_dependencies.instance.instance_id, "SHA256:abc")
    orchestrator.start("vast")
    assert orchestrator.snapshot().state == "ready"

def test_destroy_requires_exact_id_and_clears_billing_state(fake_dependencies):
    orchestrator = ready_vast_orchestrator(fake_dependencies)
    with pytest.raises(ConfirmationRequired):
        orchestrator.destroy_vast("wrong-id")
    orchestrator.destroy_vast(str(fake_dependencies.instance.instance_id))
    assert fake_dependencies.vast.destroyed == [fake_dependencies.instance.instance_id]
    assert orchestrator.snapshot().vast_instance is None
~~~

- [ ] **Step 7: Integrate Vast states, confirmations, and UI**

Add price/fingerprint confirmation states to ControlController and modal dialogs to the Tkinter UI. Show GPU name, GPU RAM, reliability, exact dph_total, instance ID, actual_status, and whether compute or disk billing may remain. Never display provider response bodies or credentials.

- [ ] **Step 8: Run focused tests and commit**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_control_ssh_model.py tests/test_control_orchestrator.py tests/test_control_controller.py -v
.\.venv\Scripts\python.exe -m compileall -q defend_control
git diff --check
~~~

Expected: PASS.

Commit:

~~~powershell
git add defend_control/ssh_tunnel.py defend_control/remote_vllm.py defend_control/model_probe.py defend_control/orchestrator.py defend_control/controller.py defend_control/ui.py tests/test_control_ssh_model.py tests/test_control_orchestrator.py tests/test_control_controller.py
git commit -m "Run DEFEND through secure Vast vLLM"
~~~

### Task 7: Complete documentation, verification, and real acceptance gate

**Files:**
- Modify: start_api.TXT
- Modify: RUN_DEFEND.txt
- Create: docs/operations/DEFEND-Control-Center.md
- Modify: tests/test_runtime_dependencies.py
- Test: tests/test_control_acceptance_contract.py

**Interfaces:**
- Consumes: the complete Control Center.
- Produces: a secret-free operator runbook and a machine-readable dry-run acceptance report.
- Produces: tools.defend_control_center --check, which performs all non-billable checks and exits nonzero on failure.

- [ ] **Step 1: Write RED acceptance-contract tests**

~~~python
def test_check_mode_never_provisions_or_starts(monkeypatch):
    provider = RecordingVastProvider()
    result = run_check_mode(settings(), secrets(), vast=provider)
    assert provider.mutations == []
    assert {item.name for item in result.checks} >= {
        "dependencies", "settings", "secrets", "ports",
        "data-root", "invitation-transport", "cloudflare",
    }

def test_tracked_operations_docs_are_ingest_excluded():
    path = Path("docs/operations/DEFEND-Control-Center.md")
    assert path.read_text("utf-8").startswith("<!-- DEFEND-AI-INGEST: EXCLUDE -->")
    with pytest.raises(AIIngestExcluded):
        assert_ai_ingest_allowed(filename=str(path), content_prefix=path.read_bytes()[:4096])
~~~

- [ ] **Step 2: Run acceptance tests and verify RED**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_control_acceptance_contract.py -v
~~~

Expected: FAIL because check mode and the operations runbook do not exist.

- [ ] **Step 3: Implement non-billable --check mode**

tools.defend_control_center --check loads settings/secrets, runs aggregate preflight for both modes, verifies no duplicate services, checks the local public route if already running, prints names/status/remediation only, and never calls Vast search/create/manage/destroy or starts processes.

- [ ] **Step 4: Write the secret-free operations runbook**

Document:

- first-run Bootstrap-DEFEND.ps1;
- desktop Start DEFEND shortcut;
- local setup fields and DPAPI limitation;
- Vast API/Hugging Face/Gmail values entered locally;
- a minimum-permission Vast API key limited to search, instance_read, and
  instance_write capabilities;
- price and fingerprint confirmation;
- Local Ollama and Vast.ai launch flows;
- Stop Local versus Stop + Destroy Vast;
- stopped-instance disk billing warning;
- invitation rollout check;
- backup of C:\DEFEND_DATA;
- diagnostics and bounded log locations;
- explicit GitHub update procedure;
- mandatory rotation of every credential that has ever appeared in Git or terminal history before production acceptance; and
- future VPS migration boundary.

Replace old Downloads paths and direct python/npm launch instructions in RUN_DEFEND.txt and start_api.TXT with the Control Center flow. Do not include values.

- [ ] **Step 5: Run full automated verification**

Run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests -v
npm.cmd test --prefix defend-ui-v2 -- --run
.\defend-ui-v2\node_modules\.bin\tsc.cmd --noEmit -p defend-ui-v2\tsconfig.json
npm.cmd run build --prefix defend-ui-v2
.\.venv\Scripts\python.exe -m compileall -q . -x "(\.venv|node_modules|\.next|\.pytest_cache)"
git diff --check
git ls-files ".superpowers/**"
~~~

Expected: all maintained Python and frontend tests PASS; TypeScript, Next build, compileall, and diff check exit 0; git ls-files emits no internal .superpowers reports.

- [ ] **Step 6: Run non-billable Windows acceptance**

Run:

~~~powershell
.\Bootstrap-DEFEND.ps1 -Repair
.\.venv\Scripts\python.exe -m tools.defend_control_center --check
~~~

Expected: dependency, settings, secrets, data, invitation, ports, and Cloudflare checks report ready or give one explicit remediation each. No Vast instance is created.

- [ ] **Step 7: Stop for operator confirmation before external cost**

Present the selected offer ID, GPU, GPU RAM, reliability, exact hourly price, storage price if returned, and the instance creation body with every secret omitted. Obtain explicit user confirmation before calling Vast create-instance.

- [ ] **Step 8: Perform the real Vast.ai acceptance**

After confirmation:

1. Create the single on-demand instance.
2. Confirm its SSH host fingerprint.
3. Wait for vLLM and model probe readiness.
4. Start API, frontend, and Cloudflare through the Control Center.
5. Open https://ai.defend-network.org and complete one ordinary user-selected question.
6. Verify API health reports defend-ai and inspect bounded logs for secret absence.
7. Stop local services.
8. Present the exact instance ID and obtain destructive confirmation.
9. Destroy the Vast instance and verify the provider no longer reports active compute/disk billing for it.

- [ ] **Step 9: Commit Task 7**

~~~powershell
git add start_api.TXT RUN_DEFEND.txt docs/operations/DEFEND-Control-Center.md tests/test_runtime_dependencies.py tests/test_control_acceptance_contract.py tools/defend_control_center.py
git commit -m "Document and verify DEFEND control operations"
~~~

- [ ] **Step 10: Request final review and publish**

Run a fresh independent security/code review of the complete implementation range, fix all Critical/Important findings with RED/GREEN regressions, rerun Step 5, push agent/admin-identity-observability, and update the existing GitHub pull request. Do not merge to main without explicit user confirmation.

## Official implementation references

- Vast.ai search offers: https://docs.vast.ai/api-reference/search/search-offers
- Vast.ai create instance: https://docs.vast.ai/api-reference/instances/create-instance
- Vast.ai show instance: https://docs.vast.ai/api-reference/instances/show-instance
- Vast.ai manage instance: https://docs.vast.ai/api-reference/instances/manage-instance
- Vast.ai destroy instance: https://docs.vast.ai/api-reference/instances/destroy-instance
- Vast.ai lifecycle walkthrough: https://docs.vast.ai/api-reference/hello-world
- vLLM LoRA serving: https://docs.vllm.ai/en/stable/features/lora/
- Hugging Face PEFT checkpoint configuration: https://huggingface.co/docs/peft/main/en/developer_guides/checkpoint
