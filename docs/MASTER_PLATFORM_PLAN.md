# DEFEND Platform — Master Execution Plan

**Status:** Active north-star plan  
**Date:** 2026-08-15  
**Purpose:** Keep parallel development of DEFEND AI, DEFEND Sports, DEFENDcoder, and Sunshine Climate Solutions AI focused while preserving product isolation and converging deliberately into one Control Center.

> This document is the coordination source of truth. Product-specific architecture specifications remain authoritative for their internal details. When this document records a local agent commit that has not been pushed to GitHub, it is marked **LOCAL / REPORTED** and must not be assumed integrated until the commit is present on a shared branch.

---

## 1. North star

DEFEND is becoming a shared platform with one owner operations surface and four independently deployable product spaces:

1. **DEFEND AI** — identity, knowledge, RAG, member/general AI.
2. **DEFEND Sports** — sports data, market intelligence, arbitrage, Table Tennis predictive research, Sports AI, alerts, portfolio/risk features.
3. **DEFENDcoder** — autonomous software-engineering product with safe workspaces, tools, model routing, GPU lifecycle, cost accounting, and eventual member tiers.
4. **SCS AI** — Sunshine Climate Solutions business/operations AI, specializing in HVAC workflows, office documents, spreadsheets, reports, customers/jobs/equipment, and future business automation.

The **DEFEND Control Center** is the owner launcher/observer for all four spaces. It is not itself a fifth product.

```text
                     DEFEND CONTROL CENTER
                              |
          +-------------------+-------------------+
          |                   |                   |
      DEFEND AI         DEFEND Sports        DEFENDcoder
          |                   |                   |
          +-------------------+-------------------+
                              |
                            SCS AI
```

Each product owns its application state, service lifecycle, ports, data roots, secrets, model policy, and external origin. Shared infrastructure is reused only through explicit interfaces.

---

## 2. Non-negotiable platform principles

### 2.1 Product isolation

- No product silently shares another product's session cookie, mutable data root, model policy, secrets, or service lifecycle.
- Shared-platform abstractions may coordinate applications without collapsing their boundaries.
- DEFEND AI behavior must not be changed as a side effect of Sports, Coder, or SCS work.
- SCS AI is an SCS subservice, not a fifth top-level application identity.

### 2.2 Control Center convergence

Control Center integration is intentionally serialized while product backends are moving. Parallel product work is encouraged; edits to shared Control Center files are not.

Until the integration milestone, SCS/Sports feature branches must not independently modify shared integration hotspots such as:

- `defend_control/ui.py`
- `defend_control/products.py`
- root/shared `control_plane.py`

The convergence branch will be:

`platform/control-center-v2-integrate`

### 2.3 Evidence before automation

- Tests first for new behavior.
- No live/billable provider calls in unit tests.
- No fabricated provider cost, token, or health values.
- Sports mathematical truth comes from structured data/quantitative code, not LLM intuition.
- SCS Office tools report what they actually changed; they do not claim a formula was recalculated unless a calculation engine verified it.
- Coder provisioning approvals bind material launch terms and measured provider data.

### 2.4 Secrets

No live API keys, Cloudflare tunnel tokens, HF tokens, Stripe keys, database credentials, or vLLM keys belong in code, CLI arguments, logs, tests, commits, status JSON, or approval hashes. Existing exposed/rotated tokens must be treated as compromised historical values.

---

## 3. Current program state

This section separates GitHub-visible baselines from newer local agent work reported during development.

### 3.1 DEFEND AI

**Existing product.** Preserve its current identity/RAG/runtime behavior while the other products mature. DEFEND AI remains one of the four Control Center launch spaces.

Near-term DEFEND AI work is intentionally limited to regression protection and eventual Control Center V2 integration. Do not use DEFEND AI as the home for Sports or Coder-specific application logic.

### 3.2 DEFEND Sports

