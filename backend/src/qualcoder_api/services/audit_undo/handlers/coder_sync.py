"""Coder create/delete/rename/visibility and sync toggle handlers."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.persistence import tables

from ..base import (
    UnsupportedAction,
    _detail,
    _missing_data,
)
from ..registry import register


@register("coder.create", "coder.delete", "coder.rename", "coder.visibility")
async def _revert_coder(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """coder.create / coder.delete / coder.rename / coder.visibility: the
    coder list lives in the per-machine settings; visibility lives in the
    project's ``coder_names`` table."""
    from qualcoder_api.services.user_settings import get_coders, set_coders

    action = row.get("action") or ""
    detail = _detail(row)
    if action == "coder.create":
        from qualcoder_api.persistence.repositories import _capture as _cap

        name = detail.get("name")
        if not name:
            raise _missing_data()
        names = get_coders()
        if undo:
            if name in names:
                set_coders([n for n in names if n != name])
            # Creation also registered the coder in this project's
            # coder_names registry — undo removes that row again.
            await session.execute(
                text("DELETE FROM coder_names WHERE name = :n"), {"n": name}
            )
            try:
                await _cap(
                    session, "coder_names", "delete", "name", name,
                    {"name": name, "visibility": 0},
                )
                await session.flush()
            except Exception:
                pass
            return f"removed coder {name!r} from the coder list"
        if name not in names:
            set_coders([*names, name])
        await session.execute(
            text(
                "INSERT OR IGNORE INTO coder_names (name, visibility) VALUES (:n, 1)"
            ),
            {"n": name},
        )
        try:
            await _cap(
                session, "coder_names", "insert", "name", name,
                {"name": name, "visibility": 1},
            )
            await session.flush()
        except Exception:
            pass
        return f"re-added coder {name!r} to the coder list"
    if action == "coder.delete":
        from qualcoder_api.persistence.repositories import _capture as _cap3

        name = detail.get("name")
        if not name:
            raise _missing_data()
        names = get_coders()
        if undo:
            if name not in names:
                set_coders([*names, name])
            # The roster is project-canonical now: restoring settings alone
            # no longer surfaces the coder — re-add the registry row too
            # (captured, so the restore reaches collaborators).
            await session.execute(
                text(
                    "INSERT OR IGNORE INTO coder_names (name, visibility) VALUES (:n, 1)"
                ),
                {"n": name},
            )
            try:
                await _cap3(
                    session, "coder_names", "insert", "name", name,
                    {"name": name, "visibility": 1},
                )
                await session.flush()
            except Exception:
                pass
            message = f"restored coder {name!r} to the coder list"
            if detail.get("reassign_to"):
                message += " (their records stay reassigned)"
            return message
        if name in names:
            set_coders([n for n in names if n != name])
        # Redo re-applies the full delete (settings + registry row).
        await session.execute(
            text("DELETE FROM coder_names WHERE name = :n"), {"n": name}
        )
        try:
            await _cap3(
                session, "coder_names", "delete", "name", name,
                {"name": name, "visibility": 0},
            )
            await session.flush()
        except Exception:
            pass
        return f"removed coder {name!r} from the coder list"
    if action == "coder.rename":
        from qualcoder_api.services.sync_schema import ENTITY_PKS

        from ..base import _sync_capture

        old = detail.get("from")
        new = detail.get("to")
        if not old or not new:
            raise _missing_data()
        source, target = (new, old) if undo else (old, new)
        names = get_coders()
        renamed = [target if n == source else n for n in names]
        set_coders(renamed)
        for table in tables.OWNER_TABLES:
            pk_name = ENTITY_PKS.get(table, "")
            ids: list = []
            if pk_name and "," not in pk_name:
                try:
                    rows = (
                        await session.execute(
                            text(f'SELECT "{pk_name}" FROM "{table}" WHERE owner = :from'),
                            {"from": source},
                        )
                    ).all()
                    ids = [r[0] for r in rows]
                except Exception:
                    ids = []
            await session.execute(
                text(f'UPDATE "{table}" SET owner = :to WHERE owner = :from'),
                {"to": target, "from": source},
            )
            if pk_name and "," not in pk_name:
                for pk_value in ids:
                    try:
                        await _sync_capture(session, table, "update", pk_name, pk_value)
                    except Exception:
                        continue
        await session.execute(
            text("UPDATE coder_names SET name = :to WHERE name = :from"),
            {"to": target, "from": source},
        )
        try:
            await _sync_capture(session, "coder_names", "delete", "name", source)
        except Exception:
            pass
        try:
            row = (
                await session.execute(
                    text("SELECT name, visibility FROM coder_names WHERE name = :n"),
                    {"n": target},
                )
            ).first()
            if row is not None:
                from qualcoder_api.persistence.repositories import _capture

                await _capture(
                    session, "coder_names", "insert", "name", target,
                    {"name": row[0], "visibility": row[1]},
                )
                await session.flush()
        except Exception:
            pass
        return f"coder {source!r} {'renamed back to' if undo else 'renamed to'} {target!r}"
    if action == "coder.visibility":
        from qualcoder_api.persistence.repositories import _capture as _cap2

        name = detail.get("name")
        if not name:
            raise _missing_data()
        applied = 1 if detail.get("visible") else 0
        if undo:
            before = detail.get("before")
            if before is None:
                await session.execute(
                    text("DELETE FROM coder_names WHERE name = :n"), {"n": name}
                )
                try:
                    await _cap2(
                        session, "coder_names", "delete", "name", name,
                        {"name": name, "visibility": 0},
                    )
                    await session.flush()
                except Exception:
                    pass
            else:
                await session.execute(
                    text(
                        "INSERT INTO coder_names (name, visibility) VALUES (:n, :v) "
                        "ON CONFLICT(name) DO UPDATE SET visibility = :v"
                    ),
                    {"n": name, "v": 1 if before else 0},
                )
                try:
                    await _cap2(
                        session, "coder_names", "update", "name", name,
                        {"name": name, "visibility": 1 if before else 0},
                    )
                    await session.flush()
                except Exception:
                    pass
            return f"coder {name!r} visibility restored"
        await session.execute(
            text(
                "INSERT INTO coder_names (name, visibility) VALUES (:n, :v) "
                "ON CONFLICT(name) DO UPDATE SET visibility = :v"
            ),
            {"n": name, "v": applied},
        )
        try:
            await _cap2(
                session, "coder_names", "update", "name", name,
                {"name": name, "visibility": applied},
            )
            await session.flush()
        except Exception:
            pass
        return f"coder {name!r} visibility re-applied"
    raise UnsupportedAction(f"no undo for {action}")


@register("sync.toggle")
async def _revert_sync_toggle(session: AsyncSession, row: dict, *, undo: bool, **kwargs) -> str:
    """sync.toggle: restore the previously stored sync switch state."""
    from qualcoder_api.services.user_settings import save_sync_settings

    detail = _detail(row)
    enabled = detail.get("before") if undo else detail.get("enabled")
    if enabled is None:
        raise _missing_data()
    save_sync_settings(bool(enabled))
    return f"sync {'restored' if undo else 're-applied'} (enabled={bool(enabled)})"
