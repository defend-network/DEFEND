from __future__ import annotations

from io import StringIO

from defend_coder.config import CoderSettings
from tools.defend_coder_admin_bootstrap import bootstrap_admin, run

from tests.test_defend_coder_session_flow import FakeCoderRepository

_FAKE_SETTINGS = CoderSettings(database_url="unused-by-fake")


class TestBootstrapAdmin:
    def test_creates_admin_account_with_hashed_password(self):
        repository = FakeCoderRepository()
        out = StringIO()

        created = bootstrap_admin(
            repository,
            username="admin",
            email="admin@defend-network.org",
            password="correct horse battery staple",
            role="admin",
            output=out.write,
        )

        assert created is True
        record = repository.get_account_by_username("admin")
        assert record is not None
        assert record.role == "admin"
        assert record.email == "admin@defend-network.org"
        assert record.password_hash != "correct horse battery staple"
        assert record.password_hash.startswith("$argon2")
        assert "correct horse battery staple" not in out.getvalue()
        assert "admin" in out.getvalue()

    def test_is_idempotent_for_existing_username(self):
        repository = FakeCoderRepository()
        out = StringIO()

        first = bootstrap_admin(
            repository,
            username="admin",
            email=None,
            password="secret-password-one",
            role="admin",
            output=out.write,
        )
        second = bootstrap_admin(
            repository,
            username="admin",
            email=None,
            password="secret-password-two",
            role="admin",
            output=out.write,
        )

        assert first is True
        assert second is False
        assert len(repository.accounts) == 1
        assert "already exists" in out.getvalue()
        assert "secret-password-two" not in out.getvalue()

    def test_creates_consumer_role_when_requested(self):
        repository = FakeCoderRepository()

        bootstrap_admin(
            repository,
            username="operator",
            email=None,
            password="operator-password",
            role="consumer",
            output=lambda _: None,
        )

        assert repository.get_account_by_username("operator").role == "consumer"

    def test_records_account_created_audit_event(self):
        repository = FakeCoderRepository()

        bootstrap_admin(
            repository,
            username="admin",
            email=None,
            password="audited-password",
            role="admin",
            output=lambda _: None,
        )

        events = [
            event
            for event in repository.audit
            if event.event_type == "account.created"
        ]
        assert len(events) == 1
        assert events[0].target_type == "coder_account"

    def test_rejects_empty_password(self):
        repository = FakeCoderRepository()

        try:
            bootstrap_admin(
                repository,
                username="admin",
                email=None,
                password="",
                role="admin",
                output=lambda _: None,
            )
        except ValueError as error:
            assert "password" in str(error)
        else:
            raise AssertionError("expected ValueError for empty password")


class TestRun:
    def test_run_prompts_and_creates(self):
        repository = FakeCoderRepository()
        prompts = iter(["prompted-password", "prompted-password"])
        out = StringIO()

        code = run(
            _FAKE_SETTINGS,
            username="admin",
            email=None,
            role="admin",
            output=out.write,
            prompt_password=lambda _: next(prompts),
            repository=repository,
        )

        assert code == 0
        assert "Created DEFENDcoder admin account 'admin'" in out.getvalue()
        assert "prompted-password" not in out.getvalue()

    def test_run_existing_username_is_noop(self):
        repository = FakeCoderRepository()
        bootstrap_admin(
            repository,
            username="admin",
            email=None,
            password="first-password",
            role="admin",
            output=lambda _: None,
        )
        out = StringIO()

        code = run(
            _FAKE_SETTINGS,
            username="admin",
            email=None,
            role="admin",
            output=out.write,
            prompt_password=lambda _: "second-password",
            repository=repository,
        )

        assert code == 0
        assert "already exists" in out.getvalue()
        assert "second-password" not in out.getvalue()

    def test_run_rejects_mismatched_passwords_without_creating(self):
        repository = FakeCoderRepository()
        prompts = iter(["password-one", "password-two"])
        out = StringIO()

        code = run(
            _FAKE_SETTINGS,
            username="admin",
            email=None,
            role="admin",
            output=out.write,
            prompt_password=lambda _: next(prompts),
            repository=repository,
        )

        assert code == 2
        assert "do not match" in out.getvalue()
        assert repository.get_account_by_username("admin") is None

    def test_run_rejects_empty_username(self):
        repository = FakeCoderRepository()
        out = StringIO()

        code = run(
            _FAKE_SETTINGS,
            username="",
            email=None,
            role="admin",
            output=out.write,
            prompt_password=lambda _: "ignored",
            repository=repository,
        )

        assert code == 2
        assert "must not be empty" in out.getvalue()