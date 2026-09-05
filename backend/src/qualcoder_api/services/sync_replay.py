"""Sync replay — row helpers, FK translation, versioned replay FSM, and
the export/import/full-state pipelines."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.timeutil import now
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.audit_capture import current_user, suspended
from qualcoder_api.services.sync_schema import (
    ENTITY_PKS,
    EXPORT_ORDER,
    FK_REFERENCES,
    NATURAL_KEYS,
    SYNC_DIR_NAME,
    SYNC_ENTITIES,
    _as_pk,
    _pk_cols,
    _pk_values,
    _pk_where,
    _row_pk,
)
from qualcoder_api.services.sync_sidecar import (
    _compact_sidecar,
    _max_sidecar_seq,
    _parse_sidecar,
    _sidecar_path,
    _trim_sync_log,
)
from qualcoder_api.services.sync_state import (
    _exported_seq,
    _imported_seq,
    load_state,
    save_state,
)

logger = logging.getLogger(__name__)


def _facade():
    """Late-bound access to the ``sync_engine`` facade namespace.

    services/sync.py and the test-suite monkey-patch several helpers
    (``_append_sidecar``, ``_insert_row``) ON the facade module; resolving
    them through it at CALL time keeps those patches effective after the
    module split. Lazy import avoids the circular dependency."""
    from qualcoder_api.services import sync_engine

    return sync_engine


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
    # LSTeach sidecars contain legacy columns (e.g. source.sort_index)
    # that no longer exist in the current schema.  Filter to known columns
    # so a stale sidecar does not abort the entire rebuild with
    # "no column named sort_index" (OperationalError → retry → empty sandbox).
    table = getattr(tables, entity, None)
    if table is not None:
        try:
            allowed = {c.name for c in table.columns}
            row = {k: v for k, v in row.items() if k in allowed}
        except Exception:
            pass
    if not row:
        return
    cols = ", ".join(row.keys())
    placeholders = ", ".join(":" + k for k in row)
    await session.execute(
        text(f"INSERT INTO {entity} ({cols}) VALUES ({placeholders})"),
        row,
    )


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
        remapped = False
        if remaps and remote_instance:
            mapped = remaps.get((entity, str(pk_value)))
            if mapped is not None:
                local_pk = _as_pk(mapped)
                remapped = True
        # Without a recorded remap, an integer PK on a natural-key-less table
        # (case links, image/AV codings, comments, …) names NO local row: the
        # counters diverge per instance, so a blind lookup latches onto an
        # unrelated occupant — overwriting it on update, deleting it on
        # delete, or faking a "concurrent edit" on insert instead of adding
        # the genuinely new row.  Leave it unset (delete→tombstone,
        # update/insert→fresh row).  Text PKs double as natural keys and the
        # singleton ``project`` row is shared by all instances, so both keep
        # the lookup.
        if remapped or not (
            not natural_keys
            and entity != "project"
            and isinstance(_as_pk(pk_value), int)
        ):
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
                await _facade()._insert_row(session, entity, insert_row)
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
        # Filter legacy columns (e.g. source.sort_index) that no longer exist.
        table = getattr(tables, entity, None)
        if table is not None:
            try:
                allowed = {c.name for c in table.columns}
                update_cols = {k: v for k, v in update_cols.items() if k in allowed}
            except Exception:
                pass
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
    # Per-session replay files (new spec 2a) vs legacy per-instance sidecars
    from qualcoder_api.services.sync_sidecar import _is_session_id, _replay_path

    is_session = _is_session_id(instance_id)
    if is_session:
        sidecar = _replay_path(project_path, instance_id)
    else:
        sidecar = _sidecar_path(project_path, instance_id)
    sidecar.parent.mkdir(parents=True, exist_ok=True)

    # Sidecar seqs are GLOBAL across the whole shared folder (the activation
    # snapshot numbers from the same space). Numbering incremental entries by
    # sync_log.id instead restarted at 1, which fell at-or-below the seq
    # watermarks of peers that had replayed the snapshot — every subsequent
    # change was then silently dropped on import. Continue the global
    # sequence instead.
    base_seq = _max_sidecar_seq(project_path)
    lines = "\n".join(
        json.dumps(
            {
                "seq": base_seq + i,
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
        for i, r in enumerate(rows, start=1)
    ) + "\n"
    try:
        await asyncio.to_thread(_facade()._append_sidecar, sidecar, lines)
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


# ── Import ───────────────────────────────────────────────────────────────

async def import_pending(session: AsyncSession, project_path: str, instance_id: str) -> dict:
    """Read every other instance's sidecar and replay rows newer than the watermark."""

    state = load_state(project_path)
    report: dict[str, dict] = {}

    # Collect all replay sources: per-session replays + legacy sidecars
    replay_sources: list[tuple[Path, str]] = []

    # Per-session replays (new spec 2a) — skip our own session
    replays_root = Path(project_path) / "replays"
    if replays_root.is_dir():
        for p in sorted(replays_root.glob("*.jsonl")):
            if p.name == "merged.json":
                continue
            sid = p.stem
            if sid == instance_id:
                continue
            # Also skip if this is a legacy instance sidecar that we already handle via changes/
            replay_sources.append((p, sid))

    # Legacy per-instance sidecars (for migration, e.g. LSTeach)
    changes_root = Path(project_path) / SYNC_DIR_NAME
    if changes_root.is_dir():
        for sidecar_dir in sorted(changes_root.iterdir()):
            if not sidecar_dir.is_dir() or sidecar_dir.name == instance_id:
                continue
            sidecar = sidecar_dir / "changes.jsonl"
            if not sidecar.exists():
                continue
            # Avoid double-counting if this instance_id is actually a session_id that already has a per-session replay
            # (session_ids contain dash, instance_ids don't, so this is safe)
            replay_sources.append((sidecar, sidecar_dir.name))

    if not replay_sources:
        return report

    for sidecar, remote_instance in replay_sources:

        # Replay rows newer than the watermark, keeping only the LATEST entry
        # per (entity, pk) above it — PLUS the latest delete below it.
        # Append-only sidecars accumulate update churn for the same row;
        # replaying the whole history would waste work, so intermediate
        # states collapse to the row's final state (idempotent under
        # natural-key matching).  But a delete→insert cycle for one PK must
        # NOT collapse to the insert alone: SQLite reuses freed INTEGER
        # PRIMARY KEYs, so the two entries are DIFFERENT logical rows.
        # Dropping the delete resurrects the old row on peers that still
        # hold it (ghost files/codings whose counts then diverge forever,
        # since the watermark advances past the dropped delete).
        by_seq: dict[int, dict] = {}
        latest: dict[tuple[str, str], int] = {}
        latest_delete: dict[tuple[str, str], int] = {}
        for e in _parse_sidecar(sidecar):
            try:
                seq = int(e.get("seq", 0))
            except (TypeError, ValueError):
                continue
            if seq <= _imported_seq(state, remote_instance):
                continue
            if seq in by_seq:
                continue  # pathological duplicate seq within one file
            key = (str(e.get("entity", "")), str(e.get("pk_value", "")))
            by_seq[seq] = e
            prev = latest.get(key)
            if prev is None or seq > prev:
                latest[key] = seq
            if str(e.get("action", "")) == "delete":
                prevd = latest_delete.get(key)
                if prevd is None or seq > prevd:
                    latest_delete[key] = seq
        if not by_seq:
            continue
        keep: set[int] = set(latest.values())
        for key, dseq in latest_delete.items():
            if dseq != latest.get(key):
                keep.add(dseq)
        pending = {seq: by_seq[seq] for seq in sorted(keep)}
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
        # Spec 2e: ack that we have merged this replay (for deletion)
        # Do this after the watermark is saved, so the ack is durable.
        try:
            from qualcoder_api.services import replay_service

            # Ack for any replay that we advanced (including per-session and legacy)
            # The replay's session id is remote_instance; our session/instance is instance_id
            if highest_applied > 0:
                replay_service.write_ack(project_path, remote_instance, instance_id)
        except Exception:
            pass
        report[remote_instance] = {
            "applied": applied,
            "conflicts": conflicts,
            "retries": retries,
        }
    return report


