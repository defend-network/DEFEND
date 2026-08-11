<!-- DEFEND-AI-INGEST: EXCLUDE -->

# DEFEND Identity and Invitations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local identity database, durable owner/admin authentication, administrator-created accounts, Gmail invitations, activation, and secure account sessions.

**Architecture:** A focused `IdentityStore` owns accounts, roles, invitations, sessions, and audit records in `identity.db`. FastAPI routes call that store through the existing `DataCore`; Gmail delivery is isolated behind a mailer interface, while the current admin API contract remains compatible during migration.

**Tech Stack:** Python 3, FastAPI, Pydantic, SQLite, `hashlib.scrypt`, `secrets`, `smtplib`, pytest, Next.js 14, TypeScript.

## Global Constraints

- The single owner is bootstrapped from existing `DEFEND_OWNER_*` environment variables; no API or UI may create another owner.
- Admins may create and disable end users; only the owner may create or manage administrators.
- Invitations are single-use, revocable, and expire after exactly 48 hours.
- Gmail invitations are sent from `chairman@defend-network.org`; credentials are environment-only.
- Raw passwords, invitation tokens, authentication cookies, and reusable session tokens are never persisted or logged.
- Public self-registration is out of scope.
- Every file under `docs/superpowers/` is developer-only and must be rejected by DEFEND document/RAG ingestion.
- Implement this plan before `2026-08-10-visitor-observability-audit-implementation.md` and `2026-08-10-admin-identity-ui-implementation.md`.

---

## File map

- Create `defend_data/identity_store.py`: identity schema, migrations, account/invitation/session persistence, role invariants.
- Create `defend_data/identity_security.py`: email normalization, scrypt password hashes, random-token hashing.
- Create `defend_data/identity_mailer.py`: Gmail SMTP adapter and delivery result.
- Create `api_identity_routes.py`: account invitation, activation, login, logout, and session APIs.
- Create `defend_data/ingest_policy.py`: developer-document exclusion policy.
- Modify `defend_data/data_core.py`: compose and close `IdentityStore`.
- Modify `admin_auth.py`: validate durable identity sessions while preserving `AdminPrincipal` dependencies.
- Modify `api_server.py`: include identity routes and reject excluded ingestion.
- Create `defend-ui-v2/app/activate/page.tsx`: activation page.
- Create `tests/` modules named below.

### Task 1: Enforce developer-document ingestion exclusion

**Files:**
- Create: `defend_data/ingest_policy.py`
- Modify: `api_server.py`
- Modify: `tools/rag_ingest.py`
- Test: `tests/test_ingest_policy.py`

**Interfaces:**
- Produces: `assert_ai_ingest_allowed(*, filename: str, content_prefix: bytes | str | None = None) -> None`
- Raises: `AIIngestExcluded` for `docs/superpowers/**` paths or the `DEFEND-AI-INGEST: EXCLUDE` marker.

- [ ] **Step 1: Write the failing policy tests**

```python
import pytest

from defend_data.ingest_policy import AIIngestExcluded, assert_ai_ingest_allowed

def test_superpowers_docs_are_excluded():
    with pytest.raises(AIIngestExcluded):
        assert_ai_ingest_allowed(filename="docs/superpowers/specs/design.md")

def test_marker_is_excluded_even_after_rename():
    with pytest.raises(AIIngestExcluded):
        assert_ai_ingest_allowed(filename="notes.md", content_prefix="<!-- DEFEND-AI-INGEST: EXCLUDE -->")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/test_ingest_policy.py -v`
Expected: FAIL because `defend_data.ingest_policy` does not exist.

- [ ] **Step 3: Implement the policy and call it at both ingestion boundaries**

