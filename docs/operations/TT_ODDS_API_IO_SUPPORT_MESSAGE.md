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
