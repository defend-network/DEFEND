# DEFEND Sports — Master Architecture & Table Tennis Intelligence

**Status:** Binding direction 2026-08-14  
**Replaces working title:** “TableTennisAI master architecture” as the product frame

## Purpose

First-class sports intelligence and market-analysis product on the DEFEND
network. Table Tennis is the first advanced sport package, not the product name.

## Separation from DEFEND AI

DEFEND AI remains identity, knowledge, RAG, and general member AI.
DEFEND Sports owns live markets, arbitrage, sport-specific prediction,
research, performance analytics, and Sports AI.

Legacy TableTennis panel inside DEFEND AI admin is V0. Migrate → parity → retire.

## Hostname

`https://defendsports.defend-network.org` (reserved; inactive until gates pass)

## Locked requirements (from QA)

- Advisory-only production boundary (no autonomous wager placement as product default)
- Priority: calibration → EV → volume → win-rate
- Protected baseline; evidence-gated challengers
- Broad research ingestion
- Tier-1 point-by-point TT data
- All-books / all-sports arbitrage alerts
- TT-first predictive intelligence
- Owner-controlled risk ceilings (no auto 10%→20% promotion)
- V1 access: **owner-only**; multi-member later

## Risk engine V2 (deliberate expansion)

```text
calibrated P + market price → EV
  + uncertainty + strategy reliability
  + bankroll + drawdown + correlated exposure
  → recommended stake
  → OWNER CEILING
```

Existing hard/soft evaluation and conservative max stake remain until V2 is
specified and tested separately.

## AI boundary

Sports AI = policy + tools + data + quantitative engines + optional LLM via
Model Gateway. Specialized sports weights only after eval justifies them.
# DEFEND Sports — Master Architecture & Table Tennis Intelligence Specification

**Status:** LOCKED product direction / implementation specification  
**Date:** 2026-08-14  
**Product:** DEFEND Sports  
**Planned host:** `defendsports.defend-network.org`

## 1. Product mission

DEFEND Sports is a persistent, multi-user sports intelligence platform. It continuously ingests sports and sportsbook data, normalizes markets, detects cross-book arbitrage and market disagreement across all supported sports, and delivers real-time advisory alerts. Table tennis is the first deep predictive-intelligence vertical.

Production is **advisory/signaling only**. The platform does not authenticate to sportsbooks and does not place wagers. A future execution interface may exist behind an explicit disabled-by-default boundary, but automated wagering is out of scope for the current product.

The system must optimize in this order:

1. calibrated predictive accuracy;
2. expected value / long-run ROI;
3. useful signal volume;
4. raw win rate.

## 2. Platform boundary

DEFEND Control Center launches and observes four independent products/services:

- **DEFEND AI** — identity, knowledge, RAG, member AI;
- **DEFEND Sports** — sports intelligence, markets, prediction, research, alerts;
- **Sunshine Climate Solutions** — CRM/accounting/operations/SCS AI;
- **DEFENDcoder** — software-engineering platform.

DEFEND Sports owns its own application server, API, data stores, background workers, Sports AI policy/tools, research systems, and admin surface. The legacy TableTennis admin panel inside DEFEND AI remains available until feature parity is reached, then is retired rather than deleted prematurely.

## 3. Existing TableTennis V0 is preserved

The repository's existing `TableTennis/` implementation is the baseline, not disposable prototype code.

Current protected baseline behavior includes:

- fresh path to 2–0 in sets;
- trailer remains on zero sets;
- `P(reach 2-0 within next 4 points) >= 0.80`;
- soft factors including second-set margin momentum, rank delta, and H2H;
- model adjustment capped at the configured limit and unable to bypass a hard failure;
- value diagnostics;
- two-way arbitrage and hedge calculations;
- advisory-only behavior.

The existing V0 files are migrated behind the new service boundary before their old UI integration is retired.

## 4. High-level architecture

