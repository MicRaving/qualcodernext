"""Persistent AI chat sessions — ``ai_chat`` / ``ai_chat_message`` rows.

Every chat turn is stored in the project database so the frontend can reload
past conversations instead of keeping them in module memory. Messages carry a
``request_json`` envelope (mode, prompt_id, picker ids) so an exchange stays
reproducible even after the app restarts.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.timeutil import now
from qualcoder_api.persistence import tables


def _chat_row(row) -> dict:
    return {
        "id": row.id,
        "title": row.title or "",
        "created": row.created or "",
        "updated": row.updated or "",
    }


def _message_row(row) -> dict:
    return {
        "id": row.id,
        "chat_id": row.chat_id,
        "role": row.role or "",
        "text": row.text or "",
        "request_json": row.request_json or "",
        "created": row.created or "",
    }


async def list_chats(session: AsyncSession) -> list[dict]:
    result = await session.execute(
        tables.ai_chat.select().order_by(tables.ai_chat.c.updated.desc(), tables.ai_chat.c.id.desc())
    )
    return [_chat_row(row) for row in result]


async def get_chat(session: AsyncSession, chat_id: int) -> dict | None:
    result = await session.execute(
        tables.ai_chat.select().where(tables.ai_chat.c.id == chat_id)
    )
    row = result.first()
    if row is None:
        return None
    messages = await session.execute(
        tables.ai_chat_message.select()
        .where(tables.ai_chat_message.c.chat_id == chat_id)
        .order_by(tables.ai_chat_message.c.id)
    )
    return {**_chat_row(row), "messages": [_message_row(m) for m in messages]}


async def create_chat(session: AsyncSession, title: str = "") -> dict:
    timestamp = now()
    result = cast(
        CursorResult[Any],
        await session.execute(
            tables.ai_chat.insert().values(title=title or "", created=timestamp, updated=timestamp)
        ),
    )
    await session.commit()
    inserted = result.inserted_primary_key
    return {
        "id": int(inserted[0]) if inserted else 0,
        "title": title or "",
        "created": timestamp,
        "updated": timestamp,
    }


async def rename_chat(session: AsyncSession, chat_id: int, title: str) -> bool:
    result = cast(
        CursorResult[Any],
        await session.execute(
            tables.ai_chat.update()
            .where(tables.ai_chat.c.id == chat_id)
            .values(title=title.strip(), updated=now())
        ),
    )
    await session.commit()
    return result.rowcount > 0


async def delete_chat(session: AsyncSession, chat_id: int) -> bool:
    await session.execute(
        tables.ai_chat_message.delete().where(tables.ai_chat_message.c.chat_id == chat_id)
    )
    result = cast(
        CursorResult[Any],
        await session.execute(tables.ai_chat.delete().where(tables.ai_chat.c.id == chat_id)),
    )
    await session.commit()
    return result.rowcount > 0


async def append_message(
    session: AsyncSession,
    chat_id: int,
    role: str,
    text: str,
    request_json: str = "",
) -> dict:
    """Insert one message and bump the chat's ``updated`` timestamp."""
    timestamp = now()
    result = cast(
        CursorResult[Any],
        await session.execute(
            tables.ai_chat_message.insert().values(
                chat_id=chat_id, role=role, text=text, request_json=request_json, created=timestamp
            )
        ),
    )
    await session.execute(
        tables.ai_chat.update().where(tables.ai_chat.c.id == chat_id).values(updated=timestamp)
    )
    await session.commit()
    inserted = result.inserted_primary_key
    return {
        "id": int(inserted[0]) if inserted else 0,
        "chat_id": chat_id,
        "role": role,
        "text": text,
        "request_json": request_json,
        "created": timestamp,
    }


async def ensure_title(session: AsyncSession, chat_id: int, fallback: str) -> None:
    """Title the chat from its first user message when still untitled."""
    result = await session.execute(
        tables.ai_chat.select().where(tables.ai_chat.c.id == chat_id)
    )
    row = result.first()
    if row is None or row.title:
        return
    first = await session.execute(
        tables.ai_chat_message.select()
        .where(tables.ai_chat_message.c.chat_id == chat_id)
        .order_by(tables.ai_chat_message.c.id)
        .limit(1)
    )
    first_row = first.first()
    if first_row is None:
        return
    title = (first_row.text or "").strip().replace("\n", " ")
    title = title[:80] if len(title) > 80 else title
    if not title:
        title = fallback
    await session.execute(
        tables.ai_chat.update().where(tables.ai_chat.c.id == chat_id).values(title=title)
    )
    await session.commit()
