<!-- DEFEND-AI-INGEST: EXCLUDE -->
# DEFEND multi-product integration checklist

Operator document, not DEFEND AI training language. Never ingest it into RAG,
memory, prompts, or model training data.

Maintained by integration review. Re-audit after any branch merge that touches
product boundaries (ports, origins, cookies, env prefixes, Control Center
launch, shared_platform, SCS/Sports setup).

Products in scope:

- DEFEND AI — member AI, identity, knowledge/RAG, legacy TableTennis panel
  (`api_server.py`, `defend-ui-v2/`, `defend_data/`, `TableTennis/`);
- DEFEND Sports / DEFENDmarkets — sports intelligence + market data plane
  (`defend_sports/`, `TableTennis/` legacy baseline; `markets/` worktrees);
- DEFENDcoder — software-engineering platform (docs only in this tree; code on
  `defendcoder/*` branches and worktrees);
- SCS AI — Sunshine Climate Solutions operations (`scs_api/`, `scs_data/`,
  `scs-ui/`);
- Control Center — desktop launcher (`defend_control/`,
  `tools/defend_control_center.py`);
- Setup & Integrations — `Bootstrap-DEFEND.*`, `Start-DEFEND.cmd`,
  `launch-control-center-v2.cmd`, `shared_platform/`.

## Canonical boundary contract

Source of truth: `shared_platform/phase0.py` (defend + scs),
`defend_sports/config.py` (sports), `docs/superpowers/specs/*` (coder).

| Product | Data root | Env prefix | Secret ns | Cookie | API | Web | Origin |
|---|---|---|---|---|---|---|---|
| DEFEND AI | `C:\DEFEND_DATA` | `DEFEND_*` | DEFEND | `defend_account_session` | 8000 | 3000 | `https://ai.defend-network.org` |
| SCS AI | `C:\SCS_DATA` | `SCS_*` | SCS | `scs_employee_session` | 8100 | 3100 | `https://ai.sunshineclimatesolutions.com` |
| DEFEND Sports | `C:\DEFEND_SPORTS_DATA` | `SPORTS_*` | SPORTS | `sports_session` | 8200 | 3200 | `https://defendsports.defend-network.org` |
| DEFENDcoder | TBD | TBD | TBD | TBD | TBD | TBD | `https://defendcoder.defend-network.org` |

Verification (2026-08-17, branch `sports/ds0-shared-platform-3app`):
`shared_platform/phase0.py:15-34`, `defend_sports/config.py:52-91`,
`defend_control/settings.py:80-82`.

## 1. Product names / labels

Status: WATCH.

- DEFEND AI labels are consistent (`defend_control/ui.py:230`,
  `tools/defend_control_center.py:548`); docs and Control Center agree.
- Control Center labels the single button "Start" / "Open DEFEND"
  (`defend_control/ui.py:269,272`); ops doc now matches
  (`docs/operations/DEFEND-Control-Center.md:75-77`).
- SCS brand drift: tab title "SCS Operations" (`scs-ui/app/layout.tsx:3`)
  vs login "Sunshine Climate Solutions" (`scs-ui/components/Login.tsx:13`)
  vs docs "SCS AI" (`docs/superpowers/specs/2026-08-14-defend-sports-master-architecture.md:27`).
- Product naming conflict across branches: this tree and the master spec call
  the sports product "DEFEND Sports"; the `markets/dm0-foundation` branch
  registers it as both `sports` AND `markets`
  (`.worktrees/defend-markets-dm0/shared_platform/application.py:13-14`,
  `defend_markets/config.py:56,73,83`) with a second origin/port set
  (8300/3300, `defendmarkets.defend-network.org`).
- DEFENDcoder exists only in docs
  (`docs/superpowers/specs/2026-08-14-defendcoder-architecture.md:2,13`);
  no code, port, or registry entry in this tree.
- Model label drift: `defend-ai` (forced, `defend_control/model_probe.py:162`,
  `orchestrator.py:679`) vs `defend-ai:latest` default
  (`tools/defend_control_center.py:418`, `api_server.py:40`). Same model in
  Ollama; label consistency only.

Owner window: markets/sports naming convergence belongs to
`markets/dm0-foundation` and `sports/ds0-task6` owners before either merges;
SCS branding to `scs/ai-foundation-v1`.

## 2. Origins / ports

Status: OK with two latent conflicts.

- DEFEND 3000/8000/8001 (`defend_control/settings.py:80-82`,
  `preflight.py:23`); SCS 3100/8100 (`shared_platform/phase0.py:32-33`); no
  numeric collisions.
- Sports 8200/3200 (`defend_sports/config.py:56-58`) matches the DS0 plan
  (`docs/superpowers/plans/2026-08-14-defend-sports-ds0-ds1.md:571-575`).