```python
class AIIngestExcluded(ValueError):
    pass

def assert_ai_ingest_allowed(*, filename: str, content_prefix=None) -> None:
    normalized = filename.replace("\\", "/").lstrip("/").lower()
    prefix = content_prefix.decode("utf-8", "ignore") if isinstance(content_prefix, bytes) else (content_prefix or "")
    if normalized.startswith("docs/superpowers/") or "DEFEND-AI-INGEST: EXCLUDE" in prefix[:4096]:
        raise AIIngestExcluded("Developer-only document is excluded from AI ingestion")
```

Call this before `save_document` in `api_server.upload_files` and before chunking in `tools/rag_ingest.py`. Return HTTP 400 with the safe exclusion message for uploads.

- [ ] **Step 4: Run policy and existing upload tests**

Run: `python -m pytest tests/test_ingest_policy.py -v && python -m compileall -q api_server.py tools/rag_ingest.py defend_data`
Expected: PASS and exit 0.

- [ ] **Step 5: Commit**

```powershell
git add defend_data/ingest_policy.py api_server.py tools/rag_ingest.py tests/test_ingest_policy.py docs/superpowers
git commit -m "Protect developer docs from AI ingestion"
```

### Task 2: Add identity schema and security primitives

**Files:**
- Create: `defend_data/identity_security.py`
- Create: `defend_data/identity_store.py`
- Modify: `defend_data/data_core.py`
- Create: `tests/conftest.py`
- Test: `tests/test_identity_store.py`
- Test: `tests/test_identity_security.py`

**Interfaces:**
- Produces: `normalize_email(value: str) -> str`, `hash_password(password: str) -> str`, `verify_password(password: str, encoded: str) -> bool`, `new_token(prefix: str) -> tuple[str, str]`.
- Produces: `IdentityStore.create_account(...)`, `get_account(...)`, `bootstrap_owner(...)`, `authenticate_account(email_or_username: str, password: str) -> AccountRecord`, `create_invitation(...)`, `consume_invitation(...)`, `create_session(...)`, `resolve_session(...)`, and `revoke_session(...)`.

Define shared fixtures in `tests/conftest.py`:

```python
@pytest.fixture
def data_paths(tmp_path):
    return DataPaths.from_env(tmp_path / "DEFEND_DATA").ensure()

@pytest.fixture
def identity(data_paths):
    store = IdentityStore(data_paths)
    yield store
    store.close()

@pytest.fixture
def owner(identity):
    return identity.bootstrap_owner(email="chairman@defend-network.org", display_name="Chairman", password="valid owner password")
```

- [ ] **Step 1: Write failing schema, role, and hash tests**

```python
def test_only_one_owner(identity):
    first = identity.bootstrap_owner(email="chairman@defend-network.org", display_name="Chairman", password="valid-password")
    second = identity.bootstrap_owner(email="chairman@defend-network.org", display_name="Chairman", password="valid-password")
    assert first.account_id == second.account_id
    with pytest.raises(RoleViolation):
        identity.create_account(email="other@example.com", display_name="Other", role="owner", created_by=first.account_id)

def test_scrypt_hash_round_trip():
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("scrypt$")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_identity_security.py tests/test_identity_store.py -v`
Expected: FAIL on missing identity modules.

- [ ] **Step 3: Implement schema version 1 and primitives**

Create tables `accounts`, `invitations`, `account_sessions`, `account_visitor_links`, `login_events`, and `audit_events`. Use account IDs `acct_<uuidhex>`, invitation IDs `inv_<uuidhex>`, and session IDs `asess_<uuidhex>`. Store only token/session hashes.

```python
@dataclass(frozen=True)
class AccountRecord:
    account_id: str
    email: str
    display_name: str
    role: Literal["owner", "admin", "user"]
    status: Literal["pending_activation", "active", "disabled", "anonymized"]
    created_at: str
    last_access_at: str | None
```

Compose `self.identity = IdentityStore(self.paths)` in `DataCore`, include it in health/stats, and close it in `DataCore.close()`.

- [ ] **Step 4: Run focused and DataCore regression tests**

