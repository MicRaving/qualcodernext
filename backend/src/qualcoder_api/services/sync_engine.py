"""Collaboration sync engine — versioned sidecars with in-app conflict resolution.

Each instance owns one append-only JSONL sidecar at
``<project>/changes/<instance_id>/changes.jsonl``.  On a 60-second cycle (and
on demand) the engine exports local ``sync_log`` rows (with their per-row
revision) and imports other instances' sidecars.  Replay uses a per-row
scalar clock (``sync_rev`` table): strictly newer rev → apply; equal rev +
different content → conflict; older rev → skip.  Conflicts are persisted to
``sync_conflict`` for in-app resolution.

Design principles
-----------------
- **Offline-first, folder-sync based** — no dedicated server required.
- **Per-instance sidecars** — same coder can run in two instances.
- **Per-row scalar clock (Lamport)** — concurrent edits detected by equal
  rev + different content.
- **Minimal sync files** — one append-only JSONL per instance, pruned when
  offline >24h.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.timeutil import now
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.audit_capture import current_user, suspended
from qualcoder_api.services.user_settings import get_instance_id

logger = logging.getLogger(__name__)

SYNC_DIR_NAME = "changes"
SYNC_INTERVAL_SECS = 60
SYNC_LOCK = asyncio.Lock()
SIDECAR_PRUNE_AFTER_SECS = 86400  # prune sidecars from instances offline >24h

# Cleanup: the sidecar and sync_log grow with every change.  The sidecar is
# compacted to one entry per (entity, pk) once it exceeds this many lines, and
# exported sync_log rows are trimmed (keeping the latest row per user so the
# per-user seq counter never resets).  This keeps the shared folder small and
# the replay fast — a fresh instance only ever sees the latest state per row.
SIDECAR_COMPACT_THRESHOLD_ENTRIES = 10_000
SIDECAR_COMPACT_THRESHOLD_BYTES = 2 * 1024 * 1024

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

# Natural (business) keys — the columns that identify the SAME logical row
# across instances even when their autoincrement PKs diverge (every instance
# starts its counters at 1, so two independently created rows collide).  These
# mirror the schema's UNIQUE constraints.  Replay matches by natural key FIRST
# and only falls back to PK for tables without one.
NATURAL_KEYS: dict[str, list[str]] = {
    "source": ["name"],
    "annotation": ["fid", "pos0", "pos1", "owner"],
    "attribute": ["name", "attr_type", "id"],
    "cases": ["name"],
    "code_cat": ["name"],
    "code_text": ["cid", "fid", "pos0", "pos1", "owner"],
    "code_name": ["name"],
    "journal": ["name"],
    "stored_sql": ["title"],
    "r_script": ["name"],
    "graph": ["name"],
    "dictionary": ["name"],
    "dictionary_entry": ["dict_id", "term"],
    "code_set": ["name"],
    # Composite-PK table: the pair (set_id, cid) is both the natural key and
    # the primary key.  FK translation normalises the values to local ids
    # before matching, so it is safe to treat both columns as natural.
    "code_set_member": ["set_id", "cid"],
}

# Foreign-key columns: ``column`` on a row stores the autoincrement PK of
# ``referenced entity``.  Because those PKs diverge between instances too, an
# incoming row's FK values must be translated (remote PK -> local PK) before
# it can be matched by natural key or inserted.  The special value
# "case_or_source" means the column refers to either ``cases`` or ``source``
# depending on the row's ``attr_type`` ("case" vs "file").
FK_REFERENCES: dict[str, dict[str, str]] = {
    "code_text": {"cid": "code_name", "fid": "source", "avid": "code_av"},
    "code_image": {"cid": "code_name", "id": "source"},
    "code_av": {"cid": "code_name", "id": "source"},
    "annotation": {"fid": "source"},
    "attribute": {"id": "case_or_source"},
    "case_text": {"caseid": "cases", "fid": "source"},
    "code_name": {"catid": "code_cat", "supercid": "code_name"},
    "code_cat": {"supercatid": "code_cat"},
    "dictionary_entry": {"dict_id": "dictionary"},
    "code_set_member": {"set_id": "code_set", "cid": "code_name"},
    "link": {"from_fid": "source", "to_fid": "source"},
    "creative_item": {"source_fid": "source"},
    "gr_cdct_text_item": {"grid": "graph", "supercatid": "code_cat", "catid": "code_cat", "cid": "code_name"},
    "gr_case_text_item": {"grid": "graph", "caseid": "cases"},
    "gr_file_text_item": {"grid": "graph", "fid": "source"},
    "gr_free_text_item": {"grid": "graph", "ctid": "code_text", "memo_ctid": "code_text", "memo_imid": "code_image", "memo_avid": "code_av"},
    "gr_pix_item": {"grid": "graph", "imid": "code_image"},
    "gr_av_item": {"grid": "graph", "avid": "code_av"},
    "gr_memo_item": {"grid": "graph"},
    "qtt_item": {"sheet_id": "qtt_sheet"},
}

# Primary-key column per synced entity.  ``_replay_one`` uses this to build
# ``WHERE pk_name = :pk`` clauses; composite keys (comma-joined column names)
# build ``WHERE c1 = :pk_0 AND c2 = :pk_1`` and use a ``":"``-joined pk_value.
# Mirrors the schema's PRIMARY KEY definitions (``tables.py``).
ENTITY_PKS: dict[str, str] = {
    "project": "rowid",
    "source": "id",
    "code_name": "cid",
    "code_cat": "catid",
    "code_text": "ctid",
    "code_image": "imid",
    "code_av": "avid",
    "annotation": "anid",
    "cases": "caseid",
    "case_text": "id",
    "attribute_type": "name",
    "attribute": "attrid",
    "journal": "jid",
    "stored_sql": "title",
    "files_filter": "filterid",
    "graph": "grid",
    "gr_cdct_text_item": "gtextid",
    "gr_case_text_item": "gcaseid",
    "gr_file_text_item": "gfileid",
    "gr_free_text_item": "gfreeid",
    "gr_memo_item": "gmemoid",
    "gr_cdct_line_item": "glineid",
    "gr_free_line_item": "gflineid",
    "gr_pix_item": "grpixid",
    "gr_av_item": "gr_avid",
    "link": "id",
    "dictionary": "id",
    "dictionary_entry": "id",
    "qtt_sheet": "id",
    "qtt_item": "id",
    "creative_item": "id",
    "comment": "id",
    "code_set": "id",
    "code_set_member": "set_id,cid",
    "r_script": "id",
}

# Dependency-ordered export/rebuild sequence: parent tables come before the
# tables that reference them (via FK_REFERENCES), so FK translation on the
# receiving side always has a recorded remap for the referenced row.
EXPORT_ORDER: list[str] = [
    "project",
    "source",
    "cases",
    "code_cat",
    "code_name",
    "attribute_type",
    "code_image",
    "code_av",
    "code_text",
    "annotation",
    "attribute",
    "case_text",
    "journal",
    "stored_sql",
    "files_filter",
    "graph",
    "gr_memo_item",
    "gr_cdct_text_item",
    "gr_case_text_item",
    "gr_file_text_item",
    "gr_free_text_item",
    "gr_pix_item",
    "gr_av_item",
    "gr_cdct_line_item",
    "gr_free_line_item",
    "dictionary",
    "dictionary_entry",
    "qtt_sheet",
    "qtt_item",
    "link",
    "creative_item",
    "comment",
    "code_set",
    "code_set_member",
    "r_script",
]


def _pk_cols(pk_name: str) -> list[str]:
    """The column(s) that make up a primary key (composite = comma-joined)."""
    if not pk_name:
        return []
    return [c.strip() for c in pk_name.split(",")]


def _pk_values(pk_name: str, pk_value: Any) -> list[Any]:
    """Split a pk_value back into per-column values (composite = ":"-joined)."""
    cols = _pk_cols(pk_name)
    if len(cols) <= 1:
        return [_as_pk(pk_value)]
    return [_as_pk(p) for p in str(pk_value).split(":")]


def _row_pk(pk_name: str, row: dict) -> Any:
    """The pk_value (single value, or composite ":"-joined) for a row dict."""
    cols = _pk_cols(pk_name)
    if len(cols) == 1:
        return row.get(pk_name)
    return ":".join(str(row.get(c, "")) for c in cols)


def _pk_where(pk_name: str, alias: str = "pk") -> tuple[str, list[str]]:
    """A ``WHERE`` clause matching all PK columns plus its bind parameter names."""
    cols = _pk_cols(pk_name)
    if len(cols) == 1:
        return f"{cols[0]} = :{alias}", [alias]
    params = [f"{alias}_{i}" for i in range(len(cols))]
    return " AND ".join(f"{c} = :{p}" for c, p in zip(cols, params, strict=True)), params

# Process-wide sync health — defined in sync.py (the compatibility shim)
# and injected here at import time to avoid circular imports.
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


# ── State (per-machine, outside the synced folder) ──────────────────────

def _state_path(project_path: str) -> Path:
    import hashlib
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
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as err:  # pragma: no cover
        logger.warning("sync state save failed: %s", err)


def _exported_seq(state: dict, instance: str) -> int:
    """Last exported sync_log id for this instance."""
    return int(state.get("exports", {}).get(instance, 0))


def _imported_seq(state: dict, instance: str) -> int:
    """Last imported seq from this remote instance."""
    return int(state.get("imports", {}).get(instance, 0))


def _recorded_conflicts(state: dict, instance: str) -> dict:
    """Return the conflicts dict for *instance* keyed by pk string."""
    conflicts = state.get("conflicts", {}).get(instance, [])
    result: dict[str, dict] = {}
    for c in conflicts:
        result[c.get("pk", "")] = c
    return result


def _conflict_summary(state: dict, instance: str) -> list[dict]:
    """Return a list of conflict summaries for *instance*."""
    return state.get("conflicts", {}).get(instance, [])


# ── Sidecar I/O ─────────────────────────────────────────────────────────

def _sidecar_path(project_path: str, instance_id: str) -> Path:
    return Path(project_path) / SYNC_DIR_NAME / instance_id / "changes.jsonl"


def _parse_sidecar(path: Path) -> list[dict]:
    """Read JSONL lines defensively; corrupt tails are dropped."""
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


def _append_sidecar(sidecar: Path, lines: str) -> None:
    """Append exported JSONL lines to a sidecar file (atomic tail)."""
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


# Indirection hooks — sync.py replaces these at import time so that
# ``monkeypatch.setattr(sync, "_append_sidecar", ...)`` takes effect.
_append_sidecar_hook = _append_sidecar
_insert_row_hook: Any = None  # set below after _insert_row is defined


def _compact_sidecar(sidecar: Path) -> int:
    """Rewrite a sidecar to one entry per (entity, pk), keeping the latest.

    The sidecar is append-only during normal operation, but it grows without
    bound as a project accumulates changes.  Once it passes the compaction
    threshold it is rewritten so each row appears exactly once (its newest
    entry).  This is safe because replay is idempotent and versioned: a fresh
    instance only needs the latest state per row, and existing instances have
    already advanced their import watermark past the dropped history.

    Returns the number of entries kept (0 when the file was left untouched).
    """
    entries = _parse_sidecar(sidecar)
    if not entries:
        return 0
    try:
        size = sidecar.stat().st_size
    except OSError:
        size = 0
    if len(entries) < SIDECAR_COMPACT_THRESHOLD_ENTRIES and size < SIDECAR_COMPACT_THRESHOLD_BYTES:
        return 0
    # Keep the latest entry per (entity, pk) — later entries win (they carry
    # a higher seq and rev).  Preserve the original order of first appearance
    # so the file stays a valid, ordered change log.
    latest: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for e in entries:
        key = (str(e.get("entity", "")), str(e.get("pk_value", "")))
        if key not in latest:
            order.append(key)
        latest[key] = e
    lines = "\n".join(
        json.dumps(latest[k], ensure_ascii=False) for k in order
    ) + "\n"
    tmp = sidecar.with_suffix(".tmp")
    try:
        tmp.write_text(lines, encoding="utf-8")
        tmp.replace(sidecar)
    except OSError as err:  # pragma: no cover - defensive
        logger.warning("sidecar compaction failed: %s", err)
        return 0
    return len(order)


async def _trim_sync_log(session: AsyncSession, exported_seq: int) -> int:
    """Delete already-exported sync_log rows, keeping the latest row per user.

    The change journal is only needed to (a) export rows newer than the
    watermark and (b) keep the per-user ``seq`` counter monotonic.  Rows at or
    below the export watermark have already reached the sidecar and are dead
    weight, so they are dropped — except the most recent row per user, which
    anchors the seq counter so it never resets.  Rows above the watermark are
    still pending export and are never touched.
    """
    result = await session.execute(
        text(
            "DELETE FROM sync_log WHERE id <= :wm AND id NOT IN ("
            "SELECT MAX(id) FROM sync_log GROUP BY user)"
        ),
        {"wm": exported_seq},
    )
    return int(getattr(result, "rowcount", 0) or 0)


# ── Export ───────────────────────────────────────────────────────────────

async def export_pending(session: AsyncSession, project_path: str, instance_id: str) -> dict:
    """Append sync_log rows newer than the watermark to the sidecar."""
    state = load_state(project_path)
    last_id = _exported_seq(state, instance_id)
    rows = (
        await session.execute(
            text(
                "SELECT id, ts, user, seq, entity, action, pk_name, pk_value, rev, row_json "
                "FROM sync_log WHERE id > :last ORDER BY id"
            ),
            {"last": last_id},
        )
    ).all()
    if not rows:
        return {"exported": 0}

    coder = current_user()
    sidecar = _sidecar_path(project_path, instance_id)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(
        json.dumps(
            {
                "seq": r[3],
                "instance": instance_id,
                "coder": coder,
                "entity": r[4],
                "action": r[5],
                "pk_name": r[6],
                "pk_value": r[7],
                "rev": r[8],
                "mtime": r[1],
                "row": json.loads(r[9]) if r[9] else None,
            },
            ensure_ascii=False,
        )
        for r in rows
    ) + "\n"
    try:
        await asyncio.to_thread(_append_sidecar, sidecar, lines)
    except OSError as err:
        logger.warning("sync sidecar append deferred: %s", err)
        return {"exported": 0, "deferred": len(rows)}

    state.setdefault("exports", {})[instance_id] = int(rows[-1][0])
    save_state(project_path, state)

    # Cleanup: compact the sidecar once it grows large, and drop the
    # already-exported sync_log rows so the journal never grows without bound.
    with contextlib.suppress(OSError):
        await asyncio.to_thread(_compact_sidecar, sidecar)
    try:
        await _trim_sync_log(session, int(rows[-1][0]))
        await session.commit()
    except Exception:  # pragma: no cover - defensive
        await session.rollback()

    return {"exported": len(rows)}


# ── Conflict recording ──────────────────────────────────────────────────

async def _record_conflict(
    session: AsyncSession,
    *,
    entity: str,
    pk: str,
    pk_name: str,
    local_rev: int,
    remote_rev: int,
    local_row: dict | None,
    remote_row: dict | None,
    remote_instance: str,
    remote_coder: str,
) -> None:
    """Persist a conflict to the sync_conflict table."""
    # Avoid duplicates: skip if an unresolved conflict for the same entity+pk exists.
    existing = await session.execute(
        text(
            "SELECT 1 FROM sync_conflict "
            "WHERE entity = :e AND pk = :p AND resolved_at IS NULL LIMIT 1"
        ),
        {"e": entity, "p": pk},
    )
    if existing.first() is not None:
        return

    await session.execute(
        text(
            "INSERT INTO sync_conflict "
            "(entity, pk, pk_name, local_rev, remote_rev, local_row, remote_row, "
            "remote_instance, remote_coder, detected_at) "
            "VALUES (:entity, :pk, :pk_name, :local_rev, :remote_rev, :local_row, "
            ":remote_row, :remote_instance, :remote_coder, :detected_at)"
        ),
        {
            "entity": entity,
            "pk": pk,
            "pk_name": pk_name,
            "local_rev": local_rev,
            "remote_rev": remote_rev,
            "local_row": json.dumps(local_row, ensure_ascii=False, default=str) if local_row else None,
            "remote_row": json.dumps(remote_row, ensure_ascii=False, default=str) if remote_row else None,
            "remote_instance": remote_instance,
            "remote_coder": remote_coder,
            "detected_at": now(),
        },
    )


# ── Replay ──────────────────────────────────────────────────────────────

async def _insert_row(session: AsyncSession, entity: str, row: dict) -> None:
    """Insert a row into *entity* (monkeypatchable in tests)."""
    cols = ", ".join(row.keys())
    placeholders = ", ".join(":" + k for k in row)
    await session.execute(
        text(f"INSERT INTO {entity} ({cols}) VALUES ({placeholders})"),
        row,
    )


def _as_pk(value: Any) -> int | str:
    """Coerce a sidecar PK to int when it looks numeric."""
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return value
    if isinstance(value, (int, float)):
        return int(value)
    return str(value)


def _normalize(v: Any) -> Any:
    """Normalize a value for content comparison.

    ``None``, ``""``, ``0`` and ``False`` all mean "empty" and compare equal —
    legacy sidecars omit columns or store ``None`` where the current schema
    stores a default (``weight=0``, ``memo_type=''``, ``important=0``, ...).
    """
    if v is None or v == "" or v == 0:
        return None
    return v


def _rows_equal(a: dict | None, b: dict | None, pk_name: str) -> bool:
    """Whether two row snapshots represent the same content.

    Ignores the primary key (per-instance identifier), treats missing or empty
    values as equal, and only compares columns present in BOTH snapshots — a
    legacy sidecar row that predates a schema column simply doesn't carry that
    column, which is not a divergence.
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    pk_cols = set(_pk_cols(pk_name))
    for k in set(a) & set(b):
        if k in pk_cols:
            continue
        if _normalize(a.get(k)) != _normalize(b.get(k)):
            return False
    return True


