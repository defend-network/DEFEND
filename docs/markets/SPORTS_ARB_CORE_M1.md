# DEFENDMarkets Sports Arbitrage Core — M1

Milestone M1 delivers an **isolated, deterministic arbitrage engine** for
DEFENDMarkets. It is a pure mathematics/domain-logic library: no database, no
HTTP, no provider API calls, no filesystem side effects, no wager placement.

> This milestone is intentionally *not* integrated into the live
> provider/database/API yet. M1 ends as an isolated library that can later be
> rebased onto the M4.5 market-truth head and connected to a
> `CanonicalOddsFeed`.

## Scope

Given a set of normalized sportsbook quotes (`ArbQuote`), the engine answers:

1. Is there a mathematically valid arbitrage?
2. Are the markets actually compatible?
3. Are the quotes fresh enough to be compared?
4. What exact stakes produce the best balanced return?
5. What is the guaranteed gross/net return after rounding, fees, buffers?
6. Are bankroll/stake constraints satisfied?
7. Is this a `MATHEMATICAL_ARB` or a plausibly `EXECUTABLE_ARB`?
8. What exact evidence produced the opportunity?

AI does **not** calculate the arb. Deterministic Decimal code does.

## Package layout

```
defend_markets/arb/
  models.py        ArbQuote, policies, Decimal validation
  identity.py      canonical market identity, participant orientation
  compatibility.py market compatibility engine
  math.py          N-way inverse-sum core + exact equalization
  staking.py       rounding, bankroll, min/max stakes, fees
  freshness.py     quote age + cross-book time policy
  risk.py          deterministic risk flags, settlement boundary
  opportunity.py   immutable opportunity snapshot, classification, expiry
  paper.py         domain-level paper arb ticket
  search.py        multi-book best-price selection
  efficiency.py    capital-efficiency metrics
tests/
  test_markets_arb_*.py  35+ hermetic scenarios
```

## Math

For N complete, mutually exclusive outcomes with decimal odds `O_1..O_N`:

    Q     = SUM(1/O_i)
    arb   = Q < 1
    margin = 1 - Q
    stake_i = S * (1/O_i) / Q
    equalized return R = S / Q
    gross profit = R - S
    gross ROI = P / S

The core is genuinely N-way (supports 2-way and 3-way markets through the same
code path). `solve_equalized_plan` returns exactly equalized, unrounded stakes;
the staking layer rounds them down to the configured increment and recomputes
every outcome return, reporting the worst case.

## Precision policy

* Money/odds arithmetic uses `Decimal` only. Binary float is never
  authoritative.
* Odds quantized to 3 fractional digits; must be strictly `> 1.0`.
* Money quantized to 2 fractional digits (configurable).
* NaN, Infinity, `odds <= 1.0`, negative stake, negative bankroll and invalid
  fee values are rejected outright.

## Market compatibility

`check_market_compatibility` returns one of:

| Result | Meaning |
|---|---|
| `COMPATIBLE` | Same event/family/period/line, complete selection set, resolved orientation, fresh |
| `INCOMPATIBLE_EVENT` | Quotes span different canonical events |
| `INCOMPATIBLE_MARKET` | Different market family (ML vs spread vs total) |
| `INCOMPATIBLE_PERIOD` | Different period (first game vs full match) |
| `INCOMPATIBLE_LINE` | Different line (`-1.5` vs `-2.5`, `74.5` vs `75.5`) |
| `INCOMPATIBLE_SELECTION_SET` | Duplicate/extra selection sides |
| `AMBIGUOUS_IDENTITY` | Participant orientation cannot be resolved |
| `INCOMPLETE_MARKET` | Not all exhaustive outcomes present |
| `STALE_QUOTE` | Quote older than the freshness window |
| `POST_COMMENCE` | Event already underway and policy is pre-match-only |
| `UNKNOWN` | No/invalid input |

Supported families: `MATCH_WINNER_2WAY`, `MATCH_WINNER_3WAY`, `SPREAD`,
`TOTAL`. Moneyline and spread are never treated as compatible. `-1.5` vs
`-2.5` and `Over 74.5` vs `Under 75.5` are **not** the same arbitrage market
(they form middles, which M1 does not model).

## Participant orientation

Canonical participant A/B orientation is stable and independent of provider
order. A book that returns `(Player B, Player A)` still maps to the same
canonical outcomes. When a quote group's participant names span more than two
distinct identities, or no single orientation is consistent, the result is
`AMBIGUOUS_IDENTITY` and the engine abstains.

## Classification

| Classification | Meaning |
|---|---|
| `NO_ARB` | `Q >= 1`, no near-arb signal |
| `NEAR_ARB` | `Q` close to 1 but `>= 1` (research/monitoring only) |
| `MATHEMATICAL_ARB` | Pure arb exists but not executable (rounding/fees/threshold) |
| `EXECUTABLE_ARB` | All execution criteria satisfied |
| `INCOMPATIBLE` | Markets not actually compatible |
| `STALE` | Quote freshness failed |
| `INCOMPLETE` | Outcome set incomplete (e.g. 2-of-3) |
| `CONSTRAINT_BLOCKED` | Staking/limits/bankroll blocked |
| `POST_COMMENCE` | Event underway, pre-match policy |
| `IDENTITY_AMBIGUOUS` | Participant mapping ambiguous |