GitHub contains the locked Sports architecture specification and the shared-platform Sports foundation. The locked product direction is: all sports receive market/arbitrage intelligence immediately; Table Tennis receives deep predictive intelligence first; production remains advisory/signaling only.

Reported local milestones include:

- Task 3 PostgreSQL foundation — `ffea82b` **LOCAL / REPORTED**
- Task 4 canonical sports market domain — `59835cf` **LOCAL / REPORTED**
- Task 5 ingestion pipeline — `df9106f` **LOCAL / REPORTED**
- Task 6 independent FastAPI service — `54e57f5` **LOCAL / REPORTED**
- Task 7 four-product Control Center product-service seam — `040fdc7` **LOCAL / REPORTED**

Task 7 reportedly provides four product cards/services and a real Sports lifecycle seam, but it has not yet been converged with the newer Coder and SCS AI branches.

### 3.3 DEFENDcoder

GitHub contains the M0 Control Center/coder architecture baseline. Reported local runtime work includes:

- compute ControlPlane — `9211bb2` **LOCAL / REPORTED**
- deployment artifacts/live-heavy readiness — `116921b` **LOCAL / REPORTED**
- owner approval/live-smoke preparation — `39f24ac` **LOCAL / REPORTED**
- direct-SSH hardening — `0062d21` **LOCAL / REPORTED**
- Vast runtype contract correction — `40ddaae` **LOCAL / REPORTED**
- approval/hash/create-payload hardening — `12c818d` **LOCAL / REPORTED**

The locked logical model mapping is:

- `defendcoder-default` -> `Qwen/Qwen3-Coder-30B-A3B-Instruct` @ `b2cff646eb4bb1d68355c01b18ae02e7cf42d120`
- `defendcoder-heavy` -> `Qwen/Qwen3-Coder-Next` @ `a7fbcb5c0e12d62a448eaa0e260346bf5dcc0feb`

Heavy deployment artifact currently targets:

- `Qwen/Qwen3-Coder-Next-FP8` @ `da6e2ed27304dd39abadd9c82ef50e8de67bdd4c`
- 2 x 80GB A100/H100 class
- TP=2
- context=32768
- vLLM 0.15.0
- `qwen3_coder` parser / auto tool choice

The first correctly serialized `ssh_direct` live run reportedly proved that Vast applied `image_runtype='ssh_direct'`, but the parsed instance metadata did not yet expose a direct host/port at the immediate post-running checkpoint. That run was destroyed quickly and cheaply by protocol. This is now a provider-lifecycle/schema investigation, not justification for repeatedly buying random hosts.

### 3.4 SCS AI

Reported SCS-AI-0 foundation commit:

- `1e10f27` **LOCAL / REPORTED**

Reported architecture includes:

- independent FastAPI service;
- ports 8300/3300;
- provider-neutral `ModelGateway`;
- tool boundary;
- independent SCS-owned Cloudflare tunnel controller;
- `SCS_AI_*` configuration namespace;
- token injection via protected env/file source, never argv;
- truthful `not_configured`/`starting`/health states.

SCS AI external origin is:

`https://ai.sunshineclimatesolutions.com`

The SCS AI Cloudflare tunnel is independent from DEFEND's tunnel and must be launched/observed as its own SCS-owned process. Until the real origin is ready and authenticated, the external route should remain a deliberate 503 placeholder.

---

## 4. Four-product Control Center V2

The owner experience must converge to four top-level cards/spaces:

### DEFEND AI

- local/API/web state;
- model/runtime state;
- data/RAG health;
- tunnel/network state;
- Open / Launch / Stop / Logs.

### DEFEND Sports

- Sports API;
- PostgreSQL/schema health;
- ingestion/feed health;
- source count/freshness;
- arb engine state;
- Sports AI state;
- alert workers;
- Open / Launch / Stop / Logs.

### DEFENDcoder