async def _read_row(
    session: AsyncSession, entity: str, pk_name: str, pk: Any
) -> dict | None:
    """Read a row by its primary key (None when missing)."""
    try:
        where, params = _pk_where(pk_name)
        binds = dict(zip(params, _pk_values(pk_name, pk), strict=True))
        result = await session.execute(
            text(f"SELECT * FROM {entity} WHERE {where}"), binds
        )
        mapping = result.mappings().first()
        if mapping:
            return {k: v for k, v in dict(mapping).items() if not k.startswith("_")}
    except Exception:  # pragma: no cover - table/row edge cases
        logger.debug("row read failed for %s pk=%r", entity, pk, exc_info=True)
    return None


async def _find_by_natural_key(
    session: AsyncSession, entity: str, row: dict, natural_keys: list[str], pk_name: str
) -> tuple[dict | None, Any]:
    """Find the local row (and its PK) that matches the natural-key columns.

    Columns whose incoming value is None are matched with ``IS NULL`` —
    dropping them from the WHERE clause would make the row match ANY local
    row agreeing on the remaining columns (e.g. a code_text with a NULL
    owner latching onto another coder's segment).
    """
    present = [k for k in natural_keys if k in row]
    if not present:
        return None, None
    where_parts = []
    params: dict[str, Any] = {}
    for k in present:
        if row.get(k) is None:
            where_parts.append(f"{k} IS NULL")
        else:
            where_parts.append(f"{k} = :nk_{k}")
            params[f"nk_{k}"] = row[k]
    where = " AND ".join(where_parts)
    try:
        result = await session.execute(
            text(f"SELECT * FROM {entity} WHERE {where} LIMIT 1"), params
        )
        mapping = result.mappings().first()
        if mapping:
            local_row = {k: v for k, v in dict(mapping).items() if not k.startswith("_")}
            return local_row, _row_pk(pk_name, local_row)
    except Exception:  # pragma: no cover - table/row edge cases
        logger.debug("natural-key lookup failed for %s", entity, exc_info=True)
    return None, None


