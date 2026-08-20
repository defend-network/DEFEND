# SCS Field Report System — MVP Delivery Report

**Date:** 2026-08-18 · **Status:** MVP COMPLETE (backend + CLI + REST API) · **Branch:** control-center-v2-integrate (worktree) · **NOT COMMITTED** — awaiting owner review

---

## 1. What was delivered

### 1.1 Master workbook catalog (canonical, immutable)

Five client-supplied workbooks were audited and staged into `C:\SCS_DATA\masters`, renamed to canonical SCS names. A sha256 registry (`C:\SCS_DATA\config\masters.sha256.json`) locks their bytes; `verify_unchanged` confirms immutability before every compose.

| Master | Source | Sections it supplies |
|---|---|---|
| `SCS-CrunchFitness.xlsx` | `Downloads\CRUNCH_FITNESS_LAKELAND.xlsx` | Cover, Certification, Abbreviations, Executive Summary |
| `SCS-Gatorade-Report.xlsm` | `Downloads\GatoradeWarehouse.xlsm` | Scope Summary, RTU Data Tags/Units, Building Pressurization, Fan Test, VFD Report, Photo Log, Remarks, Final Closeout |
| `SCS-LakePanasoffkee-Traverse.xlsx` | `Downloads\Lake Panasoffkee Elementary.xlsx` | Duct Traverse Summary, Traverse point sheets |
| `SCS-Roland-VAV.xlsx` | `Downloads\Roland Magnet K-8.xlsx` | VAV Data |
| `SCS-BP-RTU-Data-Only.xlsx` | `Downloads\SCS_Building_Pressurization_and_8_RTU_Data_Only.xlsx` | (backup/no-section source — kept, not selected) |

Selection is deterministic (per-section canonical mapping in `scs_reports/masters.py`); a section comes from exactly one master. No section may be sourced from two masters.

### 1.2 The structured job record (source of truth)

`scs_reports/schema.py` — every field carries provenance. Nothing is composed from free text; the workbook is a projection of the record.

