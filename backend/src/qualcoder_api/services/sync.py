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
import contextlib
import contextvars
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

from qualcoder_api.core.timeutil import now
from qualcoder_api.persistence import tables

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
    "creative_item", "comment", "code_set", "code_set_member",
}

# Map model/dict attribute names to raw table columns for rows that differ.
def table_row(mapping) -> dict:
    """Normalize a raw row mapping into a plain dict of table columns."""
    return {k: v for k, v in dict(mapping).items() if not k.startswith("_")}

# Set per request/task so repository-level capture knows who is acting.
_current_user: contextvars.ContextVar[str] = contextvars.ContextVar("sync_user", default="")

# Repositories call capture() for every mutation; replay and imports set
# this so their writes are not re-captured (no ping-pong).
_suspended: contextvars.ContextVar[bool] = contextvars.ContextVar("sync_suspended", default=False)

# Process-wide sync health: timestamp of the last successful cycle and the
# most recent error (surfaced to the toolbar indicator).
_last_sync_ts: float = 0.0
_last_error: str = ""
_last_error_ts: float = 0.0
_last_result: dict | None = None


def _note_success(result: dict | None) -> None:
    global _last_sync_ts, _last_result
    _last_sync_ts = time.time()
    _last_result = result


def _note_error(err: Exception) -> None:
    global _last_error, _last_error_ts
    _last_error = str(err)
    _last_error_ts = time.time()


@contextlib.asynccontextmanager
async def suspended():
    """Disable sync capture for the duration of the block (replay/imports)."""
    token = _suspended.set(True)
    try:
        yield
    finally:
        _suspended.reset(token)


def set_current_user(user: str) -> None:
    _current_user.set(user)


def current_user() -> str:
    user = _current_user.get()
    if user:
        return user
    try:
        from qualcoder_api.services.user_settings import get_codername

        return get_codername()
    except Exception:  # pragma: no cover - defensive
        return "unknown"


# ----------------------------------------------------------------------
# Capture
# ----------------------------------------------------------------------

async def capture(
    session: AsyncSession,
    *,
    entity: str,
    action: str,
    pk_name: str,
    pk_value: int | str | None,
    row: dict | None,
    user: str | None = None,
    ts: str | None = None,
) -> None:
    """Record one mutation into sync_log (no-op while suspended)."""
    if _suspended.get():
        return
    if row is None or pk_value is None:
        return

    if ts is None:
        ts = now()
    actor = user or current_user()
    # Atomic per-user sequence: the SELECT-then-INSERT pair could race on
    # concurrent requests, so the counter is computed inside the INSERT.
    await session.execute(
        text(
            "INSERT INTO sync_log (ts, user, seq, entity, action, pk_name, pk_value, row_json) "
            "VALUES (:ts, :user, "
            "(SELECT COALESCE(MAX(seq), 0) + 1 FROM sync_log WHERE user = :user2), "
            ":entity, :action, :pk_name, :pk_value, :row_json)"
        ),
        {
            "ts": ts,
            "user": actor,
            "user2": actor,
            "entity": entity,
            "action": action,
            "pk_name": pk_name,
            "pk_value": str(pk_value),
            "row_json": json.dumps(row, ensure_ascii=False, default=str),
        },
    )
    await session.flush()


async def capture_delete(
    session: AsyncSession, *, entity: str, pk_name: str, pk_value: int | str | None, row: dict | None
) -> None:
    await capture(session, entity=entity, action="delete", pk_name=pk_name,
                  pk_value=pk_value, row=row)


async def capture_insert(
    session: AsyncSession, *, entity: str, pk_name: str, pk_value: int | str | None, row: dict | None
) -> None:
    await capture(session, entity=entity, action="insert", pk_name=pk_name,
                  pk_value=pk_value, row=row)


