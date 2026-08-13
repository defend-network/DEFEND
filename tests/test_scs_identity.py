from datetime import datetime, timedelta, timezone

import pytest

from scs_data.audit import ScsAuditStore
from scs_data.identity import ScsIdentityStore
from scs_data.config import ScsPaths
from shared_platform.phase0 import phase0_contexts


@pytest.fixture
def identity(tmp_path):
    scs_context = phase0_contexts()[1]
    context = type(scs_context)(
        **{**scs_context.__dict__, "data_root": (tmp_path / "SCS_DATA").resolve()}
    )
    paths = ScsPaths.from_context(context).ensure()
    store = ScsIdentityStore(paths.database)
    yield store
    store.close()


def test_owner_bootstrap_is_single_idempotent_and_password_is_not_stored(identity):
    owner = identity.bootstrap_owner(
        email="OWNER@Example.com",
        username="owner",
        display_name="Owner",
        password="synthetic-owner-password",
    )
    repeated = identity.bootstrap_owner(
        email="owner@example.com",
        username="owner",
        display_name="Owner",
        password="synthetic-owner-password",
    )

    assert repeated.employee_id == owner.employee_id
    assert owner.roles == ("owner",)
    stored = identity.conn.execute("SELECT password_hash FROM scs_employees").fetchone()[0]
    assert stored != "synthetic-owner-password"
    with pytest.raises(ValueError, match="owner already exists"):
        identity.bootstrap_owner(
            email="different@example.com", username="other", display_name="Other", password="other-password"
        )


def test_invitation_activation_and_sessions_store_hashes_and_honor_revocation(identity):
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    invitation, raw_invitation = identity.invite_employee(
        actor_id=owner.employee_id,
        email="tech@example.com",
        display_name="Tech",
        roles=("read_only",),
    )
    persisted = identity.conn.execute(
        "SELECT token_hash FROM scs_invitations WHERE invitation_id=?", (invitation.invitation_id,)
    ).fetchone()[0]
    assert raw_invitation not in persisted

    employee = identity.activate_invitation(raw_invitation, username="tech", password="tech-password")
    assert employee.roles == ("read_only",)
    assert identity.activate_invitation
    raw_session = identity.create_session(employee.employee_id)
    assert identity.resolve_session(raw_session).employee_id == employee.employee_id
    stored_session = identity.conn.execute("SELECT session_hash FROM scs_sessions").fetchone()[0]
    assert raw_session not in stored_session
    assert identity.revoke_session(raw_session)
    assert identity.resolve_session(raw_session) is None
    with pytest.raises(ValueError, match="invalid invitation"):
        identity.activate_invitation(raw_invitation, username="again", password="another-password")


def test_operations_admin_cannot_grant_operations_admin_but_owner_can(identity):
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    admin = identity.create_active_employee_for_bootstrap(
        actor_id=owner.employee_id,
        email="admin@example.com",
        username="admin",
        display_name="Admin",
        password="admin-password",
        roles=("operations_admin",),
    )
    worker = identity.create_active_employee_for_bootstrap(
        actor_id=owner.employee_id,
        email="worker@example.com",
        username="worker",
        display_name="Worker",
        password="worker-password",
        roles=("read_only",),
    )
    with pytest.raises(PermissionError, match="owner"):
        identity.set_roles(admin.employee_id, worker.employee_id, ("operations_admin",))
    updated = identity.set_roles(owner.employee_id, worker.employee_id, ("operations_admin", "billing"))
    assert updated.roles == ("billing", "operations_admin")


def test_functions_and_technician_levels_append_history(identity):
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    tech = identity.create_active_employee_for_bootstrap(
        owner.employee_id, "tech@example.com", "tech", "Tech", "tech-password", ("read_only",)
    )
    identity.assign_function(owner.employee_id, tech.employee_id, "service_technician")
    identity.assign_function(owner.employee_id, tech.employee_id, "maintenance_technician")
    identity.set_technician_level(owner.employee_id, tech.employee_id, "technician_i")
    identity.set_technician_level(owner.employee_id, tech.employee_id, "technician_ii")

    assert identity.current_functions(tech.employee_id) == ("maintenance_technician", "service_technician")
    assert identity.current_technician_level(tech.employee_id) == "technician_ii"
    assert identity.conn.execute(
        "SELECT COUNT(*) FROM scs_technician_level_history WHERE employee_id=?", (tech.employee_id,)
    ).fetchone()[0] == 2


def test_expired_invitation_and_session_are_rejected(identity):
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    _invitation, token = identity.invite_employee(
        owner.employee_id, "late@example.com", "Late", ("read_only",), expires_at=past
    )
    with pytest.raises(ValueError, match="invalid invitation"):
        identity.activate_invitation(token, username="late", password="late-password")


def test_audit_rejects_secret_shaped_payloads_and_never_represents_values(identity):
    audit = ScsAuditStore(identity.conn)
    with pytest.raises(ValueError, match="sensitive"):
        audit.append("actor", "bad.event", "employee", "target", {"session_token": "private"})
    event = audit.append("actor", "safe.event", "employee", "target", {"role": "billing"})
    assert event.event_type == "safe.event"
    assert "private" not in repr(event)
