"""Deferred module loading for non-boot dependencies.

The backend's import chain reaches a handful of native wheels (numpy,
Pillow, httpx) through the routers it registers at startup, even though no
boot-critical request touches them: the desktop shell's first calls are
projects/sources/codes/cases only. Importing those wheels eagerly makes
every launch pay for them twice — once in Python, and once in the operating
system's antivirus, which scans each freshly mapped DLL.

``LazyModule`` keeps call sites looking like ordinary module use
(``np.array(...)``) while importing the real module on first attribute
access. Every resolved attribute is cached on the proxy, so after the first
touch the only cost is one instance-dict lookup.

The target module must be safe to import late (no import-time side effects
that the caller relies on) and must not be needed at module import time —
i.e. it is only used inside functions or in annotations covered by
``from __future__ import annotations``.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any


class LazyModule:
    """A stand-in module that imports its target on first attribute access."""

    __slots__ = ("_attrs", "_module", "_name")

    def __init__(self, name: str) -> None:
        self._name = name
        self._module: ModuleType | None = None
        self._attrs: dict[str, Any] = {}

    def _load(self) -> ModuleType:
        module = self._module
        if module is None:
            module = importlib.import_module(self._name)
            self._module = module
        return module

    def __getattr__(self, attr: str) -> Any:
        cached = self._attrs.get(attr)
        if cached is not None:
            return cached
        value = getattr(self._load(), attr)
        self._attrs[attr] = value
        return value

    def __dir__(self) -> list[str]:
        # Report the target's names so tab-completion/introspection still work.
        return sorted(set(super().__dir__()) | set(dir(self._load())))

    def __repr__(self) -> str:
        state = "loaded" if self._module is not None else "lazy"
        return f"<LazyModule {self._name!r} ({state})>"
