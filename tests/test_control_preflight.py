from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3

import defend_control.preflight as preflight_module
from defend_control.preflight import CheckResult, PreflightRunner
from defend_control.settings import ControlSettings


def settings(tmp_path: Path) -> ControlSettings:
    return ControlSettings(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        public_web_origin="https://ai.defend-network.org",
        cloudflared_exe=tmp_path / "cloudflared.exe",
        cloudflared_config=tmp_path / "cloudflared.yml",
        cloudflared_tunnel="defend-ai",
        adapter_repo="Defend-network/defend-qwen-32b-lora",
        local_model="defend-ai:latest",
        vast_max_hourly=Decimal("3.00"),
    )


def complete_secrets() -> dict[str, str]:
    return {
        "VAST_API_KEY": "synthetic-vast-value",
        "HF_TOKEN": "synthetic-hf-value",
        "VLLM_API_KEY": "synthetic-vllm-value",
        "DEFEND_OWNER_PASS": "synthetic-owner-value",
        "DEFEND_VISITOR_HMAC_KEY": "synthetic-visitor-value",
        "DEFEND_GMAIL_SMTP_USERNAME": "synthetic-mail-user",
        "DEFEND_GMAIL_APP_PASSWORD": "synthetic-mail-password",
    }


def test_preflight_returns_every_failure_without_short_circuit(tmp_path):
    runner = PreflightRunner(
        command_exists=lambda name: name not in {"ssh.exe", "cloudflared.exe"},
        port_available=lambda port: port != 8000,
        writable=lambda path: False,
        invitation_check=lambda: CheckResult(
            "invitations", False, "blocked", "Run rollout reissue"
        ),
    )
    results = runner.run("vast", settings(tmp_path), complete_secrets())
    failed = {result.name for result in results if not result.ok}
    assert {
        "ssh.exe",
        "cloudflared.exe",
        "port:8000",
        "data-root",
        "invitations",
    } <= failed


def test_preflight_reports_secret_names_only(tmp_path):
    results = PreflightRunner.for_test(missing_secrets={"HF_TOKEN"}).run(
        "vast", settings(tmp_path), {}
    )
    rendered = "\n".join(result.detail for result in results)
    assert "HF_TOKEN" in rendered
    assert "Bearer " not in rendered


def test_preflight_uses_exact_service_ports_and_aggregates_checks(tmp_path):
    observed_ports: list[int] = []
    runner = PreflightRunner.for_test(
        port_available=lambda port: not observed_ports.append(port)
    )

    results = runner.run("vast", settings(tmp_path), complete_secrets())

    assert observed_ports == [3000, 8000, 8001]
    assert {result.name for result in results} >= {
        "python-version",
        "node-version",
        "npm.cmd",
        "git",
        "ssh.exe",
        "cloudflared.exe",
        "cloudflared-config",
        "data-root",
        "settings-root",
        "logs",
        "port:3000",
        "port:8000",
        "port:8001",
        "secrets",
        "next-build",
        "invitations",
    }


def test_preflight_accepts_secret_store_without_rendering_values(tmp_path):
    secret_value = "synthetic-private-material"

    class SecretStore:
        def load(self) -> dict[str, str]:
            values = complete_secrets()
            values["HF_TOKEN"] = secret_value
            return values

    results = PreflightRunner.for_test().run("vast", settings(tmp_path), SecretStore())
    rendered = repr(results)

    assert secret_value not in rendered
    assert next(result for result in results if result.name == "secrets").ok


def test_preflight_reports_safe_error_type_not_raw_exception(tmp_path):
    def unsafe_failure() -> CheckResult:
        raise RuntimeError("Bearer synthetic-private-material")

    runner = PreflightRunner.for_test(invitation_check=unsafe_failure)
    results = runner.run("vast", settings(tmp_path), complete_secrets())
    invitation = next(result for result in results if result.name == "invitations")

    assert not invitation.ok
    assert "RuntimeError" in invitation.detail
    assert "synthetic-private-material" not in repr(invitation)
    assert "Bearer " not in repr(invitation)


