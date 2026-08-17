"""Audit log — chronological record of project changes for the history view.

Every user-driven mutation records one row: when, who, what action, on which
entity. ``detail`` carries action-specific JSON (e.g. before/after text for
edits). Bulk import paths record a single entry instead of one per row.
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.timeutil import now


async def record(
    session: AsyncSession,
    *,
    user: str,
    action: str,
    entity: str,
    entity_id: int | None = None,
    source_id: int | None = None,
    detail: dict | None = None,
) -> None:
    """Insert one audit row and commit (callers have varying commit habits)."""
    ts = now()
    await session.execute(
        text(
            "INSERT INTO audit_log (ts, user, action, entity, entity_id, source_id, detail) "
            "VALUES (:ts, :user, :action, :entity, :entity_id, :source_id, :detail)"
        ),
        {
            "ts": ts,
            "user": user,
            "action": action,
            "entity": entity,
            "entity_id": entity_id,
            "source_id": source_id,
            "detail": json.dumps(detail or {}, ensure_ascii=False),
        },
    )
    await session.commit()