- `JobRecord` → `JobMetadata`, `Equipment[]` (RTU/AHU/FCU/VAV/FAN/VFD/EXHAUST/OA), `Measurement[]` (field, value, unit, `Provenance`, source_ref, confidence, technician_confirmed, timestamp), `AirDevice[]` (design/as-found/final CFM), `Traverse[]` + `TraversePoint[]`, `Finding[]` (severity, evidence_refs), `PhotoEvidence[]` (sha256, classification, review_status), `Contractor`.
- `Provenance`: `TECH_ENTERED` (ground truth), `AI_INFERRED_TEXT`, `AI_INFERRED_VISION`, `TRANSFERRED_EXISTING` — AI-inferred values require `technician_confirmed=True` or validation BLOCKS.
- Evidence manifest: photos are copied byte-identical into `C:\SCS_DATA\jobs\<job>\originals\`, sha256 recorded; originals never modified.

### 1.3 Deterministic planner

`scs_reports/planner.py` — sections are selected purely from record content (RTUs → nameplate sheet, air devices → building pressurization, traverses → traverse sheets, VAVs → VAV sheet, fans → fan test, VFDs → VFD report, photos → photo log, notes → remarks). **No phantom sections** — empty record yields exactly cover + certification + closeout. The validator independently re-derives the expected section set and BLOCKS on any mismatch.

### 1.4 Deterministic composer

`scs_reports/composer.py` — `copy-verified-master → modify cells` per section. No phantom data, no partial writes, no cached/master copy ever mutated (byte-identical verification is a pre-compose gate and a post-compose validator check).

- RTU nameplates: cloned row blocks C..H, formulas preserved (e.g. `=IF(OR(D18="",F18=""),"",F18/D18)`).
- Building pressurization: 10 device rows, OA/Exhaust/Diffuser design + final pressure cells, columns I (design) and K (final) computed by formula (`=J11*E11` traverse totals).
- Traverses: summary rows + one sheet per traverse with point columns and FPM/area/CFM math.
- VAV: design min/max/actual rows.
- Fan test / VFD: whole-sheet-per-instance.
- Photo log + remarks: deterministically built when evidence/notes exist.
- Closeout: document matrix rows (certification, abbreviations, remarks, findings).
- Output naming: `{Project}_{JobNumber}_TAB_{YYYY-MM-DD}.xlsx`, then `_v02`, `_v03`… on regeneration. **Never overwrites** any prior output (verified by test).

### 1.5 Validation gate

`scs_reports/validation.py` — 20 checks, PASS/WARN/BLOCK (any BLOCK → report not releasable):

required header fields · no phantom equipment · no duplicate equipment · equipment instance consistency · measurement units · required measurements · calculation outputs (% design in range) · calculation inputs present · design vs actual consistency · no orphan evidence refs · photo manifest valid · no invented (unconfirmed) measurements · no phantom sections · workbook opens · formulas well-formed · print areas resolve · no placeholder text · no unexplained required blanks · master immutability.

### 1.6 CLI (`python -m scs_reports.cli`)

`init-masters | masters-status | contractors list|add | job create|show|add-equipment|add-measurement|add-air-device|add-traverse|add-finding|set-notes|add-photo | plan | compose | validate | smoke`

### 1.7 REST API (`/api/scs/reports/*` on :8100, auth required)

contractors (list/add) · jobs (list/create/get) · equipment · measurements · air-devices · traverses · findings · notes · photos (multipart upload → sha256 manifest) · plan · compose (returns validation summary + output file) · outputs. Session-cookie auth, same CORS origins as the web app.

## 2. Verification evidence

### 2.1 Automated

- **Full test suite: 1638 passed, 77 skipped** (includes all prior product suites).
- New: `tests/test_scs_reports.py` — 16 tests (paths, contractors, job round-trip, photo sha256 manifest, master immutability/tamper detection, planner selection/no-phantom, versioned outputs, gate matrix incl. phantom equipment, invented unconfirmed values, duplicates, missing fields, orphan evidence, phantom sections).
- New: `tests/test_scs_reports_api.py` — 5 tests (auth required, contractor flow, full job lifecycle through compose, 404s, multipart photo upload + staging cleanup).

### 2.2 Synthetic smoke job (tonight's gate)

`scs_reports.cli smoke` — a synthetic job (warehouse, RTU + VAV + 2 air devices, traverse, damper-closed finding, sample photos, notes):

```
OUTPUT: C:\SCS_DATA\jobs\smoke_tab_job\output\Synthetic Smoke Warehouse_999999_TAB_2026-08-18_v04.xlsx
VALIDATION = 16 PASS / 3 WARN / 0 BLOCK · WORKBOOK_OPENS = PASS
```

The 3 WARNs are legitimate signals of the synthetic scenario (VAV lacking manufacturer; RTU-1 measured 0 CFM — the finding itself; % design 0.0). Sheet-level spot checks: 13 sheets in canonical order; cover C10/C16 (project, contractor), certification C6, RTU B16..B26 (tag/manufacturer/model/refrigerant), BP rows 17-18 + F18=1445 + G18 formula, traverse summary A11 + K11 formula, VAV B11/E11, photo log A10/B10, closeout C12 — all verified.

### 2.3 Live-stack verification (real :8100)

Full lifecycle against the running SCS stack, authenticated as the demo owner:
- login 200 → cookie `scs_employee_session`
- contractor list (pre-seeded "Remedy Heating and Cooling" from the smoke run)
- job create 201 (555001), RTU + VAV equipment 201, OA-1/EF-1 air devices 201, finding 201
- plan → exactly `cover, certification, abbreviations, executive_summary, rtu_nameplate, building_pressure, vav_data, closeout`
- compose → `Live API Test_555001_TAB_2026-08-18.xlsx`, **blocked: false**, all 20 checks green
- outputs list → 1 file
- multipart photo upload → 201, PHOTO-001 sha256 recorded, staging cleaned up, persisted to job record

## 3. Hard rules enforced (from the spec)

1. **Masters are immutable** — sha256 registry; compose re-verifies; validator BLOCKS if altered.
2. **Original photos are never modified** — byte-identical copies + sha256 manifest.
3. **Nothing is invented** — AI-inferred measurements need technician confirmation or BLOCK.
4. **No phantom sections** — planner + validator agree; empty job = 3 sheets only.
5. **Validation gates release** — 0 BLOCK required.
6. **Deterministic calculations** — formulas in the workbook compute derived values; composer writes inputs + formulas, never precomputed siloed numbers.
7. **Never overwrite** — versions `_v02`, `_v03`, …; `master_unchanged` + `output versioning` tested.
8. **Structured record is the single source of truth** — API/CLI both write the record; compose is a pure projection.
9. **Human-in-the-loop** — technician_confirmed flag, review_status on photos, validation WARNs surface gaps (missing manufacturer, missing measurements) instead of inventing them.
10. **Contractor dropdown** — contractors list/add implemented (system starts empty; dropdown source ready for UI).

## 4. Environment / runtime notes

- Data root: `C:\SCS_DATA` (env `SCS_DATA_ROOT` override; `scs_data_root()` helper). Layout: `masters/`, `contractors/companies.json`, `config/` (sha256 registry), `jobs/<job_id>/{job.json, evidence.json, originals/, output/}`.
- Live stack: scs:api restarted on :8100 with the new routes (pid 60860, health ok). scs:web :3100 and scs-ai:api :8300 unchanged and still running. Control Center (CC) on 8000/3000 still runs **old** products.py — restart CC when ready so `Launch` starts `scs:api` automatically (products.py now launches scs:api first; state requires core API + AI API + web + tunnel).
- Demo owner: `demo@sunshineclimatesolutions.com` / `demo` / `demo-password-1`.
- None of this work is committed — per instruction, stopping before commit for owner review.

## 5. Acceptance test for tomorrow (real TAB job)

1. Start from a clean machine state: restart CC → `Launch SCS` (scs:api comes up with reports routes).
2. In the field: create job via UI/API → add equipment + measurements + air devices + traverse + findings → upload photos.
3. `python -m scs_reports.cli compose --job <id>` or `POST /api/scs/reports/jobs/<id>/compose`.
4. Gate: validation summary must have **0 BLOCK** before the report leaves the truck.
5. Deliver `{Project}_{JobNumber}_TAB_{YYYY-MM-DD}.xlsx` — opens in Excel with all formulas live.

## 6. Known limitations / next steps (not part of this MVP)

- **scs-ui reports screens** (job builder, evidence upload, review UI) — API is ready, UI not yet built. P0 UI items pending.
- Vision classification/fact extraction (`scs_reports/vision.py`) is a stub: `LocalVisionStub` (honest no-op) and `RemoteVisionUnconfigured` (explicit 503-style behavior) until a model endpoint is configured.
- Air-balance-calculation automation (per-air-device traverse CFM → as-found vs final logic) is deterministic data flow; field calibration per HVAC engineer rules remains manual.
- Job photos in the field flow: camera upload sizing/rotation handling untested on real hardware.
- `FINAL` status flow and PDF export (if required later) — not in scope for the MVP.
- The RAG/Fiction corpus under Downloads (extremist content) is unrelated to this task and was not touched.