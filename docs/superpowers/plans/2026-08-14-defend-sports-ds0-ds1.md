# DEFEND Sports DS0 + DS1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the independent DEFEND Sports service foundation and provider-neutral sports/market data plane without changing existing DEFEND, SCS, DEFENDcoder, or legacy TableTennis behavior.

**Architecture:** Generalize the existing two-application `shared_platform` contract so it can safely register `sports` as a third application, then build a separate FastAPI service with PostgreSQL-backed canonical sports/event/market storage. Feed providers implement narrow adapters that emit canonical observations; downstream arbitrage and prediction logic are explicitly out of scope for DS0/DS1.

**Tech Stack:** Python 3.14, FastAPI 0.141.1, Pydantic 2.13.4, psycopg 3.3.4 (`psycopg[binary]==3.3.4`), PostgreSQL, pytest 9.1.1, existing DEFEND Control Center/shared-platform conventions.

## Global Constraints

- Preserve DEFEND AI launch/runtime behavior exactly.
- Preserve SCS launch/runtime behavior exactly.
- Preserve current DEFENDcoder branch/work while avoiding shared-file conflicts where possible.
- Keep legacy `TableTennis/` and `api_admin_tt_routes.py` operational throughout DS0/DS1.
- `sports` is a distinct application namespace with its own data root, secret namespace, cookie, ports, origin, API and health state.
- Production hostname target: `https://defendsports.defend-network.org`.
- No sportsbook authentication or wager placement.
- No LLM-generated live scores/odds.
- Provider adapters emit structured canonical observations only.
- Multi-user schema boundaries are created now even if the first active account is the owner.
- User-scoped financial/portfolio data must never be stored in shared market tables.
- All source observations include provider identity and observed timestamp.
- DS0/DS1 do not implement arbitrage detection, predictive challengers, Sports AI, or the approved production dashboard.

---

## File Structure Locked for DS0/DS1

```text
shared_platform/
  application.py                  # application registry/context validation
  services.py                     # service + route deployment validation

defend_control/
  settings.py                     # sports ports/origin/process settings
  processes.py                    # start/stop sports API process
  controller.py                   # sports commands/status integration
  preflight.py                    # sports-specific prerequisites

defend_sports/
  __init__.py
  app.py                          # FastAPI factory + health
  config.py                       # SportsSettings / environment parsing
  db.py                           # psycopg connection helpers + migrations
  migrations/
    0001_foundation.sql           # canonical DS0/DS1 database schema
  domain.py                       # canonical typed domain models
  repositories.py                 # persistence API for canonical entities/observations
  providers/
    __init__.py
    base.py                       # provider adapter interfaces
    fixture.py                    # deterministic test/demo provider only
  ingestion.py                    # canonical ingestion service

tools/
  defend_sports_server.py         # local/control-plane entrypoint

tests/
  test_shared_platform_multiapp.py
  test_sports_config.py
  test_sports_db.py
  test_sports_domain.py
  test_sports_ingestion.py
  test_sports_app.py
  test_control_sports.py
  test_tabletennis_baseline_regression.py
```

---

### Task 1: Generalize `shared_platform` from exactly two apps to registered apps

**Files:**
- Modify: `shared_platform/application.py`
- Modify: `shared_platform/services.py`
- Test: `tests/test_shared_platform_multiapp.py`
- Regression: existing shared-platform/SCS tests

**Interfaces:**
- Produces `ApplicationId = Literal["defend", "scs", "sports"]`.
- Produces `validate_applications(contexts: tuple[ApplicationContext, ...]) -> tuple[ApplicationContext, ...]`.
- Keeps `validate_application_pair(first, second)` as a compatibility wrapper for existing callers.
- Produces deployment validation that accepts 2+ registered application contexts rather than exactly two.

- [ ] **Step 1: Write failing tests for the third application and collision protection**

