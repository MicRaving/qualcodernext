"""build-patch.py unit tests — file manifests, diffs, native zips.

Imports the script as a module (its `__main__` guard keeps `main()` from
running); `runpy`-based end-to-end coverage lives in test_hotpatch_e2e.py.
"""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent / "scripts" / "build-patch.py"
)


@pytest.fixture
def build_patch():
    spec = importlib.util.spec_from_file_location("build_patch", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_dist(root: Path, files: dict[str, str]) -> Path:
    dist = root / "dist"
    for relpath, content in files.items():
        target = dist / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return dist


def test_manifest_and_diff_roundtrip(build_patch, tmp_path):
    old_dist = _seed_dist(
        tmp_path / "old", {"a.dll": "v1", "b.pyd": "same", "gone.txt": "x"}
    )
    new_dist = _seed_dist(
        tmp_path / "new", {"a.dll": "v2", "b.pyd": "same", "added.txt": "y"}
    )
    old = build_patch.build_backend_files_manifest(old_dist)
    new = build_patch.build_backend_files_manifest(new_dist)
    changed, deleted = build_patch.diff_backend_files(old, new)
    assert [c["path"] for c in changed] == ["a.dll", "added.txt"]
    assert deleted == ["gone.txt"]
    assert changed[0]["size"] == len(b"v2")
    # Identical manifests diff empty.
    assert build_patch.diff_backend_files(old, old) == ([], [])


def test_native_zip_layout_and_determinism(build_patch, tmp_path):
    dist = _seed_dist(tmp_path / "dist", {"sub/a.dll": "v2", "b.pyd": "same"})
    changed = [
        {"path": "sub/a.dll", "size": 2, "sha256": "x"},
        {"path": "b.pyd", "size": 4, "sha256": "y"},
    ]
    out = tmp_path / "out"
    out.mkdir()
    zip_a, digest_a = build_patch.build_native_zip(
        "0.1.13_002", "0.1.13_001", dist, changed, ["gone.txt"], out
    )
    _zip_b, digest_b = build_patch.build_native_zip(
        "0.1.13_002", "0.1.13_001", dist, changed, ["gone.txt"], out
    )
    assert digest_a == digest_b
    with zipfile.ZipFile(zip_a) as archive:
        assert sorted(archive.namelist()) == ["b.pyd", "delta.json", "sub/a.dll"]
        delta = json.loads(archive.read("delta.json"))
        assert delta == {
            "from": "0.1.13_001",
            "to": "0.1.13_002",
            "files": changed,
            "deleted": ["gone.txt"],
        }
    with pytest.raises(SystemExit, match="unsafe delta path"):
        build_patch.build_native_zip(
            "0.1.13_002",
            "0.1.13_001",
            dist,
            [{"path": "../evil", "size": 1, "sha256": "x"}],
            [],
            out,
        )


def test_load_files_manifest_rejects_garbage(build_patch, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"nope": 1}), encoding="utf-8")
    with pytest.raises(SystemExit, match="not a backend-files manifest"):
        build_patch.load_files_manifest(str(bad))


def test_verify_base_matches_tree(build_patch, tmp_path):
    root = tmp_path / "repo"
    (root / "frontend" / "src-tauri").mkdir(parents=True)
    (root / "backend" / "src" / "qualcoder_api" / "core").mkdir(parents=True)
    (root / "frontend" / "src-tauri" / "tauri.conf.json").write_text(
        json.dumps({"version": "0.1.16"}), encoding="utf-8"
    )
    (root / "frontend" / "package.json").write_text(
        json.dumps({"version": "0.1.16"}), encoding="utf-8"
    )
    (root / "frontend" / "src-tauri" / "Cargo.toml").write_text(
        '[package]\nname = "qcnext"\nversion = "0.1.16"\n', encoding="utf-8"
    )
    (root / "backend" / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.1.16"\n', encoding="utf-8"
    )
    (root / "backend" / "src" / "qualcoder_api" / "core" / "__init__.py").write_text(
        'APP_VERSION = "0.1.16"\n', encoding="utf-8"
    )
    # Matching base passes silently.
    assert build_patch.verify_base_matches_tree("0.1.16", root) is None
    # Any drift fails loud, naming the offenders.
    (root / "frontend" / "package.json").write_text(
        json.dumps({"version": "0.1.15"}), encoding="utf-8"
    )
    with pytest.raises(SystemExit, match=r"package\.json"):
        build_patch.verify_base_matches_tree("0.1.16", root)
    # And against the real tree right now (whatever base it carries — the
    # test must survive release bumps without edits).
    real_base = build_patch.tree_versions()["tauri.conf.json"]
    assert real_base, "real tree has no parsable base version"
    assert build_patch.verify_base_matches_tree(real_base) is None
