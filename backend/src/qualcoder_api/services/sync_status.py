"""Sync status — status reporting, collaborator states, entity labels."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from sqlalchemy import text

from qualcoder_api.persistence.audit_capture import current_user
from qualcoder_api.services.sync_schema import SIDECAR_PRUNE_AFTER_SECS, SYNC_DIR_NAME
from qualcoder_api.services.sync_sidecar import _parse_sidecar
from qualcoder_api.services.sync_state import (
    _exported_seq,
    _imported_seq,
    load_state,
)

logger = logging.getLogger(__name__)


def _facade():
    """Late-bound access to the ``sync_engine`` facade namespace.

    ``_reset_health_for_project`` is a health stub that services/sync.py
    monkey-patches ON the facade; resolving it there at CALL time keeps
    the patch effective after the module split."""
    from qualcoder_api.services import sync_engine

    return sync_engine

# ── Status ───────────────────────────────────────────────────────────────

async def sync_status(session_factory, project_path: str, instance_id: str) -> dict:
    """Current sync state for the toolbar indicator."""
    _facade()._reset_health_for_project(project_path)
    if not project_path:
        return {"ok": False, "reason": "no project open"}
    try:
        async with session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT COALESCE(MAX(id), 0) FROM sync_log")
                )
            ).first()
            max_id = int(row[0]) if row else 0

            # Count unresolved conflicts.
            conflict_row = (
                await session.execute(
                    text("SELECT COUNT(*) FROM sync_conflict WHERE resolved_at IS NULL")
                )
            ).first()
            conflict_count = int(conflict_row[0]) if conflict_row else 0

        state = load_state(project_path)
        pending_export = max(0, max_id - _exported_seq(state, instance_id))
    except Exception as err:  # pragma: no cover
        return {"ok": False, "reason": str(err)}

    # Per-instance collaborator info.
    collaborators: list[dict] = []
    changes_root = Path(project_path) / SYNC_DIR_NAME
    if changes_root.is_dir():
        for sidecar_dir in sorted(changes_root.iterdir()):
            if not sidecar_dir.is_dir() or sidecar_dir.name == instance_id:
                continue
            sidecar = sidecar_dir / "changes.jsonl"
            try:
                mtime = sidecar.stat().st_mtime if sidecar.exists() else 0
            except OSError:
                mtime = 0
            entries = _parse_sidecar(sidecar) if sidecar.exists() else []
            pending_import = sum(
                1 for e in entries if e.get("seq", 0) > _imported_seq(state, sidecar_dir.name)
            )
            collaborators.append({
                "instance": sidecar_dir.name,
                "coder": entries[0].get("coder", "") if entries else "",
                "last_sync": mtime,
                "pending_import": pending_import,
                "state": _collaborator_state(mtime, pending_import),
            })

    # Compute overall state.
    import qualcoder_api.services.sync as _sync_mod
    sync_error = bool(_sync_mod._last_error)
    if sync_error:
        state_str = "error"
    elif conflict_count > 0:
        state_str = "conflict"
    elif pending_export > 0 or any(c["pending_import"] > 0 for c in collaborators):
        state_str = "syncing"
    else:
        state_str = "active"

    from qualcoder_api.services.sync import sync_enabled
    return {
        "ok": True,
        "enabled": sync_enabled(),
        "instance_id": instance_id,
        "state": state_str,
        "user": current_user(),
        "pending_export": pending_export,
        "pending_import": sum(c["pending_import"] for c in collaborators),
        "pending_conflicts": conflict_count,
        "collaborators": collaborators,
        "last_sync": _sync_mod._last_sync_ts,
        "last_error": _sync_mod._last_error,
        "last_error_at": _sync_mod._last_error_ts,
    }


def _collaborator_state(last_sync: float, pending: int) -> str:
    """Derive a collaborator's state from their last sync time."""
    if last_sync == 0:
        return "offline"
    age = time.time() - last_sync
    if age < 90:
        return "active"
    if age < SIDECAR_PRUNE_AFTER_SECS:
        return "stale"
    return "offline"


# ── List conflicts ──────────────────────────────────────────────────────

async def list_conflicts(session_factory) -> list[dict]:
    """Return all unresolved conflicts with parsed JSON rows and entity labels."""
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "SELECT * FROM sync_conflict WHERE resolved_at IS NULL "
                "ORDER BY detected_at"
            )
        )
        conflicts = []
        for row in rows.mappings():
            entity = row["entity"]
            pk = row["pk"]
            # Derive a human-readable label.
            label = _entity_label(entity, pk)
            conflicts.append({
                "id": row["id"],
                "entity": entity,
                "pk": pk,
                "pk_name": row["pk_name"],
                "local_rev": row["local_rev"],
                "remote_rev": row["remote_rev"],
                "local_row": json.loads(row["local_row"]) if row["local_row"] else None,
                "remote_row": json.loads(row["remote_row"]) if row["remote_row"] else None,
                "remote_instance": row["remote_instance"],
                "remote_coder": row["remote_coder"],
                "detected_at": row["detected_at"],
                "entity_label": label,
            })
        return conflicts


def _entity_label(entity: str, pk: str) -> str:
    """Human-readable label for a conflicting entity."""
    labels = {
        "code_name": "Code",
        "code_cat": "Category",
        "source": "File",
        "cases": "Case",
        "annotation": "Annotation",
        "journal": "Journal",
        "comment": "Comment",
        "attribute_type": "Attribute type",
        "attribute": "Attribute",
        "creative_item": "Creative item",
        "qtt_sheet": "QTT worksheet",
        "code_set": "Code set",
        "dictionary": "Dictionary",
    }
    prefix = labels.get(entity, entity)
    return f"{prefix} ({pk})"
