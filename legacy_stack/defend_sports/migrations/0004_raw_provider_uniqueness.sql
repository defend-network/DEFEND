-- P1 (owner-approved): enforce the approved provider uniqueness invariant
--     UNIQUE (provider, sport_key, provider_event_id)
--
-- The existing UNIQUE (source_id, provider_event_id) constraint and the
-- deterministic ON CONFLICT (source_id, provider_event_id) DO NOTHING
-- ingestion path are preserved unchanged. This migration adds an idempotent
-- unique index over the full approved invariant. The sport_key is taken
-- from the canonical payload location (payload->'sport'->>'slug'), COALESCEd to '' for rows
-- without a sport slug so the expression index never contains NULLs.
--
-- The migration is purely additive: it never deletes or rewrites rows.

CREATE UNIQUE INDEX IF NOT EXISTS raw_provider_events_sport_key_unique
    ON raw_provider_events (source_id, COALESCE(payload->'sport'->>'slug', ''), provider_event_id);