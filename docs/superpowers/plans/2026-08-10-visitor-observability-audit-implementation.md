<!-- DEFEND-AI-INGEST: EXCLUDE -->

# DEFEND Visitor Observability and Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record searchable visitor connection history, link authenticated accounts to visitors, retain detailed telemetry for 90 days, and audit sensitive administrative access.

**Architecture:** Extend `VisitorStore` with append-only connection observations rather than placing raw IP history on the visitor row. Keep account links and immutable audits in `IdentityStore`; a focused admin router joins bounded results at the service layer without cross-database foreign keys.

**Tech Stack:** Python 3, FastAPI, Pydantic, SQLite, HMAC-SHA256, pytest.

## Global Constraints

- Full IP and detailed connection telemetry expire after exactly 90 days.
- Store full IP, user agent, browser, platform, device type, language, fingerprint HMAC, and keyed cookie/session hashes; never store raw authentication cookies or reusable tokens.
- Device fingerprints are investigative hints and never automatically merge identities.
- Cloudflare client IP is trusted only when `DEFEND_TRUST_CLOUDFLARE=true`; otherwise use the direct peer.
- Admins and owner may view telemetry and conversation content, and every sensitive view must create an audit event.
- Search and nested history are paginated and bounded.
- Complete `2026-08-10-identity-invitations-implementation.md` first.

---

## File map

- Modify `defend_data/visitor_store.py`: connection schema, capture, search, detail, cleanup.
- Modify `defend_data/identity_store.py`: account/visitor links and audit query/write methods.
- Modify `api_batch3_routes.py`: pass connection metadata into visitor/session capture.
- Create `api_identity_admin_routes.py`: account, visitor, invitation, audit, and conversation-detail APIs.
- Modify `api_server.py`: include admin identity router and run bounded retention cleanup.
- Create `tests/test_visitor_connections.py`, `tests/test_identity_links_audit.py`, and `tests/test_identity_admin_api.py`.

### Task 1: Persist connection observations safely

**Files:**
- Modify: `defend_data/visitor_store.py`
- Modify: `api_batch3_routes.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_visitor_connections.py`

**Interfaces:**
- Produces: `VisitorStore.record_connection(*, visitor_id, session_id, ip_address, user_agent, client_meta, cookie_hash, observed_at=None) -> str`.
- Produces: `VisitorStore.connection_detail(connection_id: str) -> dict | None`.
- Produces: `VisitorStore.purge_connection_history(*, before: str) -> int`.

Add this shared fixture to `tests/conftest.py`:

```python
@pytest.fixture
def visitor_store(data_paths, monkeypatch):
    monkeypatch.setenv("DEFEND_VISITOR_HMAC_KEY", "test-key-with-at-least-thirty-two-characters")
    store = VisitorStore(data_paths)
    yield store
    store.close()
```

- [ ] **Step 1: Write failing persistence and no-raw-cookie tests**

```python
def test_connection_persists_ip_and_hashes_cookie(visitor_store):
    event_id = visitor_store.record_connection(visitor_id="vis_a", session_id="vsess_a", ip_address="203.0.113.8", user_agent="Browser/1", client_meta={"browser":"other"}, cookie_hash="cookie_hmac")
    row = visitor_store.connection_detail(event_id)
    assert row["ip_address"] == "203.0.113.8"
    assert row["cookie_hash"] == "cookie_hmac"
    assert "raw_cookie" not in row
```

- [ ] **Step 2: Run test and verify RED**

Run: `python -m pytest tests/test_visitor_connections.py -v`
Expected: FAIL because connection methods/table do not exist.

- [ ] **Step 3: Add schema version 2 and capture integration**

Create `connection_events(connection_id, visitor_id, session_id, ip_address, user_agent, browser, platform, device, language, fingerprint_hmac, cookie_hash, observed_at)` with indexes on visitor, session, IP, and time. Hash visitor/session cookie values with `DEFEND_VISITOR_HMAC_KEY` before storage.

Update `ensure_visitor_session` to call `record_connection` after visitor and session ownership are established.

- [ ] **Step 4: Run focused and existing visitor tests**

Run: `python -m pytest tests/test_visitor_connections.py -v && python -m compileall -q defend_data/visitor_store.py api_batch3_routes.py`
Expected: PASS and exit 0.

- [ ] **Step 5: Commit**

```powershell
git add defend_data/visitor_store.py api_batch3_routes.py tests/conftest.py tests/test_visitor_connections.py
git commit -m "Record visitor connection history"
```

### Task 2: Link accounts to visitors and add immutable audits

**Files:**
- Modify: `defend_data/identity_store.py`
- Test: `tests/test_identity_links_audit.py`

**Interfaces:**
- Produces: `link_visitor(*, account_id: str, visitor_id: str, linked_at: str | None = None) -> None`.
- Produces: `record_audit(*, actor_account_id, action, target_type, target_id, outcome, request_id=None, client_context=None, metadata=None) -> str`.
- Produces: `list_audit_events(*, query=None, limit=50, offset=0) -> list[dict]`.

- [ ] **Step 1: Write failing link idempotence and audit redaction tests**

```python
def test_link_is_idempotent(identity, account):
    identity.link_visitor(account_id=account.account_id, visitor_id="vis_123")
    identity.link_visitor(account_id=account.account_id, visitor_id="vis_123")
    assert identity.list_linked_visitors(account.account_id) == ["vis_123"]

def test_audit_rejects_secret_keys(identity, owner):
    with pytest.raises(ValueError):
        identity.record_audit(actor_account_id=owner.account_id, action="view", target_type="conversation", target_id="c1", outcome="success", metadata={"token":"secret"})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_identity_links_audit.py -v`
