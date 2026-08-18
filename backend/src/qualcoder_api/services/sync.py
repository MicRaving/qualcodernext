"""Collaboration sync — Option B: change-log sidecars over folder-sync tools.

Each rater works on their own copy of the ``.qda`` project folder (synced by
Nextcloud, Sync&Share, Syncthing, ...). The raw ``data.qda`` SQLite file is
NEVER merged by the sync tool; instead every mutation is captured into the
project's ``sync_log`` table and exported as JSONL sidecars under
``<project>/changes/<user>/changes.jsonl``. On a 60-second cycle (and on
demand) each rater imports the other raters' sidecar files and replays the
rows into their local database — INSERT/UPDATE/DELETE by primary key with a
deterministic last-write-wins order (user, then seq).

Per-rater sync state (last exported sync_log id, last imported seq per user)
lives in ``~/.qualcoder/sync/<project-hash>.json`` so it never travels with
the synced folder.

Replay is performed with sync capture suspended, so changes never ping-pong
between raters.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, cast

from sqlalchemy import delete, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.persistence import tables

# Capture helpers now live in persistence.audit_capture; the names are
# re-exported here so ``from qualcoder_api.services import sync`` callers
# (repos, links_service, tests) keep working unchanged.
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

logger = logging.getLogger(__name__)

SYNC_DIR_NAME = "changes"
SYNC_INTERVAL_SECS = 60
SYNC_LOCK = asyncio.Lock()

# Tables whose rows travel through the sidecar change log.
SYNC_ENTITIES = {
    "project", "source", "code_name", "code_cat", "code_text", "code_image",
    "code_av", "annotation", "cases", "case_text", "attribute_type",
    "attribute", "journal", "stored_sql", "files_filter",
    "graph", "gr_cdct_text_item", "gr_case_text_item", "gr_file_text_item",
    "gr_free_text_item", "gr_memo_item", "gr_cdct_line_item",
    "gr_free_line_item", "gr_pix_item", "gr_av_item",
    "link", "dictionary", "dictionary_entry", "qtt_sheet", "qtt_item",
    "creative_item", "comment", "code_set", "code_set_member", "r_script",
}

# Map model/dict attribute names to raw table columns for rows that differ.
# (table_row now lives in persistence.audit_capture — re-exported above.)

# Set per request/task so repository-level capture knows who is acting.
# (Definitions moved to persistence.audit_capture — re-exported above.)

# Process-wide sync health: timestamp of the last successful cycle and the
# most recent error (surfaced to the toolbar indicator).
_last_sync_ts: float = 0.0
_last_error: str = ""
_last_error_ts: float = 0.0
_last_result: dict | None = None


def _note_success(result: dict | None) -> None:
    global _last_sync_ts, _last_result, _last_error, _last_error_ts
    _last_sync_ts = time.time()
    _last_result = result
    # A successful cycle clears any previous error so the UI indicator does
    # not keep showing a stale failure.
    _last_error = ""
    _last_error_ts = 0.0


def _note_error(err: Exception) -> None:
    global _last_error, _last_error_ts
    _last_error = str(err)
    _last_error_ts = time.time()


# ----------------------------------------------------------------------
# State (per-machine, outside the synced folder)
# ----------------------------------------------------------------------

def _state_path(project_path: str) -> Path:
    digest = hashlib.sha1(project_path.encode("utf-8")).hexdigest()[:16]
    return Path.home() / ".qualcoder" / "sync" / f"{digest}.json"


def load_state(project_path: str) -> dict:
    try:
        return json.loads(_state_path(project_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(project_path: str, state: dict) -> None:
    path = _state_path(project_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as err:  # pragma: no cover - defensive
        logger.warning("sync state save failed: %s", err)


def _exported_id(state: dict, user: str) -> int:
    return int(state.get("exports", {}).get(user, 0))


def _imported_seq(state: dict, user: str) -> int:
    return int(state.get("imports", {}).get(user, 0))


def _recorded_conflicts(state: dict, rater: str) -> dict[str, dict]:
    """Per-rater entries that conflicted and must be retried next cycle,
    keyed by str(seq). Stored outside the sidecar so a conflict no longer
    blocks later entries (the watermark advances past it). Each value holds
    the original sidecar entry plus the last recorded reason."""
    return state.setdefault("conflicts", {}).setdefault(rater, {})


def _remember_conflict(state: dict, rater: str, seq: int, entry: dict, reason: str) -> None:
    _recorded_conflicts(state, rater)[str(seq)] = {"entry": entry, "reason": reason}


def _forget_conflict(state: dict, rater: str, seq: int) -> None:
    _recorded_conflicts(state, rater).pop(str(seq), None)


def _conflict_summary(state: dict, rater: str) -> list[dict]:
    """Structured summaries of a rater's pending conflicts for the UI."""
    out: list[dict] = []
    for seq in sorted(_recorded_conflicts(state, rater), key=lambda s: int(s)):
        rec = _recorded_conflicts(state, rater)[seq]
        if not isinstance(rec, dict):
            # Stale/malformed entry from an older format — drop it.
            _recorded_conflicts(state, rater).pop(seq, None)
            continue
        entry = rec.get("entry")
        if not isinstance(entry, dict):
            entry = {}
        out.append({
            "seq": int(seq),
            "entity": entry.get("entity", ""),
            "pk": str(entry.get("pk_value", "")),
            "action": entry.get("action", ""),
            "reason": rec.get("reason", ""),
        })
    return out


# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------

async def export_pending(session: AsyncSession, project_path: str, user: str) -> dict:
    """Append sync_log rows newer than the per-user watermark to the sidecar
    file. Returns the number of rows exported."""
    state = load_state(project_path)
    last_id = _exported_id(state, user)
    rows = (
        await session.execute(
            text(
                "SELECT id, ts, user, seq, entity, action, pk_name, pk_value, row_json "
                "FROM sync_log WHERE id > :last ORDER BY id"
            ),
            {"last": last_id},
        )
    ).all()
    if not rows:
        return {"exported": 0}

    sidecar_dir = Path(project_path) / SYNC_DIR_NAME / user
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    sidecar = sidecar_dir / "changes.jsonl"
    lines = "\n".join(
        json.dumps(
            {
                "id": r[0],
                "ts": r[1],
                "user": r[2],
                "seq": r[3],
                "entity": r[4],
                "action": r[5],
                "pk_name": r[6],
                "pk_value": r[7],
                "row": json.loads(r[8]) if r[8] else None,
            },
            ensure_ascii=False,
        )
        for r in rows
    ) + "\n"
    await asyncio.to_thread(_append_sidecar, sidecar, lines)

    state.setdefault("exports", {})[user] = int(rows[-1][0])
    save_state(project_path, state)
    return {"exported": len(rows)}


def _append_sidecar(sidecar: Path, lines: str) -> None:
    """Append exported JSONL lines to a sidecar file.

    Append-only: the sync tool only carries new bytes, and an append never
    re-reads/rewrites the whole file (a crash mid-write cannot corrupt the
    previously-exported lines — only the tail may be partial, which
    _parse_sidecar drops). No read-modify-write means no torn full-file
    upload on interrupted syncs. A torn tail (no trailing newline) is
    separated from the new batch with a newline so it drops on its own
    instead of swallowing the next entries.
    """
    if sidecar.exists() and sidecar.stat().st_size > 0:
        with open(sidecar, "rb") as rf:
            rf.seek(-1, os.SEEK_END)
            if rf.read(1) != b"\n":
                with open(sidecar, "ab") as wf:
                    wf.write(b"\n")
    with open(sidecar, "ab") as f:
        f.write(lines.encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())


# ----------------------------------------------------------------------
# Import / replay
# ----------------------------------------------------------------------

# Natural (business) keys used as fallback identity when autoincrement PKs
# collide between raters' databases (both counters start at 1).
NATURAL_KEYS: dict[str, list[str]] = {
    "code_text": ["cid", "fid", "pos0", "pos1", "owner"],
    "annotation": ["fid", "pos0", "pos1", "owner"],
    "attribute": ["name", "attr_type", "id"],
}


def _parse_sidecar(path: Path) -> list[dict]:
    """Read JSONL lines defensively; corrupt tails (mid-copy writes by the
    sync tool) are dropped. Non-object lines (e.g. a bare number from a torn
    write) are skipped so callers never crash on ``.get`` of a non-dict."""
    entries: list[dict] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return entries
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries


def _resolve_pk(state: dict, entity: str, pk_value: str) -> str:
    """Translate an incoming PK through the local remap table (autoincrement
    counters collide between raters; first-colliding rows get a fresh PK and
    every later reference to the original PK is remapped)."""
    return str(state.get("pkmaps", {}).get(entity, {}).get(str(pk_value), pk_value))


def _record_pk_map(state: dict, entity: str, old_pk: str, new_pk: str) -> None:
    state.setdefault("pkmaps", {}).setdefault(entity, {})[str(old_pk)] = str(new_pk)


async def _fresh_pk(session: AsyncSession, entity: str, pk_name: str) -> int:
    row = (
        await session.execute(text(f"SELECT COALESCE(MAX({pk_name}), 0) FROM {entity}"))
    ).first()
    return int(row[0]) + 1 if row else 1