Run: `python -m pytest tests/test_identity_security.py tests/test_identity_store.py -v && python -m compileall -q defend_data`
Expected: PASS and exit 0.

- [ ] **Step 5: Commit**

```powershell
git add defend_data/identity_security.py defend_data/identity_store.py defend_data/data_core.py tests/conftest.py tests/test_identity_security.py tests/test_identity_store.py
git commit -m "Add durable identity store"
```

### Task 3: Bootstrap owner and migrate admin authentication

**Files:**
- Modify: `admin_auth.py`
- Modify: `api_server.py`
- Test: `tests/test_admin_identity_auth.py`

**Interfaces:**
- Consumes: `IdentityStore.bootstrap_owner`, `IdentityStore.authenticate_account`, `IdentityStore.create_session`, `IdentityStore.resolve_session`.
- Preserves: `AdminPrincipal`, `authenticate`, `require_admin`, `require_owner`, `revoke`, and `token_from_header` call sites.

- [ ] **Step 1: Write failing compatibility and authorization tests**

```python
def test_admin_cannot_manage_admin(identity, admin_principal, target_admin):
    with pytest.raises(RoleViolation):
        identity.disable_account(actor=admin_principal, target_id=target_admin.account_id)

def test_owner_session_survives_auth_module_restart(client, configured_owner):
    login = client.post("/api/admin/login", json=configured_owner).json()
    assert client.get("/api/admin/system/health", headers={"Authorization": f"Bearer {login['token']}"}).status_code == 200
```

- [ ] **Step 2: Run test and verify RED**

Run: `python -m pytest tests/test_admin_identity_auth.py -v`
Expected: FAIL because `admin_auth` still uses `_TOKENS` only.

- [ ] **Step 3: Replace in-memory tokens with identity sessions**

Add `configure_identity_store(store: IdentityStore) -> None`, call it during FastAPI lifespan setup, and bootstrap the environment owner once. `authenticate` accepts email/username compatibility, but returns the same tuple expected by the current login route. `AdminPrincipal` gains `account_id` while retaining `username`, `role`, and `expires_at`.

- [ ] **Step 4: Run auth and current admin route tests**

Run: `python -m pytest tests/test_admin_identity_auth.py -v && python -m compileall -q admin_auth.py api_server.py api_admin_tt_routes.py`
Expected: PASS; existing owner-only TableTennis dependencies still import.

- [ ] **Step 5: Commit**

```powershell
git add admin_auth.py api_server.py tests/test_admin_identity_auth.py
git commit -m "Persist admin identity sessions"
```

### Task 4: Add invitations, Gmail delivery, activation, and account sessions

**Files:**
- Create: `defend_data/identity_mailer.py`
- Create: `api_identity_routes.py`
- Modify: `api_server.py`
- Test: `tests/test_identity_invitations_api.py`
- Test: `tests/test_identity_mailer.py`

**Interfaces:**
- Produces: `GmailInvitationMailer.send_invitation(*, recipient: str, activation_url: str, expires_at: str) -> DeliveryResult`.
- Produces endpoints: `POST /api/admin/accounts`, `POST /api/admin/invitations/{id}/resend`, `POST /api/admin/invitations/{id}/revoke`, `GET /api/activate/{token}/status`, `POST /api/activate/{token}`, `POST /api/account/login`, and `POST /api/account/logout`.

- [ ] **Step 1: Write failing invitation lifecycle tests**

```python
def test_invitation_is_single_use_and_expires_in_48_hours(client, admin_headers, frozen_now):
    created = client.post("/api/admin/accounts", headers=admin_headers, json={"email":"user@example.com","display_name":"User","role":"user"}).json()
    token = created["invitation"]["token"]
    assert created["invitation"]["expires_at"] == (frozen_now + timedelta(hours=48)).isoformat()
    assert client.post(f"/api/activate/{token}", json={"password":"a sufficiently long password"}).status_code == 200
    assert client.post(f"/api/activate/{token}", json={"password":"another sufficiently long password"}).status_code == 410
```

