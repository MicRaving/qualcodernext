"""Sync sidecar — append-only JSONL sidecar I/O, compaction, and trimming."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.services.sync_schema import (
    SYNC_DIR_NAME,
)

logger = logging.getLogger(__name__)


def _facade():
    """Late-bound access to the ``sync_engine`` facade namespace.

    The compaction thresholds are monkey-patchable ON the facade (the
    test suite does exactly that), so they are resolved through it at
    CALL time instead of via a from-import snapshot."""
    from qualcoder_api.services import sync_engine

    return sync_engine


def _sidecar_path(project_path: str, instance_id: str) -> Path:
    return Path(project_path) / SYNC_DIR_NAME / instance_id / "changes.jsonl"


def _parse_sidecar(path: Path) -> list[dict]:
    """Read JSONL lines defensively; corrupt tails are dropped."""
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


def _append_sidecar(sidecar: Path, lines: str) -> None:
    """Append exported JSONL lines to a sidecar file (atomic tail)."""
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    if sidecar.exists() and sidecar.stat().st_size > 0:
        with open(sidecar, "rb") as rf:
            rf.seek(-1, os.SEEK_END)
            if rf.read(1) != b"\n":
                with open(sidecar, "ab") as wf:
                    wf.write(b"\n")
    with open(sidecar, "ab") as f:
        f.write(lines.encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    # Directory fsync so the new file/size is visible to a second rater
    # opening immediately after activation (network-share cache).  O_DIRECTORY
    # is not available on Windows, so this is best-effort and POSIX-only.
    if hasattr(os, "O_DIRECTORY"):
        try:
            dir_fd = os.open(str(sidecar.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
            # Also fsync the changes root to make the new instance subdir visible.
            try:
                root_fd = os.open(str(sidecar.parent.parent), os.O_DIRECTORY)
                try:
                    os.fsync(root_fd)
                finally:
                    os.close(root_fd)
            except OSError:
                pass
        except OSError:
            pass


# Indirection hook — sync.py replaces this at import time so that
# ``monkeypatch.setattr(sync, "_append_sidecar", ...)`` takes effect.
_append_sidecar_hook = _append_sidecar


def _compact_sidecar(sidecar: Path) -> int:
    """Rewrite a sidecar to one entry per (entity, pk), keeping the latest.

    The sidecar is append-only during normal operation, but it grows without
    bound as a project accumulates changes.  Once it passes the compaction
    threshold it is rewritten so each row appears exactly once (its newest
    entry).  This is safe because replay is idempotent and versioned: a fresh
    instance only needs the latest state per row, and existing instances have
    already advanced their import watermark past the dropped history.

    Returns the number of entries kept (0 when the file was left untouched).
    """
    entries = _parse_sidecar(sidecar)
    if not entries:
        return 0
    try:
        size = sidecar.stat().st_size
    except OSError:
        size = 0
    if len(entries) < _facade().SIDECAR_COMPACT_THRESHOLD_ENTRIES and size < _facade().SIDECAR_COMPACT_THRESHOLD_BYTES:
        return 0
    # Keep the latest entry per (entity, pk) — later entries win (they carry
    # a higher seq and rev).  Preserve the original order of first appearance
    # so the file stays a valid, ordered change log.
    latest: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for e in entries:
        key = (str(e.get("entity", "")), str(e.get("pk_value", "")))
        if key not in latest:
            order.append(key)
        latest[key] = e
    lines = "\n".join(
        json.dumps(latest[k], ensure_ascii=False) for k in order
    ) + "\n"
    tmp = sidecar.with_suffix(".tmp")
    try:
        tmp.write_text(lines, encoding="utf-8")
        tmp.replace(sidecar)
    except OSError as err:  # pragma: no cover - defensive
        logger.warning("sidecar compaction failed: %s", err)
        return 0
    return len(order)


async def _trim_sync_log(session: AsyncSession, exported_seq: int) -> int:
    """Delete already-exported sync_log rows, keeping the latest row per user.

    The change journal is only needed to (a) export rows newer than the
    watermark and (b) keep the per-user ``seq`` counter monotonic.  Rows at or
    below the export watermark have already reached the sidecar and are dead
    weight, so they are dropped — except the most recent row per user, which
    anchors the seq counter so it never resets.  Rows above the watermark are
    still pending export and are never touched.
    """
    result = await session.execute(
        text(
            "DELETE FROM sync_log WHERE id <= :wm AND id NOT IN ("
            "SELECT MAX(id) FROM sync_log GROUP BY user)"
        ),
        {"wm": exported_seq},
    )
    return int(getattr(result, "rowcount", 0) or 0)


def _max_sidecar_seq(project_path: str) -> int:
    """The highest ``seq`` across every instance's sidecar (0 when none)."""
    changes_root = Path(project_path) / SYNC_DIR_NAME
    if not changes_root.is_dir():
        return 0
    max_seq = 0
    for sidecar_dir in changes_root.iterdir():
        if not sidecar_dir.is_dir():
            continue
        sidecar = sidecar_dir / "changes.jsonl"
        if not sidecar.exists():
            continue
        for e in _parse_sidecar(sidecar):
            try:
                max_seq = max(max_seq, int(e.get("seq", 0)))
            except (TypeError, ValueError):
                continue
    return max_seq