async def capture_update(
    session: AsyncSession, *, entity: str, pk_name: str, pk_value: int | str | None, row: dict | None
) -> None:
    await capture(session, entity=entity, action="update", pk_name=pk_name,
                  pk_value=pk_value, row=row)


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
    tmp = sidecar_dir / "changes.jsonl.tmp"
    lines = [
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
    ]
    # Append to the existing sidecar (the sync tool only carries new bytes).
    existing = b""
    if sidecar.exists():
        existing = sidecar.read_bytes()
    tmp.write_bytes(existing + ("\n".join(lines) + "\n").encode("utf-8"))
    tmp.replace(sidecar)

    state.setdefault("exports", {})[user] = int(rows[-1][0])
    save_state(project_path, state)
    return {"exported": len(rows)}


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
    sync tool) are dropped."""
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
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
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


async def _replay_one(session: AsyncSession, entry: dict, state: dict) -> str:
    """Apply a single change; returns "applied" or a conflict description."""
    entity = entry.get("entity")
    action = entry.get("action")
    pk_name = entry.get("pk_name")
    pk_value = entry.get("pk_value")
    row = entry.get("row")
    if not entity or not action or not pk_name or pk_value is None:
        return "skipped (malformed)"
    if entity not in SYNC_ENTITIES:
        return f"skipped (unknown table {entity})"
    table = getattr(tables, entity, None)
    if table is None:
        return f"skipped (unknown table {entity})"

    original_pk = str(pk_value)
    local_pk = _resolve_pk(state, entity, original_pk)

    try:
        if action == "insert":
            insert_row = dict(row) if row else None
            if not insert_row:
                return "skipped (no row)"
            # Force the pk column so identity follows the origin rater.
            insert_row[pk_name] = _as_pk(local_pk)
            try:
                if await _insert_row(session, entity, insert_row):
                    return "applied"
                return "skipped (no-op)"
            except Exception:
                # PK collision with a DIFFERENT local row: natural-key merge
                # first, else a fresh local PK + permanent remap. The pk
                # column is left out of the natural-key UPDATE so the local
                # row keeps its own identity (rewriting it would orphan
                # every reference to the local pk).
                natural_row = {k: v for k, v in insert_row.items() if k != pk_name}
                if await _update_by_natural_key(session, entity, natural_row):
                    return "applied (merged by natural key)"
                new_pk = await _fresh_pk(session, entity, pk_name)
                insert_row[pk_name] = new_pk
                if await _insert_row(session, entity, insert_row):
                    _record_pk_map(state, entity, original_pk, str(new_pk))
                    return "applied (remapped)"
                return "conflict (insert)"

        if action == "update":
            update_row = dict(row) if row else None
            if not update_row:
                return "skipped (no row)"
            update_row[pk_name] = _as_pk(local_pk)
            result = cast(CursorResult[Any], await session.execute(
                update(table).where(text(f"{pk_name} = :pk")).values(**update_row),
                {"pk": _as_pk(local_pk)},
            ))
            if result.rowcount == 0:
                natural_row = {k: v for k, v in update_row.items() if k != pk_name}
                if await _update_by_natural_key(session, entity, natural_row):
                    return "applied (merged by natural key)"
                # Row vanished locally (e.g. replaced) — re-insert the state.
                try:
                    if await _insert_row(session, entity, update_row):
                        return "applied"
                except Exception:
                    return "conflict (update)"
            return "applied"

        if action == "delete":
            result = cast(CursorResult[Any], await session.execute(
                delete(table).where(text(f"{pk_name} = :pk")), {"pk": _as_pk(local_pk)}
            ))
            if result.rowcount == 0 and not await _delete_by_natural_key(session, entity, row):
                return "skipped (already gone)"
            return "applied"
    except Exception as err:
        return f"conflict ({type(err).__name__})"
    return "skipped (unknown action)"


async def import_pending(session: AsyncSession, project_path: str, user: str) -> dict:
    """Read every other rater's sidecar file and replay rows newer than the
    per-user high-water seq. Returns a per-user report."""
    state = load_state(project_path)
    changes_root = Path(project_path) / SYNC_DIR_NAME
    report: dict[str, dict] = {}
    if not changes_root.is_dir():
        return report

    for sidecar in sorted(changes_root.glob("*/changes.jsonl")):
        rater = sidecar.parent.name
        if rater == user:
            continue
        entries = [e for e in _parse_sidecar(sidecar) if e.get("seq", 0) > _imported_seq(state, rater)]
        if not entries:
            continue
        applied = 0
        conflicts: list[str] = []
        first_conflict_seq: int | None = None
        async with suspended():
            for entry in sorted(entries, key=lambda e: (e.get("seq", 0),)):
                outcome = await _replay_one(session, entry, state)
                if outcome == "applied" or outcome.startswith("applied"):
                    applied += 1
                else:
                    conflicts.append(outcome)
                    if first_conflict_seq is None:
                        first_conflict_seq = entry.get("seq", 0)
            await session.commit()
        if conflicts:
            # Conflicted entries (and everything after them) must be retried
            # next cycle — the watermark stops right before the first one
            # instead of jumping past it.
            watermark = (first_conflict_seq or 1) - 1
        else:
            watermark = max(e.get("seq", 0) for e in entries)
        state.setdefault("imports", {})[rater] = max(
            _imported_seq(state, rater), watermark
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

def detect_shared(project_path: str, user: str | None = None) -> dict:
    """Detect whether a project lives in a shared/synced folder.

    Heuristics (first match wins):

    1. a ``.qcnext-shared`` marker file inside the project folder;
    2. a UNC path (``\\\\server\\share`` — Windows network shares);
    3. a ``changes/`` directory holding sidecar change files from OTHER
       raters (the project's own user is excluded).
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
            collaborators.append(
                {"user": rater, "last_sync": mtime, "pending_import": pending_import}
            )

    return {
        "ok": True,
        "enabled": sync_enabled(),
        "user": user,
        "pending_export": pending_export,
        "pending_import": sum(c["pending_import"] for c in collaborators),
        "collaborators": collaborators,
        "last_sync": _last_sync_ts,
        "last_error": _last_error,
        "last_error_at": _last_error_ts,
    }