# ── Full-state export & sandbox rebuild ─────────────────────────────────

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

    # Per-session replay (new spec 2a) vs legacy per-instance sidecar
    from qualcoder_api.services.sync_sidecar import _is_session_id, _replay_path

    is_session = _is_session_id(instance_id)
    if is_session:
        sidecar = _replay_path(project_path, instance_id)
    else:
        sidecar = _sidecar_path(project_path, instance_id)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n"
    try:
        await asyncio.to_thread(_facade()._append_sidecar, sidecar, lines)
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

    Gathers every instance's sidecar, keeps the latest entry per
    (instance, entity, pk) — one collapsed history per originating row —
    then replays them in dependency order so FK translation and remap
    recording work.  ``_replay_one`` assigns fresh local PKs and backfills
    ``sync_rev``.  The seeded ``project`` row (created with a new schema) is
    replaced by the exported project row.

    Collapsing must stay per-instance: autoincrement PKs diverge between
    instances (every machine starts its counters at 1), so two independent
    rows from different instances routinely share the same ``(entity,
    pk_value)``.  A global collapse kept only the higher-seq one and silently
    dropped the other — the rebuilt sandbox ended up with fewer files/codes
    than the collaborators' sandboxes.  Natural-key matching during replay
    converges true duplicates (same business key) and keeps distinct rows
    apart via fresh PKs.

    The caller is expected to have created and opened a fresh sandbox and to
    pass its ``session_factory``.  Returns an outcome report.
    """
    state = load_state(project_path)
    changes_root = Path(project_path) / SYNC_DIR_NAME
    replays_root = Path(project_path) / "replays"

    latest: dict[tuple[str, str, str], dict] = {}
    max_seq_by_instance: dict[str, int] = {}
    # Per-session replays (new spec 2a)
    if replays_root.is_dir():
        for p in sorted(replays_root.glob("*.jsonl")):
            if p.name == "merged.json":
                continue
            remote_instance = p.stem
            inst_max = 0
            for e in _parse_sidecar(p):
                try:
                    seq = int(e.get("seq", 0))
                except (TypeError, ValueError):
                    seq = 0
                inst_max = max(inst_max, seq)
                key = (remote_instance, str(e.get("entity", "")), str(e.get("pk_value", "")))
                prev = latest.get(key)
                if prev is not None and int(prev.get("seq", 0)) >= seq:
                    continue
                latest[key] = e
            if inst_max:
                max_seq_by_instance[remote_instance] = inst_max
    # Legacy per-instance sidecars (for migration, e.g. LSTeach)
    if changes_root.is_dir():
        for sidecar_dir in changes_root.iterdir():
            if not sidecar_dir.is_dir():
                continue
            remote_instance = sidecar_dir.name
            sidecar = sidecar_dir / "changes.jsonl"
            if not sidecar.exists():
                continue
            # Skip if this instance already has a per-session replay (avoid double counting)
            # Session ids contain dash, instance ids don't, so this is safe
            if (replays_root / f"{remote_instance}.jsonl").exists():
                continue
            inst_max = 0
            for e in _parse_sidecar(sidecar):
                try:
                    seq = int(e.get("seq", 0))
                except (TypeError, ValueError):
                    seq = 0
                inst_max = max(inst_max, seq)
                key = (remote_instance, str(e.get("entity", "")), str(e.get("pk_value", "")))
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