- default/heavy mode;
- selected alias/artifact;
- provider/GPU/instance;
- endpoint readiness;
- current session budget;
- measured hourly rate/cost;
- trace/failure state;
- provision/reuse/idle state;
- Open / Launch / Stop / Logs.

### SCS AI

- SCS AI API;
- model gateway state;
- office/business tool readiness;
- SCS data dependency state;
- independent SCS AI tunnel state;
- external-origin readiness;
- Open / Launch / Stop / Logs.

Control Center V2 must display truthful states. A service that is configured but not healthy is not `ready`; a model without a provider is `not_configured`; a tunnel with no healthy origin is not shown as application-ready merely because cloudflared connected.

---

## 5. Parallel execution lanes

Development proceeds in parallel in isolated worktrees.

### Lane A — DEFENDcoder live-runtime stabilization

Goal: achieve a repeatable live Heavy smoke and then move from infrastructure debugging into the actual autonomous coding product.

Current priority:

1. Correctly understand Vast `ssh_direct` endpoint publication timing/schema.
2. Capture raw create/show payloads before parsing.
3. Add a bounded post-running wait for direct endpoint publication when provider status is still converging.
4. Do not interpret immediate absence at `running` as permanent absence without evidence.
5. Avoid repeated spend until the provider lifecycle is understood.
6. Once direct transport is available: fingerprint -> bootstrap -> preserve full logs -> `/v1/models` -> exact response -> tool call -> ControlPlane smoke -> measured trace -> destroy.
7. Diagnose the separate vLLM EngineCore issue only after transport works reliably.

After first successful live smoke:

- validate warm reuse;
- measured token accounting from real completion;
- safe idle shutdown;
- M1 safe autonomous repo-editing loop;
- terminal/files/git/tests/tool observations;
- planner/reviewer/recovery later;
- member billing/tiers only after owner runtime is reliable.

### Lane B — SCS-AI-1A Office tools

Branch only from the accepted SCS AI foundation. Do not touch Coder/Sports/shared UI.

Workspace root:

`C:\SCS_DATA\ai_workspace`

Initial structure should support users/jobs/temp/exports/backups/traces without placing business artifacts in source control.

Implement Office file capabilities first:

**Workbook**
- inspect;
- read range;
- write range;
- set formula;
- format range;
- add sheet;
- export/version output.

**Document**
- inspect;
- read;
- create;
- edit;
- export/version output.

Preferred libraries: `openpyxl` and `python-docx`; no Excel/Word GUI automation for the server foundation.

Hard requirements:

- canonical resolved-path containment under the workspace root;
- deny path escape;
- no silent overwrite of master files;
- mutation produces versioned output or explicit backup;
- structured tool results/traces;
- preserve workbook/document structure where possible;
- formula writing does not imply recalculation;
- no fake business records.

Later SCS milestones:

- **SCS-AI-1B:** customer/job/equipment/estimate/invoice interfaces wired to real SCS data when available;
- **SCS-AI-1C:** manuals, project files, manufacturer documentation, knowledge/research tools;
- **SCS-AI-2:** model evaluation (`SCS-Bench`) and provider selection;
- **SCS-AI-3:** authenticated web UI + production tunnel/origin activation;
- **SCS-AI-4:** business workflow automation with approvals/audit.

Model candidates should be benchmarked, not chosen by parameter count. Qwen3-30B-A3B-Instruct-2507 is a reasonable default candidate; heavier alternatives are promoted only if SCS-Bench demonstrates enough Office/tool/HVAC benefit to justify cost.

### Lane C — DEFEND Sports Arbitrage Engine V1

Branch from the accepted Task 7 Sports tip, not arbitrary main. Do not touch shared Control Center files.

Lead with **market equivalence**, then arithmetic.

Canonical comparison must account for relevant settlement semantics such as:

- event identity;
- market type;
- period;
- selection;
- line;
- overtime inclusion;
- retirement/void behavior;
- push rules;
- best-of/set/game definition;
- other provider settlement differences.

Implement:

