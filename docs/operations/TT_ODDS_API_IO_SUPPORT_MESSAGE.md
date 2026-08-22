# Odds-API.io Table Tennis Market Delivery — Owner Support Message

Prepared: 2026-08-22 (UTC). Owner sends this to Odds-API.io support.

## Account / provider state
- Plan: Solo
- Provider: Odds-API.io (v3 REST)
- Authentication: HTTP 200, authenticated
- Selected account bookmakers: Sbobet, SingBet

## Table Tennis
- Sport: Table Tennis
- Events available: 51 current events returned by `/v3/events?sport=table-tennis`
- Sample event IDs: `73859912`, `73853632`, `73850316`
- Tested identifiers against `/v3/odds`:
  - `Sbobet` — HTTP 200, bookmaker keys present: none, market entries: 0
  - `SingBet` — HTTP 200, bookmaker keys present: none, market entries: 0
- All three event states tested (pending, live, settled) return the same empty bookmaker payload.

## Control test (same account, same bookmakers)
- Sport: Football
- Event: `71805368`
- Result: both selected bookmakers return markets and prices (ML, Spread, Totals, and more).
- Conclusion: authentication and bookmaker entitlement are working; the empty result is specific to Table Tennis market delivery.

## Classification
TT_PROVIDER_PRICE_FEED_EMPTY — Table Tennis events are delivered, but neither selected bookmaker returns any Table Tennis market for this account.

## Note on the `/events` response
The provider's `/events` sweep is truncated at 16,384 bytes, which briefly surfaced as an adapter parsing issue on our side. That defect is fixed and is independent of the empty Table Tennis price feed described above.

## Request
Please confirm whether Table Tennis pre-match/live markets for Sbobet and SingBet are expected on the Solo account, and if so, why the current account receives zero Table Tennis markets while football markets are delivered.

## Re-test addendum — 2026-08-22 (UTC)
Fresh bounded re-test on the same Solo account confirms the same condition:

- Table Tennis events returned: 51 current (pending across International TT Elite Series, International TT Cup, Czech Liga Pro).
- Sample event IDs tested against `/v3/odds`: `73922828`, `73946574`, `73924232`.
- `bookmakers=Sbobet,SingBet` → HTTP 200, `bookmaker_keys=[]`, `markets=0`, no error field.
- `bookmakers=Hard Rock` → HTTP 403: "Access denied. You're allowed max 2 bookmakers. Allowed: Sbobet, SingBet."
- Hard Rock is present and `active=true` in the 275-entry `/v3/bookmakers` catalog, but is not an enabled account slot, so its Table Tennis coverage cannot be tested under the current selection.
- Classification remains `TT_PROVIDER_PRICE_FEED_EMPTY` for the two selected books. The Hard Rock limitation is account slot scope, not a request-parameter defect.

No credential values are included in this document.

## Definitive bookmaker-filtered attestation — 2026-08-22 (UTC)
The provider's documented bookmaker-filtered discovery (`GET /v3/events?bookmaker=<book>`) was used with the actual sport slug (`table-tennis`) and exact catalog/selected identifiers:

- `GENERIC_TT_EVENTS=51` (provider-wide pending events across International TT Elite Series, International TT Cup, Czech Liga Pro).
- `Sbobet` filter: `SBOBET_TT_FILTERED_EVENTS_TOTAL=0`
- `SingBet` filter: `SINGBET_TT_FILTERED_EVENTS_TOTAL=0`
- Control (same filter, same account): `football bookmaker=Sbobet count=53`, `football bookmaker=SingBet count=54` — proving the filter is functional and the zero result is Table Tennis-specific.
- Generic `/v3/odds` on sample TT event IDs (`73922828`, `73946574`, `73924232`) with `bookmakers=Sbobet,SingBet` returns HTTP 200 with empty bookmaker maps.

Conclusion: `CURRENT_PROVIDER_BOOK_TT_COVERAGE_ZERO` for both selected books under this Solo account, which conflicts with the provider's published SBOBET and SingBet integration pages advertising Table Tennis coverage.

Question for provider support: "Your current SBOBET and SingBet integration pages list Table Tennis as a supported sport. Our authenticated selected-bookmaker account discovers Table Tennis events globally (51) but bookmaker-filtered TT discovery and per-event /odds return zero markets for both books, while the same filter returns 53-54 football events. Is Table Tennis currently available for these books on our plan, and if so which competitions/events should return prices?"

## M4.3 addendum — 2026-08-22 (UTC)
Account bookmaker slots were changed to Bet365 + Hard Rock. Re-test result:

- `Bet365` bookmaker-filtered TT events: 51 (pending across Czech Liga Pro, International TT Cup, International TT Elite Series). Exact filtered event IDs return real prices: bookmaker key `Bet365`, markets ML / Spread / Totals with decimal prices (e.g. ML home 1.66 / away 2.10). Bet365 Table Tennis feed is AVAILABLE on this account.
- `Hard Rock` bookmaker-filtered TT events: 0. Per-event `/odds?bookmakers=Hard Rock` returns 403 "Allowed: Bet365, Hard Rock" only when Hard Rock is not an enabled slot; with Hard Rock selected the filter returns 0 TT events. This is Odds-API.io exposing zero Hard Rock Table Tennis events to this account (not evidence that Hard Rock's sportsbook lacks Table Tennis).
- Bet365 prices were ingested into the DEFEND database (Bet365 observations persisted; M5 and recent-form20 shadow predictions recorded).
