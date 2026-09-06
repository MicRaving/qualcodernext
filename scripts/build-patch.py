#!/usr/bin/env python3
"""Build a nightly delta patch (`X.Y.Z_NNN`) from the Vite frontend build.

A nightly is a small signed zip of `frontend/dist` that the packaged app
downloads when the user opts into Settings → Updates → Channel: Nightly.
The backend serves the installed patch at `/` (see `main._mount_hotpatch_spa`)
and the Tauri shell navigates to it — no installer, no app restart.

Usage (from the repo root):
    python scripts/build-patch.py --version 0.1.13_001
    python scripts/build-patch.py --version 0.1.13_001 --notes "Fixed sync chip."
    python scripts/build-patch.py --version 0.1.13_002 --with-backend --notes "Sync fix."

Output (in `--out`, default `dist-patches/`):
    qcnext-frontend-0.1.13_001.zip        # deterministic zip of dist + version.json
    qcnext-frontend-0.1.13_001.zip.sha256
    qcnext-nightly.json                   # manifest the app polls (upload to the
                                          # rolling `nightly` GitHub release)
    [with --with-backend]
    qcnext-backend-0.1.13_001.zip         # restart-to-activate Python overlay
    qcnext-backend-0.1.13_001.zip.sha256
    [with --backend-dist + --backend-files-from]
    qcnext-native-0.1.13_001.zip          # boot-applied native-file delta
    qcnext-native-0.1.13_001.zip.sha256
    backend-files-0.1.13_001.json         # per-file manifest (accumulates per
                                          # version; never clobbered)

Publish: upload all three assets to the `nightly` tag release
(`gh release upload nightly dist-patches/* --clobber`). The app fetches
`.../releases/download/nightly/qcnext-nightly.json` (see
`frontend/src/stores/updates.ts: NIGHTLY_MANIFEST_URL`).

Versioning: `tauri.conf.json` / `Cargo.toml` / `package.json` keep the BASE
semver (`0.1.13`); only the patch zip + manifest carry `_001`. Tauri/Cargo
reject `_` suffixes, so never write the full nightly into those files.

Signing: pass `--sign-key updater.key` (the same unencrypted minisign key
as the Tauri updater) or set `PATCH_SIGN_KEY_FILE`. The manifest carries
the signature and the backend refuses unsigned patches — an unsigned
manifest is only useful for local smoke tests.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path

NIGHTLY_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)_(\d{1,5})$")
REPO_SLUG = "MicRaving/qualcodernext"
ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT / "backend" / "src"))
from qualcoder_api.services import minisign  # noqa: E402  (script reuses the backend signer)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a nightly frontend delta patch.")
    parser.add_argument("--version", required=False, default="", help="Nightly version, e.g. 0.1.13_001")
    parser.add_argument(
        "--frontend-dist",
        default=str(ROOT / "frontend" / "dist"),
        help="Vite build output directory (run `npm run build` first)",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "dist-patches"),
        help="Output directory for the zip + manifest",
    )
    parser.add_argument("--notes", default="", help="Short patch notes for the manifest")
    parser.add_argument(
        "--sign-key",
        default=os.environ.get("PATCH_SIGN_KEY_FILE", ""),
        help="Minisign secret key file (same key as the Tauri updater; "
        "unencrypted only). Falls back to $PATCH_SIGN_KEY_FILE. Omit for an "
        "unsigned local smoke build (the backend will refuse to install it).",
    )
    parser.add_argument(
        "--tag",
        default="nightly",
        help="Rolling GitHub release tag hosting the manifest (default: nightly)",
    )
    parser.add_argument(
        "--with-backend",
        action="store_true",
        help="Also package backend/src/qualcoder_api as a restart-to-activate "
        "overlay (qcnext-backend-<version>.zip + manifest 'backend' section).",
    )
    parser.add_argument(
        "--backend-src",
        default=str(ROOT / "backend" / "src"),
        help="Backend source root containing qualcoder_api/ (with --with-backend)",
    )
    parser.add_argument(
        "--backend-dist",
        default="",
        help="Built backend onedir dir (backend/dist/qualcoder-backend) — with "
        "--backend-files-from, emits a boot-applied native-file delta "
        "(qcnext-native-<version>.zip + manifest 'native' section).",
    )
    parser.add_argument(
        "--backend-files-from",
        default="",
        help="Previous backend-files-*.json (path or https URL) to diff "
        "--backend-dist against. The matching installed version must equal "
        "the client's backend bundle version.",
    )
    parser.add_argument(
        "--check-key",
        action="store_true",
        help="Validate the signing key against updater.key.pub and exit "
        "(fast CI preflight before the slow builds). Prints only a keynum "
        "and public-key fingerprint — never key material.",
    )
    return parser.parse_args()


def check_signing_key(sign_key: str) -> int:
    """Validate the secret key matches the repo public key. Prints metadata only."""
    if not sign_key:
        print("error: no signing key (--sign-key or $PATCH_SIGN_KEY_FILE)")
        return 2
    try:
        pub_text = (ROOT / "updater.key.pub").read_text(encoding="utf-8")
        exp_keynum, exp_pub = minisign.parse_pubkey(pub_text)
        keynum, seed = minisign.parse_secret_key(
            Path(sign_key).read_text(encoding="utf-8"), keynum_hint=exp_keynum
        )
    except (OSError, ValueError) as err:
        print(f"error: unusable signing key: {err}")
        return 2
    if minisign.ed25519_pubkey(seed) != exp_pub or keynum != exp_keynum:
        print("error: signing key does not match updater.key.pub")
        return 2
    fingerprint = hashlib.sha256(exp_pub).hexdigest()[:16]
    print(f"signing key OK (keynum {exp_keynum[::-1].hex().upper()}, pubkey {fingerprint}…)")
    return 0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


#: Source-tree entries that must never ship in a patch (caches, bytecode).
_SKIP_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def _collect_tree(root: Path, arc_prefix: str = "") -> list[tuple[str, Path]]:
    """Sorted ``(arcname, path)`` files under ``root``, minus caches/bytecode."""
    entries: list[tuple[str, Path]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in _SKIP_NAMES for part in rel.parts):
            continue
        if path.suffix in (".pyc", ".pyo"):
            continue
        arcname = f"{arc_prefix}{rel.as_posix()}" if arc_prefix else rel.as_posix()
        entries.append((arcname, path))
    return entries


def _write_deterministic(
    archive: zipfile.ZipFile, arcname: str, data: bytes
) -> None:
    info = zipfile.ZipInfo(filename=arcname, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def build_frontend_zip(version: str, dist: Path, out: Path) -> tuple[Path, str]:
    files = sorted(p for p in dist.rglob("*") if p.is_file())
    if not (dist / "index.html").exists():
        raise SystemExit(f"frontend dist has no index.html: {dist} (run `npm run build` first)")
    zip_path = out / f"qcnext-frontend-{version}.zip"
    # Deterministic: sorted entries, fixed timestamp, unix perms.
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            _write_deterministic(
                archive, str(path.relative_to(dist)).replace("\\", "/"), path.read_bytes()
            )
        _write_deterministic(
            archive, "version.json", json.dumps({"version": version}, indent=2) + "\n"
        )
    digest = sha256_file(zip_path)
    (out / f"{zip_path.name}.sha256").write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    return zip_path, digest


def build_backend_zip(version: str, src_root: Path, out: Path) -> tuple[Path, str]:
    """Zip the pure-Python ``qualcoder_api`` tree for a backend overlay.

    Native dependencies stay frozen — the overlay only carries sources, so
    a patch needing new native deps must ship as a full release instead.
    """
    package = src_root / "qualcoder_api"
    if not (package / "__init__.py").exists():
        raise SystemExit(f"backend sources not found under {src_root} (expected qualcoder_api/)")
    zip_path = out / f"qcnext-backend-{version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for arcname, path in _collect_tree(src_root):
            if not arcname.startswith("qualcoder_api/"):
                continue
            _write_deterministic(archive, arcname, path.read_bytes())
        _write_deterministic(
            archive, "version.json", json.dumps({"version": version}, indent=2) + "\n"
        )
    digest = sha256_file(zip_path)
    (out / f"{zip_path.name}.sha256").write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    return zip_path, digest


def hash_file(path: Path) -> tuple[str, int]:
    """SHA-256 hex digest + size of a file (streamed, arbitrary size)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest(), path.stat().st_size