def _translate_fks(entity: str, row: dict | None, remaps: dict | None) -> dict | None:
    """Translate FK columns in *row* from remote PKs to local PKs.

    ``remaps`` maps ``(referenced_entity, remote_pk) -> local_pk``.  Columns
    whose referenced entity has no recorded remap are left untouched (the PK
    simply did not diverge, or the reference is not yet known).
    """
    if not row or not remaps:
        return row
    refs = FK_REFERENCES.get(entity)
    if not refs:
        return row
    new_row = dict(row)
    for col, target in refs.items():
        val = new_row.get(col)
        if val is None:
            continue
        if target == "case_or_source":
            key = ("cases" if new_row.get("attr_type") == "case" else "source", str(val))
        else:
            key = (target, str(val))
        mapped = remaps.get(key)
        if mapped is not None:
            new_row[col] = _as_pk(mapped)
    return new_row


async def _read_sync_rev(
    session: AsyncSession, entity: str, pk_str: str
) -> tuple[int, bool, str]:
    """Return (rev, deleted, mtime) for a row's sync_rev entry (0/False/"" if none)."""
    result = await session.execute(
        text("SELECT rev, deleted, mtime FROM sync_rev WHERE entity = :e AND pk = :pk"),
        {"e": entity, "pk": pk_str},
    )
    info = result.first()
    if not info:
        return 0, False, ""
    return int(info[0]), bool(info[1]), str(info[2] or "")


