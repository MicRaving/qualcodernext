"""SERVER_PLAN.md Phase 5 — server CLI (migrate / bootstrap-admin)."""
from __future__ import annotations

import asyncio

import pytest


@pytest.fixture
def server_env(tmp_path, monkeypatch):
    monkeypatch.setenv("QC_SERVER_MODE", "true")
    monkeypatch.setenv("QC_SECRET_KEY", "s")
    monkeypatch.setenv("QC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("QC_ADMIN_USER", raising=False)
    monkeypatch.delenv("QC_ADMIN_PASS", raising=False)
    yield tmp_path
    from qualcoder_api.persistence import metadata_db

    asyncio.run(metadata_db.dispose_metadata_engine())


def _run_cli(args: list[str]) -> int:
    from qualcoder_api.cli import main

    return main(args)


def test_migrate_creates_schema(server_env):
    assert _run_cli(["migrate"]) == 0
    # second run is idempotent
    assert _run_cli(["migrate"]) == 0


def test_bootstrap_admin_from_args(server_env):
    assert _run_cli(["migrate"]) == 0
    assert (
        _run_cli(["bootstrap-admin", "--username", "root", "--password", "root-pw-123"])
        == 0
    )
    from qualcoder_api.persistence import metadata_db

    admin = asyncio.run(metadata_db.get_user_by_username("root"))
    assert admin is not None and admin["role"] == "admin"


def test_bootstrap_admin_skips_when_users_exist(server_env):
    _run_cli(["migrate"])
    assert _run_cli(["bootstrap-admin", "--username", "a1", "--password", "pw-12345"]) == 0
    # second run must NOT create another user nor fail
    assert _run_cli(["bootstrap-admin", "--username", "a2", "--password", "pw-12345"]) == 0
    from qualcoder_api.persistence import metadata_db

    assert asyncio.run(metadata_db.count_users()) == 1


def test_bootstrap_requires_credentials_when_no_env(server_env):
    _run_cli(["migrate"])
    assert _run_cli(["bootstrap-admin"]) == 2


def test_check_config_prints_paths(server_env, capsys):
    assert _run_cli(["check-config"]) == 0
    out = capsys.readouterr().out
    assert "data_dir" in out and "OK" in out


def test_secret_subcommand(monkeypatch, capsys):
    from qualcoder_api.cli import main

    monkeypatch.delenv("QC_SERVER_MODE", raising=False)
    assert main(["secret"]) == 0
    token = capsys.readouterr().out.strip()
    assert len(token) >= 40
