"""Hotpatch directories — backend-served SPA overlay for delta updates.

Layout under ``~/.qualcoder/hotpatch/`` (user-writable, no UAC):

- ``frontend/current/`` — the active hotpatched SPA (``index.html`` +
  ``assets/`` from ``scripts/build-patch.py``), plus ``version.json``
  (``{"version": "0.1.13_001"}``).
- ``frontend/previous/`` — the last replaced SPA, kept for one-step rollback.
- ``frontend/staging/`` — download + verify scratch dir (renamed atomically).

The Tauri shell keeps loading its embedded assets until a hotpatch is
present; once ``current/version.json`` exists the backend serves it at
``/`` (see ``main.py``) and the shell navigates to the backend URL
(decision 1: backend-served SPA). Backend-source patches live next door —
see ``services/overlay.py`` (same trust model, restart to activate).

Trust: every patch zip is checked against ``PATCH_PUBKEY`` (the same
minisign keypair as the Tauri updater — ``updater.key.pub`` at the repo
root, embedded here so packaged builds verify without the repo). SHA-256
from the manifest is checked first (cheap), the signature second
(authoritative — a forged manifest alone cannot pass).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from qualcoder_api.services.user_settings import QUALCODER_HOME
from qualcoder_api.services.versioning import is_nightly, parse

logger = logging.getLogger(__name__)

#: Embedded copy of the repo ``updater.key.pub`` (minisign, outer-base64
#: wrapped). Public — safe to ship. ``test_hotpatch`` asserts it matches
#: the repo file so key rotations update both.
PATCH_PUBKEY = (
    "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IEI4QzI3Q0IxMzQ1NERFRTIK"
    "UldUaTNsUTBzWHpDdUJsSm5VeEJoQjhFZVZOcWhGSEtDSE1Kamg0dENTOHNucU5UMHRjWlZYUm4K"
)

#: Refuse patch downloads larger than this (disk-fill guard).
MAX_PATCH_BYTES = 50 * 1024 * 1024

#: Rolling nightly release holding the latest delta patch + manifest.
#: Mirrored in ``frontend/src/stores/updates.ts`` — keep in sync.
NIGHTLY_MANIFEST_URL = (
    "https://github.com/MicRaving/qualcodernext/releases/download/nightly/qcnext-nightly.json"
)

#: Manifests are a few hundred bytes; anything larger is not our manifest.
NIGHTLY_MANIFEST_MAX_BYTES = 1 * 1024 * 1024

#: Serializes apply/rollback: FastAPI serves requests concurrently and two
#: overlapping promotes could orphan ``current``.
_PATCH_LOCK = threading.Lock()

HOTPATCH_ROOT = QUALCODER_HOME / "hotpatch"
FRONTEND_DIR = HOTPATCH_ROOT / "frontend"
FRONTEND_CURRENT = FRONTEND_DIR / "current"
FRONTEND_PREVIOUS = FRONTEND_DIR / "previous"
FRONTEND_STAGING = FRONTEND_DIR / "staging"
FRONTEND_VERSION_FILE = FRONTEND_CURRENT / "version.json"


def frontend_version() -> str | None:
    """The active hotpatched frontend version, if a hotpatch is installed."""
    version = _read_version_file(FRONTEND_CURRENT)
    if version is None and FRONTEND_VERSION_FILE.exists():
        logger.warning("hotpatch dir is incomplete — ignoring")
    return version


def frontend_spa_dir() -> Path | None:
    """The directory to serve at ``/`` when a hotpatch is active."""
    return FRONTEND_CURRENT if frontend_version() is not None else None


class HotpatchError(ValueError):
    """A patch apply/rollback failure with a user-displayable message."""


def _read_version_file(directory: Path) -> str | None:
    """The ``version.json`` version in ``directory``, with entry-point check."""
    try:
        data = json.loads((directory / "version.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str) or not version.strip():
        return None
    if not (directory / "index.html").exists():
        return None
    return version.strip()


def previous_version() -> str | None:
    """The rollback-candidate version, if a previous patch is kept."""
    return _read_version_file(FRONTEND_PREVIOUS)


def download_patch(url: str, dest: Path, timeout_secs: int = 60) -> None:
    """Download ``url`` to ``dest``. Only https (releases) and file (tests)."""
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ("https", "file"):
        raise HotpatchError("patch URL must use https")
    request = urllib.request.Request(url, headers={"User-Agent": "QCnext-hotpatch/1"})
    try:
        with (
            urllib.request.urlopen(request, timeout=timeout_secs) as response,
            open(dest, "wb") as handle,
        ):
                remaining = MAX_PATCH_BYTES + 1
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    if remaining <= 0:
                        raise HotpatchError("patch file is larger than 50 MB")
                    handle.write(chunk)
    except HotpatchError:
        raise
    except Exception as err:
        raise HotpatchError(f"could not download the patch ({type(err).__name__})") from err


def safe_unpack(zip_path: Path, dest: Path) -> None:
    """Unpack a patch zip, rejecting absolute paths and ``..`` escapes."""
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.infolist():
                target = (dest / member.filename).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    raise HotpatchError("patch archive contains an unsafe path")
            archive.extractall(dest)
    except HotpatchError:
        raise
    except Exception as err:
        raise HotpatchError(f"could not unpack the patch ({type(err).__name__})") from err


def apply_patch(version: str, url: str, sha256: str, signature: str) -> str:
    """Download, verify and activate a nightly frontend patch.

    Only ``X.Y.Z_NNN`` versions apply here — stable fulls go through the
    Tauri updater. Verifies manifest SHA-256 first, then the minisign
    signature against ``PATCH_PUBKEY``. On success the previous ``current``
    is kept as the one-step rollback. Returns the activated version.
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

    with _PATCH_LOCK:
        staging = FRONTEND_STAGING
        unpacked = staging / "unpacked"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        try:
            archive = staging / "patch.zip"
            download_patch(url, archive)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            if digest.lower() != sha256.strip().lower():
                raise HotpatchError("patch checksum mismatch — download again")
            if not minisign.verify_message(PATCH_PUBKEY, archive.read_bytes(), signature):
                raise HotpatchError("patch signature invalid — refusing to install")
            unpacked.mkdir(parents=True, exist_ok=True)
            safe_unpack(archive, unpacked)
            staged_version = _read_version_file(unpacked)
            if staged_version != version:
                raise HotpatchError("patch contents do not match the announced version")
            # Atomic promote: previous <- current <- unpacked. A crash
            # between renames can only lose the patch (embedded assets are
            # the fallback), never corrupt it — every state is verifiable
            # via version.json + index.html on the next read.
            shutil.rmtree(FRONTEND_PREVIOUS, ignore_errors=True)
            if FRONTEND_CURRENT.exists():
                os.replace(FRONTEND_CURRENT, FRONTEND_PREVIOUS)
            os.replace(unpacked, FRONTEND_CURRENT)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    logger.info("hotpatch %s applied", version)
    return version