def _record_remap(
    state: dict | None, remote_instance: str, entity: str, original: str, remapped: str
) -> None:
    """Persist a remote->local PK mapping so later cycles/updates land correctly."""
    if state is None or not remote_instance:
        return
    remaps = state.setdefault("pk_remaps", {}).setdefault(remote_instance, [])
    if not any(
        rm.get("entity") == entity and rm.get("original") == original
        for rm in remaps
    ):
        remaps.append({"entity": entity, "original": original, "remapped": remapped})


async def _replay_one(
    session: AsyncSession,
    entry: dict,
    state: dict | None = None,
    remaps: dict | None = None,
    remote_instance: str | None = None,
) -> dict:
    """Apply a single incoming change with versioned conflict detection.

    Matching is natural-key-first: rows are identified by their business keys
    (mirroring the schema's UNIQUE constraints) so that autoincrement PK
    collisions between instances never fabricate duplicates or false
    conflicts.  Foreign-key columns are translated from remote PKs to local
    PKs before matching/inserting.

    Returns a structured outcome dict:
    - ``{"status": "applied", ...}``
    - ``{"status": "conflict", ...}``
    - ``{"status": "skipped", ...}``
    - ``{"status": "retry", ...}``
    """
    entity = entry.get("entity")
    action = entry.get("action")
    pk_name = entry.get("pk_name")
    pk_value = entry.get("pk_value")
    row = entry.get("row")
    incoming_rev = int(entry.get("rev") or 0)
    if remote_instance is None:
        remote_instance = entry.get("instance") or ""
    remote_coder = entry.get("coder") or entry.get("user") or ""
    # Legacy sidecars carry ``ts``/``user`` instead of ``mtime``/``coder``.
    mtime = entry.get("mtime") or entry.get("ts") or now()

    if not entity or not action or not pk_name or pk_value is None:
        return {"status": "skipped", "reason": "malformed"}
    if entity not in SYNC_ENTITIES:
        return {"status": "skipped", "reason": f"unknown table {entity}"}
    table = getattr(tables, entity, None)
    if table is None:
        return {"status": "skipped", "reason": f"no table object for {entity}"}

    natural_keys = NATURAL_KEYS.get(entity) or []

    # Translate FK references in the incoming row (remote PK -> local PK).
    if row:
        row = _translate_fks(entity, row, remaps)

    # Resolve the local identity of this row — natural key first, PK fallback.
    local_pk: Any = _as_pk(pk_value)
    local_row: dict | None = None
    matched_nk = False

    if natural_keys and row:
        local_row, nk_pk = await _find_by_natural_key(
            session, entity, row, natural_keys, pk_name
        )
        if local_row is not None:
            local_pk = nk_pk
            matched_nk = True

    # Fall back to PK identity only when there is no natural key, or for
    # update/delete (a rename changes the natural-key values but keeps the PK).
    # For an *insert* with a natural key that found no local match, the row is
    # genuinely new — a PK lookup would wrongly latch onto an unrelated row
    # that happens to share the autoincrement PK.
    if not matched_nk and (not natural_keys or action in ("update", "delete")):
        if remaps and remote_instance:
            mapped = remaps.get((entity, str(pk_value)))
            if mapped is not None:
                local_pk = _as_pk(mapped)
        local_row = await _read_row(session, entity, pk_name, local_pk)

    pk_str = str(local_pk) if local_pk is not None else str(pk_value)

    # Record the remote->local PK mapping whenever we resolve a row's local
    # identity (even on a natural-key converge), so later rows that reference
    # this entity's PK (FK columns) translate correctly.
    if (
        local_row is not None
        and remaps is not None
        and remote_instance
        and str(pk_value) != str(local_pk)
        and (entity, str(pk_value)) not in remaps
    ):
        remaps[(entity, str(pk_value))] = str(local_pk)
        _record_remap(state, remote_instance, entity, str(pk_value), str(local_pk))

    local_rev, _local_deleted, local_mtime = await _read_sync_rev(session, entity, pk_str)
    # Backfilled sync_rev rows have an empty mtime — fall back to the row's
    # own ``date`` column so the timestamp tiebreaker still works for legacy data.
    if not local_mtime and local_row and local_row.get("date"):
        local_mtime = str(local_row.get("date") or "")

    def _conflict(reason: str) -> dict:
        return {"status": "conflict", "entity": entity, "pk": pk_str, "action": action, "reason": reason}

    async def _record(local_rev: int, remote_rev: int, local_row: dict | None, remote_row: dict | None) -> None:
        await _record_conflict(
            session,
            entity=entity,
            pk=pk_str,
            pk_name=pk_name,
            local_rev=local_rev,
            remote_rev=remote_rev,
            local_row=local_row,
            remote_row=remote_row,
            remote_instance=remote_instance,
            remote_coder=remote_coder,
        )

    async def _upsert_sync_rev(rev: int, deleted: bool, ts: str | None = None) -> None:
        await session.execute(
            text(
                "INSERT INTO sync_rev (entity, pk, rev, mtime, origin, deleted) "
                "VALUES (:e, :pk, :rev, :ts, :origin, :del) "
                "ON CONFLICT(entity, pk) DO UPDATE SET rev = :rev, mtime = :ts, "
                "origin = :origin, deleted = :del"
            ),
            {"e": entity, "pk": pk_str, "rev": rev, "ts": ts or mtime,
             "origin": remote_instance, "del": 1 if deleted else 0},
        )

    def remote_wins() -> bool | None:
        """Whether the remote version wins over the local one.

        Returns True (remote newer), False (local newer), or None when the two
        are undecidable (equal rev and no usable timestamps) — which must be
        surfaced as a conflict.
        """
        if incoming_rev != local_rev:
            return incoming_rev > local_rev
        # Equal rev: use timestamps (rev==0 is the migration baseline and
        # carries no Lamport information; legacy sidecars are also rev==0).
        if mtime and local_mtime:
            if mtime > local_mtime:
                return True
            if mtime < local_mtime:
                return False
            return None  # equal timestamps — undecidable
        return None

    async def _insert_fresh(local_row: dict | None, remote_row: dict | None) -> dict:
        """Insert *remote_row* (a genuinely new logical row) under a fresh local
        PK, recording the remote->local mapping for later references.

        Auto-increment PKs get a fresh ``MAX+1`` value (the remote PK may be
        taken by an unrelated row); text PKs (e.g. ``attribute_type.name``)
        keep the incoming value — they can't collide via a shared counter.
        """
        insert_row = dict(row) if row else {}
        if not insert_row:
            return {"status": "skipped", "reason": "no row"}
        pk_cols = _pk_cols(pk_name)
        fresh_pk: Any = None
        if len(pk_cols) == 1:
            # Auto-increment PKs get a fresh ``MAX+1`` value (the remote PK may
            # be taken by an unrelated row); text PKs (e.g.
            # ``attribute_type.name``) keep the incoming value.
            incoming_pk = _as_pk(pk_value)
            if isinstance(incoming_pk, int):
                max_pk_row = await session.execute(
                    text(f"SELECT COALESCE(MAX({pk_name}), 0) FROM {entity}")
                )
                fresh_pk = int(max_pk_row.scalar() or 0) + 1
            else:
                fresh_pk = incoming_pk
            insert_row[pk_name] = fresh_pk
        # Composite PKs (e.g. code_set_member) keep their incoming values — the
        # columns are already FK-translated to local ids and cannot collide.
        try:
            async with session.begin_nested():
                await _insert_row(session, entity, insert_row)
        except OperationalError:
            return {"status": "retry", "entity": entity, "pk": pk_str, "action": action}
        except IntegrityError:
            # A non-PK unique constraint still fires — a real conflict.
            await _record(local_rev, incoming_rev, local_row, remote_row)
            return _conflict("unique constraint")
        if fresh_pk is not None and remaps is not None and remote_instance:
            remaps[(entity, str(pk_value))] = str(fresh_pk)
        if fresh_pk is not None:
            _record_remap(state, remote_instance, entity, str(pk_value), str(fresh_pk))
        await _upsert_sync_rev(incoming_rev if incoming_rev else 1, False)
        return {"status": "applied", "detail": "inserted"}

    # ── delete ────────────────────────────────────────────────────────────
    if action == "delete":
        if local_row is None:
            # Nothing to delete locally — record a tombstone so the delete
            # propagates and future re-inserts of the same row don't resurrect it.
            await _upsert_sync_rev(max(incoming_rev, local_rev), True)
            return {"status": "applied", "detail": "tombstone"}
        if incoming_rev == 0 and local_rev == 0:
            # Both at the unversioned baseline (rev==0).  The pre-versioned
            # sync engine could record deletes that were later rolled back or
            # re-inserted without a matching insert, so a rev-0 delete is
            # ambiguous.  Never destroy local data on ambiguous evidence —
            # skip it; versioned (rev>0) deletes still propagate normally.
            return {"status": "skipped", "reason": "ambiguous legacy delete"}
        winner = remote_wins()
        if winner is True:
            where, params = _pk_where(pk_name)
            binds = dict(zip(params, _pk_values(pk_name, local_pk), strict=True))
            await session.execute(text(f"DELETE FROM {entity} WHERE {where}"), binds)
            await _upsert_sync_rev(incoming_rev, True)
            return {"status": "applied"}
        if winner is False:
            return {"status": "skipped", "reason": "stale"}
        # Undecidable concurrent edit-vs-delete.
        await _record(local_rev, incoming_rev, local_row, None)
        return _conflict("edit vs delete")

    # ── insert / update ───────────────────────────────────────────────────
    if row is None:
        return {"status": "skipped", "reason": "no row"}

    if local_row is None:
        return await _insert_fresh(None, row)

    # Local row exists — decide converge / apply / skip / conflict.
    if _rows_equal(row, local_row, pk_name):
        if incoming_rev > local_rev:
            await _upsert_sync_rev(incoming_rev, False)
        return {"status": "skipped", "reason": "converged"}

    winner = remote_wins()
    if winner is True:
        update_row = dict(row)
        pk_cols = set(_pk_cols(pk_name))
        update_cols = {k: v for k, v in update_row.items() if k not in pk_cols}
        if update_cols:
            set_clause = ", ".join(f"{k} = :{k}" for k in update_cols)
            where, params = _pk_where(pk_name)
            binds = dict(zip(params, _pk_values(pk_name, local_pk), strict=True))
            await session.execute(
                text(f"UPDATE {entity} SET {set_clause} WHERE {where}"),
                {**update_cols, **binds},
            )
        await _upsert_sync_rev(incoming_rev, False)
        return {"status": "applied"}
    if winner is False:
        return {"status": "skipped", "reason": "stale"}

    # Undecidable concurrent edit.
    await _record(local_rev, incoming_rev, local_row, row)
    return _conflict("concurrent edit")


