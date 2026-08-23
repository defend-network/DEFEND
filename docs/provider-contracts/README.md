# Provider Contract Manifests

Versioned, sha256-pinned records of the authoritative API contracts that DEFENDMarkets
adapters are implemented against. One manifest per provider: `<provider_id>.contract.json`.
Contract artifacts (schemas, official docs, SDK references) are archived next to their
manifests with their exact digest so contract drift can be detected instead of silently
accepted.

## Rules

- Never store credentials or key-bearing URLs in this directory.
- Raw evidence is immutable once recorded; corrections create new entries, never edits.
- `unknown`/`UNVERIFIED` stays `UNKNOWN` until an empirical probe (Phase C) resolves it.
- Re-fetch and re-pin artifacts when a provider announces a contract change; the old
  digest is preserved in the drift check.

## Manifest fields

| Field | Meaning |
| --- | --- |
| `provider_id` | Provider entry id in `defend_integrations/registry.py` |
| `contract_type` | `openapi` / `schema` / `postman` / `official_docs` / `sdk` / `endpoint_catalog` / `empirical` |
| `source_url_or_origin` | Where the contract was retrieved from |
| `retrieved_at` | UTC ISO timestamp of retrieval |
| `provider_version_if_known` | API version the provider exposes (v2, v4, ...) |
| `sha256` | Pin of the primary archived artifact |
| `endpoint_count` | Number of documented endpoints (when known) |
| `auth_scheme` | Authentication the API requires |
| `rate_limit_notes` | Observed/documented throttling |
| `capability_summary` | What the contract provides (feeds, markets, depth) |
| `notes` | Secondary artifacts, caveats, open questions |

## Current manifest table (2026-08-20)

| Provider | Type | Version | Auth | Endpoints | Status |
| --- | --- | --- | --- | --- | --- |
| `sportradar_tt` | schema (XSD) + official docs | v2 (trial) | api-key | 22 | DONE; OpenAPI 403 w/o key - Phase C |
| `sports_game_odds` | official docs + SDK | v2 | x-api-key | 8 | DONE; empirical probe blocked on key |
| `oddspapi` | official docs + empirical | v4 | query api_key | ~5 | DONE (probe 2026-08-18) |
| `odds_api_io` | official docs | v4 | query | ~4 | documented (prior session) |
| `the_odds_api` | official docs + empirical | v4 | query apiKey | ~10 | DONE - NO TT coverage |
| `rapidapi_tabletennis` | official docs (catalog) | v1 | X-RapidAPI-* | TBD | DONE (fluis.lacasse / tabletennisapi) |
| `rapidapi_tt_micro` | official docs (catalog) | 1.0 | X-RapidAPI-* | TBD | DONE (sportmicro; free trial 300 req/day) |
| `rapidapi_allsportsapi2` | official docs (catalog) | - | X-RapidAPI-* | TBD | DONE - 8 sports, NO TT listed |
| `rapidapi_allscores` | official docs (catalog) | - | X-RapidAPI-* | TBD | DONE - football-first, TT unverified |
| `rapidapi_tt_live` | directive host only | - | X-RapidAPI-* | UNKNOWN | UNVERIFIED - Phase C probe resolves |

## Artifacts

- `sportradar_tt-schema.zip` - official Table Tennis v2 XSD
- `sportradar_tt-official_docs.md` - readme.io overview page (markdown variant)
- `sports_game_odds-official_docs.txt` - sportsgameodds.com/llms.txt
- `sports_game_odds-sdk.md` - official Python SDK API reference

Adapters must record the manifest they were implemented against; a pin mismatch
raises `CONTRACT_DRIFT` on the provider card.