def rollback_patch() -> str | None:
    """Restore the previous patch; None when there is nothing to roll back to."""
    with _PATCH_LOCK:
        if previous_version() is None:
            return None
        shutil.rmtree(FRONTEND_CURRENT, ignore_errors=True)
        os.replace(FRONTEND_PREVIOUS, FRONTEND_CURRENT)
        version = frontend_version()
    logger.info("hotpatch rolled back to %s", version)
    return version


def fetch_nightly_manifest(timeout_secs: int = 30) -> dict:
    """Download and minimally validate the nightly manifest (server-side).

    GitHub release assets send no CORS headers, so the webview can never
    fetch the manifest directly — the frontend goes through this proxy
    (``GET /api/v1/updates/nightly``) instead. Returns the parsed object;
    shape checks (usable sections) stay client-side with the version logic.
    """
    request = urllib.request.Request(
        NIGHTLY_MANIFEST_URL, headers={"User-Agent": "QCnext-updates/1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_secs) as response:
            payload = response.read(NIGHTLY_MANIFEST_MAX_BYTES + 1)
    except Exception as err:
        raise HotpatchError(
            f"could not fetch the nightly manifest ({type(err).__name__})"
        ) from err
    if len(payload) > NIGHTLY_MANIFEST_MAX_BYTES:
        raise HotpatchError("nightly manifest is too large")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as err:
        raise HotpatchError("nightly manifest is not valid JSON") from err
    if not isinstance(data, dict) or not isinstance(data.get("version"), str):
        raise HotpatchError("nightly manifest is malformed")
    return data