# ── Import ───────────────────────────────────────────────────────────────

async def import_pending(session: AsyncSession, project_path: str, instance_id: str) -> dict:
    """Read every other instance's sidecar and replay rows newer than the watermark."""
    state = load_state(project_path)
    changes_root = Path(project_path) / SYNC_DIR_NAME
    report: dict[str, dict] = {}
    if not changes_root.is_dir():
        return report

    for sidecar_dir in sorted(changes_root.iterdir()):
        if not sidecar_dir.is_dir() or sidecar_dir.name == instance_id:
            continue
        sidecar = sidecar_dir / "changes.jsonl"
        if not sidecar.exists():
            continue

        remote_instance = sidecar_dir.name

        # Replay rows newer than the watermark, keeping only the LATEST entry
        # per (entity, pk) above it.  Append-only sidecars accumulate
        # delete→insert cycles for the same row; replaying the whole history
        # would churn the local DB (delete the row, re-insert it under a new
        # PK).  Keeping the newest entry per row collapses that churn to the
        # row's final state, which is idempotent under natural-key matching.
        pending: dict[int, dict] = {}
        latest_seq: dict[tuple[str, str], int] = {}
        for e in _parse_sidecar(sidecar):
            seq = int(e.get("seq", 0))
            if seq <= _imported_seq(state, remote_instance):
                continue
            key = (str(e.get("entity", "")), str(e.get("pk_value", "")))
            prev = latest_seq.get(key)
            if prev is not None and prev >= seq:
                continue
            if prev is not None:
                pending.pop(prev, None)
            latest_seq[key] = seq
            pending[seq] = e
        if not pending:
            continue

        applied = 0
        conflicts: list[dict] = []
        retries: list[dict] = []
        highest_applied: int = _imported_seq(state, remote_instance)
        # Build the remote->local PK remap index from persisted state so FK
        # columns and later updates land on the right local row.
        remaps: dict[tuple[str, str], str] = {}
        for rm in state.get("pk_remaps", {}).get(remote_instance, []):
            remaps[(str(rm.get("entity", "")), str(rm.get("original", "")))] = str(rm.get("remapped", ""))
        async with suspended():
            for seq in sorted(pending):
                entry = pending[seq]
                try:
                    outcome = await _replay_one(
                        session, entry, state, remaps, remote_instance
                    )
                except Exception as exc:
                    # Unexpected error — rollback this entry's partial work,
                    # record as retry, and stop importing this instance.
                    logger.warning("sync replay error for %s seq %s: %s", remote_instance, seq, exc)
                    await session.rollback()
                    retries.append({"entity": entry.get("entity", ""), "pk": str(entry.get("pk_value", "")), "action": entry.get("action", "")})
                    break
                status = outcome.get("status")
                if status == "applied":
                    applied += 1
                    highest_applied = max(highest_applied, seq)
                    # Commit after each successful apply so a later failure
                    # doesn't roll back already-applied entries.
                    await session.commit()
                elif status == "retry":
                    retries.append({k: outcome[k] for k in ("entity", "pk", "action")})
                    await session.rollback()
                    break  # Stop replaying this instance; watermark stays below.
                elif status == "conflict":
                    conflicts.append({k: outcome[k] for k in ("entity", "pk", "action", "reason")})
                    highest_applied = max(highest_applied, seq)
                    # Commit the conflict record so it survives.
                    await session.commit()
                elif status == "skipped":
                    highest_applied = max(highest_applied, seq)
                    # No DB changes for skipped, but commit any savepoint work.
                    await session.commit()
            # Final flush in case loop exited without a trailing commit.
            try:
                await session.commit()
            except Exception:
                await session.rollback()
        # Write state file BEFORE any DB commit dependency — the watermark
        # must advance even if a later DB operation fails, so the next cycle
        # doesn't re-read all entries from scratch.
        state.setdefault("imports", {})[remote_instance] = max(
            _imported_seq(state, remote_instance), highest_applied
        )
        # Persist conflicts in state for later inspection / retry.
        if conflicts:
            state.setdefault("conflicts", {})[remote_instance] = (
                state.get("conflicts", {}).get(remote_instance, []) + conflicts
            )
        save_state(project_path, state)
        report[remote_instance] = {
            "applied": applied,
            "conflicts": conflicts,
            "retries": retries,
        }
    return report


