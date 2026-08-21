"""Collaboration sync — compatibility shim.

The core sync engine now lives in ``sync_engine.py`` (versioned sidecars with
in-app conflict resolution).  This module retains the shared-folder detection
heuristics, the per-machine sync switch, and re-exports the engine API so
existing callers keep working.

Health globals (``_health_project``, ``_last_sync_ts``, etc.) are defined
HERE so that ``from qualcoder_api.services import sync; sync._last_sync_ts``
works correctly in tests that set them directly on the module.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from pathlib import Path

from qualcoder_api.persistence.audit_capture import (  # noqa: F401
    _current_user,
    _suspended,
    capture,
    capture_delete,
    capture_insert,
    capture_update,
    current_user,
    set_current_user,
    suspended,
    table_row,
)
from qualcoder_api.services.sync_engine import (  # noqa: F401
    SYNC_DIR_NAME,
    SYNC_ENTITIES,
    SYNC_INTERVAL_SECS,
    _append_sidecar,
    _conflict_summary,
    _imported_seq,
    _insert_row,
    _max_sidecar_seq,
    _parse_sidecar,
    _recorded_conflicts,
    _replay_one,
    export_full_state,
    export_pending,
    import_pending,
    list_conflicts,
    load_state,
    rebuild_from_sidecars,
    resolve_all_conflicts,
    resolve_conflict,
    run_sync_cycle,
    save_state,
    sync_status,
)
from qualcoder_api.services.sync_engine import _exported_seq as _exported_id  # noqa: F401

logger = logging.getLogger(__name__)

# ── Process-wide sync health ────────────────────────────────────────────
# Defined here so tests can do ``sync._last_sync_ts = 55.0`` and
# ``_reset_health_for_project`` modifies the SAME module-level names.

_last_sync_ts: float = 0.0
_last_error: str = ""
_last_error_ts: float = 0.0
_last_result: dict | None = None
_health_project: str = ""


def _reset_health_for_project(project_path: str) -> None:
    """Reset process-wide health globals when the active project changes."""
    global _health_project, _last_sync_ts, _last_error, _last_error_ts, _last_result
    if project_path != _health_project:
        _health_project = project_path
        _last_sync_ts = 0.0
        _last_error = ""
        _last_error_ts = 0.0
        _last_result = None


def _note_success(result: dict | None) -> None:
    global _last_sync_ts, _last_result, _last_error, _last_error_ts
    _last_sync_ts = time.time()
    _last_result = result
    _last_error = ""
    _last_error_ts = 0.0


def _note_error(err: Exception) -> None:
    global _last_error, _last_error_ts
    _last_error = str(err)
    _last_error_ts = time.time()


# ── Wire health functions into sync_engine via late binding ──────────────
# sync_engine.py needs these functions but can't import sync.py at module
# level (circular).  We patch them onto the engine module at import time.

def _patch_engine_health() -> None:
    import qualcoder_api.services.sync_engine as _eng

    _eng._note_success = _note_success
    _eng._note_error = _note_error
    _eng._reset_health_for_project = _reset_health_for_project


_patch_engine_health()


# ── Per-machine sync switch ─────────────────────────────────────────────

def sync_enabled() -> bool:
    """Whether the background sync cycle is switched on (per-machine)."""
    try:
        from qualcoder_api.services.user_settings import get_sync_settings
        return get_sync_settings().get("enabled", False)
    except Exception:  # pragma: no cover
        return False


# ── Shared-folder detection ─────────────────────────────────────────────

CLOUD_SYNC_MARKERS = (
    "onedrive", "dropbox", "google drive", "icloud", "mega", "pcloud",
    "syncthing", "nextcloud", "owncloud", "seafile", "sugarsync",
)

SYNCTHING_MARKER_DEPTH = 5


def detect_shared(project_path: str, user: str | None = None, instance_id: str | None = None) -> dict:
    """Detect whether a project lives in a shared/synced folder.

    Heuristics (first match wins):

    1. a ``.qcnext-shared`` marker file inside the project folder;
    2. a UNC path (``\\\\server\\share`` — Windows network shares);
    3. a ``changes/`` directory holding sidecar change files from OTHER
       instances (this instance's own sidecar — matched by ``instance_id``,
       falling back to ``user`` for legacy per-coder folders — is excluded);
    4. the path contains a known cloud-sync folder name (OneDrive, Dropbox,
       Google Drive, iCloud, Syncthing, Nextcloud, ...);
    5. a parent directory (up to ``SYNCTHING_MARKER_DEPTH``) carries a
       Syncthing ``.stfolder`` marker.
    """
    root = Path(project_path)
    # UNC paths are definitively shared — check the cheap string test first so
    # a network path never triggers a stat on a remote share.
    if os.name == "nt" and project_path.startswith("\\\\"):
        return {"shared": True, "reason": "network path (UNC)"}
    with contextlib.suppress(OSError):
        if (root / ".qcnext-shared").exists():
            return {"shared": True, "reason": "shared-folder marker"}
    changes_root = root / SYNC_DIR_NAME
    if changes_root.is_dir():
        for sidecar_dir in changes_root.iterdir():
            if not sidecar_dir.is_dir():
                continue
            sidecar = sidecar_dir / "changes.jsonl"
            if sidecar.exists():
                if instance_id and sidecar_dir.name == instance_id:
                    continue
                if user and sidecar_dir.name == user:
                    continue
                return {"shared": True, "reason": "change sidecars from other instances"}
    lower = project_path.lower()
    for marker in CLOUD_SYNC_MARKERS:
        if marker in lower:
            return {"shared": True, "reason": f"cloud-sync folder ({marker})"}
    cur = root
    for _ in range(SYNCTHING_MARKER_DEPTH):
        if (cur / ".stfolder").exists():
            return {"shared": True, "reason": "Syncthing folder marker"}
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return {"shared": False, "reason": "not a shared folder"}


def auto_enable_decision(project_path: str, user: str | None = None) -> dict:
    """Override-aware auto-enable decision for the project-open flow."""
    from qualcoder_api.services.project_marker import marker_exists

    # A collaboration marker means the project is already running in sandbox
    # mode — sync must be on for the sidecars to stay converged.
    if marker_exists(project_path):
        return {"sync_auto_enabled": True, "reason": "collaboration active"}
    from qualcoder_api.services.user_settings import get_sync_override

    mode = get_sync_override(project_path)
    if mode == "on":
        return {"sync_auto_enabled": True, "reason": "per-project override"}
    if mode == "off":
        return {"sync_auto_enabled": False, "reason": "per-project override"}
    from qualcoder_api.services.user_settings import get_instance_id

    detected = detect_shared(project_path, user, instance_id=get_instance_id())
    return {"sync_auto_enabled": detected["shared"], "reason": detected["reason"]}


async def project_has_multiple_coders(session) -> bool:
    """Whether the project has at least two real (non-system) coders.

    Collaboration mode is only meaningful with ≥2 coders; a single coder keeps
    reading ``data.qda`` directly.
    """
    from sqlalchemy import text

    row = await session.execute(
        text("SELECT COUNT(*) FROM coder_names WHERE name != :sys AND name != ''"),
        {"sys": "system"},
    )
    return int(row.scalar() or 0) >= 2


async def should_activate_collaboration(
    session, project_path: str
) -> tuple[bool, str]:
    """Whether collaboration mode should be activated for the open project.

    Returns ``(ok, reason)``.  Requires: sync switched on, no marker yet, and at
    least two real coders.  This is the gate both the add-coder path and the
    ``PUT /sync/settings`` path check before calling ``activate_collaboration``.
    """
    from qualcoder_api.services.project_marker import marker_exists

    if marker_exists(project_path):
        return False, "collaboration already active"
    if not sync_enabled():
        return False, "sync is not enabled"
    if not await project_has_multiple_coders(session):
        return False, "a second coder is required"
    return True, "ready to activate"