- Conflict A: `markets/dm0-foundation` reassigns the same product to
  8300/3300 + `defendmarkets.defend-network.org`
  (`.worktrees/defend-markets-dm0/defend_markets/config.py:54-56,70-73`),
  contradicting `defendsports.defend-network.org`. Must be resolved before
  merge.
- Conflict B: Control Center port preflight knows only 3000/8000/8001
  (`defend_control/preflight.py:468-504`); an already-running SCS or sports
  stack is invisible to it. Sports-aware preflight exists only on
  `sports/arb-v1` (`.worktrees/defend-sports-arb-v1/defend_control/products.py:59-106`).
- DEFEND CORS allowlist (`api_server.py:381-394`) includes
  `https://api.defend-network.org` and `https://defend-ai.defend-network.org`
  alongside the canonical `ai.defend-network.org`; confirm the two extras are
  still needed when the tunnel/origin set is next reviewed.
- Hardcoded localhost fallbacks: `scs-ui/lib/api.ts:1`
  (`http://localhost:8100`), `defend_control/health.py:57`.

Owner window: ports/origins are locked by
`sports/ds0-shared-platform-3app` (current branch) and
`platform/setup-integrations-v1`.

## 3. Control Center Launch / Open behavior

Status: WATCH.

- Canonical launcher is `Start-DEFEND.cmd` (runs
  `tools.defend_control_center`); `start_api.ps1` is a redundant wrapper;
  `RUN.txt` is retired but present.
- "Open DEFEND" opens only the single configured DEFEND origin
  (`defend_control/controller.py:301-304`, default
  `tools/defend_control_center.py:413`). SCS has no launch/open path in this
  tree: `build_scs_process_specs` (`shared_platform/phase0.py:59-89`) is never
  called by `defend_control/` or `tools/` (SCS Phase 1 is started manually per
  `docs/operations/DEFEND-Control-Center.md:222-237`).
- `launch-control-center-v2.cmd` is an orphaned dev launcher that hardcodes a
  `.worktrees/control-center-v2-integrate` path and runs the v2 multi-product
  Control Center (per-product tabs, `products.py`, `coder_m0.py`). It shares
  `%LOCALAPPDATA%\DEFEND\control-center.json` + `secrets.dpapi` and the same
  ports as v1; running both can start a second DEFEND stack that v1 only
  detects via port-occupied checks (`preflight.py:495-504`).
- `Bootstrap-DEFEND.ps1:1` declares `-Repair` but never uses it; docs tell
  users to run `Bootstrap-DEFEND.cmd -Repair`
  (`docs/operations/DEFEND-Control-Center.md:24-27`).

Owner window: v1/v2 convergence to `platform/control-center-v2-integrate`;
bootstrap repair to `platform/setup-integrations-v1`.

## 4. Login / auth boundaries

Status: OK.

- Cookies are product-scoped and hard-validated:
  `shared_platform/application.py:20,30`; `scs_data/config.py:24-26` rejects
  any context not exactly SCS; forged DEFEND cookie cannot authenticate
  (`tests/test_scs_auth_api.py:60`).
- SCS routers resolve only `context.session_cookie`
  (`scs_api/auth_routes.py:55`, `customer_routes.py:38`,
  `employee_routes.py:20`). Zero `defend_account_session` reads in SCS code.
- DEFEND admin uses separate bearer flow (`admin_auth.py:136-150`); SCS admin
  uses roles (`auth_routes.py:61-64`).
- Control Center itself does not authenticate; it stores product credentials
  in one un-namespaced DPAPI store (`defend_control/secrets.py:228-313`).
  `shared_platform/secrets.py:12-67` provides `NamespacedSecrets` but the
  Control Center does not use it — SCS credentials would land in the DEFEND
  DPAPI file unless Setup is extended.
- Caveat: DEFEND identity secrets are required for any Control Center launch
  (`defend_control/preflight.py:24-31`), i.e., DEFEND auth config is treated
  as globally mandatory.

Owner window: Control Center secret namespacing to
`platform/setup-integrations-v1` when SCS Setup fields are added.

## 5. Shared navigation

Status: OK in this tree; dead-end on sign-in.

- DEFEND AI nav: `/`, `/admin`, `/activate` only; all resolve
  (`defend-ui-v2/components/AdminWorkstation.tsx:47-59,125-131`).
- SCS nav: same-page anchors `#jobs`, `#customers`, `#employees`
  (`scs-ui/components/Workspace.tsx:15`); no cross-product links anywhere
  (verified by grep). Minor: `#customers` anchor renders even when the
  `view_customers` section is gated (`Workspace.tsx:21`).