```text
Sports/live-data feeds      Sportsbook odds feeds
          |                         |
          +-----------+-------------+
                      v
              Ingestion adapters
                      v
             Normalization layer
                      v
              Canonical event bus
                      |
       +--------------+---------------+
       |                              |
       v                              v
All-Sport Market Engine      Table Tennis Intelligence
       |                              |
       +--------------+---------------+
                      v
                 Signal Engine
                      v
            Personalization/Risk
                      v
                 Alert Router
          +-----------+-----------+
          |           |           |
        Web UI       Push        other approved
                                 notification channels
```

The LLM is not the source of live scores, odds, probability math, bankroll arithmetic, or arbitrage truth. Structured feeds and quantitative models produce those facts. Sports AI reasons over auditable structured outputs and supporting research.

## 5. Shared versus user-scoped state

### Shared/global

Store once and reuse across users:

- sports, leagues, tournaments;
- teams and players;
- canonical matches/events;
- live point/set/game state;
- historical results;
- sportsbook identities;
- normalized markets and odds snapshots;
- line movement;
- model predictions;
- model/strategy versions;
- research datasets and experiments;
- detected arbitrage opportunities;
- data-quality/source-health metadata.

### User-scoped

Strict tenant isolation applies to:

- bankroll;
- risk preferences;
- sportsbook preferences/availability;
- watchlists;
- alerts and notification settings;
- logged wagers;
- open exposure;
- P/L;
- recommendation history;
- user-specific portfolio analytics.

Production multi-user persistence should target PostgreSQL rather than extending the owner-only SQLite schema indefinitely.

## 6. Roles

Initial authorization model:

- **OWNER** — all platform, feed, research, model, strategy and risk-policy controls;
- **ADMIN** — operations/users/feeds without unrestricted model-policy promotion;
- **ANALYST** — research, backtests and model inspection;
- **MEMBER** — live intelligence, Sports AI, personal portfolio, preferences and alerts.

Only authorized global operators can promote challenger models/strategies or alter platform hard limits.

## 7. All-sport market engine

All supported sports receive market intelligence immediately. Deep predictive models are not required before the market engine operates.

Capabilities:

- broad sportsbook odds ingestion;
- canonical event/team/player identity resolution;
- canonical market/selection normalization;
- American/decimal/fractional odds conversion;
- implied probability;
- overround/vig estimation and removal where appropriate;
- cross-book price comparison;
- true-arbitrage detection;
- stake distribution mathematics for informational arb alerts;
- hedge/middle analysis;
- line movement history;
- stale-price detection;
- market disagreement;
- market consensus/reference price;
- data-quality scoring;
- opportunity TTL/expiration;
- real-time alerts.

Market equivalence must be verified before calling an opportunity an arbitrage. Settlement-rule differences, overtime inclusion, retirements, void rules, set/game definitions and alternate-line differences are first-class normalization concerns.

Arbitrage is detected and surfaced broadly across books. Geographic/book accessibility is metadata and a user filter; it does not prevent the research/market engine from recording the opportunity.

## 8. Table Tennis deep-intelligence vertical

Table tennis receives the first full predictive/research stack.

### Tier-1 data requirement

Point-by-point data is a Tier-1 target. Temporary set/match-level feeds are acceptable during bootstrap, but the research architecture must support sequences such as:

```text
server -> score -> next point -> server transition -> timeout/event -> set result
```

Capture as much legally obtainable research data as practical, including matches that never create an actionable signal.

### Feature families

The research system may investigate, among others:

- serve and receive performance;
- score-state conditional performance;
- short point streaks;
- momentum persistence versus mean reversion;
- deuce performance;
- closing ability;
- response after losing consecutive points;
- set-to-set adaptation;
- opponent/matchup interactions;
- player Elo/Glicko-style ratings;
- recency-weighted form;
- fatigue/schedule effects when defensible data exists;
- league/tournament effects;
- H2H with sample-size controls;
- rank/ratings differences;
- market movement and market disagreement;
- bookmaker reaction latency;
- historical analog states;
- model uncertainty and data quality.

