from pathlib import Path

import pytest

from scs_data.config import ScsPaths
from scs_data.core import ScsDataCore
from shared_platform.phase0 import build_scs_process_specs, phase0_contexts


def test_scs_processes_are_local_non_billable_and_receive_only_scs_configuration(tmp_path):
    _defend, scs = phase0_contexts()
    scs = type(scs)(**{**scs.__dict__, "data_root": (tmp_path / "SCS_DATA").resolve()})
    specs = build_scs_process_specs(scs, Path("C:/repo"), "python", "npm.cmd")
    assert specs.api.argv[-1] == "8100" and specs.web.env["SCS_WEB_PORT"] == "3100"
    assert specs.api.health_url == "http://127.0.0.1:8100/health"
    assert specs.web.health_url == "http://127.0.0.1:3100/"
    assert all(key.startswith("SCS_") for spec in (specs.api, specs.web) for key in spec.env)
    assert not any("cloudflare" in value.lower() or "vast" in value.lower() for spec in (specs.api, specs.web) for value in spec.argv)


def test_scs_backup_and_cookie_boundaries_reject_defend(tmp_path):
    _defend, original = phase0_contexts()
    scs = type(original)(**{**original.__dict__, "data_root": (tmp_path / "SCS_DATA").resolve()})
    core = ScsDataCore(scs)
    assert scs.session_cookie == "scs_employee_session"
    assert "defend" not in str(core.paths.root).casefold()
    with pytest.raises(ValueError):
        core.backup_manifest((tmp_path / "DEFEND_DATA" / "backups").resolve())
    core.close()


def test_forged_scs_context_cannot_reuse_defend_boundary(tmp_path):
    _defend, scs = phase0_contexts()
    forged = type(scs)("scs", (tmp_path / "DEFEND_DATA").resolve(), "SCS", "SCS", "defend_account_session", scs.public_origin, 8100, 3100)
    with pytest.raises(ValueError, match="isolation boundary"):
        ScsPaths.from_context(forged)


def test_scs_modules_do_not_import_defend_composition_or_identity():
    forbidden = ("defend_data.DataCore", "from defend_data.identity import", "api_identity_routes", "api_server")
    for path in (*Path("scs_data").glob("*.py"), *Path("scs_api").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert not any(value in source for value in forbidden), path
