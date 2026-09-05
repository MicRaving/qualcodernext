"""Sync conflicts — conflict resolution (single + bulk)."""

from __future__ import annotations

import json
import logging

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualcoder_api.core.timeutil import now
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.audit_capture import current_user
from qualcoder_api.services.sync_replay import _read_row
from qualcoder_api.services.sync_schema import SYNC_LOCK, _as_pk
from qualcoder_api.services.user_settings import get_instance_id

logger = logging.getLogger(__name__)

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
        # Upsert, not bare UPDATE: rows that predate versioned sync have no
        # sync_rev entry, and a bare UPDATE would silently keep it that way.
        await session.execute(
            text(
                "INSERT INTO sync_rev (entity, pk, rev, mtime, origin, deleted) "
                "VALUES (:e, :pk, :rev, :ts, :origin, :del) "
                "ON CONFLICT(entity, pk) DO UPDATE SET rev = :rev, mtime = :ts, "
                "origin = :origin, deleted = :del"
            ),
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