def build_backend_files_manifest(dist_dir: Path) -> dict[str, dict[str, object]]:
    """Per-file ``{relpath: {sha256, size}}`` manifest of a built onedir."""
    if not dist_dir.is_dir():
        raise SystemExit(f"backend onedir not found: {dist_dir}")
    files: dict[str, dict[str, object]] = {}
    for arcname, path in _collect_tree(dist_dir):
        sha256, size = hash_file(path)
        files[arcname] = {"sha256": sha256, "size": size}
    return {"files": files}


def diff_backend_files(
    old: dict[str, dict[str, object]], new: dict[str, dict[str, object]]
) -> tuple[list[dict[str, object]], list[str]]:
    """Diff two file manifests → ``(changed[{path,size,sha256}], deleted[paths])``."""
    old_files = old.get("files", {})
    new_files = new.get("files", {})
    changed = [
        {"path": path, "size": meta["size"], "sha256": meta["sha256"]}
        for path, meta in sorted(new_files.items())
        if old_files.get(path) != meta
    ]
    deleted = sorted(path for path in old_files if path not in new_files)
    return changed, deleted


def build_native_zip(
    version: str,
    from_version: str,
    dist_dir: Path,
    changed: list[dict[str, object]],
    deleted: list[str],
    out: Path,
) -> tuple[Path, str]:
    """Zip changed onedir files + ``delta.json`` for a boot-applied delta.

    Contents always come from the freshly built ``dist_dir`` (the target
    state); ``changed``/``deleted`` come from diffing manifests, so each
    delta chains exactly onto its stated predecessor (no restore gaps).
    """
    zip_path = out / f"qcnext-native-{version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for entry in changed:
            relpath = str(entry["path"])
            if relpath.startswith(("/", "\\")) or ".." in Path(relpath).parts:
                raise SystemExit(f"unsafe delta path: {relpath!r}")
            source = dist_dir / relpath
            _write_deterministic(archive, relpath, source.read_bytes())
        _write_deterministic(
            archive,
            "delta.json",
            json.dumps(
                {"from": from_version, "to": version, "files": changed, "deleted": deleted},
                indent=2,
            )
            + "\n",
        )
    digest = sha256_file(zip_path)
    (out / f"{zip_path.name}.sha256").write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    return zip_path, digest