- odds conversion;
- implied probability;
- vig/overround diagnostics;
- canonical market equivalence;
- two-way arbitrage;
- N-way arbitrage where applicable;
- stake allocation math;
- locked return percentage;
- freshness/TTL validation;
- stale-leg rejection;
- opportunity lifecycle.

Opportunity lifecycle is append/audit oriented:

`OPEN -> STALE -> CLOSED`

Reserve `INVALIDATED` for normalization/source defects. Never mutate historical odds rows to make a current opportunity disappear.

Required fixtures include:

- Table Tennis match winner;
- soccer three-way market;
- two-way US sport;
- stale price;
- superficially similar but non-equivalent market;
- cross-book same selection/different line case that must not become a false simple arb.

**Detector policy:** detect mathematically valid opportunities regardless of tiny edge. Do not bury product policy inside the math engine.

**Surfacing policy (later):** minimum edge, expected dollars, freshness, liquidity, source confidence, user book availability, etc.

No wager execution. No bankroll personalization in Arb V1. No real feed required for the first engine milestone.

After Arb V1, integrate a real provider adapter, then alerts, while Table Tennis historical/live point-level data research advances separately.

---

## 6. DEFENDcoder live provisioning policy — speed without fragility

The live market is volatile. Approval must protect money and configuration without making an approved purchase impossible because a non-material market statistic moved by a tiny amount.

### 6.1 Separate eligibility from immutable approval terms

**Eligibility/ranking fields** determine whether an offer may be proposed:

- verified status;
- supported GPU family/count/VRAM;
- price ceiling;
- reliability floor;
- direct-port capability where required;
- disk/network/CUDA/runtime compatibility.

**Material approval fields** bind what the owner is actually authorizing:

- provider;
- offer/machine identity when exact-offer approval is required;
- GPU model/count/VRAM class;
- maximum allowed total hourly rate;
- session budget;
- model logical repo/revision;
- deployment repo/revision/precision;
- runtime image/minimum version;
- tensor parallel size;
- context;
- tool parser/options;
- disk allocation;
- launch runtype/transport;
- other fields that materially change cost, security, model, or runtime behavior.

### 6.2 Reliability tolerance

Reliability is a **selection/risk metric**, not a byte-for-byte approval invariant.

If an offer was approved while satisfying the policy floor, a tiny provider-side drift such as `0.9950 -> 0.9949` should not automatically invalidate the owner's authorization solely because the decimal changed.

Recommended policy:

- proposal target/preferred reliability: >= 0.995;
- configurable execution tolerance below the proposal floor for short-lived drift, initially 0.001 absolute (example: approved at >=0.995 may still execute at >=0.994 if all material terms remain valid);
- never tolerate loss of `verified=true` when verification is required;
- never tolerate a price above the approved maximum;
- never tolerate GPU/model/count/VRAM, model artifact, image, TP, context, disk, transport, or security changes without new approval;
- log proposal reliability and execution reliability separately.

The exact tolerance belongs in owner-configurable policy and tests. It is not permission to silently accept a materially degraded host.

### 6.3 Approval-to-create latency

Once explicit owner approval is received:

1. immediately fetch the approved offer;
2. validate **material terms + policy tolerances**;
3. build the exact create payload;
4. verify no forbidden secret/material mutation;
5. create immediately if still eligible;
6. do not perform repeated ranking/polling that needlessly loses the offer;
7. if the exact offer vanished, return to prepare mode rather than substituting silently.

Target: seconds from approval to create, not minutes, when the offer is still valid.

### 6.4 Diagnostic transport policy

For the current `ssh_direct` investigation:

- capture sanitized raw create/show payloads;
- allow a bounded wait after provider `running` for endpoint metadata to populate;
- distinguish provider status convergence from permanent endpoint absence;
- preserve diagnostics before destroy;
- do not repeatedly buy hosts to answer a schema question that can be answered from provider documentation/payloads;
- once the direct endpoint lifecycle is understood, encode it in deterministic tests.

