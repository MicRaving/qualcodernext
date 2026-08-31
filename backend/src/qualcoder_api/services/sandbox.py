"""Local sandbox management for collaboration mode.

In collaboration mode the live working SQLite database lives OUTSIDE the
shared folder at ``~/.qualcoder/projects/<uuid>/<instance>/sandbox.sqlite`` —
keyed per instance so two raters on the same machine (or a rater and a second
app window) never fight over one SQLite file.  Only the append-only sidecars
and the cold ``data.qda`` archive live in the shared folder.  This module owns
the sandbox path, creation, crash recovery and teardown.

Crash recovery uses a single ``.bak`` rotation: the previous session's sandbox
is kept alongside the current one so a corrupt sandbox can fall back to the
last good state before rebuilding from sidecars.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from qualcoder_api.persistence.schema import create_new_project_schema

logger = logging.getLogger(__name__)

_SANDBOX_ROOT = Path.home() / ".qualcoder" / "projects"


def _instance_segment(instance_id: str) -> str:
    """The per-instance path segment (instance ids contain no path separators)."""
    return instance_id or "default"


def sandbox_dir(uuid: str, instance_id: str = "") -> Path:
    """The local directory holding this instance's sandbox (not synced)."""
    return _SANDBOX_ROOT / uuid / _instance_segment(instance_id)


def sandbox_path(uuid: str, instance_id: str = "") -> Path:
    """The live sandbox database path."""
    return sandbox_dir(uuid, instance_id) / "sandbox.sqlite"


def sandbox_backup_path(uuid: str, instance_id: str = "") -> Path:
    """The previous session's sandbox (crash recovery fallback)."""
    return sandbox_dir(uuid, instance_id) / "sandbox.sqlite.bak"


def sandbox_exists(uuid: str, instance_id: str = "") -> bool:
    return sandbox_path(uuid, instance_id).exists()


def prepare_sandbox_dir(uuid: str, instance_id: str = "") -> Path:
    d = sandbox_dir(uuid, instance_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_sandbox_from(source_db: str, uuid: str, instance_id: str = "") -> Path:
    """Copy a (checkpointed) database file into the sandbox location.

    The caller is responsible for checkpointing ``source_db`` first so the
    copy is self-consistent.  Returns the sandbox path.
    """
    target = sandbox_path(uuid, instance_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Rotate the previous sandbox to .bak before overwriting so a corrupt
    # new copy can fall back to the last known-good state.
    _rotate_backup(uuid, instance_id)
    shutil.copy2(source_db, target)
    return target


def _rotate_backup(uuid: str, instance_id: str = "") -> None:
    """Keep one previous sandbox as ``.bak`` (rotate, not accumulate)."""
    try:
        src = sandbox_path(uuid, instance_id)
        bak = sandbox_backup_path(uuid, instance_id)
        if src.exists():
            bak.unlink(missing_ok=True)
            shutil.copy2(src, bak)
    except OSError as err:  # pragma: no cover - defensive
        logger.warning("sandbox .bak rotation failed: %s", err)


async def create_fresh_sandbox(
    uuid: str,
    *,
    app_version: str = "QualCoder 4.0",
    codername: str = "default",
    instance_id: str = "",
) -> Path:
    """Create an empty sandbox database with the current schema.

    Used as the starting point for ``rebuild_from_sidecars``.  Returns the
    sandbox path.
    """
    import aiosqlite

    target = sandbox_path(uuid, instance_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    _rotate_backup(uuid, instance_id)
    target.unlink(missing_ok=True)
    conn = await aiosqlite.connect(str(target))
    try:
        await create_new_project_schema(conn, app_version=app_version, codername=codername)
    finally:
        await conn.close()
    return target


def remove_sandbox(uuid: str) -> None:
    """Delete the whole sandbox tree for a project (revert to single-coder)."""
    d = _SANDBOX_ROOT / uuid
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def sandbox_candidate_paths(uuid: str, instance_id: str = "") -> list[Path]:
    """Sandbox files to try in order when opening (live, then .bak)."""
    return [sandbox_path(uuid, instance_id), sandbox_backup_path(uuid, instance_id)]