```python
from pathlib import Path
import pytest

from shared_platform.application import ApplicationContext, validate_applications
from shared_platform.services import RouteProfile, ServiceProfile, validate_deployment


def ctx(app_id: str, root: Path, prefix: str, cookie: str, origin: str, api: int, web: int):
    return ApplicationContext(
        application_id=app_id,
        data_root=root,
        environment_prefix=prefix,
        secret_namespace=prefix,
        session_cookie=cookie,
        public_origin=origin,
        api_port=api,
        web_port=web,
    )


def test_validate_three_application_contexts(tmp_path):
    defend = ctx("defend", tmp_path / "defend", "DEFEND", "defend_session", "https://defend-network.org", 8000, 3000)
    scs = ctx("scs", tmp_path / "scs", "SCS", "scs_session", "https://scs.defend-network.org", 8100, 3100)
    sports = ctx("sports", tmp_path / "sports", "SPORTS", "sports_session", "https://defendsports.defend-network.org", 8200, 3200)
    validated = validate_applications((defend, scs, sports))
    assert [x.application_id for x in validated] == ["defend", "scs", "sports"]


def test_cross_application_port_collision_is_rejected(tmp_path):
    defend = ctx("defend", tmp_path / "defend", "DEFEND", "defend_session", "https://defend-network.org", 8000, 3000)
    sports = ctx("sports", tmp_path / "sports", "SPORTS", "sports_session", "https://defendsports.defend-network.org", 8000, 3200)
    with pytest.raises(ValueError, match="port collision"):
        validate_applications((defend, sports))
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_shared_platform_multiapp.py -v
```

Expected: failure because `sports` is not an accepted `ApplicationId` and generalized validation does not yet exist.

- [ ] **Step 3: Implement a registered multi-application validator while preserving the old wrapper**

Core shape:

```python
ApplicationId = Literal["defend", "scs", "sports"]
_APPLICATION_IDS = ("defend", "scs", "sports")


def validate_applications(contexts: tuple[ApplicationContext, ...]) -> tuple[ApplicationContext, ...]:
    if len(contexts) < 2:
        raise ValueError("deployment requires at least two application contexts")
    by_id = {item.application_id: item for item in contexts}
    if len(by_id) != len(contexts):
        raise ValueError("deployment application ids must be unique")

    # pairwise collision checks for roots, namespace, cookie, origin and ports
    ...

    return tuple(sorted(contexts, key=lambda x: _APPLICATION_IDS.index(x.application_id)))


def validate_application_pair(first, second):
    validated = validate_applications((first, second))
    if {x.application_id for x in validated} != {"defend", "scs"}:
        raise ValueError("deployment requires exactly one defend and one scs context")
    return next(x for x in validated if x.application_id == "defend"), next(x for x in validated if x.application_id == "scs")
```

Do not remove compatibility behavior relied upon by SCS tests.

- [ ] **Step 4: Generalize `ServiceProfile`, `RouteProfile`, and `DeploymentProfile`**

Change hard-coded `{defend, scs}` checks to the registered application IDs. `DeploymentProfile.contexts` and `.routes` become variable-length tuples. `validate_deployment()` must require exactly one API service, one web service, and one route for every supplied application context while preserving service-name/port collision checks.

- [ ] **Step 5: Run shared-platform and SCS regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests -k "shared_platform or scs" -v
```

Expected: all existing tests plus new multi-app tests pass.

- [ ] **Step 6: Commit**

```bash
git add shared_platform/application.py shared_platform/services.py tests/test_shared_platform_multiapp.py
git commit -m "refactor: generalize shared platform application registry"
```

---

### Task 2: Add DEFEND Sports application configuration and dependency

**Files:**
- Modify: `requirements-runtime.txt`
- Create: `defend_sports/__init__.py`
- Create: `defend_sports/config.py`
- Test: `tests/test_sports_config.py`

**Interfaces:**
- Produces `SportsSettings.from_env()`.
- Produces `SportsSettings.application_context()`.
- Environment namespace is `SPORTS_*`.

- [ ] **Step 1: Add failing configuration tests**

Test the exact defaults:

```python
assert settings.api_port == 8200
assert settings.web_port == 3200
assert settings.public_origin == "https://defendsports.defend-network.org"
assert settings.session_cookie == "sports_session"
assert settings.data_root.is_absolute()
```

Also assert `SPORTS_DATABASE_URL` is required for non-test database access and is never included in `repr(settings)`.

- [ ] **Step 2: Pin PostgreSQL client dependency**

Append:

```text
psycopg[binary]==3.3.4
```

to `requirements-runtime.txt`.

- [ ] **Step 3: Implement `SportsSettings`**

Required fields:

```python
@dataclass(frozen=True)
class SportsSettings:
    data_root: Path
    database_url: str
    api_port: int = 8200
    web_port: int = 3200
    public_origin: str = "https://defendsports.defend-network.org"
    session_cookie: str = "sports_session"

    @classmethod
    def from_env(cls) -> "SportsSettings": ...
    def application_context(self) -> ApplicationContext: ...