# ── Full-state export & sandbox rebuild ─────────────────────────────────

def _max_sidecar_seq(project_path: str) -> int:
    """The highest ``seq`` across every instance's sidecar (0 when none)."""
    changes_root = Path(project_path) / SYNC_DIR_NAME
    if not changes_root.is_dir():
        return 0
    max_seq = 0
    for sidecar_dir in changes_root.iterdir():
        if not sidecar_dir.is_dir():
            continue
        sidecar = sidecar_dir / "changes.jsonl"
        if not sidecar.exists():
            continue
        for e in _parse_sidecar(sidecar):
            try:
                max_seq = max(max_seq, int(e.get("seq", 0)))
            except (TypeError, ValueError):
                continue
    return max_seq


async def export_full_state(
    session: AsyncSession, project_path: str, instance_id: str
) -> dict:
    """Snapshot the ENTIRE project into this instance's sidecar.

    Called once on collaboration activation (and after each consolidation) so
    a fresh instance, or a rebuilt sandbox, can reconstruct the full database
    from the sidecars alone.  Rows are emitted in dependency order (parents
    first) so FK translation on the receiving side always has a recorded remap.
    Entries carry the row's current ``sync_rev`` (0 when it has none) so live
    instances replaying the snapshot do not fabricate spurious conflicts.

    Returns ``{"exported": N}`` (or ``{"exported": 0, "deferred": N}`` when the
    sidecar write was deferred).
    """
    state = load_state(project_path)
    coder = current_user()
    rev_map: dict[tuple[str, str], int] = {}
    result = await session.execute(text("SELECT entity, pk, rev FROM sync_rev"))
    for entity, pk, rev in result:
        rev_map[(str(entity), str(pk))] = int(rev or 0)

    base_seq = _max_sidecar_seq(project_path)
    entries: list[dict] = []
    ts = now()
    for entity in EXPORT_ORDER:
        pk_name = ENTITY_PKS.get(entity)
        if not pk_name:
            continue
        try:
            rows = await session.execute(text(f"SELECT * FROM {entity}"))
        except Exception:  # pragma: no cover - schema drift
            continue
        for mapping in rows.mappings():
            row = {k: v for k, v in dict(mapping).items() if not k.startswith("_")}
            if entity == "project":
                pk_value: Any = 1
            else:
                pk_value = _row_pk(pk_name, row)
            if pk_value is None:
                continue
            base_seq += 1
            entries.append({
                "seq": base_seq,
                "instance": instance_id,
                "coder": coder,
                "entity": entity,
                "action": "insert",
                "pk_name": pk_name,
                "pk_value": pk_value,
                "rev": rev_map.get((entity, str(pk_value)), 0),
                "mtime": ts,
                "row": row,
            })

    if not entries:
        return {"exported": 0}

    sidecar = _sidecar_path(project_path, instance_id)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n"
    try:
        await asyncio.to_thread(_append_sidecar, sidecar, lines)
    except OSError as err:  # pragma: no cover - defensive
        logger.warning("full-state export append deferred: %s", err)
        return {"exported": 0, "deferred": len(entries)}

    # Record the snapshot marker so the caller can advance the consolidation
    # watermark and know the sidecar now carries a full snapshot up to this seq.
    state["snapshot"] = {"instance": instance_id, "seq": base_seq, "at": ts}
    save_state(project_path, state)
    return {"exported": len(entries)}


