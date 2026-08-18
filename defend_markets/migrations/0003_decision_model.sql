ALTER TABLE market_opportunities
    ADD COLUMN IF NOT EXISTS model_probability NUMERIC(18,12)
        CHECK (model_probability >= 0 AND model_probability <= 1),
    ADD COLUMN IF NOT EXISTS model_detail_json JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE market_decisions
    ADD COLUMN IF NOT EXISTS model_probability NUMERIC(18,12)
        CHECK (model_probability >= 0 AND model_probability <= 1);