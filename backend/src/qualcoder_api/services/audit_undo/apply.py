"""Registry-driven entry point for audit undo/redo."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from . import handlers  # noqa: F401  (registers every handler)
from .base import _NOT_INVERTIBLE_MESSAGES, UnsupportedAction
from .registry import HANDLERS


async def apply(
    session: AsyncSession, row: dict, *, undo: bool, project_path: str | None = None
) -> str:
    """Apply the inverse (undo=True) or re-apply (undo=False) of one audit row."""
    action = row.get("action") or ""
    handler = HANDLERS.get(action)
    if handler is None:
        message = _NOT_INVERTIBLE_MESSAGES.get(action)
        if message:
            raise UnsupportedAction(message)
        raise UnsupportedAction(f"no undo for {action}")
    return await handler(session, row, undo=undo, project_path=project_path)