async def _insert_row(session: AsyncSession, entity: str, row: dict) -> bool:
    cols = ", ".join(row.keys())
    placeholders = ", ".join(":" + k for k in row)
    result = cast(CursorResult[Any], await session.execute(
        text(f"INSERT INTO {entity} ({cols}) VALUES ({placeholders})"), row
    ))
    return result.rowcount > 0


async def _update_by_natural_key(session: AsyncSession, entity: str, row: dict) -> bool:
    keys = NATURAL_KEYS.get(entity)
    if not keys:
        return False
    where = " AND ".join(f"{k} = :{k}" for k in keys)
    update_cols = {k: v for k, v in row.items() if k not in keys}
    if not update_cols:
        return False
    result = cast(CursorResult[Any], await session.execute(
        text(f"UPDATE {entity} SET {', '.join(f'{k} = :{k}' for k in update_cols)} WHERE {where}"),
        {**row},
    ))
    return result.rowcount > 0


async def _delete_by_natural_key(session: AsyncSession, entity: str, row: dict | None) -> bool:
    keys = NATURAL_KEYS.get(entity)
    if not keys or not row:
        return False
    where = " AND ".join(f"{k} = :{k}" for k in keys if k in row)
    if not where:
        return False
    result = cast(CursorResult[Any], await session.execute(
        text(f"DELETE FROM {entity} WHERE {where}"),
        {k: row[k] for k in keys if k in row},
    ))
    return result.rowcount > 0


def _as_pk(value) -> int | str:
    """Coerce a sidecar PK to int when it looks numeric (string PKs such as
    ``attribute_type.name`` stay strings)."""
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return value
    if isinstance(value, int):
        return value
    return str(value)


async def _replay_one(session: AsyncSession, entry: dict, state: dict) -> dict:
    """Apply a single change; returns a structured outcome dict.

    Outcome shapes:
    - ``{"status": "applied", "detail": "..."}``
    - ``{"status": "conflict", "entity", "pk", "action", "reason"}``
    - ``{"status": "skipped", "reason": "..."}``
    """
    entity = entry.get("entity")
    action = entry.get("action")
    pk_name = entry.get("pk_name")
    pk_value = entry.get("pk_value")
    row = entry.get("row")
    if not entity or not action or not pk_name or pk_value is None:
        return {"status": "skipped", "reason": "malformed"}
    if entity not in SYNC_ENTITIES:
        return {"status": "skipped", "reason": f"unknown table {entity}",
                "entity": entity, "pk": str(pk_value), "action": action}
    table = getattr(tables, entity, None)
    if table is None:
        return {"status": "skipped", "reason": f"unknown table {entity}",
                "entity": entity, "pk": str(pk_value), "action": action}

    original_pk = str(pk_value)
    local_pk = _resolve_pk(state, entity, original_pk)

    def _conflict(reason: str) -> dict:
        return {"status": "conflict", "entity": entity, "pk": original_pk,
                "action": action, "reason": reason}

    try:
        if action == "insert":
            insert_row = dict(row) if row else None
            if not insert_row:
                return {"status": "skipped", "reason": "no row"}
            # Force the pk column so identity follows the origin rater.
            insert_row[pk_name] = _as_pk(local_pk)
            try:
                if await _insert_row(session, entity, insert_row):
                    return {"status": "applied", "detail": "applied"}
                return {"status": "skipped", "reason": "no-op"}
            except Exception:
                # PK collision with a DIFFERENT local row: natural-key merge
                # first, else a fresh local PK + permanent remap. The pk
                # column is left out of the natural-key UPDATE so the local
                # row keeps its own identity (rewriting it would orphan
                # every reference to the local pk).
                natural_row = {k: v for k, v in insert_row.items() if k != pk_name}
                if await _update_by_natural_key(session, entity, natural_row):
                    return {"status": "applied", "detail": "merged by natural key"}
                new_pk = await _fresh_pk(session, entity, pk_name)
                insert_row[pk_name] = new_pk
                if await _insert_row(session, entity, insert_row):
                    _record_pk_map(state, entity, original_pk, str(new_pk))
                    return {"status": "applied", "detail": "remapped"}
                return _conflict("insert")

        if action == "update":
            update_row = dict(row) if row else None
            if not update_row:
                return {"status": "skipped", "reason": "no row"}
            update_row[pk_name] = _as_pk(local_pk)
            result = cast(CursorResult[Any], await session.execute(
                update(table).where(text(f"{pk_name} = :pk")).values(**update_row),
                {"pk": _as_pk(local_pk)},
            ))
            if result.rowcount == 0:
                natural_row = {k: v for k, v in update_row.items() if k != pk_name}
                if await _update_by_natural_key(session, entity, natural_row):
                    return {"status": "applied", "detail": "merged by natural key"}
                # Row vanished locally (e.g. replaced) — re-insert the state.
                try:
                    if await _insert_row(session, entity, update_row):
                        return {"status": "applied", "detail": "re-inserted"}
                except Exception:
                    return _conflict("update")
            return {"status": "applied", "detail": "applied"}

        if action == "delete":
            result = cast(CursorResult[Any], await session.execute(
                delete(table).where(text(f"{pk_name} = :pk")), {"pk": _as_pk(local_pk)}
            ))
            if result.rowcount == 0 and not await _delete_by_natural_key(session, entity, row):
                return {"status": "skipped", "reason": "already gone"}
            return {"status": "applied", "detail": "applied"}
    except Exception as err:
        return _conflict(type(err).__name__)
    return {"status": "skipped", "reason": "unknown action"}