```

Windows default data root: `C:\DEFEND_SPORTS_DATA`; non-Windows default: `./DEFEND_SPORTS_DATA` resolved absolute.

- [ ] **Step 4: Run tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sports_config.py -v
```

- [ ] **Step 5: Commit**

```bash
git add requirements-runtime.txt defend_sports tests/test_sports_config.py
git commit -m "feat: add DEFEND Sports application settings"
```

---

### Task 3: Create PostgreSQL foundation and multi-user canonical schema

**Files:**
- Create: `defend_sports/db.py`
- Create: `defend_sports/migrations/0001_foundation.sql`
- Test: `tests/test_sports_db.py`

**Interfaces:**
- Produces `SportsDatabase.connect()` context manager.
- Produces `SportsDatabase.migrate()`.
- Produces `SportsDatabase.health() -> dict[str, object]`.

- [ ] **Step 1: Write migration contract test**

The migration must create these DS0/DS1 tables:

```text
sports_schema_migrations
sports_users
sports_user_risk
sportsbooks
sports
leagues
participants
sport_events
live_observations
markets
selections
odds_snapshots
provider_sources
provider_health
raw_provider_events
audit_events
```

Tests should execute against `SPORTS_TEST_DATABASE_URL`; if it is absent, mark PostgreSQL integration tests skipped with a clear reason instead of silently using SQLite.

- [ ] **Step 2: Write SQL migration**

Important constraints:

```sql
CREATE TABLE sports_users (
    user_id UUID PRIMARY KEY,
    external_subject TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('OWNER','ADMIN','ANALYST','MEMBER')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sports_user_risk (
    user_id UUID PRIMARY KEY REFERENCES sports_users(user_id) ON DELETE CASCADE,
    bankroll NUMERIC(18,4) NOT NULL CHECK (bankroll >= 0),
    user_max_stake_pct NUMERIC(8,6) NOT NULL CHECK (user_max_stake_pct >= 0 AND user_max_stake_pct <= 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Shared market data tables must not contain `user_id`.

`odds_snapshots` must include `source_id`, `market_id`, `selection_id`, decimal odds, `observed_at`, `received_at`, and raw-source reference.

`live_observations` must support `state_json JSONB`, `observed_at`, `received_at`, provider source, and event identity so sport-specific point states can evolve without destructive schema churn.

- [ ] **Step 3: Implement migration runner**

Use psycopg transactions and a migration table keyed by integer version. Never interpolate connection URL into SQL strings/log output.

- [ ] **Step 4: Run PostgreSQL integration tests**

```powershell
$env:SPORTS_TEST_DATABASE_URL="postgresql://..."
.\.venv\Scripts\python.exe -m pytest tests/test_sports_db.py -v
```

Expected: migration idempotence passes and `health()` reports schema version 1.

- [ ] **Step 5: Commit**

```bash
git add defend_sports/db.py defend_sports/migrations/0001_foundation.sql tests/test_sports_db.py
git commit -m "feat: add DEFEND Sports PostgreSQL foundation"
```

---

### Task 4: Define provider-neutral canonical sports domain

**Files:**
- Create: `defend_sports/domain.py`
- Test: `tests/test_sports_domain.py`

**Interfaces:**
- Produces immutable models: `SourceRef`, `CanonicalEvent`, `LiveObservation`, `CanonicalMarket`, `CanonicalSelection`, `OddsObservation`.
- All provider adapters use these models; provider-specific dicts must not leak downstream.

- [ ] **Step 1: Write validation tests**

Examples:

```python
from datetime import datetime, timezone
from decimal import Decimal
import pytest

from defend_sports.domain import OddsObservation, SourceRef


def test_odds_requires_decimal_above_one():
    with pytest.raises(ValueError):
        OddsObservation(
            source=SourceRef(provider="fixture", external_id="book-a"),
            event_external_id="event-1",
            market_key="match_winner",
            selection_key="player-a",
            decimal_odds=Decimal("1.00"),
            observed_at=datetime.now(timezone.utc),
        )
```

Add tests that timestamps must be timezone-aware and provider/external IDs cannot be blank.

- [ ] **Step 2: Implement canonical dataclasses/Pydantic models**

Use `Decimal` for prices/probability-sensitive money/odds representations where arithmetic precision matters. Keep provider raw payloads outside canonical models except for an optional opaque raw-event reference ID.

- [ ] **Step 3: Run tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sports_domain.py -v
```