- No sports/markets or coder UI exists in this tree, so no nav can route to
  them from DEFEND AI or SCS (markets UI exists only on the markets branch,
  unlinked: `.worktrees/defend-markets-dm0/defend-ui-v2/app/markets/`).
- Sign-in dead-end: the only member sign-in text is
  `defend-ui-v2/components/AccountActivation.tsx:120`; `POST /api/account/login`
  and `/api/account/logout` have no UI caller. Login UX is an open product
  question, not an integration defect.

Owner window: login UX to `agent/admin-identity-observability`.

## 6. Mobile responsiveness

Status: OK (DEFEND AI), WATCH (SCS).

- DEFEND AI responsive breakpoints 980/700/480 px; identity tables use
  contained horizontal scroll; no page-level overflow.
- SCS is partially responsive: single `@media(max-width:600px)` block, no
  touch-target sizing, `nav{overflow:auto}` only
  (`scs-ui/app/globals.css:1`). No explicit viewport meta in
  `scs-ui/app/layout.tsx:4` (relies on Next.js default injection).
- Control Center is desktop tkinter (`defend_control/ui.py:5-6`); no
  responsive claim.

Owner window: SCS polish to `scs/ai-foundation-v1`.

## 7. Health / status semantics

Status: WATCH (shapes differ by product; wire endpoints are DEFEND-only).

- DEFEND `/health` now self-identifies:
  `{"ok", "application_id": "defend", "model", "tools"}`
  (`api_server.py:415-419`, aligned 2026-08-17).
- SCS `/health`: `{"ok", "application_id": "scs", "schema_version"}`
  (`scs_api/app.py:39`); duplicated logic in `scs_data/core.py:32-44`.
- Sports: `defend_sports/db.py:65-82` (`application_id: "sports"`) but no wire
  endpoint in this tree (app exists only on `sports/ds0-task6`:
  `.worktrees/defend-sports-task6/defend_sports/app.py:22-24`).
- Control Center probes: API `:8000/health`, frontend `:3000/`,
  cloudflare/public origin, model `:8001/v1` (`defend_control/orchestrator.py:834-881`).
  SCS health is never checked by the Control Center in this tree.
- Duplicated probe implementations: `defend_control/health.py:95-164` vs
  `defend_control/model_probe.py:37-76` (private `_NoRedirectHandler`).

Owner window: SCS/sports health supervision to the Control Center belongs to
`sports/ds0-task7`; probe dedup to `platform/control-center-v2-integrate`.

## 8. Setup / config ownership

Status: WATCH.

- Control Center Setup is DEFEND-only but presented as global
  (`defend_control/ui.py:21-43`); DEFEND-specific constraints hard-coded in
  the settings object (`defend_control/settings.py:14,83,181-212`).
- SCS reads only `SCS_*` (`scs_api/runtime.py:26-42`); no `DEFEND_*` or
  `control-center.json` reads anywhere in SCS (clean ownership). SCS settings
  have no Setup path — they live in `shared_platform/phase0.py:25-34` and
  `scs_data/config.py`.
- Sports config owned by `defend_sports/config.py:52-91`; not in the Control
  Center (per plan Task 7, assigned to `defend_control/settings.py` etc.;
  implemented only on `sports/arb-v1`).
- Env-var mismatch (latent): `shared_platform/phase0.py:86` sets
  `SCS_API_ORIGIN` on the web process, but the UI reads
  `NEXT_PUBLIC_SCS_API_ORIGIN` (`scs-ui/lib/api.ts:1`); `NEXT_PUBLIC_` values
  are inlined at build time, so the browser always uses the
  `http://localhost:8100` fallback. Harmless while SCS is local-only; must be
  fixed with a build-time value before public activation.
- `scs_data/*` imports utility modules from `defend_data` (`scs_data/core.py:7`,
  `identity.py:9`, `migrations.py:6`) — SCS cannot run without the DEFEND
  package installed.

Owner window: per-product Setup to `platform/setup-integrations-v1`; SCS env
injection to the same window ahead of public activation.

## 9. Duplicated code

Status: WATCH (tolerable for now; dedup after product stabilization).

- `defend_control/local_model.py:105-170` vs `remote_vllm.py:273-344`:
  ~95% duplicate process-spec builders; `shared_platform/phase0.py:59-89` is a
  third builder unused by the Control Center.
- Health probe duplicated in `defend_control/health.py` vs
  `model_probe.py:37-76`.
- Auth surface: `scs_api/auth_routes.py` (136 lines) vs
  `api_identity_routes.py` (579 lines) — parallel login/logout/session/
  invitation/rate-limit flows (~70% flow similarity, different stores).
- Identity stores: `scs_data/identity.py` vs
  `defend_data/identity_store.py`; append-only audit duplicated in
  `scs_data/audit.py:38-67`.
