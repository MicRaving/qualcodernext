"""Nightly pipeline end-to-end: build-patch.py → manifest → apply_patch.

Uses a fixture SPA and an ephemeral signing key (never the real release
key) to prove the whole chain — deterministic zip, signature, manifest,
download, verify, activate — without network or the 3 MB real dist.
"""

from __future__ import annotations

import json
import runpy
import sys

import pytest

from qualcoder_api.services import hotpatch, minisign


@pytest.fixture
def fixture_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>nightly fixture</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return dist


def test_build_sign_and_apply_roundtrip(monkeypatch, tmp_path, fixture_dist):
    pub, sec = minisign.generate_keypair()
    key_file = tmp_path / "patch.key"
    key_file.write_text(sec, encoding="utf-8")
    out = tmp_path / "out"

    argv = [
        "build-patch.py",
        "--version", "0.1.13_007",
        "--frontend-dist", str(fixture_dist),
        "--out", str(out),
        "--notes", "e2e fixture",
        "--sign-key", str(key_file),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    # Resolve the script relative to this test file (robust to cwd).
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "build-patch.py"
    # The script ends with sys.exit(main()) — SystemExit(0) means success.
    with pytest.raises(SystemExit) as exit:
        runpy.run_path(str(script), run_name="__main__")
    assert exit.value.code == 0

    manifest = json.loads((out / "qcnext-nightly.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.1.13_007"
    assert manifest["base"] == "0.1.13"
    # The install floor always equals the base: deltas never cross bases.
    assert manifest["min_base"] == "0.1.13"
    assert manifest["signature"], "signed builds must carry a signature"

    root = tmp_path / "hotpatch" / "frontend"
    (root / "current").mkdir(parents=True)
    monkeypatch.setattr(hotpatch, "FRONTEND_DIR", root)
    monkeypatch.setattr(hotpatch, "FRONTEND_CURRENT", root / "current")
    monkeypatch.setattr(hotpatch, "FRONTEND_PREVIOUS", root / "previous")
    monkeypatch.setattr(hotpatch, "FRONTEND_STAGING", root / "staging")
    monkeypatch.setattr(hotpatch, "FRONTEND_VERSION_FILE", root / "current" / "version.json")
    monkeypatch.setattr(hotpatch, "PATCH_PUBKEY", pub)

    zip_path = out / "qcnext-frontend-0.1.13_007.zip"
    assert hotpatch.apply_patch(
        version=manifest["version"],
        url=zip_path.as_uri(),
        sha256=manifest["sha256"],
        signature=manifest["signature"],
    ) == "0.1.13_007"
    assert hotpatch.frontend_version() == "0.1.13_007"
    assert (root / "current" / "assets" / "app.js").exists()


def test_build_with_backend_section(monkeypatch, tmp_path, fixture_dist):
    from pathlib import Path

    from qualcoder_api.services import overlay

    pub, sec = minisign.generate_keypair()
    key_file = tmp_path / "patch.key"
    key_file.write_text(sec, encoding="utf-8")
    backend_src = tmp_path / "bsrc"
    (backend_src / "qualcoder_api").mkdir(parents=True)
    (backend_src / "qualcoder_api" / "__init__.py").write_text('APP_VERSION = "x"\n', encoding="utf-8")
    out = tmp_path / "out"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build-patch.py",
            "--version", "0.1.13_008",
            "--frontend-dist", str(fixture_dist),
            "--backend-src", str(backend_src),
            "--with-backend",
            "--out", str(out),
            "--sign-key", str(key_file),
        ],
    )
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "build-patch.py"
    with pytest.raises(SystemExit) as exit:
        runpy.run_path(str(script), run_name="__main__")
    assert exit.value.code == 0

    manifest = json.loads((out / "qcnext-nightly.json").read_text(encoding="utf-8"))
    assert manifest["kind"] == "both"
    backend = manifest["backend"]
    assert backend["signature"], "backend section must be signed"

    root = tmp_path / "patches"
    (root / "current").mkdir(parents=True)
    monkeypatch.setattr(overlay, "PATCHES_ROOT", root)
    monkeypatch.setattr(overlay, "OVERLAY_CURRENT", root / "current")
    monkeypatch.setattr(overlay, "OVERLAY_PREVIOUS", root / "previous")
    monkeypatch.setattr(overlay, "OVERLAY_STAGING", root / "staging")
    monkeypatch.setattr(hotpatch, "PATCH_PUBKEY", pub)

    zip_path = out / "qcnext-backend-0.1.13_008.zip"
    assert overlay.apply_overlay(
        version=manifest["version"],
        url=zip_path.as_uri(),
        sha256=backend["sha256"],
        signature=backend["signature"],
    ) == "0.1.13_008"
    assert overlay.overlay_version() == "0.1.13_008"
