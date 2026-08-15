import importlib
import inspect
import os
import socket

import pytest
from starlette.testclient import TestClient

from defend_sports.config import SportsSettings
from defend_sports.db import SportsDatabase
from defend_sports.ingestion import IngestionService
from defend_sports.providers.fixture import FixtureSportsProvider

requires_database = pytest.mark.skipif(
    not os.environ.get("SPORTS_TEST_DATABASE_URL"),
    reason="SPORTS_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

_FORBIDDEN_ROUTE_FRAGMENTS = ("wager", "bet", "place", "execution", "stake", "trade")


@pytest.fixture(scope="session")
def database():
    url = os.environ.get("SPORTS_TEST_DATABASE_URL")
    if not url:
        return None
    database = SportsDatabase(url)
    database.migrate()
    return database


@pytest.fixture(autouse=True)
def _clean_shared_tables(database):
    if database is None:
        yield
        return
    with database.connect() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    TRUNCATE odds_snapshots, live_observations, raw_provider_events,
                             provider_health, selections, markets, sport_events,
                             leagues, participants, sports, provider_sources
                    RESTART IDENTITY CASCADE
                    """
                )
    yield


class FakeSportsDatabase:
    def __init__(self, health_result=None, connect_error=None):
        self._health_result = health_result
        self._connect_error = connect_error
        self.connect_calls = 0

    def health(self):
        return self._health_result

    def migrate(self):
        return 1

    def __enter__(self):
        raise TypeError("SportsDatabase is not a context manager; use connect()")

    def __exit__(self, *args):
        raise TypeError("SportsDatabase is not a context manager; use connect()")

    def connect(self):
        self.connect_calls += 1
        if self._connect_error is not None:
            raise self._connect_error
        return _NullConnection()


class _NullConnection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _healthy_health():
    return {
        "ok": True,
        "application_id": "sports",
        "schema_version": 1,
        "database": "ready",
    }


def _unhealthy_health():
    return {
        "ok": False,
        "application_id": "sports",
        "schema_version": 0,
        "database": "unavailable",
    }


def _settings(tmp_path) -> SportsSettings:
    return SportsSettings(
        data_root=tmp_path / "sports-data",
        database_url="postgresql://sports:super-secret-password@db.example.invalid/sports",
    )


def _app(settings, database):
    from defend_sports.app import build_sports_app

    return build_sports_app(settings, database)


class TestHealthEndpoint:
    def test_health_returns_exact_application_identity(self, tmp_path):
        client = TestClient(_app(_settings(tmp_path), FakeSportsDatabase(health_result=_healthy_health())))

        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == _healthy_health()

    def test_health_reflects_database_unavailability_honestly(self, tmp_path):
        client = TestClient(_app(_settings(tmp_path), FakeSportsDatabase(health_result=_unhealthy_health())))

        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {
            "ok": False,
            "application_id": "sports",
            "schema_version": 0,
            "database": "unavailable",
        }

    def test_health_payload_never_exposes_connection_url_or_password(self, tmp_path):
        client = TestClient(_app(_settings(tmp_path), FakeSportsDatabase(health_result=_healthy_health())))

        body = client.get("/health").text

        assert "super-secret-password" not in body
        assert "postgresql://" not in body
        assert "database_url" not in body
        assert "db.example.invalid" not in body


class TestSystemSourcesEndpoint:
    def test_sources_reports_unavailable_when_database_is_down(self, tmp_path):
        database = FakeSportsDatabase(
            health_result=_healthy_health(),
            connect_error=RuntimeError("database unreachable"),
        )
        client = TestClient(_app(_settings(tmp_path), database))

        response = client.get("/v1/system/sources")

        assert response.status_code == 200
        assert response.json() == {
            "ok": False,
            "application_id": "sports",
            "database": "unavailable",
            "sources": [],
        }
        assert database.connect_calls == 1


class TestServiceBoundary:
    def test_application_construction_makes_no_provider_network_calls(self, tmp_path, monkeypatch):
        def forbidden(*args, **kwargs):
            raise AssertionError("application construction attempted a network call")

        with monkeypatch.context() as context:
            context.setattr(socket, "socket", forbidden)
            database = FakeSportsDatabase(health_result=_healthy_health())
            app = _app(_settings(tmp_path), database)

        assert app is not None
        assert database.connect_calls == 0

    def test_importing_sports_app_opens_no_global_database_connection(self, monkeypatch):
        module = importlib.import_module("defend_sports.app")

        assert not any(isinstance(value, SportsDatabase) for value in vars(module).values())
        assert not hasattr(module, "_database")
        assert not hasattr(module, "app")

    def test_no_wagering_or_execution_endpoints_exist(self, tmp_path):
        app = _app(_settings(tmp_path), FakeSportsDatabase(health_result=_healthy_health()))

        paths = {route.path for route in app.routes}
        assert paths == {
            "/health",
            "/v1/system/sources",
            "/openapi.json",
            "/docs",
            "/docs/oauth2-redirect",
            "/redoc",
        }
        for path in paths:
            lowered = path.casefold()
            for fragment in _FORBIDDEN_ROUTE_FRAGMENTS:
                assert fragment not in lowered

    def test_sports_app_has_no_platform_runtime_dependencies(self):
        import defend_sports.app as app_module
        import tools.defend_sports_server as server_module

        for module in (app_module, server_module):
            source = inspect.getsource(module)
            for forbidden in ("api_server", "scs_api", "scs_data", "defend_control", "defendcoder", "vast", "vllm"):
                assert forbidden not in source


@requires_database
class TestPostgreSqlIntegration:
    def test_health_schema_version_comes_from_real_database(self, database, tmp_path):
        client = TestClient(_app(_settings(tmp_path), database))

        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "application_id": "sports",
            "schema_version": 1,
            "database": "ready",
        }
        assert "postgresql://" not in response.text
        assert "devtest" not in response.text

    def test_system_sources_returns_safe_source_health_information(self, database, tmp_path):
        IngestionService(database).ingest(FixtureSportsProvider().poll())
        client = TestClient(_app(_settings(tmp_path), database))

        response = client.get("/v1/system/sources")

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["application_id"] == "sports"
        assert payload["database"] == "ready"

        by_key = {source["source_key"]: source for source in payload["sources"]}
        assert set(by_key) == {"book-a", "book-b", "fixture"}

        fixture = by_key["fixture"]
        assert fixture["provider_name"] == "fixture"
        assert fixture["is_active"] is True
        assert fixture["raw_events"] == 2
        assert fixture["odds_snapshots"] == 0
        assert fixture["latest_health"]["status"] == "HEALTHY"
        assert fixture["latest_health"]["observed_at"] is not None

        assert by_key["book-a"]["raw_events"] == 0
        assert by_key["book-a"]["odds_snapshots"] == 4
        assert by_key["book-b"]["odds_snapshots"] == 4

        body = response.text
        assert "match_id" not in body
        assert "scoreboard" not in body
        assert "participants" not in body
        assert "postgresql://" not in body
        assert "devtest" not in body
        assert "super-secret-password" not in body

    def test_system_sources_is_operational_when_no_sources_exist(self, database, tmp_path):
        client = TestClient(_app(_settings(tmp_path), database))

        response = client.get("/v1/system/sources")

        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert response.json()["sources"] == []