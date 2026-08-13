<!-- DEFEND-AI-INGEST: EXCLUDE -->
# DEFEND Control Center operations

This is an operator document, not DEFEND AI training language. Never ingest it
into RAG, memory, prompts, or model training data.

## What the one button does

`Start-DEFEND.cmd` opens the Windows Control Center. Opening it does not start a
model, rent a GPU, expose the site, or begin billing. Each launch requires a fresh
choice between Local Ollama and Vast.ai. `Start DEFEND` then performs preflight,
starts the selected model, starts the API and production frontend, verifies each
health boundary, and starts or safely reuses the named Cloudflare tunnel.

The Control Center owns processes it starts and keeps them inside Windows Job
Objects so closing or stopping can clean up child processes. It never kills a
verified external Cloudflare process that it did not start.

## First run and repair

1. Use the repository checkout on the computer that will run DEFEND.
2. Double-click `Bootstrap-DEFEND.cmd` once. The wrapper runs
   `Bootstrap-DEFEND.ps1` in a one-process PowerShell session without changing
   the machine execution policy. Use `Bootstrap-DEFEND.cmd -Repair` after
   dependency or runtime changes. It creates/repairs the Python environment,
   installs the locked runtime/development manifests, installs frontend
   dependencies, and creates a production frontend build.
3. Create a desktop shortcut to `Start-DEFEND.cmd` if desired.
4. Open `Start-DEFEND.cmd`, choose Setup, enter the required values, and save.

Setup stores ordinary settings in `%LOCALAPPDATA%\DEFEND\control-center.json`.
Secret values are encrypted with Windows DPAPI CurrentUser in
`%LOCALAPPDATA%\DEFEND\secrets.dpapi`, with a current-user-only ACL. They can be
decrypted only by the same Windows user profile. Backups of that file are not a
portable secret backup; retain credentials in an approved password manager.

## Setup values

Local settings include the repository root, `C:\DEFEND_DATA`, the public HTTPS
origin, the exact cloudflared executable/config/tunnel, the fixed adapter
repository, local Ollama model, maximum hourly Vast price, vLLM image, disk size,
and model context length.

Secret fields include:

- owner username, email, and a unique strong owner password;
- a stable high-entropy visitor HMAC key of at least 32 characters;
- Gmail SMTP username, app password, sender, host, port, and TLS mode;
- a Vast API key with only the minimum required capabilities: offer search,
  instance read, and instance write;
- a Hugging Face read token that can access the private pinned adapter/base
  snapshots; and
- a unique high-entropy vLLM API key.

Never place a value in Git, these documents, shell history, screenshots, tickets,
chat, frontend variables, process arguments, or logs.

## Non-billable readiness check

From the repository, run `Bootstrap-DEFEND.cmd -Repair`, then use the Control
Center check command documented by `Start-DEFEND.cmd --check` or the module's
`--check` option. It validates both Local and Vast configurations, dependency
names, settings, secret names, fixed ports, writable data/log locations,
invitation transport, frontend build, and Cloudflare files. It never searches
offers, creates/manages/destroys an instance, registers a key, or starts a process.

Every blocked line includes one remediation. Resolve every block before enabling
public traffic. If ports are occupied, the check also probes the configured public
health route but still treats duplicate local listeners conservatively.

## Local Ollama launch

1. Open `Start-DEFEND.cmd`.
2. Select Local Ollama.
3. Click Start DEFEND.
4. Wait for Model, API, Frontend, and Cloudflare to show ready.
5. Use Open Public Site or open the configured HTTPS origin.
6. Click Stop Local when finished.

## Vast.ai launch

1. Open `Start-DEFEND.cmd`, select Vast.ai, and click Start DEFEND.
2. Review the exact offer ID, GPU, GPU RAM, reliability, hourly compute price,
   and any returned storage price. Declining creates nothing.
3. After explicit approval, one instance is created. Billing may now be active.
4. Review the exact instance ID and SSH SHA256 host fingerprint. Confirm only if
   it matches the instance being provisioned. Billing continues while waiting.
5. The Control Center pins that host key, starts a loopback-only SSH forward,
   sends bounded bootstrap material over encrypted SSH stdin, starts vLLM bound
   to the remote loopback interface, verifies `defend-ai`, immediately removes
   the temporary remote Hugging Face token file, performs a neutral generation
   probe, then starts local API/frontend/Cloudflare services. The adapter's
   validated LoRA rank is passed explicitly to vLLM, and vLLM request/access
   logging is disabled.

`Stop Local` stops computer-owned services but deliberately does not claim that
the Vast instance or disk billing ended. To end it, choose `Stop + Destroy Vast`,
review the billing warning, type/confirm the exact instance ID, and wait until the
provider no longer reports the instance as active.

