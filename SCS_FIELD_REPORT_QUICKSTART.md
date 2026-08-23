# SCS Field Report System — Quick Start

Field report workflow for Sunshine Climate Solutions, built into the SCS
operations web app. No CLI needed — everything runs from the Control Center
and the Reports screen.

## Field workflow (13 steps)

1. Open the **Control Center** (http://127.0.0.1:3000) and log in as owner.
2. Click **Launch** (SCS) — starts scs:api, scs-ai:api, scs:web, and the tunnel.
3. Click **Open** (SCS), then open **Reports**.
4. **New TAB Job** — enter project, site, date, technician.
5. **Select or add** the hiring contractor.
6. Enter **job/site info** and the categories tested.
7. Add **equipment and readings** (air devices, traverses, findings).
8. **Upload photos** of nameplates and field conditions.
9. **Review** missing or uncertain evidence — confirm or mark N/A.
10. Generate the **report plan**.
11. **Compose** the workbook.
12. **Clear WARN / BLOCK** items the report points out.
13. **Export the XLSX** and open it to verify before delivering.

Every screen autosaves (debounced). Status on the home screen derives from
record content: DRAFT → EVIDENCE_INCOMPLETE → READY_TO_PLAN → PLANNED →
READY_TO_EXPORT → VALIDATION_BLOCK/WARN → EXPORTED.

## Prerequisites

- Python venv: `C:\Users\thoma\Documents\Codex\DEFEND\.venv`
- Data root: `C:\SCS_DATA` (overridable with `SCS_DATA_ROOT`)
- Masters catalog (read-only, byte-verified): `C:\SCS_DATA\masters`
- Working copy: `.worktrees\control-center-v2-integrate` (branch
  `control-center-v2-integrate`)

## Starting the stack manually (if not using the Control Center)

SCS core API (port 8100):

```powershell
& "C:\Users\thoma\Documents\Codex\DEFEND\.venv\Scripts\python.exe" -m uvicorn scs_api.runtime:app --host 127.0.0.1 --port 8100
```

SCS web app (port 3100):

```powershell
# from scs-ui
npm run build
npm run start
```

Health check: `http://127.0.0.1:8100/health` returns
`{"ok": true, "application_id": "scs", "schema_version": 5}`.

## Sign in

- Employee: `demo` / `demo-password-1`
- Open http://127.0.0.1:3100, log in, choose **Reports** in the nav.

## API surface (base `http://127.0.0.1:8100/api/scs/reports`)

| Method | Path | Purpose |
| --- | --- | --- |
| GET/POST | `/contractors` | list / add hiring contractor |
| GET/POST | `/jobs` | list / create job |
| GET/PUT | `/jobs/{job_id}` | load / full-record replace (edit+delete anywhere) |
| POST | `/jobs/{job_id}/photos` | multipart upload (`files[]`), SHA-256 ingest |
| GET | `/jobs/{job_id}/plan` | planned sections |
| POST | `/jobs/{job_id}/compose` | compose workbook + grouped validation |
| GET | `/jobs/{job_id}/outputs` | list `.xlsx` outputs |
| GET | `/jobs/{job_id}/outputs/{filename}` | download output |
| GET | `/vision/status` | vision provider status |

Auth: session cookie `scs_employee_session` (Secure — scripts must send
the `Cookie` header explicitly over http; browsers on loopback are fine).

## Data locations

- Jobs: `C:\SCS_DATA\jobs\<job_id>\` (`job.json`, `plan.json`,
  `evidence.json`, `originals/`, `extracted/`, `output/`)
- Photo staging: `C:\SCS_DATA\config\_uploads\<job_id>\` (cleaned after ingest)
- Logs: `C:\SCS_DATA\logs\scs-api.{out,err}.log`

## Known limits

- Vision provider: stub only (`NOT_CONFIGURED`); no auto-extraction yet.
- `categories_tested` is stored on the record but not yet composed into
  the workbook.
- Validation warnings (e.g., "missing airflow_cfm", "% design 0.0") are
  advisory; blocks are rare and explainable.

## Tests

- Backend reports: `pytest tests/test_scs_reports.py tests/test_scs_reports_api.py`
- Frontend: `cd scs-ui && npm test`
- Build/typecheck: `cd scs-ui && npm run build`