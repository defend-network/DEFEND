-- M4.7 sports arbitrage integration: immutable opportunity snapshots, dedicated
-- PAPER_ARB tickets, and the owner sportsbook access profile. Additive only.

-- Append-only immutable arb opportunity snapshots. A new quote combination
-- always produces a new snapshot and old snapshots are marked EXPIRED or
-- SUPERSEDED logically and never mutated in place.
CREATE TABLE IF NOT EXISTS quant_arb_opportunities (
    opportunity_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    canonical_event_id TEXT NOT NULL,
    canonical_market_key TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_verified_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    expired_at TIMESTAMPTZ,
    bookmakers JSONB NOT NULL DEFAULT '[]'::jsonb,
    quote_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    odds JSONB NOT NULL DEFAULT '[]'::jsonb,
    inverse_sum NUMERIC(20,12) NOT NULL,
    raw_margin NUMERIC(20,12) NOT NULL,
    stake_plan JSONB NOT NULL DEFAULT '[]'::jsonb,
    worst_case_profit NUMERIC(20,6),
    worst_case_roi NUMERIC(20,12),
    freshness_state TEXT,
    cross_book_time_delta NUMERIC(12,3),
    settlement_compatibility TEXT,
    classification TEXT NOT NULL,
    risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    policy_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'EXPIRED', 'SUPERSEDED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_quant_arb_opp_event
    ON quant_arb_opportunities(canonical_event_id, detected_at);
CREATE INDEX IF NOT EXISTS idx_quant_arb_opp_status
    ON quant_arb_opportunities(status, expires_at);

-- Dedicated PAPER_ARB tickets (P33): separate strategy identity from
-- PAPER_MAIN/PAPER_RESEARCH predictive tickets.
CREATE TABLE IF NOT EXISTS quant_paper_arb_tickets (
    arb_ticket_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    opportunity_id TEXT NOT NULL,
    canonical_event_id TEXT NOT NULL,
    canonical_market_key TEXT NOT NULL,
    strategy TEXT NOT NULL DEFAULT 'PAPER_ARB',
    decision_time TIMESTAMPTZ NOT NULL,
    legs JSONB NOT NULL DEFAULT '[]'::jsonb,
    bookmakers JSONB NOT NULL DEFAULT '[]'::jsonb,
    odds JSONB NOT NULL DEFAULT '[]'::jsonb,
    stakes JSONB NOT NULL DEFAULT '[]'::jsonb,
    expected_return NUMERIC(20,6),
    worst_case_profit NUMERIC(20,6),
    quote_age_seconds JSONB NOT NULL DEFAULT '{}'::jsonb,
    constraints JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT,
    settlement_id BIGINT,
    settlement_revision BIGINT,
    capital_allocated NUMERIC(20,6),
    realized_payout NUMERIC(20,6),
    realized_pnl NUMERIC(20,6),
    roi NUMERIC(20,12),
    void_state TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (opportunity_id)
);

-- Owner sportsbook access profile (P35). Default UNKNOWN, never inferred.
CREATE TABLE IF NOT EXISTS quant_book_access_profile (
    bookmaker TEXT PRIMARY KEY,
    owner_can_legally_access TEXT NOT NULL DEFAULT 'UNKNOWN',
    account_available TEXT NOT NULL DEFAULT 'UNKNOWN',
    currency TEXT,
    known_balance NUMERIC(20,2),
    known_stake_limits JSONB NOT NULL DEFAULT '{}'::jsonb,
    settlement_rule_state TEXT NOT NULL DEFAULT 'UNKNOWN',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
