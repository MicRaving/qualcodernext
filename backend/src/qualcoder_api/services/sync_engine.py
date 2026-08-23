"""Collaboration sync engine — public facade.

The implementation is split across:
- ``sync_schema`` — constants, entity sets, PK helpers, export order
- ``sync_state`` — per-machine state-file I/O and watermarks
- ``sync_sidecar`` — append-only JSONL sidecar I/O, compaction, trimming
- ``sync_replay`` — row helpers, FK translation, replay FSM, export/import
- ``sync_conflicts`` — conflict resolution (single + bulk)
- ``sync_status`` — status reporting, collaborator states, entity labels

This facade re-exports every public name so existing imports keep working.
Health globals (_note_success, _note_error, _reset_health_for_project) live
here and are monkey-patched by ``sync.py`` at import time.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text

from qualcoder_api.services.sync_conflicts import (  # noqa: F401
    _resolve_conflict_locked,
    resolve_all_conflicts,
    resolve_conflict,
)
from qualcoder_api.services.sync_replay import (  # noqa: F401
    _find_by_natural_key,
    _insert_row,
    _max_sidecar_seq,
    _normalize,
    _read_row,
    _record_conflict,
    _record_remap,
    _replay_one,
    _rows_equal,
    _translate_fks,
    export_full_state,
    export_pending,
    import_pending,
    rebuild_from_sidecars,
)
from qualcoder_api.services.sync_schema import (  # noqa: F401
    ENTITY_PKS,
    EXPORT_ORDER,
    FK_REFERENCES,
    NATURAL_KEYS,
    SIDECAR_COMPACT_THRESHOLD_BYTES,
    SIDECAR_COMPACT_THRESHOLD_ENTRIES,
    SIDECAR_PRUNE_AFTER_SECS,
    SYNC_DIR_NAME,
    SYNC_ENTITIES,
    SYNC_INTERVAL_SECS,
    SYNC_LOCK,
    _as_pk,
    _pk_cols,
    _pk_values,
    _pk_where,
    _row_pk,
)
from qualcoder_api.services.sync_sidecar import (  # noqa: F401
    _append_sidecar,
    _compact_sidecar,
    _parse_sidecar,
    _sidecar_path,
    _trim_sync_log,
)
from qualcoder_api.services.sync_state import (  # noqa: F401
    _conflict_summary,
    _exported_seq,
    _imported_seq,
    _recorded_conflicts,
    load_state,
    save_state,
)
from qualcoder_api.services.sync_status import (  # noqa: F401
    _collaborator_state,
    _entity_label,
    list_conflicts,
    sync_status,
)

logger = logging.getLogger(__name__)

# ── Health stubs (monkey-patched by sync.py at import time) ─────────────
# These are module-level globals so that bare-name calls inside this
# module resolve to sync.py's versions after patching.
_health_project: str = ""
_last_sync_ts: float = 0.0
_last_error: str = ""
_last_error_ts: float = 0.0
_last_result: dict | None = None


def _reset_health_for_project(project_path: str) -> None:
    """Stub — replaced by sync.py's version at import time."""
    global _health_project, _last_sync_ts, _last_error, _last_error_ts, _last_result
    if project_path != _health_project:
        _health_project = project_path
        _last_sync_ts = 0.0
        _last_error = ""
        _last_error_ts = 0.0
        _last_result = None


def _note_success(result: dict | None) -> None:
    """Stub — replaced by sync.py's version at import time."""
    global _last_sync_ts, _last_result, _last_error, _last_error_ts
    import time
    _last_sync_ts = time.time()
    _last_result = result
    _last_error = ""
    _last_error_ts = 0.0


def _note_error(err: Exception) -> None:
    """Stub — replaced by sync.py's version at import time."""
    global _last_error, _last_error_ts
    import time
    _last_error = str(err)
    _last_error_ts = time.time()


# ── Cycle ────────────────────────────────────────────────────────────


async def baseline_first_sync(session, project_path: str, instance_id: str) -> bool:
    """First-sync bootstrap for NEW collaborators (user directive after the
    offline-backup freeze: a fresh instance must never replay the entire
    existing sidecar backlog on enable).

    When this instance has NO prior sync state, adopt the shared project's
    current state as already-seen:

    - ``imports[remote] = max seq`` of every OTHER sidecar  → their history
      is skipped; only future entries flow.
    - ``exports[instance] = MAX(id) FROM sync_log`` → pre-existing rows are
      not re-pushed.

    Returns True when a baseline was written. An instance that already has
    state (enable→disable→re-enable, or legacy) is left untouched so no
    legitimate pending entries are skipped mid-stream.
    """
    from qualcoder_api.core.timeutil import now

    state = load_state(project_path)
    baselines = state.setdefault("baselines", {})
    if baselines.get(instance_id) is not None:
        return False
    if state.get("exports", {}).get(instance_id) is not None:
        return False

    changes_root = Path(project_path) / SYNC_DIR_NAME
    if changes_root.is_dir():
        for sidecar_dir in changes_root.iterdir():
            if not sidecar_dir.is_dir() or sidecar_dir.name == instance_id:
                continue
            sidecar = sidecar_dir / "changes.jsonl"
            if not sidecar.exists():
                continue
            max_seq = 0
            for e in _parse_sidecar(sidecar):
                try:
                    max_seq = max(max_seq, int(e.get("seq", 0)))
                except (TypeError, ValueError):
                    continue
            state.setdefault("imports", {})[sidecar_dir.name] = max_seq

    row = (
        await session.execute(text("SELECT COALESCE(MAX(id), 0) FROM sync_log"))
    ).first()
    state.setdefault("exports", {})[instance_id] = int(row[0]) if row else 0
    baselines[instance_id] = now()
    save_state(project_path, state)
    logger.info(
        "first-sync baseline written for %s on %s", instance_id, project_path
    )
    return True


async def run_sync_cycle(session_factory, project_path: str, instance_id: str) -> dict:
    """One export + import pass. Serialized app-wide by SYNC_LOCK."""
    _reset_health_for_project(project_path)
    if not project_path:
        return {"ok": False, "reason": "no project open"}
    async with SYNC_LOCK:
        try:
            async with session_factory() as session:
                exported = await export_pending(session, project_path, instance_id)
            async with session_factory() as session:
                imported = await import_pending(session, project_path, instance_id)
            result = {"ok": True, **exported, "imported": imported}
            _note_success(result)
            return result
        except Exception as err:  # pragma: no cover
            logger.exception("sync cycle failed: %s", err)
            _note_error(err)
            return {"ok": False, "reason": str(err)}