Feature discovery is not evidence of an exploitable pattern. Every candidate lens must survive validation.

## 9. Champion/challenger governance

The existing fresh-2–0 / 80%-within-four-points strategy is the protected production baseline initially.

Evolution stages:

1. **Rigid baseline** — current hard gates control production signals.
2. **Shadow challengers** — alternative models/strategies make timestamped predictions but cannot alter production recommendations.
3. **Evidence-gated discretion** — a challenger can receive limited production authority only after successful chronological out-of-sample evaluation and a live shadow period.
4. **Adaptive validated strategies** — multiple proven strategies may be selected contextually.
5. **Continuous research** — the system proposes/tests alternative lenses without bypassing evidence gates.

Promotion is reversible. Performance degradation, calibration failure, data drift or other defined regression criteria can demote a strategy.

Required validation chain:

```text
hypothesis
 -> historical training/development
 -> chronological out-of-sample test
 -> calibration evaluation
 -> live shadow period
 -> promotion threshold
 -> limited production
 -> continuous monitoring/demotion
```

No LLM-generated hypothesis receives production authority merely because its explanation sounds persuasive.

## 10. Model evaluation priorities

Primary metrics should include:

- calibration/Brier/log-loss style probability quality;
- chronological out-of-sample performance;
- expected value and realized ROI with uncertainty bounds;
- closing-line value where meaningful;
- drawdown;
- strategy hit/coverage rate;
- signal volume;
- data freshness/quality at prediction time;
- model/version attribution;
- performance by league/player/market/state;
- shadow-versus-champion comparison.

Raw win rate is a secondary diagnostic, not the optimization target.

## 11. Risk and bankroll engine

Risk policy has three layers:

```text
Platform hard maximum (OWNER controlled)
              |
User maximum (cannot exceed platform maximum)
              |
Dynamic recommendation from risk engine
```

Initial account/bootstrap values may use a `$50` bankroll and a user maximum of `10%` while the system is proving itself. The architecture must support an owner-configurable platform maximum up to the currently approved `20%` policy without code changes. Increasing the ceiling is an explicit owner action, not an automatic reward the model grants itself.

Dynamic stake recommendations can be continuous and may display rounded values such as 5%, 10%, 15% or 20%, but must never exceed the effective user/platform ceiling.

Sizing must not use confidence alone. Inputs should include calibrated probability, market price, estimated EV, uncertainty, strategy reliability, data quality, drawdown, open exposure and correlated positions.

The owner/admin UI must make platform defaults/ceilings easy to inspect and change with authorization, validation and audit history.

## 12. Persistent monitoring

DEFEND Sports runs continuously even when no browser is open.

Background services continuously:

1. poll/stream data sources;
2. normalize incoming state;
3. update canonical live events and markets;
4. run all-sport market analysis;
5. run eligible table-tennis production/shadow models;
6. create/update/expire signals;
7. personalize eligible alerts;
8. route notifications;
9. record post-signal outcomes for research.

Every live observation/signal carries timestamps including `observed_at` and `computed_at`, source identity/health, age/freshness, and an expiration/TTL where applicable.

Stale or conflicting source data can downgrade or suppress a signal.

## 13. Alert taxonomy

Supported alert levels:

- **INFO** — interesting information/disagreement, no action implied;
- **WATCH** — approaching validated signal criteria;
- **SIGNAL** — validated production strategy triggered;
- **HIGH-CONFIDENCE** — exceptional calibrated opportunity with strong data quality;
- **ARBITRAGE** — qualifying cross-book mathematical opportunity;
- **URGENT ARBITRAGE** — strong arb with very fresh/high-quality prices.

Members can configure pushed alert tiers, sports, leagues, books, quiet hours and notification channels. The live dashboard retains the broader intelligence stream.

## 14. Explainability contract

Meaningful signals must be evidence-first and inspectable.

A deep-analysis view should expose:

