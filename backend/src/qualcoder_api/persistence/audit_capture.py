"""Audit capture — the sync_log change journal for the persistence layer.

The repository classes record every mutation into the project's ``sync_log``
table so collaboration sync (``services.sync``) can export and replay rows.
These helpers live in ``persistence`` so repository classes never import the
``services`` layer at module level:
``persistence.repo`` → ``persistence.audit_capture``.

The ``services.sync`` module re-exports every name here for its own capture
logic and for backwards compatibility (``from qualcoder_api.services import
sync; sync.capture_insert(...)`` keeps working).
"""

from __future__ import annotations

import contextlib
import contextvars
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.timeutil import now


def table_row(mapping) -> dict:
    """Normalize a raw row mapping into a plain dict of table columns."""
    return {k: v for k, v in dict(mapping).items() if not k.startswith("_")}


# Set per request/task so repository-level capture knows who is acting.
_current_user: contextvars.ContextVar[str] = contextvars.ContextVar("sync_user", default="")

# Repositories call capture() for every mutation; replay and imports set
# this so their writes are not re-captured (no ping-pong).
_suspended: contextvars.ContextVar[bool] = contextvars.ContextVar("sync_suspended", default=False)


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
