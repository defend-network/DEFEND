# DEFEND — Architecture Map

## CANONICAL RUNTIME

| Concern | Location |
| --- | --- |
| DEFEND AI | `defend_ai/` (+ `defend-ui-v2/`, `defend_data/`) |
| DEFENDcoder | `defend_coder/` (+ `defendcoder-ui/`) |
| DEFENDMarkets | `defend_markets/` + `defendmarkets-ui/` |
| SCS | `scs_*` (`scs_api/`, `scs_data/`, `scs_copilot/`, `scs_knowledge/`, `scs_reports/`, `scs_ai/`, `scs_diagnostics/`, `scs_engineering/`, `scs_equipment/`, `scs_procedures/`, `scs-ui/`) |
| Control Center | `defend_control/` |
| Neutral shared | `shared_platform/` |

## LEGACY

`legacy_stack/` — NOT canonical runtime. See `legacy_stack/README.md`.
`archive/` (reserved) — non-importable historical reference.

## Rules

- Canonical product code may NOT import `legacy_stack` (no exceptions;
  enforced by `tests/test_legacy_firewall.py`).
- `shared_platform/` imports no product and no Control Center.
- No legacy compatibility shims remain inside `defend_control/`.
- Legacy tools live under `legacy_stack/tools/`; legacy TT under
  `legacy_stack/table_tennis/`.

## Documentation

- `docs/platform/architecture-ledger.md` — durable ownership/debt ledger.
- `docs/platform/stack-registry.json` — machine-readable stack classification.
- `legacy_stack/README.md` — legacy quarantine notice.

## Known open migrations (P0.3R)

- `defend_markets/collector.py` still imports/writes `legacy_stack.defend_sports`
  (AUDIT-01 — Markets lane migration pending).
- `defend_control/{controller,orchestrator,local_model,remote_vllm,preflight}.py`
  still contain DEFEND-AI provider authority (AUDIT-02/03 — AI lane).
- `defend_control/products.py` still holds product settings/process builders.
- Root-level DEFEND-AI runtime files (`api_server.py`, `control_plane.py`, ...)
  are `CANONICAL_DEFEND_AI_MISPLACED` (next AI directive moves them).
