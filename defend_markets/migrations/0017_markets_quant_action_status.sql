-- M4.6: widen improvement action statuses for the verification lifecycle.

ALTER TABLE quant_improvement_actions
    DROP CONSTRAINT IF EXISTS quant_improvement_actions_status_check;
ALTER TABLE quant_improvement_actions
    ADD CONSTRAINT quant_improvement_actions_status_check
    CHECK (status IN ('PROPOSED','STARTED','COMPLETED','FAILED','REJECTED','MONITORING',
                      'WAITING_FOR_TRIGGER','BLOCKED'));
