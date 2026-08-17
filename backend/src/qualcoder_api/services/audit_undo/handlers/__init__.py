"""Imports every handler module so the @register decorators run on import."""
from . import code, coding, entity, graph, source  # noqa: F401
