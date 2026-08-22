"""Project backups — snapshot, restore, GFS retention (SERVER_PLAN.md §9).

Snapshots are zips of the project directory EXCLUDING transport-internal
state (``changes/``, ``presence/``, lock files, ``backups/``). The WAL is
checkpointed first so ``data.qda`` is consistent. Every archive carries a
sha256 checksum; restore verifies it before swapping anything.

Retention is grandfather-father-son per ``QC_BACKUP_RETENTION``
(``daily=N,weekly=N,monthly=N``): a snapshot is KEPT when it is the newest
of its calendar day (within the last ``daily`` days), or newest of its ISO
week, or newest of its month — union of the three buckets.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException

from qualcoder_api.core.server_config import load_server_config
from qualcoder_api.persistence import metadata_db
from qualcoder_api.services.cleanup_service import checkpoint
from qualcoder_api.services.session_manager import manager

logger = logging.getLogger(__name__)

SKIP_DIRS = {"changes", "presence", "backups"}
SKIP_FILES = {"server.lock", "project_in_use.lock"}

CHUNK = 1024 * 1024


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _stamp() -> str:
    # Microsecond precision: two backups within one second must not
    # overwrite each other's archive.
    return _utcnow().strftime("%Y%m%d-%H%M%S%f")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _zip_project(source: Path, dest: Path) -> None:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                if name in SKIP_FILES:
                    continue
                full = Path(root) / name
                zf.write(full, str(full.relative_to(source)))


# ── Snapshot ────────────────────────────────────────────────────────────


async def create_backup(project_id: str, kind: str = "manual") -> dict:
    """Checkpoint WAL, zip the project, record it. Returns the new row."""
    cfg = load_server_config()
    project = await metadata_db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    source = Path(project["data_path"])
    if not source.is_dir():
        raise HTTPException(status_code=404, detail="project data missing")

    db_file = source / "data.qda"
    if db_file.exists():
        await checkpoint(str(db_file))

    backups_dir = cfg.backups_root / project_id
    backups_dir.mkdir(parents=True, exist_ok=True)
    archive = backups_dir / f"{project['name']}_{_stamp()}_{kind}.zip"
    _zip_project(source, archive)

    backup_id = await metadata_db.add_backup_record(
        project_id,
        kind,
        str(archive),
        archive.stat().st_size,
        _sha256(archive),
    )
    row = await metadata_db.get_backup_record(project_id, backup_id)
    assert row is not None  # just inserted
    return row


async def restore_backup(project_id: str, backup_id: int) -> dict:
    """Verify + swap an archived snapshot into the live project dir.

    The session closes first (single writer); the next authenticated
    request reopens transparently via the session manager."""
    record = await metadata_db.get_backup_record(project_id, backup_id)
    if record is None:
        raise HTTPException(status_code=404, detail="backup not found")
    project = await metadata_db.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    archive = Path(record["local_path"])
    if not archive.is_file():
        raise HTTPException(status_code=410, detail="backup archive missing on disk")
    if _sha256(archive) != record["checksum"]:
        raise HTTPException(status_code=500, detail="backup checksum mismatch — refusing restore")

    target = Path(project["data_path"])
    staging = Path(tempfile.mkdtemp(prefix="qc-restore-"))
    try:
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                p = Path(member)
                if p.is_absolute() or ".." in p.parts:
                    raise HTTPException(
                        status_code=422, detail=f"unsafe zip entry: {member}"
                    )
            zf.extractall(staging)
        if not (staging / "data.qda").is_file():
            raise HTTPException(status_code=422, detail="backup contains no data.qda")

        # Single-writer: close the session before touching live data.
        await manager.close(project_id)
        for child in target.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        for child in staging.iterdir():
            shutil.move(str(child), str(target / child.name))
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    await metadata_db.touch_project(project_id)
    logger.info("backup %s restored into %s", backup_id, project_id)
    return {"ok": True, "restored_from": backup_id}


# ── Retention (grandfather-father-son) ──────────────────────────────────


def parse_retention(policy: str) -> dict[str, int]:
    """``daily=14,weekly=8,monthly=12`` → counts, defaults preserved."""
    counts = {"daily": 14, "weekly": 8, "monthly": 12}
    for part in policy.split(","):
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        key = key.strip().lower()
        if key in counts and raw.strip().lstrip("-").isdigit():
            counts[key] = max(0, int(raw))
    return counts


def gfs_keep_ids(records: list[dict], counts: dict[str, int]) -> set[int]:
    """IDs kept under grandfather-father-son, ``records`` NEWEST first.

    Only the NEWEST snapshot of each calendar day can occupy a daily slot;
    likewise for ISO weeks and months. A record survives when it occupies a
    slot whose newest-first index is within that bucket's count.
    """
    day_keys: list[str] = []
    week_keys: list[str] = []
    month_keys: list[str] = []
    kept: set[int] = set()

    for rec in records:
        dt = rec["dt"]
        iso = dt.isocalendar()
        dkey = dt.date().isoformat()
        wkey = f"{iso.year}-W{iso.week:02d}"
        mkey = f"{dt.year}-{dt.month:02d}"

        d_new = dkey not in day_keys
        w_new = wkey not in week_keys
        m_new = mkey not in month_keys
        if d_new:
            day_keys.append(dkey)
        if w_new:
            week_keys.append(wkey)
        if m_new:
            month_keys.append(mkey)

        if (
            (d_new and day_keys.index(dkey) < counts["daily"])
            or (w_new and week_keys.index(wkey) < counts["weekly"])
            or (m_new and month_keys.index(mkey) < counts["monthly"])
        ):
            kept.add(rec["id"])
    return kept


async def apply_retention(policy: str | None = None) -> int:
    """Prune snapshots per policy; returns how many were deleted."""
    counts = parse_retention(policy or load_server_config().backup_retention)
    factory = metadata_db.metadata_factory()

    from sqlalchemy import text

    async with factory() as session:
        rows = (
            await session.execute(
                text("SELECT id, local_path, created_at FROM backup_records")
            )
        ).mappings().all()

    records: list[dict] = [
        {
            "id": int(r["id"]),
            "path": str(r["local_path"]),
            "dt": datetime.fromisoformat(str(r["created_at"])),
        }
        for r in rows
    ]
    records.sort(key=lambda r: r["dt"], reverse=True)

    kept = gfs_keep_ids(records, counts)
    deleted = 0
    for rec in records:
        if rec["id"] in kept:
            continue
        Path(rec["path"]).unlink(missing_ok=True)
        await metadata_db.delete_backup_record(rec["id"])
        deleted += 1
    return deleted


# ── Scheduled sweep ─────────────────────────────────────────────────────


async def run_all_scheduled(max_age_hours: int = 24) -> int:
    """One scheduled snapshot per active project lacking a fresh one."""
    cutoff = (
        (_utcnow() - timedelta(hours=max_age_hours)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    )
    ran = 0
    for pid in await metadata_db.list_active_project_ids():
        latest = await metadata_db.latest_backup_created(pid)
        if latest is not None and latest >= cutoff:
            continue
        try:
            await create_backup(pid, kind="scheduled")
            ran += 1
        except Exception:
            logger.exception("scheduled backup failed for project %s", pid)
    return ran
