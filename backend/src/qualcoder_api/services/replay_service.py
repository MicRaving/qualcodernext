"""Per-session replay files and ack-based deletion for online projects.

Each session appends its changes to ``replays/<session_id>.jsonl`` (one file
per session, not per machine).  Other instances replay those files.  The
session admin (last-closing session) merges all replays into the master
``data.qda`` when every other session is closed, and replay files are deleted
only when every instance has acked them *and* they are in the master.

Legacy sidecars at ``changes/<instance>/changes.jsonl`` are still read as a
single replay source for migration (LSTeach).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

REPLAY_DIR_NAME = "replays"
ACK_DIR_NAME = "acks"
MASTER_WATERMARK_FILE = "replays/merged.json"
LEGACY_CHANGES_DIR = "changes"


def _replays_dir(project_path: str) -> Path:
    return Path(project_path) / REPLAY_DIR_NAME


def _acks_root(project_path: str) -> Path:
    return Path(project_path) / ACK_DIR_NAME


def _master_watermark_path(project_path: str) -> Path:
    return Path(project_path) / MASTER_WATERMARK_FILE


def replay_path(project_path: str, session_id: str) -> Path:
    return _replays_dir(project_path) / f"{session_id}.jsonl"


def ack_path(project_path: str, replay_session_id: str, acker_session_id: str) -> Path:
    return _acks_root(project_path) / replay_session_id / f"{acker_session_id}.json"


def _parse_replay(path: Path) -> list[dict]:
    """Parse a replay file defensively; corrupt tails are dropped."""
    entries: list[dict] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return entries
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries


def _max_replay_seq(project_path: str) -> int:
    """Highest seq across all per-session replays and legacy sidecars."""
    max_seq = 0
    # Per-session replays
    replays_dir = _replays_dir(project_path)
    if replays_dir.is_dir():
        for p in replays_dir.glob("*.jsonl"):
            for e in _parse_replay(p):
                try:
                    max_seq = max(max_seq, int(e.get("seq", 0)))
                except (TypeError, ValueError):
                    continue
    # Legacy sidecars (for migration)
    legacy_root = Path(project_path) / LEGACY_CHANGES_DIR
    if legacy_root.is_dir():
        for d in legacy_root.iterdir():
            if not d.is_dir():
                continue
            p = d / "changes.jsonl"
            if not p.exists():
                continue
            for e in _parse_replay(p):
                try:
                    max_seq = max(max_seq, int(e.get("seq", 0)))
                except (TypeError, ValueError):
                    continue
    return max_seq


def append_replay(project_path: str, session_id: str, lines: str) -> bool:
    """Append lines to the session's replay file (fsynced). Returns True on success."""
    path = replay_path(project_path, session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure file ends with newline before appending
        if path.exists() and path.stat().st_size > 0:
            with open(path, "rb") as rf:
                rf.seek(-1, os.SEEK_END)
                if rf.read(1) != b"\n":
                    with open(path, "ab") as wf:
                        wf.write(b"\n")
        with open(path, "ab") as f:
            f.write(lines.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        if hasattr(os, "O_DIRECTORY"):
            with contextlib.suppress(OSError):
                dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        return True
    except OSError as err:
        logger.warning("append_replay failed for %s: %s", session_id, err)
        return False


def list_replays(project_path: str) -> list[Path]:
    """All per-session replay files plus legacy sidecars (for replay)."""
    out: list[Path] = []
    replays_dir = _replays_dir(project_path)
    if replays_dir.is_dir():
        out.extend(sorted(replays_dir.glob("*.jsonl")))
    # Include legacy sidecars as replays (migration)
    legacy_root = Path(project_path) / LEGACY_CHANGES_DIR
    if legacy_root.is_dir():
        for d in sorted(legacy_root.iterdir()):
            if not d.is_dir():
                continue
            p = d / "changes.jsonl"
            if p.exists() and p.stat().st_size > 0:
                out.append(p)
    return out


def list_session_replays(project_path: str) -> list[Path]:
    """Only per-session replays (excludes legacy)."""
    replays_dir = _replays_dir(project_path)
    if not replays_dir.is_dir():
        return []
    return sorted(replays_dir.glob("*.jsonl"))


def write_ack(project_path: str, replay_session_id: str, acker_session_id: str) -> bool:
    """Record that acker_session has merged replay_session."""
    path = ack_path(project_path, replay_session_id, acker_session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "replay_session_id": replay_session_id,
            "acker_session_id": acker_session_id,
            "acked_at": time.time(),
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
        with contextlib.suppress(OSError), open(path, "rb") as f:
            os.fsync(f.fileno())
        return True
    except OSError as err:
        logger.warning("write_ack failed %s->%s: %s", acker_session_id, replay_session_id, err)
        return False


def has_acked(project_path: str, replay_session_id: str, acker_session_id: str) -> bool:
    return ack_path(project_path, replay_session_id, acker_session_id).exists()


def all_acked(project_path: str, replay_session_id: str) -> bool:
    """True if every *active* (non-closed, non-stale) session has acked this replay.

    Closed and stale (crashed, no heartbeat for the TTL) sessions are
    implicitly acked — they can no longer import, so their ack would block
    replay deletion forever.  The replay's own session is considered to have
    merged it (it created it).
    """
    from qualcoder_api.services.session_service import list_sessions

    sessions = list_sessions(project_path, include_closed=True)
    for s in sessions:
        sid = s.get("session_id")
        if sid == replay_session_id:
            continue
        if s.get("closed") or s.get("_stale"):
            continue
        # Active session must have acked
        if not has_acked(project_path, replay_session_id, sid):
            return False
    return True


def read_master_watermark(project_path: str) -> dict:
    path = _master_watermark_path(project_path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"merged_sessions": [], "max_seq": 0, "merged_at": None}


def write_master_watermark(
    project_path: str, merged_sessions: list[str], max_seq: int, merged_by: str
) -> None:
    path = _master_watermark_path(project_path)
    data = {
        "merged_sessions": sorted(set(merged_sessions)),
        "max_seq": int(max_seq),
        "merged_at": time.time(),
        "merged_by": merged_by,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
        with contextlib.suppress(OSError), open(path, "rb") as f:
            os.fsync(f.fileno())
    except OSError as err:
        logger.warning("write_master_watermark failed: %s", err)


def is_merged_in_master(project_path: str, replay_session_id: str) -> bool:
    wm = read_master_watermark(project_path)
    return replay_session_id in wm.get("merged_sessions", [])


def can_delete_replay(project_path: str, replay_session_id: str) -> bool:
    """Replay can be deleted iff merged into master AND all acked."""
    if not is_merged_in_master(project_path, replay_session_id):
        return False
    return all_acked(project_path, replay_session_id)


def delete_replay_if_deletable(project_path: str, replay_session_id: str) -> bool:
    """Delete replay file and its acks if deletable. Returns True if deleted."""
    if not can_delete_replay(project_path, replay_session_id):
        return False
    # Delete replay file (per-session)
    replay_file = replay_path(project_path, replay_session_id)
    # Also check legacy path (if replay_session_id is an instance_id, the file is at changes/<instance>/changes.jsonl)
    # For new per-session replays, the file is at replays/<session>.jsonl
    # For legacy, we should not delete the legacy file via this path; handle separately.
    deleted = False
    if replay_file.exists():
        with contextlib.suppress(OSError):
            replay_file.unlink()
            deleted = True
        # Delete acks
        ack_dir = _acks_root(project_path) / replay_session_id
        if ack_dir.is_dir():
            with contextlib.suppress(OSError):
                for p in ack_dir.glob("*.json"):
                    p.unlink(missing_ok=True)
                ack_dir.rmdir()
    return deleted


def cleanup_replays(project_path: str) -> int:
    """Delete all deletable replays (merged into master + acked by every
    active session), then prune closed/stale session files. Returns count deleted."""
    from qualcoder_api.services.session_service import prune_sessions

    count = 0
    # Only consider per-session replays for deletion; legacy sidecars are not deleted via acks
    for replay_file in list_session_replays(project_path):
        session_id = replay_file.stem
        if delete_replay_if_deletable(project_path, session_id):
            count += 1
    with contextlib.suppress(Exception):
        prune_sessions(project_path)
    return count