async def rebuild_from_sidecars(
    session_factory, project_path: str, instance_id: str
) -> dict:
    """Rebuild a (fresh, empty) sandbox database from the sidecar change log.

    Gathers every instance's sidecar, keeps the latest entry per (entity, pk)
    across all instances, then replays them in dependency order so FK
    translation and remap recording work.  ``_replay_one`` assigns fresh local
    PKs and backfills ``sync_rev``.  The seeded ``project`` row (created with a
    new schema) is replaced by the exported project row.

    The caller is expected to have created and opened a fresh sandbox and to
    pass its ``session_factory``.  Returns an outcome report.
    """
    state = load_state(project_path)
    changes_root = Path(project_path) / SYNC_DIR_NAME

    latest: dict[tuple[str, str], dict] = {}
    max_seq_by_instance: dict[str, int] = {}
    if changes_root.is_dir():
        for sidecar_dir in changes_root.iterdir():
            if not sidecar_dir.is_dir():
                continue
            remote_instance = sidecar_dir.name
            sidecar = sidecar_dir / "changes.jsonl"
            if not sidecar.exists():
                continue
            inst_max = 0
            for e in _parse_sidecar(sidecar):
                try:
                    seq = int(e.get("seq", 0))
                except (TypeError, ValueError):
                    seq = 0
                inst_max = max(inst_max, seq)
                key = (str(e.get("entity", "")), str(e.get("pk_value", "")))
                prev = latest.get(key)
                if prev is not None and int(prev.get("seq", 0)) >= seq:
                    continue
                latest[key] = e
            if inst_max:
                max_seq_by_instance[remote_instance] = inst_max

    order = {entity: i for i, entity in enumerate(EXPORT_ORDER)}
    ordered = sorted(
        latest.values(),
        key=lambda e: (order.get(str(e.get("entity", "")), 99), int(e.get("seq", 0))),
    )

    applied = conflicts = retries = 0
    remaps: dict[tuple[str, str], str] = {}
    async with session_factory() as session, suspended():
        # Drop the schema-seeded project row so the exported one replays in.
        await session.execute(text("DELETE FROM project"))
        for entry in ordered:
            try:
                outcome = await _replay_one(
                    session, entry, state, remaps, entry.get("instance") or ""
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("rebuild replay error for %s: %s", entry.get("entity"), exc)
                await session.rollback()
                retries += 1
                break
            status = outcome.get("status")
            if status == "applied":
                applied += 1
            elif status == "conflict":
                conflicts += 1
            elif status == "retry":
                retries += 1
                break
            await session.commit()
        # If no project row came through the sidecars, reseed a minimal one.
        count = (await session.execute(text("SELECT COUNT(*) FROM project"))).scalar()
        if not count:
            await session.execute(
                text(
                    "INSERT INTO project (databaseversion, date, memo, about, codername) "
                    "VALUES ('v31', :ts, '', :about, :coder)"
                ),
                {"ts": now(), "about": "rebuilt sandbox", "coder": current_user()},
            )
            await session.commit()

    # Advance each instance's import watermark so the next real sync cycle does
    # not re-replay the entire history from scratch.
    for remote_instance, inst_max in max_seq_by_instance.items():
        state.setdefault("imports", {})[remote_instance] = max(
            _imported_seq(state, remote_instance), inst_max
        )
    state.setdefault("imports", {})[instance_id] = max(
        _imported_seq(state, instance_id), _max_sidecar_seq(project_path)
    )
    save_state(project_path, state)

    return {
        "applied": applied,
        "conflicts": conflicts,
        "retries": retries,
        "entries": len(ordered),
    }


# ── Conflict resolution ─────────────────────────────────────────────────

async def resolve_conflict(
    session_factory,
    project_path: str,
    conflict_id: int,
    resolution: str,
    merged_row: dict | None = None,
) -> dict:
    """Resolve a conflict by choosing local, remote, or a merged version.

    The resolution is applied to the local DB and a new sync_log entry is
    emitted so other instances converge.

    Serialized app-wide by SYNC_LOCK: a background import cycle replaying
    the same (entity, pk) while the resolution is mid-flight would otherwise
    interleave UPDATE/INSERT/tombstone writes.
    """
    async with SYNC_LOCK:
        return await _resolve_conflict_locked(
            session_factory, project_path, conflict_id, resolution, merged_row
        )


async def _resolve_conflict_locked(
    session_factory,
    project_path: str,
    conflict_id: int,
    resolution: str,
    merged_row: dict | None = None,
) -> dict:
    instance_id = get_instance_id()
    async with session_factory() as session:
        row = await session.execute(
            text("SELECT * FROM sync_conflict WHERE id = :id"),
            {"id": conflict_id},
        )
        conflict = row.mappings().first()
        if not conflict:
            return {"ok": False, "reason": "conflict not found"}
        if conflict["resolved_at"] is not None:
            return {"ok": False, "reason": "already resolved"}

        entity = conflict["entity"]
        pk = conflict["pk"]
        pk_name = conflict["pk_name"]
        local_rev = int(conflict["local_rev"])
        remote_rev = int(conflict["remote_rev"])
        table = getattr(tables, entity, None)
        if table is None:
            return {"ok": False, "reason": f"unknown entity {entity}"}

        local_pk = _as_pk(pk)
        new_rev = max(local_rev, remote_rev) + 1
        ts = now()

        # The snapshot in ``sync_conflict.local_row`` may be stale or (for
        # conflicts recorded before the natural-key rework) null even though
        # the row exists locally.  Re-read the authoritative local row.
        current_local = await _read_row(session, entity, pk_name, local_pk)

        # Whether the resolved outcome is a deleted row (drives the sync_log
        # action so other instances converge to the same state).
        resolved_deleted = False

        if resolution == "local":
            # Keep local — just bump rev so others see it as newer.  Only when
            # the row is genuinely absent locally does the resolution
            # propagate as a delete.
            resolved_deleted = current_local is None

        elif resolution == "remote":
            remote_row = json.loads(conflict["remote_row"]) if conflict["remote_row"] else None
            if remote_row:
                # Apply remote row.
                update_row = dict(remote_row)
                update_row[pk_name] = local_pk
                # Check if row still exists locally.
                existing = await session.execute(
                    text(f"SELECT 1 FROM {entity} WHERE {pk_name} = :pk"),
                    {"pk": local_pk},
                )
                if existing.first():
                    update_cols = {k: v for k, v in update_row.items() if k != pk_name}
                    if update_cols:
                        set_clause = ", ".join(f"{k} = :{k}" for k in update_cols)
                        await session.execute(
                            text(f"UPDATE {entity} SET {set_clause} WHERE {pk_name} = :pk"),
                            {**update_cols, "pk": local_pk},
                        )
                else:
                    cols = ", ".join(update_row.keys())
                    placeholders = ", ".join(":" + k for k in update_row)
                    await session.execute(
                        text(f"INSERT INTO {entity} ({cols}) VALUES ({placeholders})"),
                        update_row,
                    )
            else:
                # Remote was a delete.
                await session.execute(
                    text(f"DELETE FROM {entity} WHERE {pk_name} = :pk"),
                    {"pk": local_pk},
                )
                resolved_deleted = True

        elif resolution == "merged" and merged_row:
            apply_row = dict(merged_row)
            apply_row[pk_name] = local_pk
            existing = await session.execute(
                text(f"SELECT 1 FROM {entity} WHERE {pk_name} = :pk"),
                {"pk": local_pk},
            )
            if existing.first():
                update_cols = {k: v for k, v in apply_row.items() if k != pk_name}
                if update_cols:
                    set_clause = ", ".join(f"{k} = :{k}" for k in update_cols)
                    await session.execute(
                        text(f"UPDATE {entity} SET {set_clause} WHERE {pk_name} = :pk"),
                        {**update_cols, "pk": local_pk},
                    )
            else:
                cols = ", ".join(apply_row.keys())
                placeholders = ", ".join(":" + k for k in apply_row)
                await session.execute(
                    text(f"INSERT INTO {entity} ({cols}) VALUES ({placeholders})"),
                    apply_row,
                )
        else:
            return {"ok": False, "reason": f"unknown resolution: {resolution}"}

        # Update sync_rev for the resolved row (tombstone when deleted).
        await session.execute(
            text("UPDATE sync_rev SET rev = :rev, mtime = :ts, origin = :origin, deleted = :del WHERE entity = :e AND pk = :pk"),
            {"rev": new_rev, "ts": ts, "origin": instance_id, "del": 1 if resolved_deleted else 0, "e": entity, "pk": pk},
        )

        # Read the resulting row for the sync_log entry.
        resolved_row = None
        try:
            r = await session.execute(text(f"SELECT * FROM {entity} WHERE {pk_name} = :pk"), {"pk": local_pk})
            m = r.mappings().first()
            if m:
                resolved_row = {k: v for k, v in dict(m).items() if not k.startswith("_")}
        except Exception:
            pass

        # Emit a sync_log entry for the resolution (captured for export).  A
        # delete resolution propagates as a delete so other instances remove
        # the row too.  The per-user MAX(seq)+1 counter can collide with a
        # concurrent writer — retry inside a savepoint (same pattern as
        # audit_capture.capture) so the resolution itself is never rolled
        # back with it.
        action = "delete" if resolved_deleted else "update"
        for _attempt in range(3):
            try:
                async with session.begin_nested():
                    await session.execute(
                        text(
                            "INSERT INTO sync_log (ts, user, seq, entity, action, pk_name, pk_value, rev, row_json) "
                            "VALUES (:ts, :user, "
                            "(SELECT COALESCE(MAX(seq), 0) + 1 FROM sync_log WHERE user = :user2), "
                            ":entity, :action, :pk_name, :pk, :rev, :row_json)"
                        ),
                        {
                            "ts": ts,
                            "user": current_user(),
                            "user2": current_user(),
                            "entity": entity,
                            "action": action,
                            "pk_name": pk_name,
                            "pk": pk,
                            "rev": new_rev,
                            "row_json": json.dumps(resolved_row, ensure_ascii=False, default=str) if resolved_row else None,
                        },
                    )
                break
            except IntegrityError:
                continue
        else:
            logger.warning(
                "sync_log seq collision while resolving conflict %s for user %s",
                conflict_id,
                current_user(),
            )

        # Mark the conflict as resolved.
        await session.execute(
            text(
                "UPDATE sync_conflict SET resolved_at = :ts, resolution = :res WHERE id = :id"
            ),
            {"ts": ts, "res": resolution, "id": conflict_id},
        )

        await session.commit()
        return {"ok": True, "resolution": resolution}


async def resolve_all_conflicts(
    session_factory,
    project_path: str,
    resolution: str,
) -> dict:
    """Resolve every pending conflict with the same strategy.

    ``resolution`` is one of "local" (keep mine everywhere) or "remote" (take
    theirs everywhere).  "merged" is not supported in bulk — a merged row is
    per-conflict by definition.  Each conflict is resolved through the same
    path as a single resolution, so the rev bump and sync_log propagation are
    identical.  Returns the number of conflicts resolved.
    """
    if resolution not in ("local", "remote"):
        return {"ok": False, "reason": "bulk resolution must be 'local' or 'remote'"}
    async with session_factory() as session:
        rows = await session.execute(
            text("SELECT id FROM sync_conflict WHERE resolved_at IS NULL ORDER BY id")
        )
        ids = [r[0] for r in rows]
    resolved = 0
    for conflict_id in ids:
        result = await resolve_conflict(
            session_factory, project_path, conflict_id, resolution, None
        )
        if result.get("ok"):
            resolved += 1
    return {"ok": True, "resolved": resolved}


# ── Status ───────────────────────────────────────────────────────────────

async def sync_status(session_factory, project_path: str, instance_id: str) -> dict:
    """Current sync state for the toolbar indicator."""
    _reset_health_for_project(project_path)
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


# ── Cycle ────────────────────────────────────────────────────────────────

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
