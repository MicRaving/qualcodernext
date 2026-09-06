"""Sync state — per-machine state-file I/O and watermark helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading as _threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Serializes load→mutate→save sequences within this process (e.g. concurrent
# sync enables). Cross-process races are benign: the file is per-machine and
# writers are the local sync loop + manual triggers only.
_STATE_LOCK = _threading.Lock()


# ── State (per-machine, outside the synced folder) ──────────────────────

def _normalize_project_path(project_path: str) -> str:
    """Canonicalize a project path before hashing (and comparing).

    The same shared folder can surface under different spellings — slash
    direction, ``.`` segments, letter case on Windows, mapped-drive letter
    vs UNC path.  Each spelling previously hashed to a DIFFERENT state file,
    so reopening via another spelling silently reset all watermarks and
    replayed the entire history (and split export watermarks across files).
    """
    return os.path.normcase(os.path.normpath(project_path))


def _state_path(project_path: str) -> Path:
    digest = hashlib.sha1(
        _normalize_project_path(project_path).encode("utf-8")
    ).hexdigest()[:16]
    return Path.home() / ".qualcoder" / "sync" / f"{digest}.json"


def load_state(project_path: str) -> dict:
    try:
        return json.loads(_state_path(project_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(project_path: str, state: dict) -> None:
    path = _state_path(project_path)
    try:
        with _STATE_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
            tmp.replace(path)
    except OSError as err:  # pragma: no cover
        logger.warning("sync state save failed: %s", err)


def _exported_seq(state: dict, instance: str) -> int:
    """Last exported sync_log id for this instance."""
    return int(state.get("exports", {}).get(instance, 0))


def _imported_seq(state: dict, instance: str) -> int:
    """Last imported seq from this remote instance."""
    return int(state.get("imports", {}).get(instance, 0))


def _recorded_conflicts(state: dict, instance: str) -> dict:
    """Return the conflicts dict for *instance* keyed by pk string."""
    conflicts = state.get("conflicts", {}).get(instance, [])
    result: dict[str, dict] = {}
    for c in conflicts:
        result[c.get("pk", "")] = c
    return result


def _conflict_summary(state: dict, instance: str) -> list[dict]:
    """Return a list of conflict summaries for *instance*."""
    return state.get("conflicts", {}).get(instance, [])
