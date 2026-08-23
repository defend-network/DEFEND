# LEGACY STACK — NOT CANONICAL RUNTIME

Nothing under this directory may be used as the implementation authority for
DEFEND AI, DEFENDcoder, DEFENDMarkets, SCS, Control Center, or shared_platform.

Canonical product code may not import from `legacy_stack` except through the
exactly enumerated transitional exceptions documented in
`docs/platform/architecture-ledger.md` and enforced by
`tests/test_legacy_firewall.py`.

If transitional runtime must still execute from here, it must be launched only
through an explicitly named LEGACY adapter/tool.

## Status taxonomy

Every module under `legacy_stack/` carries exactly one of:

- `LEGACY_ACTIVE_TRANSITIONAL` — old runtime still temporarily executable for
  migration/data inspection, explicitly NOT canonical.
- `LEGACY_COMPATIBILITY_SHIM` — tiny old import-path adapter only, zero
  business/runtime logic.
- `HISTORICAL_REQUIRED` — migration/provenance/history artifacts whose ordering
  or identity must remain intact.

Machine-readable classification: `docs/platform/stack-registry.json`.

## Contents

- `defend_sports/` — legacy DEFEND Sports runtime (transition/data-inspection).
  `LEGACY_ACTIVE_TRANSITIONAL`; canonical replacement is `defend_markets/`.
  Its SQL migrations under `defend_sports/migrations/` are `HISTORICAL_REQUIRED`.