---

## 7. Sports revenue path

Sports is a near-term product/revenue candidate, but the system must remain advisory and data-driven.

Order of operations:

1. canonical ingestion foundation;
2. Arb V1 on deterministic fixtures;
3. provider research and real odds adapter;
4. live opportunity lifecycle and alerts;
5. multi-user preferences/book availability;
6. Table Tennis data acquisition and research stack;
7. shadow predictive models;
8. evidence-gated production predictive intelligence;
9. portfolio/risk analytics.

The Sports LLM is not the predictor or arb calculator. It explains, queries, researches, and reasons over structured outputs.

Initial risk architecture remains owner configurable; any future stake recommendations must be advisory, auditable, calibrated, and bounded by user/platform limits.

---

## 8. SCS business-value path

SCS AI is valuable when it reduces administrative and technical workload, not when it merely chats.

Priority workflow targets:

- TAB/commissioning workbook cleanup;
- formula and range manipulation;
- professional report generation;
- Word/PDF closeout packages;
- estimate/invoice preparation;
- customer/job/equipment lookup;
- HVAC manual/project-document research;
- email/report drafting;
- eventually approved workflow automation.

Build `SCS-Bench` from realistic tasks. Preserve input artifacts and expected outcomes so model/provider/tool changes can be compared objectively.

Example evaluation families:

- repair/normalize a messy workbook without destroying formatting;
- identify missing TAB readings;
- add formulas correctly and honestly report recalculation state;
- generate a professional client summary;
- populate an estimate/report template;
- modify a document without corrupting structure;
- use tools correctly after an error;
- retrieve relevant HVAC job/manual information without inventing data.

---

## 9. Evaluation assets from day one

### SCS-Bench

Every realistic Office/HVAC workflow should become a reusable evaluation fixture where licensing/privacy permit.

### Sports-Bench

Include true arbs, false arbs caused by settlement mismatch, stale legs, three-way markets, different lines, duplicate provider observations, and price movement before alert.

### Coder-Bench

Use actual repository tasks, multi-file edits, terminal/test loops, failure recovery, tool correctness, cost, latency, and final patch quality. Compare hosted reference models against self-hosted aliases before promoting model/routing changes.

---

## 10. Integration milestone

Do not wait for a calendar week. Trigger integration when these three gates are met:

1. **DEFENDcoder:** first successful repeatable live smoke or a clearly isolated provider blocker with stable local interfaces;
2. **SCS AI:** Office Tools 1A green with containment/versioning tests;
3. **Sports:** Arb Engine V1 green with equivalence and lifecycle tests.

Then temporarily freeze shared-surface feature work and create/use:

`platform/control-center-v2-integrate`

Integration sequence:

1. establish exact parent commits for Sports Task 7, latest stable Coder runtime, and SCS AI;
2. cherry-pick/merge product commits in a documented order;
3. resolve shared-platform and Control Center conflicts intentionally;
4. make all four product cards truthful and functional;
5. run full regression from a clean worktree;
6. smoke each product independently;
7. verify stopping one product cannot kill another product's process/tunnel;
8. document local startup/shutdown and origins;
9. only then promote the integrated branch toward main.

---

## 11. External origins / tunnels

Target public spaces:

- DEFEND AI: existing DEFEND AI origin;
- DEFEND Sports: `https://defendsports.defend-network.org`;
- DEFENDcoder: `https://defendcoder.defend-network.org`;
- SCS AI: `https://ai.sunshineclimatesolutions.com`.

Inactive products may deliberately return 503 until their authenticated origin is production-ready. DNS/tunnel reachability alone is not application readiness.

SCS AI's tunnel is independent and must be started/stopped/observed independently. Document the 8300 origin binding when switching its Cloudflare route from placeholder 503 to live origin.

---

## 12. Deferred work — intentionally not forgotten

### DEFENDcoder