- [ ] **Step 2: Run invitation tests and verify RED**

Run: `python -m pytest tests/test_identity_invitations_api.py tests/test_identity_mailer.py -v`
Expected: FAIL because routes and mailer do not exist.

- [ ] **Step 3: Implement transactional invitation and activation flows**

Use `email.message.EmailMessage`, `smtplib.SMTP_SSL` or STARTTLS according to environment configuration, and a 48-hour expiry constant. Return the raw invitation token only once to the authorized creation/resend response so the workstation can copy it. Store delivery state and bounded error text.

```python
@dataclass(frozen=True)
class DeliveryResult:
    delivered: bool
    provider_message_id: str | None = None
    error: str | None = None
```

Apply generic login/activation failures and bounded in-process rate limiting keyed by cleaned client IP plus normalized email/token hash.

- [ ] **Step 4: Run API, mailer, auth, and schema tests**

Run: `python -m pytest tests/test_identity_invitations_api.py tests/test_identity_mailer.py tests/test_admin_identity_auth.py tests/test_identity_store.py -v`
Expected: PASS with mocked SMTP and no network access.

- [ ] **Step 5: Commit**

```powershell
git add defend_data/identity_mailer.py api_identity_routes.py api_server.py tests/test_identity_invitations_api.py tests/test_identity_mailer.py
git commit -m "Add account invitations and activation API"
```

### Task 5: Add the activation page and phase verification

**Files:**
- Create: `defend-ui-v2/app/activate/page.tsx`
- Create: `defend-ui-v2/components/AccountActivation.tsx`
- Modify: `defend-ui-v2/lib/api.ts`
- Modify: `start_api.TXT`
- Test: `tests/test_identity_activation_contract.py`

**Interfaces:**
- Consumes: `GET /api/activate/{token}/status` and `POST /api/activate/{token}`.
- Produces: a public activation page with loading, valid, expired, consumed, revoked, success, and error states.

- [ ] **Step 1: Write a failing API contract test**

```python
def test_activation_status_never_returns_token_hash(client, invitation_token):
    payload = client.get(f"/api/activate/{invitation_token}/status").json()
    assert payload["status"] == "pending"
    assert "token_hash" not in payload
```

- [ ] **Step 2: Run contract test and verify RED**

Run: `python -m pytest tests/test_identity_activation_contract.py -v`
Expected: FAIL until the final response contract is implemented.

- [ ] **Step 3: Implement typed client calls and activation UI**

```ts
export type ActivationStatus = "pending" | "expired" | "consumed" | "revoked";
export const activationStatus = (token: string) => json<ActivationStatusResponse>(`/api/activate/${encodeURIComponent(token)}/status`);
export const activateAccount = (token: string, password: string) => json<{ok: true}>(`/api/activate/${encodeURIComponent(token)}`, {method: "POST", body: JSON.stringify({password})});
```

Document required Gmail/public-origin environment variables in `start_api.TXT` without values.

- [ ] **Step 4: Run full phase verification**

Run: `python -m pytest tests/test_ingest_policy.py tests/test_identity_security.py tests/test_identity_store.py tests/test_admin_identity_auth.py tests/test_identity_invitations_api.py tests/test_identity_mailer.py tests/test_identity_activation_contract.py -v`
Run: `python -m compileall -q .`
Run: `C:\Program Files\nodejs\npm.cmd run build --prefix defend-ui-v2`
Expected: all tests PASS and Next.js build exits 0.

- [ ] **Step 5: Commit**

```powershell
git add defend-ui-v2/app/activate/page.tsx defend-ui-v2/components/AccountActivation.tsx defend-ui-v2/lib/api.ts start_api.TXT tests/test_identity_activation_contract.py
git commit -m "Add secure account activation page"
```