- signal level;
- calibrated model probability;
- market-implied probability;
- estimated edge;
- best current market/book;
- suggested stake and applicable ceilings;
- baseline gate state;
- supporting factors;
- counterpoints/risks;
- data quality/freshness;
- strategy/version;
- model/version;
- probability and edge history;
- what would change the recommendation;
- similar historical situations;
- relevant point-by-point evidence.

Sports AI must be able to answer questions such as "Why?", "What would change your mind?", "What did this strategy get wrong in similar states?", and "Show the historical evidence" from stored, auditable data.

## 15. Locked visual direction

The approved DEFEND Sports UI is a dark professional analytics interface with high-information density and clear color communication:

- green: favorable/validated/healthy;
- yellow/amber: watch/uncertain/approaching threshold;
- red: hard fail/risk/stale/negative evidence;
- neutral white/gray: descriptive state.

Color must never be the sole carrier of meaning; text labels/icons accompany status colors.

### Primary navigation

- Live Dashboard
- Live Table Tennis
- Arbitrage Center
- All Sports
- Signals
- Alerts
- My Watchlist
- Portfolio
- P&L & History
- Bankroll & Risk
- Research Center
- Models & Strategies
- Sports AI
- Settings

Owner/admin users additionally receive the global operations/admin surface.

## 16. Live Table Tennis Board

The Live Table Tennis Board continuously displays **all monitored live table-tennis matches** and ranks them by best validated **Opportunity Score**, not simply raw win probability.

Each row should include, when available:

- rank;
- match and league;
- live sets/points and server;
- best market/book and price;
- calibrated model probability;
- market-implied probability;
- edge;
- model confidence/uncertainty;
- signal tier;
- data age/freshness.

Default ranking uses a composite Opportunity Score emphasizing:

1. expected edge/EV;
2. calibrated model confidence/uncertainty;
3. data quality/freshness;
4. validated strategy reliability;
5. relevant market movement;
6. liquidity/book quality where known.

A very high-confidence favorite with no price advantage must not automatically outrank a lower-confidence but strongly positive-EV validated opportunity.

Users can filter/sort by league, market, sportsbook, signal type, confidence, edge and freshness.

## 17. Match deep-analysis screen

Selecting a live match opens a dense analysis surface with tabs/sections for:

- Overview
- Analysis
- Point by Point
- Market
- H2H
- History

The overview highlights signal status, probability, market implied probability, edge, best price/book and personalized suggested stake. Supporting evidence and counterpoints are shown side-by-side. Baseline gate, data quality, active strategy and model version remain visible. Time-series views show model probability and edge movement. The screen explicitly shows "What would change our mind?" and similar historical situations.

## 18. Sports AI

DEFEND Sports has its own Sports AI application/runtime and tool policy. It may initially share an underlying foundation-model provider through the Model Gateway; separate product identity does not require separate weights.

Sports AI tools can access authorized structured sports data, quantitative model outputs, research results and the current user's permitted portfolio/preferences. It must not fabricate live scores/odds or substitute LLM intuition for deterministic market math.

Future specialized sports adapters/weights are promoted only if evaluations show measurable benefit.

## 19. Data/API strategy

Use licensed/authorized feeds and provider APIs where practical. Do not make fragile sportsbook-page scraping the production source of truth when a reliable licensed feed exists.

Required provider capabilities should be evaluated separately:

### Market/odds provider

Needs broad sport/league coverage, multiple sportsbooks, stable event/market IDs, timestamps, pregame/live odds, line movement or sufficiently frequent snapshots, and preferably Hard Rock Bet coverage.

### Table-tennis event provider

Needs broad tournament/player coverage and, ideally, point-by-point live state including server. Historical point sequences are highly valuable.

### Historical research sources

May include licensed feeds plus legally usable public/downloadable datasets. Provenance, license/terms, source timestamp and schema version must be stored.

Provider adapters must map into DEFEND Sports canonical schemas so providers can be replaced without rewriting prediction/market logic.

## 20. Data model direction

Production entities should include at minimum:

