"""Live coder presence — per-instance presence files inside the project folder.

Every open app instance owns one small JSON file at
``<project>/presence/<pid>.json`` with ``{coder, os_user, pid, ts, file_id,
file_name}``. The background heartbeat loop (``main._presence_loop``) keeps
``ts`` fresh while a project is open; the frontend reports the file currently
being worked on via ``POST /sync/presence/activity``. Other instances scan the
folder (``read``) and drop dead/stale files, so every rater sees who is
actively working and on which file — regardless of the sync switch.

Unlike the presence-registry lock file (append/rewrite of a shared file), each
instance owns its own file, so concurrent heartbeats never clobber each other.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import time
from pathlib import Path

logger = logging.getLogger(__name__)

#: Subfolder of the project folder holding per-instance presence files.
PRESENCE_DIR_NAME = "presence"

#: Interval of the background heartbeat loop (main._presence_loop).
PRESENCE_HEARTBEAT_SECS = 15

#: Files older than this are pruned by readers (stale / offline instances).
PRESENCE_TTL_SECS = 300


def _state_path(project_path: str) -> Path:
    return Path(project_path) / PRESENCE_DIR_NAME


def instance_file(project_path: str) -> Path:
    """The presence file owned by THIS backend process."""
    return _state_path(project_path) / f"{os.getpid()}.json"


def _pid_alive(pid: int) -> bool:
    """True if a process with the given pid is still running."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def touch(
    project_path: str,
    coder: str,
    *,
    file_id: int | None = None,
    file_name: str = "",
    instance_id: str = "",
) -> bool:
    """Write/refresh this instance's presence file. Returns True when written
    (or a real change was recorded), False when skipped (nothing changed and
    the heartbeat is still fresh — avoids syncing the same file repeatedly).

    The heartbeat loop calls this every ``PRESENCE_HEARTBEAT_SECS``; the
    activity endpoint calls it with the current file.
    """
    if not project_path or not coder:
        return False
    now = time.time()
    path = instance_file(project_path)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        unchanged = (
            existing.get("coder") == coder
            and existing.get("file_id") == file_id
            and existing.get("file_name") == file_name
        )
        if unchanged and now - float(existing.get("ts", 0)) < PRESENCE_HEARTBEAT_SECS:
            return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "coder": coder,
                    "os_user": os.environ.get("USERNAME") or os.environ.get("USER", ""),
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "ts": now,
                    "file_id": file_id,
                    "file_name": file_name,
                    "instance": instance_id,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        tmp.replace(path)
        return True
    except OSError as err:  # pragma: no cover - defensive
        logger.warning("presence touch failed: %s", err)
        return False


def clear(project_path: str) -> None:
    """Remove THIS instance's presence file (project close)."""
    try:
        path = instance_file(project_path)
        if path.exists():
            path.unlink()
    except OSError:  # pragma: no cover - defensive
        pass


def read(project_path: str, exclude_pid: int | None = None) -> list[dict]:
    """Live presence entries of OTHER instances, pruning dead/stale files.

    ``exclude_pid`` skips a pid (the caller's own). Returns the entries sorted
    by last activity (newest first).

    Liveness is only meaningful for entries on THIS host: a remote rater's pid
    is meaningless in the local process table, so remote entries (different
    ``host``, or legacy files without one) are kept while their ``ts`` is
    within the TTL window and pruned when it is stale or absurdly in the
    future (clock skew on another machine).
    """
    root = _state_path(project_path)
    if not root.is_dir():
        return []
    exclude = exclude_pid if exclude_pid is not None else os.getpid()
    this_host = socket.gethostname()
    now = time.time()
    out: list[dict] = []
    for path in sorted(root.glob("*.json")):
        if path.name.endswith(".tmp"):
            continue
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
            continue
        pid = int(entry.get("pid", 0))
        ts = float(entry.get("ts", 0))
        if pid == exclude:
            continue
        local = entry.get("host") == this_host
        stale = now - ts > PRESENCE_TTL_SECS or ts - now > PRESENCE_TTL_SECS
        if stale or (local and (pid <= 0 or not _pid_alive(pid))):
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
            continue
        out.append(
            {
                "coder": entry.get("coder", ""),
                "os_user": entry.get("os_user", ""),
                "pid": pid,
                "ts": ts,
                "file_id": entry.get("file_id"),
                "file_name": entry.get("file_name", ""),
                "instance": entry.get("instance", ""),
            }
        )
    return sorted(out, key=lambda e: e["ts"], reverse=True)
