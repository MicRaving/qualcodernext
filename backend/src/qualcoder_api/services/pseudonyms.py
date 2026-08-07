"""Pseudonyms — original/pseudonym pairs stored in ``pseudonyms.json``.

Port of the upstream ``pseudonyms.py`` dialog data layer: the pairs live in
the project folder so they travel with the project. Case-sensitive;
original must be unique and at least 2 chars, pseudonym unique and at least
3 chars (blank pseudonyms get a random 6-char code).
"""

from __future__ import annotations

import json
import random
import string
from pathlib import Path


def pseudonyms_path(project_path: str) -> Path:
    return Path(project_path) / "pseudonyms.json"


def load_pseudonyms(project_path: str) -> list[dict]:
    try:
        data = json.loads(pseudonyms_path(project_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [d for d in data if isinstance(d, dict) and d.get("original") and d.get("pseudonym")]


def _save(project_path: str, data: list[dict]) -> None:
    pseudonyms_path(project_path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def add_pseudonym(project_path: str, original: str, pseudonym: str = "") -> dict:
    """Add an original/pseudonym pair; blank pseudonym gets a random code."""
    original = original.strip()
    if len(original) < 2:
        raise ValueError("original text is too short (minimum 2 characters)")
    pseudonym = pseudonym.strip()
    if 0 < len(pseudonym) < 3:
        raise ValueError("pseudonym is too short (minimum 3 characters)")
    data = load_pseudonyms(project_path)
    if any(d["original"] == original for d in data):
        raise ValueError("original entry already exists")
    if not pseudonym:
        characters = string.ascii_uppercase + string.digits
        used = {d["pseudonym"] for d in data}
        while True:
            candidate = "".join(random.choices(characters, k=6))
            if candidate not in used:
                pseudonym = candidate
                break
    if any(d["pseudonym"] == pseudonym for d in data):
        raise ValueError("pseudonym entry already exists")
    entry = {"original": original, "pseudonym": pseudonym}
    _save(project_path, [*data, entry])
    return entry


def delete_pseudonym(project_path: str, original: str) -> None:
    data = load_pseudonyms(project_path)
    data = [d for d in data if d["original"] != original]
    _save(project_path, data)


def apply_pseudonyms(text: str, project_path: str) -> str:
    """Word-boundary replacement of every pseudonym pair in ``text``."""
    import re

    out = text
    for entry in load_pseudonyms(project_path):
        out = re.sub(rf"\b{re.escape(entry['original'])}\b", entry["pseudonym"], out)
    return out
