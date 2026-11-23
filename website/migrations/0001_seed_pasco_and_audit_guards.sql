INSERT OR IGNORE INTO chapters (
  id,
  slug,
  name,
  county,
  state,
  status,
  description,
  contact_email
) VALUES (
  'chapter_pasco',
  'pasco-county',
  'Pasco County',
  'Pasco',
  'FL',
  'in_development',
  'The founding DEFEND chapter is being organized in Pasco County, Florida.',
  'chairman@defend-network.org'
);

CREATE UNIQUE INDEX IF NOT EXISTS role_assignments_single_active_owner
  ON role_assignments (role_key)
  WHERE role_key = 'owner' AND revoked_at IS NULL;

CREATE TRIGGER IF NOT EXISTS admin_audit_events_no_update
BEFORE UPDATE ON admin_audit_events
BEGIN
  SELECT RAISE(ABORT, 'admin_audit_events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS admin_audit_events_no_delete
BEFORE DELETE ON admin_audit_events
BEGIN
  SELECT RAISE(ABORT, 'admin_audit_events are append-only');
END;
