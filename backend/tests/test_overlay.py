"""Backend-overlay tests — staged Python patches (restart to activate).

Overlay directories live under `~/.qualcoder/patches/`; every test
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
from qualcoder_api.services import minisign, overlay
from qualcoder_api.services.hotpatch import HotpatchError


@pytest.fixture
def overlay_dirs(monkeypatch, tmp_path):
    root = tmp_path / "patches"
    current = root / "current"
    current.mkdir(parents=True)
    monkeypatch.setattr(overlay, "PATCHES_ROOT", root)
    monkeypatch.setattr(overlay, "OVERLAY_CURRENT", current)
    monkeypatch.setattr(overlay, "OVERLAY_PREVIOUS", root / "previous")
    monkeypatch.setattr(overlay, "OVERLAY_STAGING", root / "staging")
    return current


@pytest.fixture
def overlay_key(monkeypatch):
    from qualcoder_api.services import hotpatch

    pub, sec = minisign.generate_keypair()
    monkeypatch.setattr(hotpatch, "PATCH_PUBKEY", pub)
    return pub, sec


def _make_overlay_zip(dest: Path, version: str) -> Path:
    zip_path = dest / f"qcnext-backend-{version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("qualcoder_api/__init__.py", 'APP_VERSION = "x"\n')
        archive.writestr("version.json", json.dumps({"version": version}))
    return zip_path


def _signed_overlay(tmp_path: Path, version: str, sec: str) -> dict[str, str]:
    zip_path = _make_overlay_zip(tmp_path, version)
    payload = zip_path.read_bytes()
    return {
        "version": version,
        "url": zip_path.as_uri(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "signature": minisign.sign_message(sec, payload),
    }


def test_overlay_dir_default_and_override(monkeypatch, tmp_path):
    monkeypatch.delenv("QC_OVERLAY_DIR", raising=False)
    assert overlay.overlay_dir() == overlay.OVERLAY_CURRENT
    monkeypatch.setenv("QC_OVERLAY_DIR", str(tmp_path / "custom"))
    assert overlay.overlay_dir() == tmp_path / "custom"


def test_apply_overlay_stages_package(overlay_dirs, overlay_key, tmp_path):
    _pub, sec = overlay_key
    assert overlay.apply_overlay(**_signed_overlay(tmp_path, "0.1.13_001", sec)) == "0.1.13_001"
    assert overlay.overlay_version() == "0.1.13_001"
    assert overlay.overlay_previous_version() is None
    assert (overlay_dirs / "qualcoder_api" / "__init__.py").exists()


def test_apply_overlay_requires_package(overlay_dirs, overlay_key, tmp_path):
    # Sign with the trusted test key but ship no package tree.
    _trusted_pub, trusted_sec = overlay_key
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr("version.json", json.dumps({"version": "0.1.13_001"}))
    payload = empty.read_bytes()
    with pytest.raises(HotpatchError, match=r"do not match|incomplete|package"):
        overlay.apply_overlay(
            version="0.1.13_001",
            url=empty.as_uri(),
            sha256=hashlib.sha256(payload).hexdigest(),
            signature=minisign.sign_message(trusted_sec, payload),
        )
    assert overlay.overlay_version() is None


def test_apply_overlay_keeps_previous_and_rolls_back(overlay_dirs, overlay_key, tmp_path):
    _pub, sec = overlay_key
    overlay.apply_overlay(**_signed_overlay(tmp_path, "0.1.13_001", sec))
    overlay.apply_overlay(**_signed_overlay(tmp_path, "0.1.13_002", sec))
    assert overlay.overlay_version() == "0.1.13_002"
    assert overlay.overlay_previous_version() == "0.1.13_001"
    assert overlay.rollback_overlay() == "0.1.13_001"
    assert overlay.overlay_previous_version() is None
    assert overlay.rollback_overlay() is None


def test_apply_overlay_rejects_bad_signature(overlay_dirs, overlay_key, tmp_path):
    _other_pub, other_sec = minisign.generate_keypair()
    patch = _signed_overlay(tmp_path, "0.1.13_001", other_sec)
    with pytest.raises(HotpatchError, match="signature invalid"):
        overlay.apply_overlay(**patch)
    assert overlay.overlay_version() is None


async def test_overlay_endpoints(monkeypatch, tmp_path):
    root = tmp_path / "patches"
    (root / "current").mkdir(parents=True)
    monkeypatch.setattr(overlay, "PATCHES_ROOT", root)
    monkeypatch.setattr(overlay, "OVERLAY_CURRENT", root / "current")
    monkeypatch.setattr(overlay, "OVERLAY_PREVIOUS", root / "previous")
    monkeypatch.setattr(overlay, "OVERLAY_STAGING", root / "staging")
    from qualcoder_api.services import hotpatch as hotpatch_module

    pub, sec = minisign.generate_keypair()
    monkeypatch.setattr(hotpatch_module, "PATCH_PUBKEY", pub)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/patches/version")
        assert res.status_code == 200
        assert res.json()["overlay_version"] is None
        patch = _signed_overlay(tmp_path, "0.1.13_009", sec)
        res = await client.post("/api/v1/patches/apply", json=patch)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["overlay_version"] == "0.1.13_009"
        assert body["overlay_active"] is False
        bad = dict(patch, sha256="0" * 64)
        res = await client.post("/api/v1/patches/apply", json=bad)
        assert res.status_code == 400
        res = await client.post("/api/v1/patches/rollback")
        assert res.status_code == 404


def test_overlay_origin_detection(monkeypatch, tmp_path):
    import qualcoder_api.services.overlay as overlay_module
    from qualcoder_api.api.v1 import router as router_module

    fake_root = tmp_path / "patches"
    monkeypatch.setattr(overlay, "PATCHES_ROOT", fake_root)
    monkeypatch.setattr(
        overlay_module,
        "__file__",
        str(fake_root / "current" / "qualcoder_api" / "services" / "overlay.py"),
    )
    assert router_module._overlay_module_origin() == "overlay"
    monkeypatch.setattr(overlay_module, "__file__", "/elsewhere/overlay.py")
    assert router_module._overlay_module_origin() == "frozen"
