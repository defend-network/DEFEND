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

## HISTORICAL NON-RUNTIME

`archive/` (reserved) — non-importable historical reference.

## Documentation

- `docs/platform/architecture-ledger.md` — durable ownership/debt ledger.
- `docs/platform/stack-registry.json` — machine-readable stack classification.
- `legacy_stack/README.md` — legacy quarantine notice.

## Rules

- Canonical product code may NOT import `legacy_stack` (enumerated exceptions
  enforced by `tests/test_legacy_firewall.py`).
- `shared_platform/` imports no product and no Control Center.
- Compatibility shims are logic-free; see `tests/test_stack_taxonomy.py`.
