from pathlib import Path

import pytest

from scs_data.config import ScsPaths
from scs_data.core import ScsDataCore
from shared_platform.application import ApplicationContext


def context(root: Path, application_id: str = "scs") -> ApplicationContext:
    return ApplicationContext(
        application_id=application_id,
        data_root=root,
        environment_prefix=application_id.upper(),
        secret_namespace=application_id.upper(),
        session_cookie="scs_employee_session" if application_id == "scs" else "defend_account_session",
        public_origin="https://ai.sunshineclimatesolutions.com" if application_id == "scs" else "https://ai.defend-network.org",
        api_port=8100 if application_id == "scs" else 8000,
        web_port=3100 if application_id == "scs" else 3000,
    )


def test_scs_paths_reject_defend_context_and_stay_below_scs_root(tmp_path):
    root = (tmp_path / "SCS_DATA").resolve()
    paths = ScsPaths.from_context(context(root))

    assert paths.root == root
    assert paths.database == root / "db" / "scs.sqlite3"
    assert all(path == root or root in path.parents for path in paths.directories())
    with pytest.raises(ValueError, match="SCS context"):
        ScsPaths.from_context(context((tmp_path / "DEFEND_DATA").resolve(), "defend"))


def test_data_core_creates_only_scs_tree_and_migrates_once(tmp_path):
    root = (tmp_path / "SCS_DATA").resolve()
    defend_root = (tmp_path / "DEFEND_DATA").resolve()

    with ScsDataCore(context(root)) as first:
        rows = first.conn.execute("SELECT version FROM scs_schema_migrations").fetchall()
        assert [row[0] for row in rows] == [1]
        assert first.health() == {"ok": True, "application_id": "scs", "schema_version": 1}
    with ScsDataCore(context(root)) as second:
        assert second.conn.execute("SELECT COUNT(*) FROM scs_schema_migrations").fetchone()[0] == 1

    assert root.is_dir()
    assert not defend_root.exists()


def test_backup_manifest_is_scs_scoped_and_rejects_other_application_root(tmp_path):
    root = (tmp_path / "SCS_DATA").resolve()
    with ScsDataCore(context(root)) as data:
        manifest = data.backup_manifest(root / "backups" / "snapshot-1")
        assert manifest["application_id"] == "scs"
        assert manifest["schema_version"] == 1
        assert manifest["database"] == "db/scs.sqlite3"
        assert "DEFEND" not in repr(manifest)
        with pytest.raises(ValueError, match="SCS data root"):
            data.backup_manifest((tmp_path / "DEFEND_DATA" / "snapshot").resolve())


def test_close_is_idempotent(tmp_path):
    data = ScsDataCore(context((tmp_path / "SCS_DATA").resolve()))
    data.close()
    data.close()
