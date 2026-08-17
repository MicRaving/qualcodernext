"""Handler registry: adding a new undoable action is one decorated function."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

RevertHandler = Callable[..., Awaitable[str]]
HANDLERS: dict[str, RevertHandler] = {}
F = TypeVar("F", bound=Callable[..., Awaitable[str]])


def register(*actions: str) -> Callable[[F], F]:
    """Register a handler function for every listed audit ``action`` string."""
    def deco(fn: F) -> F:
        for action in actions:
            HANDLERS[action] = fn
        return fn
    return deco
