"""Native-file deltas — boot-applied backend binary patches, no installer.

Layout under ``~/.qualcoder/hotpatch/native/`` (user-writable, no UAC):

- ``staged/`` — a downloaded + verified delta (changed files at their
  install relpaths + ``delta.json``) plus ``plan.json``.
- ``prev/`` — backups of files the last apply overwrote/removed.
- ``applied.json`` — ``{from, to, files, deleted, previous_to}`` of the
  active delta, written by the Tauri shell when it executes the plan.
- ``plan.json`` — ``{action: "apply"|"restore", version}`` for the shell.

Why boot-time: Windows locks loaded DLLs, so the backend can only STAGE
(user-data dir, nothing locked) — the Tauri shell executes the plan at
boot before spawning the backend (see ``frontend/src-tauri/src``). Each
delta chains exactly onto its stated predecessor (``delta.from`` must
equal the client's current pointer), so restores can never strand files.

Only ``X.Y.Z_NNN`` versions; deltas larger than ``NATIVE_DELTA_MAX_BYTES``
are refused (ship a full release instead — mirrored in the frontend).
Trust matches frontend patches: manifest SHA-256 first, minisign second.
"""

from __future__ import annotations

import hashlib
import json
import logging
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
from qualcoder_api.services.versioning import base_of, is_nightly, parse

logger = logging.getLogger(__name__)

NATIVE_ROOT = QUALCODER_HOME / "hotpatch" / "native"
NATIVE_STAGED = NATIVE_ROOT / "staged"
NATIVE_PREV = NATIVE_ROOT / "prev"
NATIVE_PLAN = NATIVE_ROOT / "plan.json"
NATIVE_APPLIED = NATIVE_ROOT / "applied.json"

#: Refuse deltas above this (ship a full release instead). Mirrored in
#: `frontend/src/stores/updates.ts` — keep the two in sync.
NATIVE_DELTA_MAX_BYTES = 60 * 1024 * 1024

_NATIVE_LOCK = threading.Lock()


def bundle_base_version() -> str:
    """Base backend version the installed bundle corresponds to.

    A Python overlay moves the *effective* version forward but never the
    bundle underneath — native files are orthogonal to overlays.
    """
    from qualcoder_api.core import APP_VERSION

    try:
        return base_of(APP_VERSION)
    except ValueError:
        return APP_VERSION


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def applied_delta() -> dict | None:
    """The active delta record (``applied.json``), if the shell wrote one."""
    data = _read_json(NATIVE_APPLIED)
    if not data or not isinstance(data.get("to"), str):
        return None
    return data


def current_pointer() -> str:
    """The version a new delta must chain onto (applied ``to``, else base)."""
    applied = applied_delta()
    if applied and isinstance(applied.get("to"), str):
        return applied["to"]
    return bundle_base_version()


def staged_version() -> str | None:
    """The staged (plan-pending) delta version, if a plan file exists."""
    plan = _read_json(NATIVE_PLAN)
    if not plan or plan.get("action") != "apply":
        return None
    version = plan.get("version")
    return version if isinstance(version, str) else None


def native_status() -> dict:
    """UI-facing native-delta state (all values JSON-safe)."""
    applied = applied_delta()
    return {
        "staged": staged_version(),
        "applied_from": applied.get("from") if applied else None,
        "applied_to": applied.get("to") if applied else None,
        "previous_to": applied.get("previous_to") if applied else None,
        "bundle_base": bundle_base_version(),
        "pointer": current_pointer(),
    }


def _verify_staged(unpacked: Path, version: str, expected_from: str) -> dict:
    """Cross-check an unpacked delta against its ``delta.json`` + request."""
    data = _read_json(unpacked / "delta.json")
    if not data:
        raise HotpatchError("patch is missing its delta manifest")
    if data.get("to") != version or data.get("from") != expected_from:
        raise HotpatchError("patch contents do not match the announced version")
    files = data.get("files")
    deleted = data.get("deleted")
    if not isinstance(files, list) or not isinstance(deleted, list):
        raise HotpatchError("patch delta manifest is malformed")
    for entry in files:
        if not isinstance(entry, dict):
            raise HotpatchError("patch delta manifest is malformed")
        relpath = entry.get("path")
        target = unpacked / relpath if isinstance(relpath, str) else unpacked
        if not isinstance(relpath, str) or not target.is_file():
            raise HotpatchError(f"patch is missing file {relpath!r}")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest.lower() != str(entry.get("sha256", "")).lower():
            raise HotpatchError(f"patch file failed its checksum: {relpath!r}")
    return {"from": data["from"], "to": data["to"], "files": files, "deleted": deleted}


def stage_native(
    version: str,
    from_version: str,
    url: str,
    sha256: str,
    signature: str,
    size: int,
) -> dict:
    """Download, verify and stage a native delta (shell applies at boot).

    Exact chaining: ``from_version`` must equal the current pointer, else
    the client would strand files between versions. Returns the status.
    """
    from qualcoder_api.services import minisign

    try:
        parse(version)
    except ValueError:
        raise HotpatchError(f"invalid patch version {version!r}") from None
    if not is_nightly(version):
        raise HotpatchError("only nightly (X.Y.Z_NNN) patches apply here")
    if size > NATIVE_DELTA_MAX_BYTES:
        raise HotpatchError("patch is too large — wait for the full release")
    pointer = current_pointer()
    if from_version != pointer:
        raise HotpatchError(
            f"this patch chains onto {from_version}; yours is at {pointer}"
        )
    if not url or not sha256 or not signature:
        raise HotpatchError("patch download, checksum and signature are required")

    with _NATIVE_LOCK:
        staging = NATIVE_STAGED
        unpacked = staging / "unpacked"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        try:
            archive = staging / "patch.zip"
            download_patch(url, archive)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            if digest.lower() != sha256.strip().lower():
                raise HotpatchError("patch checksum mismatch — download again")
            if not minisign.verify_message(
                _hotpatch.PATCH_PUBKEY, archive.read_bytes(), signature
            ):
                raise HotpatchError("patch signature invalid — refusing to install")
            unpacked.mkdir(parents=True, exist_ok=True)
            safe_unpack(archive, unpacked)
            _verify_staged(unpacked, version, from_version)
            # Promote the verified tree into place (the zip itself is
            # dropped — the shell only needs files + delta.json); the plan
            # is written last so a crash never leaves a half-staged apply.
            (staging / "patch.zip").unlink(missing_ok=True)
            for child in unpacked.iterdir():
                shutil.move(str(child), staging / child.name)
            shutil.rmtree(unpacked, ignore_errors=True)
            NATIVE_ROOT.mkdir(parents=True, exist_ok=True)
            NATIVE_PLAN.write_text(
                json.dumps({"action": "apply", "version": version}) + "\n",
                encoding="utf-8",
            )
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            if NATIVE_PLAN.exists():
                NATIVE_PLAN.unlink()
            raise
    logger.info("native delta %s staged (applies at next boot)", version)
    return native_status()


def rollback_native() -> dict | None:
    """Queue a restore of the pre-delta backups (shell executes at boot).

    Returns the status, or None when no delta is active to undo.
    """
    with _NATIVE_LOCK:
        applied = applied_delta()
        if applied is None:
            return None
        NATIVE_ROOT.mkdir(parents=True, exist_ok=True)
        NATIVE_PLAN.write_text(
            json.dumps({"action": "restore", "version": applied.get("to")}) + "\n",
            encoding="utf-8",
        )
    logger.info("native delta restore queued for next boot")
    return native_status()