```bash
git add defend_sports/domain.py tests/test_sports_domain.py
git commit -m "feat: define canonical sports market domain"
```

---

### Task 5: Add repositories and idempotent ingestion pipeline

**Files:**
- Create: `defend_sports/repositories.py`
- Create: `defend_sports/ingestion.py`
- Create: `defend_sports/providers/base.py`
- Create: `defend_sports/providers/fixture.py`
- Create: `defend_sports/providers/__init__.py`
- Test: `tests/test_sports_ingestion.py`

**Interfaces:**

```python
class SportsProvider(Protocol):
    @property
    def provider_name(self) -> str: ...
    def poll(self) -> ProviderBatch: ...

@dataclass(frozen=True)
class ProviderBatch:
    raw_events: tuple[RawProviderEvent, ...]
    events: tuple[CanonicalEvent, ...]
    live: tuple[LiveObservation, ...]
    odds: tuple[OddsObservation, ...]
```

`IngestionService.ingest(batch)` persists raw provenance first, then canonical observations transactionally where appropriate.

- [ ] **Step 1: Write fixture-provider tests**

Create deterministic fixture data for one table-tennis event and one non-table-tennis event with two books and timestamped prices. Assert ingestion:

- stores provider source once;
- stores canonical event identity;
- retains each odds snapshot rather than overwriting history;
- retains raw payload reference;
- is idempotent for a duplicate provider event ID;
- updates provider health on success/failure.

- [ ] **Step 2: Implement provider interface**

No network provider is added in DS1. `FixtureSportsProvider` exists only to prove the interface and end-to-end persistence.

- [ ] **Step 3: Implement repository methods**

Required methods:

```python
upsert_source(...)
upsert_event(...)
append_live_observation(...)
upsert_market(...)
upsert_selection(...)
append_odds_snapshot(...)
record_raw_event(...)
record_provider_health(...)
```

Use database uniqueness constraints for idempotency rather than in-memory deduplication.

- [ ] **Step 4: Implement `IngestionService` and run tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sports_ingestion.py -v
```

- [ ] **Step 5: Commit**

```bash
git add defend_sports/repositories.py defend_sports/ingestion.py defend_sports/providers tests/test_sports_ingestion.py
git commit -m "feat: add provider-neutral sports ingestion pipeline"
```

---

### Task 6: Create independent DEFEND Sports FastAPI service and health contract

**Files:**
- Create: `defend_sports/app.py`
- Create: `tools/defend_sports_server.py`
- Test: `tests/test_sports_app.py`

**Interfaces:**
- `build_sports_app(settings: SportsSettings, db: SportsDatabase) -> FastAPI`
- `GET /health`
- `GET /v1/system/sources`
- No betting/wager-placement endpoint.

- [ ] **Step 1: Write API tests**

Health response contract:

```json
{
  "ok": true,
  "application_id": "sports",
  "schema_version": 1,
  "database": "ready"
}
```

No database URL, credentials, raw tokens or provider secrets may appear.

- [ ] **Step 2: Implement app factory**

Follow the SCS app-factory pattern rather than constructing global DB connections at import time.

- [ ] **Step 3: Implement server entrypoint**

`tools/defend_sports_server.py` loads `SportsSettings.from_env()`, runs migrations explicitly at startup, builds the app, and serves on `127.0.0.1:8200` by default.

- [ ] **Step 4: Run tests and local smoke**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sports_app.py -v
.\.venv\Scripts\python.exe tools\defend_sports_server.py
```

Then from another shell:

```powershell
Invoke-RestMethod http://127.0.0.1:8200/health
```

- [ ] **Step 5: Commit**

```bash
git add defend_sports/app.py tools/defend_sports_server.py tests/test_sports_app.py
git commit -m "feat: add independent DEFEND Sports API service"
```

---

### Task 7: Integrate DEFEND Sports into Control Center without touching model launch semantics

**Files:**
- Modify: `defend_control/settings.py`
- Modify: `defend_control/processes.py`
- Modify: `defend_control/preflight.py`
- Modify: `defend_control/controller.py`
- Modify only if required by established command routing: `control_plane.py`
- Test: `tests/test_control_sports.py`
- Regression: `tests/test_control_*.py`

**Interfaces:**
- Commands: `sports.start`, `sports.stop`, `sports.status`, `sports.smoke`.
- Sports service is CPU/API infrastructure in DS0/DS1; it does not request the DEFEND chat GPU or coder GPU.

- [ ] **Step 1: Write control regression tests before modifying control code**