def test_real_invitation_gate_reads_existing_database_without_mutation(tmp_path):
    configured = settings(tmp_path)
    database = configured.data_root / "db" / "identity.db"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE TABLE invitations (
                invitation_id TEXT,
                account_id TEXT,
                created_at TEXT,
                expires_at TEXT,
                consumed_at TEXT,
                revoked_at TEXT,
                transport_version TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO invitations VALUES (?,?,?,?,?,?,?)",
            (
                "inv-legacy",
                "account-1",
                datetime.now(timezone.utc).isoformat(),
                (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                None,
                None,
                "legacy_path",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    before = database.read_bytes()

    runner = PreflightRunner.for_test(use_real_invitation_check=True)
    results = runner.run("vast", configured, complete_secrets())

    invitation = next(result for result in results if result.name == "invitations")
    assert not invitation.ok
    assert "1" in invitation.detail
    assert database.read_bytes() == before
    assert not (configured.data_root / "raw").exists()


def test_real_invitation_gate_does_not_create_missing_data_root(tmp_path):
    configured = settings(tmp_path)
    assert not configured.data_root.exists()

    results = PreflightRunner.for_test(use_real_invitation_check=True).run(
        "ollama", configured, complete_secrets()
    )

    assert next(result for result in results if result.name == "invitations").ok
    assert not configured.data_root.exists()


def test_invitation_gate_allows_unchanged_empty_wal_and_stale_shm(tmp_path):
    configured = settings(tmp_path)
    database = configured.data_root / "db" / "identity.db"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE TABLE invitations (
                invitation_id TEXT,
                account_id TEXT,
                created_at TEXT,
                expires_at TEXT,
                consumed_at TEXT,
                revoked_at TEXT,
                transport_version TEXT
            )
            """
        )
        connection.commit()
    finally:
        connection.close()

    database.with_name(f"{database.name}-wal").write_bytes(b"")
    database.with_name(f"{database.name}-shm").write_bytes(b"\0" * 32_768)

    results = PreflightRunner.for_test(use_real_invitation_check=True).run(
        "vast", configured, complete_secrets()
    )

    invitation = next(result for result in results if result.name == "invitations")
    assert invitation.ok
    assert invitation.detail == "Invitation rollout ready"


def test_preflight_requires_configured_cloudflared_executable_path(tmp_path):
    configured = settings(tmp_path)
    runner = PreflightRunner(
        command_exists=lambda _name: True,
        port_available=lambda _port: True,
        writable=lambda _path: True,
        invitation_check=lambda: CheckResult(
            "invitations", True, "Invitation rollout ready"
        ),
        path_exists=lambda path: path != configured.cloudflared_exe,
        module_exists=lambda _name: True,
        python_version=lambda: (3, 14),
        node_version=lambda: (22, 0),
    )

    results = runner.run("vast", configured, complete_secrets())

    assert not next(
        result for result in results if result.name == "cloudflared.exe"
    ).ok


def test_preflight_rejects_file_where_writable_directory_is_required(tmp_path):
    configured = settings(tmp_path)
    configured.data_root.write_text("not a directory", encoding="utf-8")
    runner = PreflightRunner(
        command_exists=lambda _name: True,
        port_available=lambda _port: True,
        invitation_check=lambda: CheckResult(
            "invitations", True, "Invitation rollout ready"
        ),
        path_exists=lambda _path: True,
        module_exists=lambda _name: True,
        python_version=lambda: (3, 14),
        node_version=lambda: (22, 0),
    )

    results = runner.run("vast", configured, complete_secrets())

    assert not next(result for result in results if result.name == "data-root").ok


def test_ollama_preflight_still_aggregates_missing_ssh(tmp_path):
    runner = PreflightRunner(
        command_exists=lambda name: name != "ssh.exe",
        port_available=lambda _port: True,
        writable=lambda _path: True,
        invitation_check=lambda: CheckResult(
            "invitations", False, "blocked", "Run rollout reissue"
        ),
        path_exists=lambda _path: True,
        module_exists=lambda _name: True,
        python_version=lambda: (3, 14),
        node_version=lambda: (22, 0),
    )

    results = runner.run("ollama", settings(tmp_path), complete_secrets())

    failed = {result.name for result in results if not result.ok}
    assert {"ssh.exe", "invitations"} <= failed


def test_invitation_gate_fails_closed_when_wal_appears_during_query(
    tmp_path, monkeypatch
):
    configured = settings(tmp_path)
    database = configured.data_root / "db" / "identity.db"
    database.parent.mkdir(parents=True)
    setup = sqlite3.connect(database)
    try:
        setup.execute("PRAGMA journal_mode=WAL")
        setup.execute(
            """
            CREATE TABLE invitations (
                invitation_id TEXT,
                account_id TEXT,
                created_at TEXT,
                expires_at TEXT,
                consumed_at TEXT,
                revoked_at TEXT,
                transport_version TEXT
            )
            """
        )
        setup.commit()
    finally:
        setup.close()

    original_connect = sqlite3.connect
    writers: list[sqlite3.Connection] = []
    triggered = False

    class TriggerConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self._connection = connection

        def execute(self, statement: str):
            nonlocal triggered
            if not triggered and statement.startswith("PRAGMA table_info"):
                triggered = True
                writer = original_connect(database)
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute(
                    "INSERT INTO invitations VALUES (?,?,?,?,?,?,?)",
                    (
                        "inv-concurrent",
                        "account-concurrent",
                        datetime.now(timezone.utc).isoformat(),
                        (
                            datetime.now(timezone.utc) + timedelta(hours=1)
                        ).isoformat(),
                        None,
                        None,
                        "legacy_path",
                    ),
                )
                writer.commit()
                writers.append(writer)
            return self._connection.execute(statement)

        def close(self) -> None:
            self._connection.close()

    def connect(candidate, *args, **kwargs):
        connection = original_connect(candidate, *args, **kwargs)
        return TriggerConnection(connection) if kwargs.get("uri") else connection

    monkeypatch.setattr(preflight_module.sqlite3, "connect", connect)
    try:
        results = PreflightRunner.for_test(use_real_invitation_check=True).run(
            "vast", configured, complete_secrets()
        )
    finally:
        for writer in writers:
            writer.close()

    invitation = next(result for result in results if result.name == "invitations")
    assert triggered
    assert not invitation.ok
    assert "stable" in invitation.detail.casefold()
