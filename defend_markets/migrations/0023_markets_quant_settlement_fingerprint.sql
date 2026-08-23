-- M4.7.2 P17/P18: persist the normalized-result fingerprint on the settlement
-- row so revision detection compares canonical fingerprints directly instead of
-- reconstructing (and mismatching) orientation from a boolean flag.

ALTER TABLE quant_settlements
    ADD COLUMN IF NOT EXISTS normalized_result_fingerprint TEXT;
