"""Shared helpers for graph_service sub-modules.

Extracted to avoid circular imports between ``graph_items``, ``graph_lines``,
and ``graph_service``.
"""

from __future__ import annotations

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.persistence.repo.base import _rowdict as _row_dict  # noqa: F401


async def _insert(session: AsyncSession, table, values: dict) -> int:
    from qualcoder_api.persistence.repositories import _capture

    result = await session.execute(insert(table).values(**values))
    await session.commit()
    from qualcoder_api.persistence.repositories import _inserted_pk

    pk = int(_inserted_pk(result))
    await _capture(session, table.name, "insert", table.primary_key.columns.keys()[0], pk, dict(values))
    await session.commit()
    return pk


async def _capture_row(session: AsyncSession, table, pk_name: str, pk_value: int, action: str) -> None:
    """Capture the current state of a graph row after an update."""
    from qualcoder_api.persistence.repositories import _capture, _rowdict

    row = (await session.execute(select(table).where(table.c[pk_name] == pk_value))).first()
    if row is not None:
        await _capture(session, table.name, action, pk_name, pk_value, _rowdict(row))
    await session.commit()


async def _capture_delete(session: AsyncSession, table, pk_name: str, pk_value: int, row) -> None:
    """Capture a graph row that is about to be deleted (the row is gone by
    the time a post-delete re-select runs, which silently skipped deletes)."""
    from qualcoder_api.persistence.repositories import _capture, _rowdict

    if row is not None:
        await _capture(session, table.name, "delete", pk_name, pk_value, _rowdict(row))
    await session.commit()


async def _record_audit(session: AsyncSession, action: str, entity: str, entity_id: int, detail: dict) -> None:
    """Record a graph item/line mutation in the audit log."""
    from qualcoder_api.services import audit
    from qualcoder_api.services.user_settings import get_codername

    await audit.record(
        session, user=get_codername(), action=action, entity=entity,
        entity_id=entity_id, detail=detail,
    )
