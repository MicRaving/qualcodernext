"""SERVER_PLAN.md Phase 0 — server_config + mode gating.

Local-mode invariant: with QC_SERVER_MODE unset, nothing here changes
behavior (the full suite runs in exactly that mode).
"""
from __future__ import annotations

import pytest

from qualcoder_api.core.server_config import (
    ServerConfigError,
    is_server_mode,
    load_server_config,
    resolve_under_root,
    validate_server_config,
)


def test_server_mode_off_by_default(monkeypatch):
    monkeypatch.delenv("QC_SERVER_MODE", raising=False)
    assert is_server_mode() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_server_mode_on_variants(monkeypatch, value):
    monkeypatch.setenv("QC_SERVER_MODE", value)
    assert is_server_mode() is True


def test_config_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("QC_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    cfg = load_server_config()
    assert cfg.data_dir == (tmp_path / "data").resolve()
    assert cfg.metadata_db == (tmp_path / "data" / "metadata" / "qualcoder.db").resolve()
    assert cfg.token_ttl_secs == 604800
    assert cfg.session_idle_secs == 900
    assert cfg.max_upload_bytes == 2 * 1024 * 1024 * 1024
    assert cfg.secret_key is None


def test_config_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("QC_DATA_DIR", str(tmp_path / "custom"))
    monkeypatch.setenv("QC_SECRET_KEY", "s3cret")
    monkeypatch.setenv("QC_TOKEN_TTL_SECS", "60")
    monkeypatch.setenv("QC_CORS_ORIGINS", "https://a.example, https://b.example")
    cfg = load_server_config()
    assert cfg.data_dir == (tmp_path / "custom").resolve()
    assert cfg.secret_key == "s3cret"
    assert cfg.token_ttl_secs == 60
    assert cfg.cors_origins == ["https://a.example", "https://b.example"]


def test_secret_key_required_in_server_mode(tmp_path):
    cfg = load_server_config()
    assert cfg.secret_key is None
    with pytest.raises(ServerConfigError, match="QC_SECRET_KEY"):
        validate_server_config(cfg)


def test_secret_key_present_passes(monkeypatch):
    monkeypatch.setenv("QC_SECRET_KEY", "x")
    validate_server_config(load_server_config())  # must not raise


def test_resolve_under_root_rejects_escapes(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    ok = resolve_under_root(root, "projects/abc")
    assert ok == (root / "projects" / "abc").resolve()
    for bad in ("../escape", "/abs/path", "a/../../b", ".."):
        with pytest.raises(ValueError, match="escapes the managed root"):
            resolve_under_root(root, bad)


def test_project_dir_validates_uuid_hex(monkeypatch, tmp_path):
    monkeypatch.setenv("QC_DATA_DIR", str(tmp_path))
    from qualcoder_api.core.server_config import project_dir

    good = "0f3c9d2e8b7a4c1d9e0f1a2b3c4d5e6f"
    d = project_dir(good)
    assert d.name == good
    for bad in ("", "../x", "not-a-uuid".replace("-", ""), "XYZ"):
        with pytest.raises(ValueError):
            project_dir(bad)


def test_local_mode_lifespan_unchanged():
    """Invariant #1: server mode OFF keeps the singleton service wiring."""
    import qualcoder_api.main as main_mod
    from qualcoder_api.api.v1.deps import CURRENT_SERVICE, get_service

    assert CURRENT_SERVICE.get() is None
    assert get_service() is main_mod.service
