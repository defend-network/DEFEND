-- M4.7.2 P18: a provider may revise the SAME source_result_id. The old
-- UNIQUE(canonical_event_id, source_result_id) constraint forbids immutable
-- revision rows that share a source_result_id. Replace it with a revision-aware
-- uniqueness so same-source-id corrections append a new revision.

ALTER TABLE quant_settlements
    DROP CONSTRAINT IF EXISTS quant_settlements_canonical_event_id_source_result_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_quant_settlements_event_source_revision
    ON quant_settlements(canonical_event_id, source_result_id, revision);
