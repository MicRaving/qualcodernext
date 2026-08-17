"""Audit capture helpers extracted from services/sync.py.

Provides ``table_row`` and ``capture`` — the two functions that
``persistence.repositories`` needs — without pulling in the full sync
module at import time.  This breaks the persistence→services circular
dependency: ``repositories`` can import these at the top level while the
actual ``services.sync`` module is only resolved at call-time via lazy
imports.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def table_row(mapping) -> dict:
    """Normalize a raw row mapping into a plain dict of table columns.

    Copied verbatim from ``services.sync.table_row``.
    """
    return {k: v for k, v in dict(mapping).items() if not k.startswith("_")}


async def capture(
    session: AsyncSession,
    *,
    entity: str,
    action: str,
    pk_name: str,
    pk_value: int | str | None,
    row: dict | None,
) -> None:
    """Record one mutation into sync_log (delegates to services.sync.capture).

    The import of ``services.sync`` happens at call-time so the module-level
    import graph never forms a cycle.
    """
    # Late import avoids the circular dependency:
    #   persistence.repositories -> persistence.audit_capture -> services.sync
    from qualcoder_api.services import sync

    await sync.capture(
        session,
        entity=entity,
        action=action,
        pk_name=pk_name,
        pk_value=pk_value,
        row=row,
    )