async def import_pending(session: AsyncSession, project_path: str, user: str) -> dict:
    """Read every other rater's sidecar file and replay rows newer than the
    per-user high-water seq, plus any recorded conflicts. Returns a per-user
    report.

    A conflicted entry no longer blocks the rest of the sidecar: later
    entries are still applied, the watermark advances past them, and the
    conflicted entry is recorded in per-machine state and retried on the next
    cycle (see ``retry_conflicts`` / the ``conflicts`` state key).
    """
    state = load_state(project_path)
    changes_root = Path(project_path) / SYNC_DIR_NAME
    report: dict[str, dict] = {}
    if not changes_root.is_dir():
        return report

    for sidecar in sorted(changes_root.glob("*/changes.jsonl")):
        rater = sidecar.parent.name
        if rater == user:
            continue
        # Combine previously-recorded conflicts (which may sit below the
        # watermark) with brand-new sidecar entries, then replay in seq order.
        pending: dict[int, dict] = {}
        for key, rec in _recorded_conflicts(state, rater).items():
            if isinstance(rec, dict) and isinstance(rec.get("entry"), dict):
                pending[int(key)] = rec["entry"]
            else:
                # Stale/malformed record from an older format — drop it.
                _forget_conflict(state, rater, int(key))
        for e in _parse_sidecar(sidecar):
            if e.get("seq", 0) > _imported_seq(state, rater):
                pending[int(e["seq"])] = e
        if not pending:
            continue
        applied = 0
        conflicts: list[dict] = []
        highest_applied: int = _imported_seq(state, rater)
        async with suspended():
            for seq in sorted(pending):
                entry = pending[seq]
                outcome = await _replay_one(session, entry, state)
                if outcome.get("status") == "applied":
                    applied += 1
                    _forget_conflict(state, rater, seq)
                    highest_applied = max(highest_applied, int(seq))
                elif outcome.get("status") == "conflict":
                    reason = outcome.get("reason", "conflict")
                    conflicts.append(
                        {k: outcome[k] for k in ("entity", "pk", "action")} | {"reason": reason}
                    )
                    _remember_conflict(state, rater, int(seq), entry, reason)
            await session.commit()
        state.setdefault("imports", {})[rater] = max(
            _imported_seq(state, rater), highest_applied
        )
        save_state(project_path, state)
        report[rater] = {"applied": applied, "conflicts": conflicts}
    return report


# ----------------------------------------------------------------------
# Cycle
# ----------------------------------------------------------------------

async def run_sync_cycle(session_factory, project_path: str, user: str) -> dict:
    """One export + import pass. Serialized app-wide by SYNC_LOCK."""
    if not project_path:
        return {"ok": False, "reason": "no project open"}
    async with SYNC_LOCK:
        try:
            async with session_factory() as session:
                exported = await export_pending(session, project_path, user)
            async with session_factory() as session:
                imported = await import_pending(session, project_path, user)
            result = {"ok": True, **exported, "imported": imported}
            _note_success(result)
            return result
        except Exception as err:  # pragma: no cover - defensive
            logger.exception("sync cycle failed: %s", err)
            _note_error(err)
            return {"ok": False, "reason": str(err)}


def sync_enabled() -> bool:
    """Whether the background sync cycle is switched on (per-machine)."""
    try:
        from qualcoder_api.services.user_settings import get_sync_settings

        return get_sync_settings().get("enabled", False)
    except Exception:  # pragma: no cover - defensive
        return False