def load_files_manifest(source: str) -> dict:
    """Load a backend-files manifest from a local path or https URL."""
    text: str
    if source.startswith("https://"):
        import urllib.request

        request = urllib.request.Request(source, headers={"User-Agent": "QCnext-build-patch/1"})
        with urllib.request.urlopen(request, timeout=60) as response:
            text = response.read().decode("utf-8")
    else:
        text = Path(source).read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise SystemExit(f"not a backend-files manifest: {source}")
    return data


def main() -> int:
    args = parse_args()
    if args.check_key:
        return check_signing_key(args.sign_key)
    if not args.version:
        print("error: --version is required (e.g. 0.1.13_001)")
        return 2
    match = NIGHTLY_RE.match(args.version.strip())
    if not match:
        print(f"error: --version must be X.Y.Z_NNN (e.g. 0.1.13_001), got {args.version!r}")
        return 2
    version = args.version.strip()
    base = f"{match.group(1)}.{match.group(2)}.{match.group(3)}"
    dist = Path(args.frontend_dist)
    if not dist.is_dir():
        print(f"error: frontend dist not found: {dist}")
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    zip_path, digest = build_frontend_zip(version, dist, out)
    zip_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"wrote {zip_path.name} ({zip_mb:.2f} MB, sha256 {digest[:12]}…)")

    backend_section: dict[str, str] = {}
    if args.with_backend:
        backend_zip, backend_digest = build_backend_zip(version, Path(args.backend_src), out)
        backend_mb = backend_zip.stat().st_size / (1024 * 1024)
        print(f"wrote {backend_zip.name} ({backend_mb:.2f} MB, sha256 {backend_digest[:12]}…)")
        backend_section = {
            "url": (
                f"https://github.com/{REPO_SLUG}/releases/download/{args.tag}/{backend_zip.name}"
            ),
            "sha256": backend_digest,
            "signature": "",
            "size": backend_zip.stat().st_size,
        }

    def _sign(payload: bytes) -> str:
        if not args.sign_key:
            return ""
        key_text = Path(args.sign_key).read_text(encoding="utf-8")
        return minisign.sign_message(key_text, payload)

    payload = zip_path.read_bytes()
    signature = _sign(payload)
    if backend_section:
        backend_section["signature"] = _sign((out / f"qcnext-backend-{version}.zip").read_bytes())

    # Native-file delta: diff the fresh onedir against the stated
    # predecessor manifest. The predecessor's post-apply file manifest
    # (backend-files-<from>.json) is the exact chaining point — each delta
    # applies onto its predecessor only, so restores can never strand files.
    # The target-state files manifest is always published (never clobbered)
    # as the next run's predecessor.
    native_section: dict[str, object] = {}
    current_files = (
        build_backend_files_manifest(Path(args.backend_dist)) if args.backend_dist else None
    )
    if current_files is not None:
        files_out = out / f"backend-files-{version}.json"
        files_out.write_text(
            json.dumps({"version": version, "files": current_files["files"]}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {files_out.name} ({len(current_files['files'])} files)")
    if current_files is not None and args.backend_files_from:
        from_manifest = load_files_manifest(args.backend_files_from)
        from_version = from_manifest.get("version")
        # Stable baselines carry a base semver instead of a nightly.
        if not (
            (isinstance(from_version, str) and NIGHTLY_RE.match(from_version))
            or (isinstance(from_version, str) and re.match(r"^\d+\.\d+\.\d+$", from_version))
        ):
            raise SystemExit("predecessor manifest needs a 'version' (X.Y.Z or X.Y.Z_NNN)")
        changed, deleted = diff_backend_files(
            from_manifest, {"files": current_files["files"]}
        )
        if not changed and not deleted:
            print(f"no native changes since {from_version} — skipping native section")
        else:
            native_zip, native_digest = build_native_zip(
                version, from_version, Path(args.backend_dist), changed, deleted, out
            )
            native_mb = native_zip.stat().st_size / (1024 * 1024)
            print(
                f"wrote {native_zip.name} ({native_mb:.2f} MB, "
                f"{len(changed)} changed, {len(deleted)} deleted, sha256 {native_digest[:12]}…)"
            )
            native_section = {
                "from": from_version,
                "to": version,
                "url": (
                    f"https://github.com/{REPO_SLUG}/releases/download/{args.tag}/{native_zip.name}"
                ),
                "sha256": native_digest,
                "signature": _sign(native_zip.read_bytes()),
                "size": native_zip.stat().st_size,
            }
    elif args.backend_files_from and current_files is None:
        raise SystemExit("error: --backend-files-from needs --backend-dist")

    if args.sign_key:
        print("signed patch (backend verifies against updater.key.pub)")
    else:
        print("warning: unsigned build (no --sign-key) — the backend will refuse to install it")
    manifest = {
        "version": version,
        "base": base,
        "notes": args.notes or f"QCnext nightly {version}",
        "pub_date": datetime.datetime.now(datetime.UTC).isoformat(),
        "url": f"https://github.com/{REPO_SLUG}/releases/download/{args.tag}/{zip_path.name}",
        "sha256": digest,
        "signature": signature,
        "size": zip_path.stat().st_size,
        "kind": "both" if backend_section else "frontend",
        **({"backend": backend_section} if backend_section else {}),
        **({"native": native_section} if native_section else {}),
    }
    (out / "qcnext-nightly.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {zip_path.name} ({zip_mb:.2f} MB, sha256 {digest[:12]}…)")
    print("wrote qcnext-nightly.json")
    print(f"publish: gh release upload {args.tag} {out}/* --clobber")
    return 0


if __name__ == "__main__":
    sys.exit(main())