## Invitations and identity rollout

Before enabling traffic, the invitation transport check must report no live
legacy path-token invitations. If blocked, stop traffic, back up data, verify
Gmail settings, and use the offline invitation rollout `check`/`reissue` workflow.
Reissue is transactional and prints counts/status only. Never restore a legacy
path or query-string token route.

## Data backup

Stop local DEFEND services and all identity database writers before backing up
`C:\DEFEND_DATA`. Preserve the full directory, including database files and
attachments. Verify the backup can be enumerated and restored to a separate test
location. Do not copy a live SQLite main file while WAL/SHM writers are active.

## Permanent Knowledge / RAG ingestion

Keep DEFEND online and sign in to the Admin workspace. Open `Knowledge / RAG`,
choose up to 20 PDF or DOCX files (25 MB maximum per file), and select `Index`.
The panel processes files one at a time and reports extracting, embedding,
indexed, skipped, or failed for every document. A failed document does not stop
the rest of the batch. Re-uploading identical content reports `skipped` without
embedding it again. Use the Documents view to confirm the permanent corpus and
chunk counts after completion.

The panel now displays the active embedding provider and checks it before a job
is accepted. All permanent ingestion, semantic queries, and temporary research
cache ingestion share that provider. The default remains the local Ollama model
`qwen3-embedding:0.6b` for compatibility. This model creates search vectors; it
does not replace, train, or fine-tune the primary DEFEND language model running
under Ollama or vLLM.

For an independently managed local vLLM embedding service, set these environment
variables on the API process before launch:

- `DEFEND_EMBEDDING_PROVIDER=vllm`
- `DEFEND_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B`
- `DEFEND_EMBEDDING_BASE_URL=http://127.0.0.1:8002/v1`
- `DEFEND_EMBEDDING_API_KEY` to a unique service key
- `DEFEND_EMBEDDING_VECTOR_DIM=1024`
- `DEFEND_EMBEDDING_BATCH_SIZE=32`
- `DEFEND_EMBEDDING_TIMEOUT_SECONDS=120`

Only loopback endpoints are accepted, and the API key is never included in the
admin status response. The embedding vLLM service is separate from the main
generative vLLM service because embedding and text generation have different
models, endpoints, scaling, and failure modes. Until launcher orchestration for
that second service is delivered, start it independently before indexing. Do not
put its API key in Git, frontend environment variables, command arguments, or
screenshots.

Existing vectors must not be mixed across embedding models or dimensions. If the
embedding model changes, create a backed-up replacement index and re-index the
approved corpus before switching search traffic. The current index requires
exactly 1,024 dimensions.

The initial `C:\Users\thoma\Downloads\RAG` collection contains 13 eligible
PDF/DOCX documents. Its 1,355 CSV files, 4 JSON files, and ZIP archive are not
eligible for this workflow; they require a separate dataset-aware ingestion
design. Permanent originals and metadata are stored under the configured DEFEND
data root. Never add corpus documents to Git.

## Diagnostics

The Control Center shows bounded status and safe exception types. Bounded logs
are stored below `C:\DEFEND_DATA\logs`. They must not contain Authorization,
Cookie, provider response bodies, invitation links, generated answers from the
probe, or any secret value. Use component names, timestamps, safe error types,
instance/offer IDs, and prices for diagnosis.

## GitHub updates

Use a normal Git branch and pull request. Pull updates into the repository, run
`Bootstrap-DEFEND.cmd -Repair`, run the non-billable check, review the diff, and
only then launch. Never update a deployment by dragging files into GitHub or by
copying a partial Downloads folder over the repository. Do not merge a deployment
branch until tests, review, backup, credential rotation, and acceptance gates are
complete.

## Mandatory credential rotation before production

Rotate every credential that has ever appeared in Git history, source, terminal
history, chat, screenshots, clipboard captures, logs, or test fixtures. This
includes all previous owner passwords, HMAC keys, Gmail app passwords, API keys,
Hugging Face tokens, Vast keys, vLLM keys, Cloudflare credentials, and reusable
session material. Re-enter only the replacements through Setup, revoke the old
values at each provider, and verify the old values no longer authenticate.

## Future VPS boundary

For now, the API, frontend, persistent data, identity store, and Cloudflare tunnel
run on this computer; Vast hosts only ephemeral model inference. A future VPS move
must relocate the local application/data boundary as a separate migration with
backups, TLS/proxy trust, shared rate limiting, secret management, monitoring, and
rollback. Do not silently turn the current desktop Control Center into a VPS
deployment.