# ----------------------------------------------------------------------
# Shared-folder detection (auto-enable on project open)
# ----------------------------------------------------------------------

# Known cloud-sync folder names whose presence in the path strongly implies a
# synced (collaborative) location. Matched case-insensitively against path
# components.
CLOUD_SYNC_MARKERS = (
    "onedrive", "dropbox", "google drive", "icloud", "mega", "pcloud",
    "syncthing", "nextcloud", "owncloud", "seafile", "sugarsync",
)

# Maximum number of parent directories to scan for a Syncthing marker.
SYNCTHING_MARKER_DEPTH = 5


def detect_shared(project_path: str, user: str | None = None) -> dict:
    """Detect whether a project lives in a shared/synced folder.

    Heuristics (first match wins):

    1. a ``.qcnext-shared`` marker file inside the project folder;
    2. a UNC path (``\\\\server\\share`` — Windows network shares);
    3. a ``changes/`` directory holding sidecar change files from OTHER
       raters (the project's own user is excluded);
    4. the path contains a known cloud-sync folder name (OneDrive, Dropbox,
       Google Drive, iCloud, Syncthing, Nextcloud, ...);
    5. a parent directory (up to ``SYNCTHING_MARKER_DEPTH``) carries a
       Syncthing ``.stfolder`` marker.
    """
    root = Path(project_path)
    if (root / ".qcnext-shared").exists():
        return {"shared": True, "reason": "shared-folder marker"}
    if os.name == "nt" and project_path.startswith("\\\\"):
        return {"shared": True, "reason": "network path (UNC)"}
    changes_root = root / SYNC_DIR_NAME
    if changes_root.is_dir():
        for sidecar in sorted(changes_root.glob("*/changes.jsonl")):
            if user and sidecar.parent.name == user:
                continue
            return {"shared": True, "reason": "change sidecars from other raters"}
    # Cloud-sync folder name in the path.
    lower = project_path.lower()
    for marker in CLOUD_SYNC_MARKERS:
        if marker in lower:
            return {"shared": True, "reason": f"cloud-sync folder ({marker})"}
    # Syncthing marker in an ancestor directory.
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
    """Override-aware auto-enable decision for the project-open flow.

    The per-project ``sync_override`` ("on"/"off") wins over the heuristic;
    "auto" (the default) enables sync when the project lives in a shared
    folder.
    """
    from qualcoder_api.services.user_settings import get_sync_override

    mode = get_sync_override(project_path)
    if mode == "on":
        return {"sync_auto_enabled": True, "reason": "per-project override"}
    if mode == "off":
        return {"sync_auto_enabled": False, "reason": "per-project override"}
    detected = detect_shared(project_path, user)
    return {"sync_auto_enabled": detected["shared"], "reason": detected["reason"]}


async def sync_status(session_factory, project_path: str, user: str) -> dict:
    """Current sync state for the toolbar indicator."""
    if not project_path:
        return {"ok": False, "reason": "no project open"}
    try:
        async with session_factory() as session:
            row = (
                await session.execute(
                    text("SELECT COALESCE(MAX(id), 0) FROM sync_log WHERE user = :u"),
                    {"u": user},
                )
            ).first()
            max_id = int(row[0]) if row else 0
        state = load_state(project_path)
        pending_export = max(0, max_id - _exported_id(state, user))
    except Exception as err:  # pragma: no cover - defensive
        return {"ok": False, "reason": str(err)}

    collaborators: list[dict] = []
    changes_root = Path(project_path) / SYNC_DIR_NAME
    if changes_root.is_dir():
        for sidecar in sorted(changes_root.glob("*/changes.jsonl")):
            rater = sidecar.parent.name
            if rater == user:
                continue
            try:
                mtime = sidecar.stat().st_mtime
            except OSError:
                mtime = 0
            entries = _parse_sidecar(sidecar)
            pending_import = sum(
                1 for e in entries if e.get("seq", 0) > _imported_seq(state, rater)
            )
            conflicts = _conflict_summary(state, rater)
            collaborators.append(
                {
                    "user": rater,
                    "last_sync": mtime,
                    "pending_import": pending_import,
                    "pending_conflicts": len(conflicts),
                    "conflicts": conflicts,
                }
            )

    return {
        "ok": True,
        "enabled": sync_enabled(),
        "user": user,
        "pending_export": pending_export,
        "pending_import": sum(c["pending_import"] for c in collaborators),
        "pending_conflicts": sum(c["pending_conflicts"] for c in collaborators),
        "collaborators": collaborators,
        "last_sync": _last_sync_ts,
        "last_error": _last_error,
        "last_error_at": _last_error_ts,
    }