`EXECUTABLE_ARB` requires *all* of: complete mutually exclusive outcome set,
same canonical event/market/period/line, orientation verified, valid odds,
`Q < 1`, fresh + temporally comparable quotes, pre-match (when required),
rounding remains profitable, bankroll sufficient, known min/max stakes
satisfied, configured fees included, and worst-case **net** ROI >= the
configured policy threshold. If max-stake information is unknown, the
opportunity carries `MAX_STAKE_UNKNOWN` and may be classified
`MATHEMATICAL_ARB` with `EXECUTION_CAPACITY_UNVERIFIED` rather than fully
`EXECUTABLE_ARB`.

## Stake assumptions

* Stakes are rounded **down** to the configured increment after exact
  equalization.
* Per-leg `min_stake` / `max_stake` from the quote where known; unknown max
  stake is `UNKNOWN`, not infinite.
* Bankroll is modeled per bookmaker. An arb requiring more capital at one book
  than available is `BANKROLL_CONSTRAINT_FAIL`; the engine reports the shortfall
  and a maximum feasible total stake.
* Execution costs are optional per-leg: fixed cost, commission rate, exchange
  fee rate, other rate. The sportsbook default is zero explicit commission
  after using displayed decimal odds (the vig is *not* double-counted as a fee).
* An execution buffer (e.g. 0.40%) and a minimum net margin (e.g. 0.50%) are
  configurable policy values — never hard-coded magic numbers. Policy version
  is recorded on every opportunity.

## Freshness

* `max_quote_age_seconds` — a quote older than this is `STALE`.
* `max_cross_book_delta_seconds` — quotes must be contemporaneous; a wide
  spread between youngest and oldest comparable quote is rejected
  (`CROSS_BOOK_TIME_DELTA_HIGH`).
* `pre_match_only` — quotes at/after commence are rejected or downgraded.
* Historical quotes remain evidence; they are just never presented as
  currently actionable.

## Risk flags

Deterministic, evidence-derived flags (never invented probabilities):
`QUOTE_AGE_HIGH`, `CROSS_BOOK_TIME_DELTA_HIGH`, `MAX_STAKE_UNKNOWN`,
`MIN_STAKE_UNKNOWN`, `BANKROLL_TIGHT`, `LOW_MARGIN`, `ROUNDING_SENSITIVE`,
`MARKET_IDENTITY_WEAK`, `PARTICIPANT_IDENTITY_WEAK`,
`SETTLEMENT_RULES_UNVERIFIED`, `PROVIDER_TIMESTAMP_UNKNOWN`.

## Settlement compatibility

Commercial arbitrage requires compatible settlement semantics. M1 ships a
placeholder boundary: `SettlementCompatibility` with
`VERIFIED_COMPATIBLE` / `UNKNOWN` / `INCOMPATIBLE`. M1 does not research every
bookmaker rule; a strict policy can require `VERIFIED_COMPATIBLE` before
classifying an opportunity `EXECUTABLE_ARB`.

## Opportunity lifecycle

* Opportunities are immutable snapshots; new material quote changes create a
  new snapshot.
* A stable fingerprint derives from canonical market identity + quote IDs +
  policy version, so the same quote combination does not spam duplicates.
* Opportunities carry `detected_at`, `last_verified_at` and `expires_at`.
  Expired opportunities are classified `EXPIRED` and never presented as
  actionable.
* Paper arb tickets (`PaperArbTicket`) preserve decision time, legs, stakes,
  prices, books, expected return, worst-case profit and policy version in
  memory only; persistence is deferred to post-M4.5 integration.

## Known limitations

* No live provider/feed integration (Odds-API.io becomes one adapter later).
* No middling, no position-taking across correlated markets.
* No settlement-rule research beyond the placeholder boundary.
* No account automation or wager placement of any kind.
* No general-purpose optimization dependency; constraint optimization is a
  bounded deterministic closed-form solver.

## Guarantee statement

The engine's "guarantee" is a **mathematical guarantee conditional on
successful, accepted, settled legs**: if both legs are placed exactly as
planned at the recorded prices and settle in your favor, the worst-case return
is the computed value. Execution reality — odds movement, bookmaker limits,
latency, settlement disputes — is not guaranteed income. Nothing in M1 claims
real-world income.

## Future live-feed integration boundary

M1 consumes the immutable `ArbQuote` schema. Future feeds (Odds-API.io,
OddspAPI, others) plug into the same schema as adapters. The engine does not
know or care which provider produced a quote; it only consumes normalized
evidence. `defend_markets/quant/improve.py`, the shared Markets migrations,
the Odds-API.io integration, the scheduler, settlement pipeline, M5, shadow
predictor, paper tables, provider selection, Control Center, DEFENDcoder, SCS
and DEFEND AI are **not** modified by this milestone.
