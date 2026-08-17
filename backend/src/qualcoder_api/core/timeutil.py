"""Central timestamp helper."""
from __future__ import annotations

import datetime


def now() -> str:
    """Current local time as an ISO-ish string (YYYY-MM-DD HH:MM:SS)."""
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
