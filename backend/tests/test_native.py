"""Native-delta tests — staging rolls (shell applies at boot).

Native directories live under `~/.qualcoder/hotpatch/native/`; every test
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
from qualcoder_api.services import minisign, native
from qualcoder_api.services.hotpatch import HotpatchError


@pytest.fixture
def native_dirs(monkeypatch, tmp_path):
    root = tmp_path / "native"
    (root / "staged").mkdir(parents=True)
    monkeypatch.setattr(native, "NATIVE_ROOT", root)
    monkeypatch.setattr(native, "NATIVE_STAGED", root / "staged")
    monkeypatch.setattr(native, "NATIVE_PREV", root / "prev")
    monkeypatch.setattr(native, "NATIVE_PLAN", root / "plan.json")
    monkeypatch.setattr(native, "NATIVE_APPLIED", root / "applied.json")
    return root


@pytest.fixture
def native_key(monkeypatch):
    from qualcoder_api.services import hotpatch

    pub, sec = minisign.generate_keypair()
    monkeypatch.setattr(hotpatch, "PATCH_PUBKEY", pub)
    return pub, sec


def _make_delta_zip(
    dest: Path, name: str, from_version: str, to_version: str, files: dict[str, str]
) -> Path:
    zip_path = dest / name
    entries = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for relpath, content in files.items():
            data = content.encode("utf-8")
            archive.writestr(relpath, data)
            entries.append(
                {
                    "path": relpath,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        archive.writestr(
            "delta.json",
            json.dumps({"from": from_version, "to": to_version, "files": entries, "deleted": []}),
        )
    return zip_path


def _signed_delta(tmp_path: Path, from_version: str, to_version: str, sec: str) -> dict:
    zip_path = _make_delta_zip(
        tmp_path, f"qcnext-native-{to_version}.zip", from_version, to_version, {"a.dll": "v2"}
    )
    payload = zip_path.read_bytes()
    return {
        "version": to_version,
        "from_version": from_version,
        "url": zip_path.as_uri(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "signature": minisign.sign_message(sec, payload),
        "size": len(payload),
    }


def test_stage_writes_plan(native_dirs, native_key, tmp_path, monkeypatch):
    _pub, sec = native_key
    monkeypatch.setattr(native, "bundle_base_version", lambda: "0.1.13")
    status = native.stage_native(
        **_signed_delta(tmp_path, "0.1.13", "0.1.13_001", sec)
    )
    assert status["staged"] == "0.1.13_001"
    assert status["pointer"] == "0.1.13"
    plan = json.loads((native_dirs / "plan.json").read_text(encoding="utf-8"))
    assert plan == {"action": "apply", "version": "0.1.13_001"}
    assert (native_dirs / "staged" / "a.dll").exists()
    assert (native_dirs / "staged" / "patch.zip").exists() is False


def test_stage_enforces_exact_chaining(native_dirs, native_key, tmp_path, monkeypatch):
    _pub, sec = native_key
    monkeypatch.setattr(native, "bundle_base_version", lambda: "0.1.13")
    patch = _signed_delta(tmp_path, "0.1.12", "0.1.13_001", sec)
    with pytest.raises(HotpatchError, match=r"chains onto 0\.1\.12"):
        native.stage_native(**patch)
    assert native.staged_version() is None


def test_stage_rejects_oversize_and_bad_signature(
    native_dirs, native_key, tmp_path, monkeypatch
):
    _pub, sec = native_key
    monkeypatch.setattr(native, "bundle_base_version", lambda: "0.1.13")
    patch = _signed_delta(tmp_path, "0.1.13", "0.1.13_001", sec)
    patch["size"] = native.NATIVE_DELTA_MAX_BYTES + 1
    with pytest.raises(HotpatchError, match="too large"):
        native.stage_native(**patch)
    patch["size"] = 10
    _other_pub, other_sec = minisign.generate_keypair()
    evil = _make_delta_zip(tmp_path, "evil.zip", "0.1.13", "0.1.13_001", {"a.dll": "evil"})
    payload = evil.read_bytes()
    patch.update(
        url=evil.as_uri(),
        sha256=hashlib.sha256(payload).hexdigest(),
        signature=minisign.sign_message(other_sec, payload),
    )
    with pytest.raises(HotpatchError, match="signature invalid"):
        native.stage_native(**patch)
    assert native.staged_version() is None


def test_rollback_queues_restore_only_when_active(native_dirs, tmp_path):
    assert native.rollback_native() is None
    (native_dirs / "applied.json").write_text(
        json.dumps({"from": "0.1.13", "to": "0.1.13_001", "previous_to": None}),
        encoding="utf-8",
    )
    status = native.rollback_native()
    assert status is not None
    plan = json.loads((native_dirs / "plan.json").read_text(encoding="utf-8"))
    assert plan == {"action": "restore", "version": "0.1.13_001"}


async def test_native_endpoints(monkeypatch, tmp_path):
    root = tmp_path / "native"
    (root / "staged").mkdir(parents=True)
    monkeypatch.setattr(native, "NATIVE_ROOT", root)
    monkeypatch.setattr(native, "NATIVE_STAGED", root / "staged")
    monkeypatch.setattr(native, "NATIVE_PREV", root / "prev")
    monkeypatch.setattr(native, "NATIVE_PLAN", root / "plan.json")
    monkeypatch.setattr(native, "NATIVE_APPLIED", root / "applied.json")
    monkeypatch.setattr(native, "bundle_base_version", lambda: "0.1.13")
    from qualcoder_api.services import hotpatch as hotpatch_module

    pub, sec = minisign.generate_keypair()
    monkeypatch.setattr(hotpatch_module, "PATCH_PUBKEY", pub)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/native/version")
        assert res.status_code == 200
        assert res.json()["pointer"] == "0.1.13"
        patch = _signed_delta(tmp_path, "0.1.13", "0.1.13_004", sec)
        res = await client.post("/api/v1/native/apply", json=patch)
        assert res.status_code == 200, res.text
        assert res.json()["staged"] == "0.1.13_004"
        res = await client.post("/api/v1/native/rollback")
        assert res.status_code == 404
        (root / "applied.json").write_text(
            json.dumps({"from": "0.1.13", "to": "0.1.13_004", "previous_to": None}),
            encoding="utf-8",
        )
        res = await client.post("/api/v1/native/rollback")
        assert res.status_code == 200
