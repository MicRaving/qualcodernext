"""Hotpatch service + version endpoint tests.

The hotpatch directories live under `~/.qualcoder/hotpatch/`; every test
redirects them into a tmp dir so the developer's real install is untouched.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from qualcoder_api.main import app
from qualcoder_api.services import hotpatch, minisign, user_settings
from qualcoder_api.services.hotpatch import HotpatchError


@pytest.fixture
def hotpatch_dirs(monkeypatch, tmp_path):
    root = tmp_path / "hotpatch" / "frontend"
    current = root / "current"
    current.mkdir(parents=True)
    monkeypatch.setattr(hotpatch, "FRONTEND_DIR", root)
    monkeypatch.setattr(hotpatch, "FRONTEND_CURRENT", current)
    monkeypatch.setattr(hotpatch, "FRONTEND_PREVIOUS", root / "previous")
    monkeypatch.setattr(hotpatch, "FRONTEND_STAGING", root / "staging")
    monkeypatch.setattr(
        hotpatch, "FRONTEND_VERSION_FILE", current / "version.json"
    )
    return current


@pytest.fixture
def patch_key(monkeypatch):
    """Ephemeral signing key, installed as the trusted patch pubkey."""
    pub, sec = minisign.generate_keypair()
    monkeypatch.setattr(hotpatch, "PATCH_PUBKEY", pub)
    return pub, sec


def _make_patch_zip(dest: Path, version: str, extra: dict[str, str] | None = None) -> Path:
    zip_path = dest / f"qcnext-frontend-{version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", "<html>nightly</html>")
        archive.writestr("version.json", json.dumps({"version": version}))
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return zip_path


def _signed_patch(tmp_path: Path, version: str, sec: str) -> dict[str, str]:
    zip_path = _make_patch_zip(tmp_path, version)
    payload = zip_path.read_bytes()
    return {
        "version": version,
        "url": zip_path.as_uri(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "signature": minisign.sign_message(sec, payload),
    }


def test_no_hotpatch_without_version_file(hotpatch_dirs):
    assert hotpatch.frontend_version() is None
    assert hotpatch.frontend_spa_dir() is None


def test_hotpatch_requires_index_html(hotpatch_dirs):
    (hotpatch_dirs / "version.json").write_text(
        json.dumps({"version": "0.1.13_001"}), encoding="utf-8"
    )
    assert hotpatch.frontend_version() is None
    (hotpatch_dirs / "index.html").write_text("<html></html>", encoding="utf-8")
    assert hotpatch.frontend_version() == "0.1.13_001"
    assert hotpatch.frontend_spa_dir() == hotpatch_dirs


def test_hotpatch_ignores_corrupt_version(hotpatch_dirs):
    (hotpatch_dirs / "index.html").write_text("<html></html>", encoding="utf-8")
    (hotpatch_dirs / "version.json").write_text("not json", encoding="utf-8")
    assert hotpatch.frontend_version() is None


async def test_hotpatch_version_endpoint_reports_channel(monkeypatch, tmp_path):
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    # Redirect the hotpatch probe away from the developer's real install.
    monkeypatch.setattr(hotpatch, "FRONTEND_CURRENT", tmp_path / "empty")
    monkeypatch.setattr(
        hotpatch, "FRONTEND_VERSION_FILE", tmp_path / "empty" / "version.json"
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/hotpatch/version")
        assert res.status_code == 200
        body = res.json()
        assert body["channel"] == "stable"
        assert body["frontend_version"] is None
        assert body["previous_version"] is None
        assert isinstance(body["app_version"], str) and body["app_version"]


def test_embedded_pubkey_matches_repo_key():
    repo_root = Path(__file__).resolve().parent.parent.parent
    repo_key = (repo_root / "updater.key.pub").read_text(encoding="utf-8").strip()
    assert repo_key == hotpatch.PATCH_PUBKEY


def test_apply_patch_activates_version(hotpatch_dirs, patch_key, tmp_path):
    _pub, sec = patch_key
    patch = _signed_patch(tmp_path, "0.1.13_001", sec)
    assert hotpatch.apply_patch(**patch) == "0.1.13_001"
    assert hotpatch.frontend_version() == "0.1.13_001"
    assert hotpatch.previous_version() is None
    assert (hotpatch_dirs / "index.html").exists()


def test_apply_keeps_previous_and_rolls_back(hotpatch_dirs, patch_key, tmp_path):
    _pub, sec = patch_key
    hotpatch.apply_patch(**_signed_patch(tmp_path, "0.1.13_001", sec))
    hotpatch.apply_patch(**_signed_patch(tmp_path, "0.1.13_002", sec))
    assert hotpatch.frontend_version() == "0.1.13_002"
    assert hotpatch.previous_version() == "0.1.13_001"
    assert hotpatch.rollback_patch() == "0.1.13_001"
    assert hotpatch.frontend_version() == "0.1.13_001"
    assert hotpatch.previous_version() is None
    assert hotpatch.rollback_patch() is None


def test_apply_rejects_bad_checksum(hotpatch_dirs, patch_key, tmp_path):
    _pub, sec = patch_key
    patch = _signed_patch(tmp_path, "0.1.13_001", sec)
    patch["sha256"] = "0" * 64
    with pytest.raises(HotpatchError, match="checksum mismatch"):
        hotpatch.apply_patch(**patch)
    assert hotpatch.frontend_version() is None


def test_apply_rejects_bad_signature(hotpatch_dirs, patch_key, tmp_path):
    _other_pub, other_sec = minisign.generate_keypair()
    patch = _signed_patch(tmp_path, "0.1.13_001", other_sec)
    with pytest.raises(HotpatchError, match="signature invalid"):
        hotpatch.apply_patch(**patch)
    assert hotpatch.frontend_version() is None


def test_apply_rejects_stable_and_mismatched_versions(hotpatch_dirs, patch_key, tmp_path):
    _pub, sec = patch_key
    stable = _signed_patch(tmp_path, "0.1.13_001", sec)
    stable["version"] = "0.1.14"
    with pytest.raises(HotpatchError, match="only nightly"):
        hotpatch.apply_patch(**stable)
    mismatch = _signed_patch(tmp_path, "0.1.13_001", sec)
    mismatch["version"] = "0.1.13_002"
    with pytest.raises(HotpatchError, match="do not match"):
        hotpatch.apply_patch(**mismatch)
    with pytest.raises(HotpatchError, match="invalid patch version"):
        hotpatch.apply_patch("garbage", mismatch["url"], mismatch["sha256"], mismatch["signature"])
    assert hotpatch.frontend_version() is None


def test_apply_rejects_insecure_urls_and_zip_slip(hotpatch_dirs, patch_key, tmp_path):
    _pub, sec = patch_key
    patch = _signed_patch(tmp_path, "0.1.13_001", sec)
    patch["url"] = "http://example.test/patch.zip"
    with pytest.raises(HotpatchError, match="must use https"):
        hotpatch.apply_patch(**patch)
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr("../evil.html", "x")
        archive.writestr("index.html", "<html></html>")
        archive.writestr("version.json", json.dumps({"version": "0.1.13_001"}))
    evil_patch = {
        "version": "0.1.13_001",
        "url": evil.as_uri(),
        "sha256": hashlib.sha256(evil.read_bytes()).hexdigest(),
        "signature": minisign.sign_message(sec, evil.read_bytes()),
    }
    with pytest.raises(HotpatchError, match="unsafe path"):
        hotpatch.apply_patch(**evil_patch)
    assert hotpatch.frontend_version() is None


async def test_apply_and_rollback_endpoints(monkeypatch, tmp_path):
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "settings.json")
    root = tmp_path / "hotpatch" / "frontend"
    (root / "current").mkdir(parents=True)
    monkeypatch.setattr(hotpatch, "FRONTEND_DIR", root)
    monkeypatch.setattr(hotpatch, "FRONTEND_CURRENT", root / "current")
    monkeypatch.setattr(hotpatch, "FRONTEND_PREVIOUS", root / "previous")
    monkeypatch.setattr(hotpatch, "FRONTEND_STAGING", root / "staging")
    monkeypatch.setattr(hotpatch, "FRONTEND_VERSION_FILE", root / "current" / "version.json")
    pub, sec = minisign.generate_keypair()
    monkeypatch.setattr(hotpatch, "PATCH_PUBKEY", pub)
    patch = _signed_patch(tmp_path, "0.1.13_005", sec)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/hotpatch/apply", json=patch)
        assert res.status_code == 200, res.text
        assert res.json()["frontend_version"] == "0.1.13_005"
        bad = dict(patch, sha256="0" * 64)
        res = await client.post("/api/v1/hotpatch/apply", json=bad)
        assert res.status_code == 400
        res = await client.post("/api/v1/hotpatch/rollback")
        assert res.status_code == 404
        patch2 = _signed_patch(tmp_path, "0.1.13_006", sec)
        res = await client.post("/api/v1/hotpatch/apply", json=patch2)
        assert res.status_code == 200
        res = await client.post("/api/v1/hotpatch/rollback")
        assert res.status_code == 200
        assert res.json()["frontend_version"] == "0.1.13_005"
