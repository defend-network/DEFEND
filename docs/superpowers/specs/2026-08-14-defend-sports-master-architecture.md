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
