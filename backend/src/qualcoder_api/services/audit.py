"""Audit log — chronological record of project changes for the history view.

Every user-driven mutation records one row: when, who, what action, on which
entity. ``detail`` carries action-specific JSON (e.g. before/after text for
edits). Bulk import paths record a single entry instead of one per row.
"""

from __future__ import annotations

import datetime
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ACTION_VOCABULARY = (
    "coding.create",
    "coding.delete",
    "coding.autocode",
    "coding.undo",
    "annotation.create",
    "annotation.update",
    "annotation.delete",
    "case.create",
    "case.update",
    "case.delete",
    "case.link_file",
    "case.unlink_file",
    "attribute.create",
    "attribute.delete",
    "attribute.set_value",
    "journal.create",
    "journal.update",
    "journal.delete",
    "code.create",
    "code.rename",
    "code.delete",
    "code.merge",
    "category.create",
    "category.delete",
    "category.merge",
    "source.import",
    "source.link",
    "source.delete",
    "source.edit",
    "interchange.import",
)


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
    ts = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
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