- AUTO/FAST/MAXIMUM routing;
- planner/reviewer/recovery;
- member accounts/sandboxes;
- Stripe-backed billing;
- paid Heavy tier;
- model/adapter training from successful traces;
- broader GPU/provider abstraction.

### DEFEND Sports

- real external odds feed;
- Table Tennis point-level feed;
- prediction research stack;
- alerts/notifications;
- member UI;
- bankroll/portfolio personalization;
- Sports AI production UI;
- historical research/experiment platform.

### SCS AI

- business DB interfaces;
- knowledge/manual tools;
- final model/provider selection;
- authenticated web UI;
- production tunnel activation;
- workflow approvals/audit;
- email/calendar/accounting integrations where appropriate.

### Platform

- Control Center V2 integration;
- unified observability without shared mutable state;
- deployment docs;
- CI/release gates;
- backup/restore and disaster recovery;
- production authentication/authorization review.

---

## 13. Immediate next actions

### Agent / Window A — DEFENDcoder

- commit the prepared raw-payload/direct-endpoint lifecycle diagnostics before another paid run;
- investigate Vast instance schema/timing;
- implement bounded endpoint-publication wait if supported by evidence;
- modify approval verification so material terms are strict but reliability uses an explicit small policy tolerance;
- optimize approval -> create path for immediate purchase;
- test all changes without billable calls;
- only then perform another owner-approved live run.

### Agent / Window B — SCS AI

Start **SCS-AI-1A Office File Tools** from `scs/ai-foundation-v1` @ `1e10f27` (or the exact accessible commit once pushed). Office tools first; business interfaces later; knowledge tools last. No shared Control Center edits.

### Agent / Window C — Sports

Start **Arbitrage Engine V1** from the accepted Task 7 tip `040fdc7` (or exact accessible commit once pushed). Equivalence first, math second, lifecycle third. Fixtures only initially. No shared Control Center edits.

### Owner coordination

- ensure important local commits are pushed to durable remote branches before integration;
- rotate any tunnel/API secrets ever exposed in terminal/chat history;
- approve billable Coder instances only from a current material plan;
- keep product feature work moving even if Vast is temporarily blocked.

---

## 14. Definition of the next major checkpoint

The program reaches the next major checkpoint when:

- DEFEND AI remains regression-green;
- DEFEND Sports can ingest canonical data and detect/track mathematically valid fixture arbs without false equivalence;
- DEFENDcoder can reliably acquire or clearly diagnose compute, launch the pinned runtime, and produce a real measured smoke trace;
- SCS AI can safely manipulate representative XLSX/DOCX artifacts inside its contained workspace;
- Control Center V2 integration has a clean path to launch/observe all four spaces.

At that point, shift from foundation-building to **product usability, real data/provider integrations, UI, and controlled production rollout**.

---

## 15. Decision log captured by this plan

- Four top-level Control Center spaces are locked: DEFEND AI, DEFEND Sports, DEFENDcoder, SCS AI.
- All sports get arbitrage/market intelligence; Table Tennis gets deep predictive intelligence first.
- Sports production is advisory/signaling; deterministic code owns arb/probability math.
- SCS AI is tool-first, especially Office/HVAC workflows.
- Coder default/heavy are distinct; Heavy uses pinned Coder-Next deployment artifacts.
- Coder cost accounting is first-class and must use measured/provider-reported data.
- Control Center integration is serialized; product work proceeds in parallel.
- SCS AI owns a separate Cloudflare tunnel lifecycle.
- Coder approval hashes bind material launch configuration, including transport.
- Volatile reliability values are policy/ranking inputs with explicit tolerance, not fragile exact-hash equality fields.
- After owner approval, qualifying volatile compute should be purchased promptly rather than lost to unnecessary re-ranking.
- Tiny reliability drift alone must not force a new approval when the offer remains inside the explicitly configured execution tolerance and all material cost/security/runtime terms remain valid.
