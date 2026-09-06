"""Backend-source overlay — restart-only Python patches without an installer.

Layout under ``~/.qualcoder/patches/`` (user-writable, no UAC):

- ``current/`` — the active overlay: a ``qualcoder_api/`` package tree plus
  ``version.json``. ``runtime_hook.py`` prepends it to ``sys.path`` at boot
  (before any app import), so loose sources shadow the frozen PYZ.
- ``previous/`` — one-step rollback. ``staging/`` — download scratch dir.

Native dependencies (FFmpeg, onnx, PyMuPDF…) stay frozen — overlays only
carry pure-Python ``qualcoder_api`` sources (~2-5 MB zipped). A patch that
needs new native deps must ship as a full release instead.

Activation needs a backend process restart (the Tauri shell exposes
``restart_backend``; the open project is cleanly closed on shutdown and
reopened by the frontend). Trust is identical to frontend patches: manifest
SHA-256 first, minisign signature against the release key second.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
from pathlib import Path

from qualcoder_api.services import hotpatch as _hotpatch
from qualcoder_api.services.hotpatch import (
    HotpatchError,
    download_patch,
    safe_unpack,
)
from qualcoder_api.services.user_settings import QUALCODER_HOME
from qualcoder_api.services.versioning import is_nightly, parse

logger = logging.getLogger(__name__)

PATCHES_ROOT = QUALCODER_HOME / "patches"
OVERLAY_CURRENT = PATCHES_ROOT / "current"
OVERLAY_PREVIOUS = PATCHES_ROOT / "previous"
OVERLAY_STAGING = PATCHES_ROOT / "staging"

_OVERLAY_LOCK = threading.Lock()


def overlay_dir() -> Path:
    """The overlay directory ``runtime_hook`` puts on ``sys.path``.

    ``QC_OVERLAY_DIR`` overrides (tests); otherwise the user-data default.
    Mirrors the hook's inline logic — keep the two in sync.
    """
    override = os.environ.get("QC_OVERLAY_DIR")
    if override:
        return Path(override)
    return OVERLAY_CURRENT


def _read_overlay_version(directory: Path) -> str | None:
    """The overlay version when ``directory`` is a complete package overlay."""
    try:
        data = json.loads((directory / "version.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str) or not version.strip():
        return None
    # A package overlay without the package is incomplete — never trust it.
    if not (directory / "qualcoder_api" / "__init__.py").exists():
        return None
    return version.strip()


def overlay_version() -> str | None:
    """The active backend-overlay version, if one is installed."""
    return _read_overlay_version(OVERLAY_CURRENT)


def overlay_previous_version() -> str | None:
    """The rollback-candidate overlay version, if one is kept."""
    return _read_overlay_version(OVERLAY_PREVIOUS)


def apply_overlay(version: str, url: str, sha256: str, signature: str) -> str:
    """Download, verify and stage a backend-source patch.

    Takes effect on the next backend restart (the caller restarts via the
    Tauri ``restart_backend`` command). Same trust rules as frontend
    patches; only ``X.Y.Z_NNN`` versions. Returns the staged version.
    """
    from qualcoder_api.services import minisign

    try:
        parse(version)
    except ValueError:
        raise HotpatchError(f"invalid patch version {version!r}") from None
    if not is_nightly(version):
        raise HotpatchError("only nightly (X.Y.Z_NNN) patches apply here")
    if not url or not sha256 or not signature:
        raise HotpatchError("patch download, checksum and signature are required")

    with _OVERLAY_LOCK:
        staging = OVERLAY_STAGING
        unpacked = staging / "unpacked"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        try:
            archive = staging / "patch.zip"
            download_patch(url, archive)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            if digest.lower() != sha256.strip().lower():
                raise HotpatchError("patch checksum mismatch — download again")
            # Late binding (not a from-import): tests swap the trusted key.
            if not minisign.verify_message(
                _hotpatch.PATCH_PUBKEY, archive.read_bytes(), signature
            ):
                raise HotpatchError("patch signature invalid — refusing to install")
            unpacked.mkdir(parents=True, exist_ok=True)
            safe_unpack(archive, unpacked)
            staged_version = _read_overlay_version(unpacked)
            if staged_version != version:
                raise HotpatchError("patch contents do not match the announced version")
            shutil.rmtree(OVERLAY_PREVIOUS, ignore_errors=True)
            if OVERLAY_CURRENT.exists():
                os.replace(OVERLAY_CURRENT, OVERLAY_PREVIOUS)
            os.replace(unpacked, OVERLAY_CURRENT)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    logger.info("backend overlay %s staged (restart to activate)", version)
    return version


def rollback_overlay() -> str | None:
    """Restore the previous overlay; None when there is nothing to roll back to."""
    with _OVERLAY_LOCK:
        if overlay_previous_version() is None:
            return None
        shutil.rmtree(OVERLAY_CURRENT, ignore_errors=True)
        os.replace(OVERLAY_PREVIOUS, OVERLAY_CURRENT)
        version = overlay_version()
    logger.info("backend overlay rolled back to %s", version)
    return version
