"""User-defined AI instruction templates — ``ai_prompt`` rows.

Custom templates are stored per project and exposed to the frontend together
with the built-in catalog under ids ``custom:<row-id>`` (see
``ai_prompts.CUSTOM_PROMPT_PREFIX``). ``list_catalog`` merges both sources so
``GET /ai/prompts`` returns one picker-ready list.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.timeutil import now
from qualcoder_api.persistence import tables
from qualcoder_api.services.ai_prompts import (
    CATALOG,
    CUSTOM_PROMPT_PREFIX,
    GLOBAL_PROMPT_PREFIX,
    is_custom_prompt_id,
)


def _template_row(row) -> dict:
    return {
        "id": row.id,
        "name": row.name or "",
        "description": row.description or "",
        "text": row.text or "",
        "created": row.created or "",
        "updated": row.updated or "",
    }


async def list_templates(session: AsyncSession) -> list[dict]:
    result = await session.execute(
        tables.ai_prompt.select().order_by(tables.ai_prompt.c.id)
    )
    return [_template_row(row) for row in result]


async def get_template(session: AsyncSession, template_id: int) -> dict | None:
    result = await session.execute(
        tables.ai_prompt.select().where(tables.ai_prompt.c.id == template_id)
    )
    row = result.first()
    return _template_row(row) if row is not None else None


async def create_template(
    session: AsyncSession, name: str, description: str = "", text: str = ""
) -> dict:
    timestamp = now()
    result = cast(
        CursorResult[Any],
        await session.execute(
            tables.ai_prompt.insert().values(
                name=name.strip(), description=description.strip(), text=text, created=timestamp, updated=timestamp
            )
        ),
    )
    await session.commit()
    inserted = result.inserted_primary_key
    return {
        "id": int(inserted[0]) if inserted else 0,
        "name": name.strip(),
        "description": description.strip(),
        "text": text,
        "created": timestamp,
        "updated": timestamp,
    }


async def update_template(
    session: AsyncSession,
    template_id: int,
    name: str | None = None,
    description: str | None = None,
    text: str | None = None,
) -> dict | None:
    current = await get_template(session, template_id)
    if current is None:
        return None
    values = {"updated": now()}
    if name is not None:
        values["name"] = name.strip()
    if description is not None:
        values["description"] = description.strip()
    if text is not None:
        values["text"] = text
    await session.execute(
        tables.ai_prompt.update().where(tables.ai_prompt.c.id == template_id).values(**values)
    )
    await session.commit()
    return await get_template(session, template_id)


async def delete_template(session: AsyncSession, template_id: int) -> bool:
    result = cast(
        CursorResult[Any],
        await session.execute(tables.ai_prompt.delete().where(tables.ai_prompt.c.id == template_id)),
    )
    await session.commit()
    return result.rowcount > 0


async def list_catalog(session: AsyncSession) -> list[dict]:
    """Built-in prompts + app-wide templates + project templates, picker-ready."""
    from qualcoder_api.services import user_settings

    built_in = [
        {
            "id": prompt.id,
            "mode": prompt.mode,
            "name": prompt.name,
            "label": prompt.label,
            "description": prompt.description,
            "hidden": prompt.hidden,
            "group": prompt.group,
            "custom": False,
        }
        for prompt in CATALOG.prompts
    ]
    global_prompts = [
        {
            "id": f"{GLOBAL_PROMPT_PREFIX}{row['id']}",
            "mode": "general",
            "name": row["name"],
            "label": row["name"],
            "description": row.get("description", ""),
            "hidden": False,
            "group": "custom",
            "custom": True,
            "global": True,
        }
        for row in user_settings.get_ai_global_prompts()
    ]
    custom = [
        {
            "id": f"{CUSTOM_PROMPT_PREFIX}{row['id']}",
            "mode": "general",
            "name": row["name"],
            "label": row["name"],
            "description": row["description"],
            "hidden": False,
            "group": "custom",
            "custom": True,
        }
        for row in await list_templates(session)
    ]
    return built_in + global_prompts + custom


async def list_editor_templates(session: AsyncSession) -> list[dict]:
    """Everything the template editor can edit, with defaults + scope.

    ``scope`` is ``builtin`` (shipped, editable via an app-wide override),
    ``app`` (a globally saved template) or ``project`` (this project's row).
    ``default`` carries the shipped text for built-ins (None otherwise) so the
    editor can offer "Reset to default".
    """
    from qualcoder_api.services import user_settings

    overrides = user_settings.get_ai_prompt_overrides()
    templates: list[dict] = []
    for prompt in CATALOG.prompts:
        if prompt.hidden or not prompt.group:
            continue  # only the pickable groups (analysis / specialized)
        templates.append(
            {
                "id": prompt.id,
                "name": prompt.name,
                "label": prompt.label,
                "description": prompt.description,
                "text": overrides.get(prompt.id, prompt.text),
                "default": prompt.text,
                "group": prompt.group,
                "scope": "builtin",
            }
        )
    templates.extend(
        {
            "id": f"{GLOBAL_PROMPT_PREFIX}{row['id']}",
            "name": row["name"],
            "label": row["name"],
            "description": row.get("description", ""),
            "text": row.get("text", ""),
            "default": None,
            "group": "custom",
            "scope": "app",
        }
        for row in user_settings.get_ai_global_prompts()
    )
    templates.extend(
        {
            "id": f"{CUSTOM_PROMPT_PREFIX}{row['id']}",
            "name": row["name"],
            "label": row["name"],
            "description": row["description"],
            "text": row["text"],
            "default": None,
            "group": "custom",
            "scope": "project",
        }
        for row in await list_templates(session)
    )
    return templates


def resolve_custom_row_id(prompt_id: str) -> int | None:
    """Extract the ``ai_prompt`` row id from a ``custom:<n>`` prompt id."""
    if not is_custom_prompt_id(prompt_id):
        return None
    try:
        return int(prompt_id[len(CUSTOM_PROMPT_PREFIX):])
    except ValueError:
        return None
