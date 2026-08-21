"""Project collaboration marker — ``.qcnext-project``.

The marker file lives at the project folder root and records that the project
was activated for collaboration mode (≥2 coders with sync enabled).  Its
presence determines how the project opens:

* **No marker** → single-coder mode: ``data.qda`` is the live working
  database (opened directly, unchanged legacy behaviour).
* **Marker present** → collaboration mode: the live working database is a
  local sandbox under ``~/.qualcoder/projects/<uuid>/sandbox.sqlite`` and
  ``data.qda`` in the shared folder is a cold archive refreshed on close.

Once written the marker is kept until an explicit "revert to single-coder"
action — this is a deliberate one-way door so a sandbox with uncommitted data
is never stranded by a mode toggle.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from qualcoder_api.core.timeutil import now

logger = logging.getLogger(__name__)

MARKER_FILENAME = ".qcnext-project"
MARKER_VERSION = 1


def _marker_path(project_path: str) -> Path:
    return Path(project_path) / MARKER_FILENAME


def read_marker(project_path: str) -> dict | None:
    """Return the parsed marker dict, or None when absent/invalid."""
    path = _marker_path(project_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("uuid"):
        return None
    return data


def marker_exists(project_path: str) -> bool:
    return read_marker(project_path) is not None


def write_marker(
    project_path: str,
    uuid: str,
    *,
    codername: str = "",
    schema_version: int = 0,
) -> dict:
    """Write (or overwrite) the marker file. Atomic (tmp + replace)."""
    marker = {
        "version": MARKER_VERSION,
        "uuid": uuid,
        "schema_version": schema_version,
        "activated_at": now(),
        "activated_by": codername or "",
        "consolidation_watermark": {"timestamp": "", "max_sidecar_seq": 0},
    }
    path = _marker_path(project_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(marker, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as err:  # pragma: no cover - defensive
        logger.warning("could not write project marker: %s", err)
    return marker


def update_consolidation_watermark(
    project_path: str, timestamp: str, max_sidecar_seq: int
) -> None:
    """Patch the consolidation watermark (best effort)."""
    marker = read_marker(project_path)
    if not marker:
        return
    marker["consolidation_watermark"] = {
        "timestamp": timestamp,
        "max_sidecar_seq": int(max_sidecar_seq or 0),
    }
    path = _marker_path(project_path)
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(marker, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as err:  # pragma: no cover - defensive
        logger.warning("could not update consolidation watermark: %s", err)


def consolidation_watermark(project_path: str) -> tuple[str, int]:
    """The last consolidation watermark as (timestamp, max_sidecar_seq)."""
    marker = read_marker(project_path)
    if not marker:
        return "", 0
    wm = marker.get("consolidation_watermark") or {}
    return str(wm.get("timestamp", "")), int(wm.get("max_sidecar_seq", 0))


def remove_marker(project_path: str) -> None:
    """Delete the marker file (revert to single-coder mode)."""
    try:
        _marker_path(project_path).unlink(missing_ok=True)
    except OSError as err:  # pragma: no cover - defensive
        logger.warning("could not remove project marker: %s", err)
