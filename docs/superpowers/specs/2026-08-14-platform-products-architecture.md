# DEFEND Platform — Four Product Architecture

**Status:** Binding platform shape as of 2026-08-14  
**Supersedes:** Treating Table Tennis / sports as an in-panel module of DEFEND AI only

## Platform boundary

```text
DEFEND Control Center
│
├── DEFEND AI
│   └── identity / knowledge / RAG / member AI
│
├── DEFEND Sports
│   └── sports intelligence + market analysis
│
├── Sunshine Climate Solutions (SCS)
│   └── CRM / accounting / operations / SCS AI
│
└── DEFENDcoder
    └── software engineering platform
```

Applications may share ControlPlane infrastructure (ports, processes, GPUs,
models, tunnels, health, secrets, logs, cost). They must not share ordinary
user identities, sessions, application data, tools, indexes, or audit records.
The owner identity is the only identity mapped across products.

## Public origins (reserved)

| Product | Origin | Status |
|---|---|---|
| DEFEND AI | `https://ai.defend-network.org` | Existing path |
| DEFEND Sports | `https://defendsports.defend-network.org` | Reserved |
| SCS | `https://ai.sunshineclimatesolutions.com` | Reserved / gated |
| DEFENDcoder | `https://defendcoder.defend-network.org` | Reserved / inactive |

## Product ≠ model

Each product owns policy, tools, and data. Weights are selected via a model
gateway. Specialized adapters/LoRAs are added only after evaluation shows gain.

### DEFEND Sports AI (service, not necessarily unique weights day one)

```text
DEFEND Sports AI
  ├── Sports system policy
  ├── Sports tools
  ├── live market data
  ├── TT prediction engine
  ├── research database
  ├── statistical models
  └── explanation/reasoning model
         │
         ▼
   Model Gateway → appropriate model
```

Quantitative models produce P(outcome), intervals, calibration, features,
market probability, and edge. The LLM interrogates those systems; it is not
the sole calculator.

## DEFEND Sports surface (target)

```text
DEFEND Sports
├── Live
├── Arbitrage (all sports / all books / alerts)
├── Table Tennis Intelligence
├── Research (strategies, backtests, challengers)
├── Performance (calibration, ROI, CLV, drawdown)
└── Sports AI (conversational analyst)
```

### Package layout (target)

```text
defend_sports/
├── core/          # markets, odds, normalization, arbitrage, risk
├── sports/
│   └── table_tennis/   # first sport package
├── feeds/
├── books/
├── research/
├── models/
└── api/
```

Existing `TableTennis/` (or equivalent) code is **legacy V0**. Migrate to
feature parity, verify, then retire the admin-panel embedding. Do not delete
first.

## Risk policy (owner-controlled ceilings)

- Starting bankroll and max stake ceiling are owner-configured.
- No automatic promotion of stake ceiling after “proof.”
- Dynamic sizing may recommend continuous values under the owner ceiling.
- Stake must consider calibrated probability, market price (EV), uncertainty,
  strategy reliability, bankroll, drawdown, and correlated exposure — not
  confidence alone.

## Access

**DEFEND Sports V1 = owner-only**, matching the current TableTennis panel.
Architecture must not block later member accounts, bankrolls, and alerts, but
multi-tenant design is not required for the first production boundary.

## Control Center

Product rows: status + Launch / Stop / Open / Logs per product where wired.
`LAUNCH ALL` is a future convenience, not a requirement for M0.
ControlPlane owns compute, tunnels, and secrets; products do not orchestrate
each other.