Expected: FAIL on missing link/audit methods.

- [ ] **Step 3: Implement link and append-only audit methods**

Use `INSERT OR IGNORE` for links. Audit rows may be inserted and queried but never updated or deleted through `IdentityStore`. Reject metadata keys matching `password`, `token`, `cookie`, `authorization`, or `secret` recursively.

- [ ] **Step 4: Run store test suites**

Run: `python -m pytest tests/test_identity_links_audit.py tests/test_identity_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add defend_data/identity_store.py tests/test_identity_links_audit.py
git commit -m "Link accounts and add identity audit log"
```

### Task 3: Add searchable bounded admin APIs

**Files:**
- Create: `api_identity_admin_routes.py`
- Modify: `api_server.py`
- Modify: `defend_data/visitor_store.py`
- Test: `tests/test_identity_admin_api.py`

**Interfaces:**
- Produces endpoints: `GET /api/admin/accounts`, `GET /api/admin/accounts/{id}`, `PATCH /api/admin/accounts/{id}`, `POST /api/admin/accounts/{id}/anonymize`, `DELETE /api/admin/accounts/{id}`, `GET /api/admin/visitors`, `GET /api/admin/visitors/{id}`, `GET /api/admin/visitors/{id}/conversations/{conversation_id}`, `GET /api/admin/invitations`, and `GET /api/admin/audit`.

- [ ] **Step 1: Write failing search, permission, and audit tests**

```python
def test_conversation_view_is_audited(client, admin_headers, seeded_conversation):
    response = client.get(f"/api/admin/visitors/{seeded_conversation.visitor_id}/conversations/{seeded_conversation.id}", headers=admin_headers)
    assert response.status_code == 200
    events = client.get("/api/admin/audit?action=conversation.view", headers=admin_headers).json()["items"]
    assert events[0]["target_id"] == seeded_conversation.id

def test_admin_cannot_disable_admin(client, admin_headers, target_admin):
    assert client.patch(f"/api/admin/accounts/{target_admin.account_id}", headers=admin_headers, json={"status":"disabled"}).status_code == 403
```

- [ ] **Step 2: Run API tests and verify RED**

Run: `python -m pytest tests/test_identity_admin_api.py -v`
Expected: FAIL because the admin router does not exist.

- [ ] **Step 3: Implement router with shared paging/query models**

```python
class PageParams(BaseModel):
    q: str = Field(default="", max_length=200)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)
```

Use parameterized SQL only. Cap conversation messages at 500 and nested session/connection histories at 200. Record audit events after authorization and before returning sensitive detail; record failure outcome when a permitted actor's lookup fails.

- [ ] **Step 4: Run API, auth, visitor, and audit tests**

Run: `python -m pytest tests/test_identity_admin_api.py tests/test_admin_identity_auth.py tests/test_visitor_connections.py tests/test_identity_links_audit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add api_identity_admin_routes.py api_server.py defend_data/visitor_store.py tests/test_identity_admin_api.py
git commit -m "Expose audited identity administration APIs"
```

### Task 4: Enforce 90-day retention and verify the phase

**Files:**
- Modify: `api_server.py`
- Modify: `start_api.TXT`
- Test: `tests/test_connection_retention.py`

**Interfaces:**
- Consumes: `VisitorStore.purge_connection_history(before=...)`.
- Produces: startup cleanup and a daily in-process cleanup guard; repeated calls are idempotent.

- [ ] **Step 1: Write failing retention boundary tests**

```python
def seed_connection(store, *, observed_at):
    return store.record_connection(visitor_id="vis_seed", session_id="vsess_seed", ip_address="203.0.113.8", user_agent="Browser/1", client_meta={"browser":"other","platform":"other","device":"desktop","language":"en"}, cookie_hash="cookie_hmac", observed_at=observed_at.isoformat())

def test_cleanup_deletes_only_records_older_than_90_days(visitor_store, frozen_now):
    seed_connection(visitor_store, observed_at=frozen_now - timedelta(days=91))
    keep = seed_connection(visitor_store, observed_at=frozen_now - timedelta(days=90))
    assert visitor_store.purge_connection_history(before=(frozen_now - timedelta(days=90)).isoformat()) == 1
    assert visitor_store.connection_detail(keep) is not None
```

- [ ] **Step 2: Run retention test and verify RED**

Run: `python -m pytest tests/test_connection_retention.py -v`
Expected: FAIL until cleanup boundary/startup integration is complete.

- [ ] **Step 3: Add startup and once-per-day cleanup guard**

Compute `datetime.now(timezone.utc) - timedelta(days=90)` and store only the last cleanup timestamp in process memory. Document the fixed retention and Cloudflare trust variables in `start_api.TXT`.

- [ ] **Step 4: Run full phase verification**

Run: `python -m pytest tests/test_visitor_connections.py tests/test_identity_links_audit.py tests/test_identity_admin_api.py tests/test_connection_retention.py -v`
Run: `python -m compileall -q api_server.py api_identity_admin_routes.py defend_data`
Expected: all tests PASS and compilation exits 0.

- [ ] **Step 5: Commit**

```powershell
git add api_server.py start_api.TXT tests/test_connection_retention.py
git commit -m "Enforce connection telemetry retention"
```