- Data-root-from-env parsing exists four times: `defend_data/config.py`,
  `defend_sports/config.py:43-49`, `scs_data/config.py:20-39`,
  `shared_platform/application.py:19-69`; the markets branch adds a fifth
  (`.worktrees/defend-markets-dm0/defend_markets/config.py`).
- Store patterns: `defend_sports/repositories.py` vs `TableTennis/tt_store.py`
  (idempotent upserts + append-only snapshots + health).

Owner window: dedup belongs to `platform/control-center-v2-integrate` and
`platform/setup-integrations-v1`; do not refactor while sports DS0 and SCS
Phase 1 branches are open.

## 10. Stale "Sports" naming

Status: OK in this tree.

- No label says "Sports" while rendering the legacy TableTennis panel; the
  legacy panel is labeled "TableTennisAI"
  (`defend-ui-v2/components/AdminWorkstation.tsx:129`,
  `TableTennisPanel.tsx:213`) and stays until sports feature parity
  (`docs/superpowers/specs/2026-08-14-defend-sports-master-architecture.md:30,478`).
- "Sports" appears only as the real product (`defend_sports/`,
  `shared_platform/application.py:13`) and as the markets domain concept
  (`defend_sports/domain.py:105-138`).
- The only "Sports" UI label is on the markets branch sports desk
  (`.worktrees/defend-markets-dm0/defend-ui-v2/components/markets/marketsSections.ts`).

Owner window: rename risk belongs to `markets/dm0-foundation` before merge.

## 11. Dead buttons / routes

Status: WATCH.

- Control Center: all six buttons wired (`defend_control/ui.py:268-275`); no
  dead buttons.
- Dead route: `/api/admin/tt/health` (`api_admin_tt_routes.py:186-189`,
  registered `api_server.py:399`) has no UI or test caller — keep while the
  legacy TT panel is supported; retire with the panel.
- SCS routes with no UI caller: `POST /api/scs/auth/logout`,
  `GET /api/scs/auth/session`, `POST /api/scs/auth/activate`,
  invitation `retry`/`revoke` (`scs_api/auth_routes.py:84-131`), customer
  detail/summary (`customer_routes.py:62,86`), enrollments
  (`membership_routes.py:49`), import preview (`import_routes.py:25`).
- SCS UI dead prop: summary/metrics section
  (`scs-ui/components/Workspace.tsx:20`) never receives `summary`
  (`app/page.tsx:8`).
- Orphan scripts: `launch-control-center-v2.cmd` (worktree-hardcoded),
  `start_api.ps1` (wrapper around `Start-DEFEND.cmd`), retired `RUN.txt`.
- Unused parameter: `Bootstrap-DEFEND.ps1:1` `-Repair`.

Owner window: route retirement with legacy TT panel; SCS activation UI to
`scs/ai-foundation-v1`.

## 12. Accidental routing to DEFEND AI

Status: OK in this tree.

- SCS: zero DEFEND ports/origins/cookies/brand in `scs_api/`, `scs_data/`,
  `scs-ui/` (verified by grep). UI targets only 8100.
- Sports: `defend_sports/` uses only `SPORTS_*` env, no 8000/3000, no
  `defend_account_session` (verified).
- Legacy TT is intentionally DEFEND-AI-wired (`api_server.py:399`,
  `TableTennis/tt_store.py:16,26`) per the parity plan.
- Control Center: `controller.py:301-304` opens the single configured DEFEND
  origin — on the v2 multi-product center this could open DEFEND AI for a
  user who meant another product; per-product open is in the v2 worktree
  (`admin_surface.py:5`).
- Markets branch registers `sports` and `markets` as two applications for one
  product (`.worktrees/defend-markets-dm0/shared_platform/application.py:13-14`)
  — the single biggest routing hazard before merge.

Owner window: markets registration to `markets/dm0-foundation`; v2 per-product
open to `platform/control-center-v2-integrate`.

## Change log

2026-08-17 (branch `sports/ds0-shared-platform-3app`):

- Fixed: SCS API now sends CORS headers for its web origin and local
  `localhost:3100` / `127.0.0.1:3100` with credentials
  (`scs_api/app.py`). Browser login at 3100 → 8100 was previously blocked.
- Fixed: DEFEND `/health` now includes `application_id: "defend"`, matching
  SCS and sports health shapes (`api_server.py:415-419`).
- Fixed: ops doc labels updated to actual Control Center buttons "Start" and
  "Open DEFEND" (`docs/operations/DEFEND-Control-Center.md:75-77,82`).
- Verified: full unit suite 512 passed / 12 skipped (basetemp override
  required; `%TEMP%\pytest-of-*` has an environment permission issue).