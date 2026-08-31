"""Session-based collaboration — per-session lifecycle for online projects.

Each time a project is opened in online mode a new *session* is created:

* ``sessions/<session_id>.json`` — activity + close report for that session.
* ``replays/<session_id>.jsonl`` — append-only replay file for that session.

The session admin (the last-closing session) merges all replays into the
master ``data.qda`` when every other session is closed or stale, and replay
files are deleted only when every instance has acked them *and* they are in
the master.  A new open after a close always creates a fresh session/replay.

This replaces the old per-machine ``changes/<instance>/changes.jsonl`` model
for new projects; legacy sidecars are still read as a single fallback replay.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import secrets
import socket
import time
from pathlib import Path

logger = logging.getLogger(__name__)

SESSION_DIR_NAME = "sessions"
REPLAY_DIR_NAME = "replays"
ACK_DIR_NAME = "acks"
MASTER_WATERMARK_FILE = "replays/merged.json"

# Heartbeat / staleness — same as presence (15s heartbeat, 300s TTL).
SESSION_HEARTBEAT_SECS = 15
SESSION_TTL_SECS = 300


def _sessions_dir(project_path: str) -> Path:
    return Path(project_path) / SESSION_DIR_NAME


def _replays_dir(project_path: str) -> Path:
    return Path(project_path) / REPLAY_DIR_NAME


def _acks_dir(project_path: str) -> Path:
    return Path(project_path) / ACK_DIR_NAME


def _master_watermark_path(project_path: str) -> Path:
    return Path(project_path) / MASTER_WATERMARK_FILE


def _session_path(project_path: str, session_id: str) -> Path:
    return _sessions_dir(project_path) / f"{session_id}.json"


def _replay_path(project_path: str, session_id: str) -> Path:
    return _replays_dir(project_path) / f"{session_id}.jsonl"


def generate_session_id(instance_id: str = "") -> str:
    """Unique session id: <instance>-<timestamp>-<rand>."""
    rand = secrets.token_hex(4)
    ts = int(time.time() * 1000) % 10000000
    base = instance_id[:6] if instance_id else "sess"
    return f"{base}-{ts}-{rand}"


def create_session(
    project_path: str,
    coder: str,
    instance_id: str = "",
    pid: int | None = None,
    host: str | None = None,
) -> str:
    """Create a new session file and its empty replay file. Returns session_id."""
    session_id = generate_session_id(instance_id)
    now = time.time()
    data = {
        "session_id": session_id,
        "instance_id": instance_id,
        "coder": coder,
        "pid": pid or os.getpid(),
        "host": host or socket.gethostname(),
        "opened_at": now,
        "last_heartbeat": now,
        "closed_at": None,
        "closed": False,
    }
    sess_path = _session_path(project_path, session_id)
    replay_path = _replay_path(project_path, session_id)
    try:
        sess_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = sess_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(sess_path)
        # fsync file + directory for immediate visibility on SMB/OneDrive
        with contextlib.suppress(OSError):
            with open(sess_path, "rb") as f:
                f.flush()
                os.fsync(f.fileno())
            if hasattr(os, "O_DIRECTORY"):
                with contextlib.suppress(OSError):
                    dir_fd = os.open(str(sess_path.parent), os.O_DIRECTORY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
        # Create empty replay file
        replay_path.parent.mkdir(parents=True, exist_ok=True)
        replay_path.touch(exist_ok=True)
        if hasattr(os, "O_DIRECTORY"):
            with contextlib.suppress(OSError):
                dir_fd = os.open(str(replay_path.parent), os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
    except OSError as err:
        logger.warning("create_session failed for %s: %s", session_id, err)
    return session_id


def heartbeat(project_path: str, session_id: str) -> bool:
    """Refresh last_heartbeat for the session. Returns True if written."""
    path = _session_path(project_path, session_id)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    now = time.time()
    # Throttle: don't rewrite if heartbeat is still fresh
    last = float(data.get("last_heartbeat", 0))
    if now - last < SESSION_HEARTBEAT_SECS and not data.get("closed"):
        return False
    data["last_heartbeat"] = now
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
        with contextlib.suppress(OSError), open(path, "rb") as f:
            os.fsync(f.fileno())
        return True
    except OSError as err:
        logger.warning("heartbeat failed for %s: %s", session_id, err)
        return False


def close_session(project_path: str, session_id: str) -> bool:
    """Mark a session as closed. Returns True if newly closed."""
    path = _session_path(project_path, session_id)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if data.get("closed"):
        return False
    data["closed"] = True
    data["closed_at"] = time.time()
    data["last_heartbeat"] = time.time()
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
        with contextlib.suppress(OSError), open(path, "rb") as f:
            os.fsync(f.fileno())
        return True
    except OSError as err:
        logger.warning("close_session failed for %s: %s", session_id, err)
        return False


def read_session(project_path: str, session_id: str) -> dict | None:
    try:
        return json.loads(_session_path(project_path, session_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_sessions(project_path: str, include_closed: bool = True) -> list[dict]:
    """List all session files, pruning stale closed sessions' acks later."""
    root = _sessions_dir(project_path)
    if not root.is_dir():
        return []
    out: list[dict] = []
    now = time.time()
    for p in sorted(root.glob("*.json")):
        if p.name.endswith(".tmp"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # Stale open sessions (no heartbeat for TTL) are treated as closed/crashed
        if not data.get("closed"):
            last = float(data.get("last_heartbeat", 0) or data.get("opened_at", 0))
            if now - last > SESSION_TTL_SECS or last - now > SESSION_TTL_SECS:
                # Mark as implicitly closed (stale) for the caller, but don't
                # rewrite the file here — the merger will treat it as closed.
                data["_stale"] = True
        if not include_closed and data.get("closed"):
            continue
        out.append(data)
    return sorted(out, key=lambda d: d.get("opened_at", 0))


def is_all_other_closed(project_path: str, current_session_id: str) -> bool:
    """True if every other session is closed or stale (eligible for merge)."""
    sessions = list_sessions(project_path, include_closed=True)
    now = time.time()
    for s in sessions:
        if s.get("session_id") == current_session_id:
            continue
        if s.get("closed"):
            continue
        # Check staleness
        last = float(s.get("last_heartbeat", 0) or s.get("opened_at", 0))
        if now - last > SESSION_TTL_SECS or last - now > SESSION_TTL_SECS:
            continue  # stale → treat as closed
        # Found an active session
        return False
    return True


def get_active_sessions(project_path: str) -> list[dict]:
    """Active (not closed, not stale) sessions."""
    now = time.time()
    active: list[dict] = []
    for s in list_sessions(project_path, include_closed=True):
        if s.get("closed"):
            continue
        last = float(s.get("last_heartbeat", 0) or s.get("opened_at", 0))
        if now - last > SESSION_TTL_SECS or last - now > SESSION_TTL_SECS:
            continue
        active.append(s)
    return active


def prune_sessions(project_path: str) -> int:
    """Delete session files that can no longer matter: closed sessions older
    than the TTL, and stale (crashed) sessions whose heartbeat is long gone.
    Closed sessions have already exported their final replay, so their file is
    only needed for ack/merge bookkeeping for one TTL window.  Returns the
    number of files removed."""
    root = _sessions_dir(project_path)
    if not root.is_dir():
        return 0
    now = time.time()
    removed = 0
    for p in root.glob("*.json"):
        if p.name.endswith(".tmp"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        closed_at = float(data.get("closed_at", 0))
        last = float(data.get("last_heartbeat", 0) or data.get("opened_at", 0))
        if data.get("closed"):
            if closed_at and now - closed_at > SESSION_TTL_SECS:
                with contextlib.suppress(OSError):
                    p.unlink(missing_ok=True)
                    removed += 1
        elif now - last > SESSION_TTL_SECS * 2 or last - now > SESSION_TTL_SECS * 2:
            # Crashed long ago — prune its file and (below) its acks.
            with contextlib.suppress(OSError):
                p.unlink(missing_ok=True)
                removed += 1
        # Best-effort: drop this session's acks (they can no longer be needed).
        ack_dir = _acks_dir(project_path) / p.stem
        if ack_dir.is_dir():
            with contextlib.suppress(OSError):
                for f in ack_dir.glob("*.json"):
                    f.unlink(missing_ok=True)
                ack_dir.rmdir()
    return removed