Tests must prove:

```text
sports.start does not call Vast provisioning
sports.stop does not stop DEFEND AI
sports.stop does not stop SCS
sports.stop does not stop DEFENDcoder
sports.status redacts SPORTS_DATABASE_URL
sports.smoke checks /health
existing chat launch tests remain unchanged
```

- [ ] **Step 2: Add settings**

Required settings:

```text
SPORTS_API_PORT=8200
SPORTS_WEB_PORT=3200
SPORTS_PUBLIC_ORIGIN=https://defendsports.defend-network.org
SPORTS_DATA_ROOT=C:\DEFEND_SPORTS_DATA
SPORTS_DATABASE_URL=<secret/environment only>
```

`SPORTS_DATABASE_URL` must not be serialized into observation/status UI payloads.

- [ ] **Step 3: Add process lifecycle**

Start the API as a named process using the repository venv and `tools/defend_sports_server.py`. Stop only that owned process. Reuse existing bounded log/redaction patterns.

- [ ] **Step 4: Add preflight and health**

Preflight checks:

- sports port free;
- data root creatable/writable;
- database URL configured;
- PostgreSQL reachable;
- migrations can be inspected/applied;
- no port/data-root collision with DEFEND/SCS.

- [ ] **Step 5: Run complete Control Center regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_control_*.py -v
```

Expected: no existing control behavior regression.

- [ ] **Step 6: Commit**

```bash
git add defend_control control_plane.py tests/test_control_sports.py
git commit -m "feat: integrate DEFEND Sports service with Control Center"
```

---

### Task 8: Characterize and freeze legacy TableTennis baseline behavior

**Files:**
- Create: `tests/test_tabletennis_baseline_regression.py`
- Read only initially: `TableTennis/tt_engine.py`, `TableTennis/tt_rules.yaml`

**Interfaces:**
- No production migration yet.
- Produces executable regression evidence that DS3 can later use when porting the baseline.

- [ ] **Step 1: Encode the existing 2–0 hard-gate behavior as tests**

Required cases:

```text
P=0.79 -> hard fail
P=0.80 with eligible fresh 2-0 path -> hard pass (subject to final floor)
trailer has 1 set -> hard fail
already 2-0 -> hard fail
model_adjust above +0.08 -> clipped to +0.08
negative model adjustment below -0.08 -> clipped to -0.08
model adjustment cannot convert hard fail into bet
```

- [ ] **Step 2: Encode existing arb math regression tests**

Assert one known two-way arb and one non-arb pair, using decimal odds and existing `find_two_way_arb` behavior.

- [ ] **Step 3: Run baseline tests without modifying V0 engine**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_tabletennis_baseline_regression.py -v
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_tabletennis_baseline_regression.py
git commit -m "test: freeze legacy TableTennis baseline behavior"
```

---

## DS0 + DS1 Acceptance Gate

The milestone is complete only when all conditions are true:

- [ ] `sports` is a registered application without breaking DEFEND/SCS validation.
- [ ] `https://defendsports.defend-network.org` is represented as the canonical public origin in configuration.
- [ ] DEFEND Sports starts/stops/statuses independently through Control Center.
- [ ] Starting/stopping Sports does not provision/destroy model GPUs.
- [ ] PostgreSQL migration version 1 applies idempotently.
- [ ] Multi-user identity/risk boundary exists in schema.
- [ ] Shared canonical sports/event/market/odds tables contain no user financial state.
- [ ] A deterministic fixture provider ingests at least one table-tennis and one other-sport event.
- [ ] Odds history is append-only at the observation level.
- [ ] Provider provenance, observed time and received time are stored.
- [ ] `/health` is green and redacts secrets.
- [ ] Legacy TableTennis baseline regression tests pass unchanged.
- [ ] Existing DEFEND, SCS and Control Center tests remain green.
- [ ] No arbitrage/prediction/dashboard scope has leaked into DS0/DS1.

## After DS0 + DS1

The next separate implementation plan is **DS2 — All-Sport Arbitrage Engine**. In parallel, provider selection/procurement should identify:

1. a broad multi-book pregame/live odds source, with Hard Rock Bet coverage preferred;
2. a table-tennis live feed with point-by-point state and server when possible;
3. historical table-tennis point/match datasets;
4. ranking/player identity sources;
5. historical odds/line-movement availability.

Do not hard-wire vendor schemas into `defend_sports/domain.py`; each selected vendor receives its own adapter.