- users / roles;
- bankrolls and risk policies;
- sportsbooks;
- sports / leagues / competitions;
- participants (players/teams);
- events/matches;
- live state observations;
- point events where supported;
- canonical markets/selections;
- odds snapshots;
- data-source health/freshness;
- model versions;
- strategy versions;
- predictions;
- signals;
- arbitrage opportunities/legs;
- shadow predictions;
- alerts/deliveries;
- user watchlists/preferences;
- logged wagers/settlements;
- experiments/backtests;
- audit events.

Raw provider payloads should be retained where licensing/storage rules permit so normalization bugs can be reproduced.

## 21. Future execution seam

Current enabled action implementation:

```text
ActionInterface
└── ManualAdvisoryAction  [ENABLED]
```

Future architecture may add provider-specific execution adapters, but they remain disabled and outside the current production boundary unless explicitly designed, legally/technically validated, secured and approved in a later specification.

## 22. Migration strategy

Do not delete or rewrite the existing TableTennis module in place first.

1. Characterize V0 behavior with regression tests.
2. Create DEFEND Sports service/data boundaries.
3. Port the baseline engine behind the new interfaces without changing its protected behavior.
4. Import/migrate V0 history with explicit provenance.
5. Connect live feed adapters.
6. Add all-sport normalization/arb engine.
7. Add Table Tennis research/prediction pipeline.
8. Build the approved DEFEND Sports UI.
9. Run old and new paths in parallel where useful.
10. Verify feature/data parity.
11. Retire the old DEFEND AI TableTennis panel only after acceptance.

## 23. Initial implementation milestones

### DS0 — Service foundation

Independent DEFEND Sports service, configuration, auth boundary, health checks, database migrations and Control Center launch/stop/status integration.

### DS1 — Canonical market/data plane

Provider adapter interfaces, canonical sports/event/market schemas, odds snapshots, freshness/source health and raw-event capture.

### DS2 — All-sport arbitrage

Cross-book normalization, market-equivalence checks, arb calculations, opportunity lifecycle/TTL and live dashboard alerts.

### DS3 — Table Tennis baseline migration

Port current hard/soft strategy and regression tests without behavior drift; ingest live set/point state.

### DS4 — Table Tennis research platform

Historical/point-level ingestion, player ratings/features, chronological backtesting, calibration, champion/challenger registry and shadow predictions.

### DS5 — Multi-user product

Member bankroll/risk/preferences, watchlists, personalized alerts, P/L/history, tenant isolation and role-based admin.

### DS6 — Approved UI

Implement the locked Live Table Tennis board and deep-analysis interface, Arbitrage Center, dashboards and Sports AI experience.

### DS7 — Continuous improvement

Outcome capture, closing-price tracking, drift detection, automated research reports, evidence-gated strategy promotion/demotion and later sport-specific predictive verticals.

## 24. Non-negotiable invariants

- Advisory/signaling only in current production scope.
- Live state and odds come from structured data sources, never LLM invention.
- Existing baseline cannot be silently weakened by an AI model.
- Challenger discretion is earned through evidence.
- Prediction truth and conversational explanation are separate concerns.
- Calibration/EV outrank raw win rate.
- Data freshness is part of signal validity.
- User financial/portfolio state is tenant-isolated.
- Owner global controls are audited.
- User risk limits cannot exceed the platform hard limit.
- No automatic increase of the platform risk ceiling.
- All-sport arbitrage is universal; deep predictive intelligence starts with table tennis.
- Existing V0 TableTennis code/history is preserved through migration until parity is verified.

## 25. Immediate next engineering action

Create a separate implementation plan for **DS0 + DS1 only** before coding the broader product. That plan should map the existing DEFEND Control Center patterns, establish the DEFEND Sports service boundary and PostgreSQL schema/migrations, define provider-neutral canonical event/market interfaces, and add regression characterization around the existing TableTennis baseline. Do not build predictive challengers or prematurely retire the existing panel during DS0/DS1.
