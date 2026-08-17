"""Legacy 120-color code palette and colour ranges."""
from __future__ import annotations

import random

# Legacy 120-color code palette (color_selector.py, ported verbatim).
CODE_COLORS = [
    "#F5F6CE", "#F2F5A9", "#F4FA58", "#F7FE2E", "#DDE600", "#F8ECE0", "#F6E3CE", "#F5D0A9", "#F7BE81", "#FAAC58",
    "#F5ECCE", "#F3E2A9", "#F5DA81", "#F7D358", "#FACC2E", "#FFE2CC", "#FFC599", "#FFA866", "#FF8B33", "#FF6F00",
    "#F8E6E0", "#F6D8CE", "#F5BCA9", "#F79F81", "#FA8258", "#FADCCC", "#F5B999", "#F09666", "#EB7333", "#E65100",
    "#F8E0E0", "#F6CECE", "#F5A9A9", "#F78181", "#FA5858", "#F0D1D1", "#E2A4A4", "#D37676", "#C54949", "#B71C1C",
    "#F2D6CE", "#E5AE9D", "#D8866D", "#CB5E3C", "#BF360C", "#E7CEDB", "#CF9EB8", "#B76E95", "#9F3E72", "#880E4F",
    "#F8E0E6", "#F6CED8", "#F5A9BC", "#F7819F", "#FA5882", "#F8E0F7", "#F6CEF5", "#F5A9F2", "#F781F3", "#FA58F4",
    "#D1DED2", "#A3BEA5", "#769E78", "#487E4B", "#1B5E20", "#DEE9E4", "#BED3C9", "#9EBDAE", "#7EA793", "#5E9179",
    "#CEF6E3", "#A9F5D0", "#81F7BE", "#58FAAC", "#00FF7F", "#E0F8E0", "#CEF6CE", "#A9F5A9", "#81F781", "#58FA58",
    "#D0F5A9", "#BEF781", "#ACFA58", "#9AFE2E", "#80FF00", "#CEF6F5", "#A9F5F2", "#81F7F3", "#58FAF4", "#00F0F0",
    "#E4D3F5", "#CAA8EB", "#B07CE1", "#9651D7", "#7D26CD", "#ECE0F8", "#E3CEF6", "#D0A9F5", "#BE81F7", "#AC58FA",
    "#DADAF5", "#B5B5EC", "#9090E3", "#6B6BDA", "#4646D1", "#CEE3F6", "#A9D0F5", "#81BEF7", "#3498DB", "#5882FA",
    "#CEDAEC", "#9EB5D9", "#6D91C6", "#3D6CB3", "#0D47A1", "#E8E8E8", "#D8D8D8", "#C8C8C8", "#B8B8B8", "#A8A8A8",
]

COLOUR_RANGES = [
    {"name": "yellow", "min": 0, "max": 5},
    {"name": "orange", "min": 6, "max": 30},
    {"name": "red", "min": 31, "max": 45},
    {"name": "pink", "min": 46, "max": 60},
    {"name": "green", "min": 61, "max": 85},
    {"name": "cyan", "min": 86, "max": 90},
    {"name": "purple", "min": 91, "max": 100},
    {"name": "blue", "min": 101, "max": 115},
    {"name": "gray", "min": 116, "max": 120},
    {"name": "all", "min": 0, "max": 120},
]


def random_code_color() -> str:
    """Pick a random color from the code palette (custom scheme when set)."""
    try:
        from qualcoder_api.services.user_settings import get_color_scheme

        scheme = get_color_scheme()
        palette = scheme.get("colors") or CODE_COLORS
    except Exception:  # pragma: no cover - settings never raise here
        palette = CODE_COLORS
    return palette[random.randint(0, len(palette) - 1)]
