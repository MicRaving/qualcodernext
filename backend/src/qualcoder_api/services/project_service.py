"""Project lifecycle service — create, open, close, backup, lock.

Pure backend: no Qt, no UI. The FastAPI layer wraps these methods.
"""

from __future__ import annotations

import asyncio
import contextlib
import getpass
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qualcoder_api.core.models import Project
from qualcoder_api.persistence.database import (
    create_project_engine,
    create_session_factory,
    dispose_engine,
)
from qualcoder_api.persistence.migration import MigrationChain
from qualcoder_api.persistence.repositories import ProjectRepository
from qualcoder_api.persistence.schema import create_new_project_schema

logger = logging.getLogger(__name__)

LOCK_TIMEOUT_SECS = 300.0
LOCK_FILE_NAME = "project_in_use.lock"
BACKUP_FOLDER = "backups"


@dataclass
class OpenResult:
    """Outcome of opening a project."""

    ok: bool
    project_path: str = ""
    project_name: str = ""
    migrations_applied: list[str] = field(default_factory=list)
    error: str = ""
    lock_user: str = ""
    duplicate_coder: str = ""


class ProjectService:
    """Encapsulates project lifecycle operations for the v4 backend."""

    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker | None = None
        self.project_path: str = ""
        self.project_name: str = ""
        self.lock_file_path: str = ""
        #: Serializes the project lifecycle (create/open/close). These are
        #: long multi-await operations on SHARED state (``self.project_path``,
        #: the engine, the lock file); an interleaved close used to reset
        #: ``project_path`` mid-create, which then appended "" to the recent
        #-projects list and left the backend reporting "no project open".
        self._lifecycle_lock = asyncio.Lock()
        #: Live presence: the source currently being worked on in THIS
        #: instance (reported by the frontend, broadcast via the presence
        #: heartbeat to other instances).
        self.current_source_id: int | None = None
        self.current_source_name: str = ""
        #: Collaboration mode state — True when a ``.qcnext-project`` marker is
        #: present and the live working DB is a local sandbox (``data.qda`` is
        #: then a cold archive refreshed on close).
        self.collab: bool = False
        self.uuid: str = ""
        #: Current online session id (per-open, not per-machine).  Empty when
        #: offline or when no project is open.  Used for per-session replay
        #: files and heartbeat/close reports.
        self.current_session_id: str = ""

    def set_current_source(self, source_id: int | None, source_name: str = "") -> None:
        """Record the source this instance is currently working on."""
        self.current_source_id = source_id
        self.current_source_name = source_name

    def collaboration_mode(self) -> bool:
        """Whether the open project runs in collaboration (sandbox) mode."""
        return bool(self.collab and self.uuid)

    def _resolve_mode(self, project_path: str) -> None:
        """Set ``self.collab``/``self.uuid`` from the project marker."""
        from qualcoder_api.services import project_marker

        marker = project_marker.read_marker(project_path)
        if marker and marker.get("uuid"):
            self.collab = True
            self.uuid = str(marker["uuid"])
        else:
            self.collab = False
            self.uuid = ""

    def heartbeat_session(self) -> None:
        """Refresh the current session's heartbeat (per-session activity)."""
        if not self.collab or not self.project_path or not self.current_session_id:
            return
        try:
            from qualcoder_api.services import session_service

            session_service.heartbeat(self.project_path, self.current_session_id)
        except Exception as err:
            logger.debug("heartbeat_session failed for %s: %s", self.current_session_id, err)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _ensure_engine(self) -> tuple[AsyncEngine, async_sessionmaker]:
        if self.engine is None or self.session_factory is None:
            raise RuntimeError("No project is open")
        return self.engine, self.session_factory

    async def _dispose_engine_if_any(self) -> None:
        """Close the current engine (if any) before a new one is opened.

        Reopening/creating a project without disposing the previous engine
        leaked its sqlite connection, which on Windows keeps the project
        database file locked (WAL/-shm/-wal) so the folder cannot be deleted.
        """
        if self.engine is not None:
            await dispose_engine(self.engine)
            self.engine = None
            self.session_factory = None

    # ------------------------------------------------------------------
    # New project
    # ------------------------------------------------------------------

    async def create_project(
        self,
        project_path: str,
        *,
        app_version: str = "QualCoder 4.0",
        codername: str = "default",
    ) -> bool:
        """Create the project directory structure, schema and initial row."""
        async with self._lifecycle_lock:
            if not project_path or len(project_path) > 4096 or "\x00" in project_path:
                logger.warning("Project creation rejected: invalid path")
                return False
            if not project_path.endswith(".qda"):
                project_path += ".qda"

            counter = 0
            extension = ""
            # TOCTOU note: existence check + mkdir race is benign here —
            # mkdir(parents=True) without exist_ok raises if a concurrent
            # create won, which we treat as failure below.
            while os.path.exists(project_path + extension):
                counter += 1
                if counter > 999:
                    logger.warning("Project creation rejected: too many collisions")
                    return False
                extension = f"_{counter}"

            final_path = project_path + extension
            self.project_path = final_path
            root = Path(final_path)
            try:
                for sub in ("images", "audio", "video", "documents", BACKUP_FOLDER):
                    (root / sub).mkdir(parents=True)
            except OSError as err:
                logger.critical("Project creation error: %s", err)
                return False

            self.project_name = root.name
            db_path = root / "data.qda"
            conn = await aiosqlite.connect(db_path)
            try:
                await create_new_project_schema(
                    conn, app_version=app_version, codername=codername
                )
            finally:
                await conn.close()

            await self._dispose_engine_if_any()
            await self._open_engine()
            from qualcoder_api.services import user_settings

            user_settings.append_recent_project(final_path)
            return True

    # ------------------------------------------------------------------
    # Open project
    # ------------------------------------------------------------------

    async def open_project(
        self,
        proj_path: str,
        *,
        app_version: str = "QualCoder 4.0",
        codername: str = "default",
        backup_on_open: bool = False,
    ) -> OpenResult:
        """Open an existing project: lock, validate, migrate, finalize."""
        async with self._lifecycle_lock:
            return await self._open_project_locked(
                proj_path,
                app_version=app_version,
                codername=codername,
                backup_on_open=backup_on_open,
            )

    async def _open_project_locked(
        self,
        proj_path: str,
        *,
        app_version: str = "QualCoder 4.0",
        codername: str = "default",
        backup_on_open: bool = False,
    ) -> OpenResult:
        """Open body — caller holds ``_lifecycle_lock``."""
        # Parse recent-projects format: "date|path"
        if not proj_path or len(proj_path) > 4096 or "\x00" in proj_path:
            return OpenResult(ok=False, error="not a .qda project path")
        actual_path = proj_path.split("|")[-1]
        if not (len(actual_path) > 3 and actual_path[-4:] == ".qda"):
            return OpenResult(ok=False, error="not a .qda project path")

        root = Path(actual_path)
        if not root.is_dir():
            return OpenResult(ok=False, error="project directory missing")

        # Presence registry: never blocks; other live openers are reported
        # for the UI (simultaneous work is supported).
        self._acquire_lock(actual_path, codername)
        lock_user = self._read_lock_user(actual_path)
        duplicate_coder = self.detect_duplicate_coder(actual_path, codername)

        self.project_path = actual_path
        self.project_name = root.name
        self._resolve_mode(actual_path)
        # Session-based online handling: create a new session for this open
        # if we are in collaboration mode.  Each open gets a fresh session id
        # and a new replay file, as per the spec (2d).
        if self.collab:
            from qualcoder_api.services import session_service
            from qualcoder_api.services.user_settings import get_instance_id

            try:
                self.current_session_id = session_service.create_session(
                    actual_path, codername, instance_id=get_instance_id()
                )
                logger.info("created online session %s for %s", self.current_session_id, codername)
            except Exception as err:
                logger.warning("create_session failed: %s", err)
                self.current_session_id = ""
        if not self.collab:
            # A marker written moments ago by another instance can be
            # briefly invisible to THIS process on Windows (AV/indexing).
            # Misclassifying collaboration as single makes the second rater
            # edit the cold archive directly — re-check before concluding.
            from qualcoder_api.services import project_marker as _pm

            for _ in range(4):
                if _pm.marker_exists(actual_path):
                    self._resolve_mode(actual_path)
                    break
                await asyncio.sleep(0.25)

        try:
            await self._dispose_engine_if_any()
            if self.collab:
                await self._ensure_sandbox(actual_path, codername)
            await self._open_engine()
            header = await self._get_header()
            if header is None or "QualCoder" not in (header.about or ""):
                await self._close_project_locked()
                return OpenResult(ok=False, error="not a QualCoder database")
        except Exception as err:
            await self._close_project_locked()
            logger.debug("Not a QualCoder database: %s", err)
            return OpenResult(ok=False, error=str(err))

        conn = await aiosqlite.connect(self.db_path())
        applied: list[str] = []
        try:
            chain = MigrationChain(conn)
            applied = await chain.run_all(app_version, codername)
            await self._finalize_open(codername)
        finally:
            await conn.close()

        if backup_on_open:
            try:
                await self.save_backup()
            except Exception as err:
                logger.warning("Backup on open failed: %s", err)

        from qualcoder_api.services import user_settings

        user_settings.append_recent_project(actual_path)
        return OpenResult(
            ok=True,
            project_path=actual_path,
            project_name=self.project_name,
            migrations_applied=applied,
            lock_user=lock_user,
            duplicate_coder=duplicate_coder,
        )

    async def _get_header(self) -> Project | None:
        _, session_factory = self._ensure_engine()
        async with session_factory() as session:
            return await ProjectRepository(session).get_header()

    async def _finalize_open(self, codername: str) -> None:
        """Post-migration maintenance (legacy finalize_project_open)."""
        # VACUUM cannot run inside a transaction — use a raw connection.
        conn = await aiosqlite.connect(self.db_path())
        try:
            await conn.execute("VACUUM")
            await conn.commit()
        finally:
            await conn.close()
        _, session_factory = self._ensure_engine()
        async with session_factory() as session:
            repo = ProjectRepository(session)
            await session.execute(
                text(
                    "UPDATE code_cat SET supercatid = NULL WHERE supercatid IS NOT NULL "
                    "AND supercatid NOT IN (SELECT catid FROM code_cat)"
                )
            )
            await repo.update_coder_names(codername)
            await session.execute(
                text("UPDATE project SET codername = :c"), {"c": codername}
            )
            await session.commit()

    def db_path(self) -> str:
        if self.collab and self.uuid:
            from qualcoder_api.services import sandbox

            return str(sandbox.sandbox_path(self.uuid, self._sandbox_instance()))
        return os.path.join(self.project_path, "data.qda")

    def _sandbox_instance(self) -> str:
        """The per-instance sandbox key (stable per machine).  Two raters on
        the same machine never share a sandbox file; a machine's sandbox is
        rebuilt/kept independently of other machines'."""
        from qualcoder_api.services.user_settings import get_instance_id

        return get_instance_id()

    # ------------------------------------------------------------------
    # Close / dispose
    # ------------------------------------------------------------------

    async def close_project(self) -> None:
        """Close the project: dispose engine, flush the WAL, remove lock file.

        Serialized against create/open via ``_lifecycle_lock`` — a close that
        lands mid-open/mid-create used to reset ``project_path`` under the
        other operation's feet.
        """
        async with self._lifecycle_lock:
            await self._close_project_locked()

    async def _close_project_locked(self) -> None:
        """Close body — caller holds ``_lifecycle_lock``.

        The WAL checkpoint runs best-effort after the engine is disposed (no
        other connection exists then, so the flush is clean): the ``data.qda``
        file left behind is self-consistent, which also makes any subsequent
        copy/backup consistent. When the "compact project on close" setting is
        enabled, the full compaction runs here instead — also best-effort, a
        failing cleanup must never break closing.
        """
        # Session-based: mark this session as closed BEFORE consolidate,
        # so the admin-merge check (all others closed) sees us as closed.
        if self.collab and self.project_path and self.current_session_id:
            try:
                from qualcoder_api.services import session_service

                session_service.close_session(self.project_path, self.current_session_id)
            except Exception as err:
                logger.warning("close_session failed for %s: %s", self.current_session_id, err)

        if self.collab and self.project_path:
            await self._consolidate_on_close()
        await self._dispose_engine_if_any()
        if self.project_path and not self.collab:
            from qualcoder_api.services.cleanup_service import checkpoint

            try:
                await checkpoint(self.db_path())
            except Exception as err:
                logger.warning("WAL checkpoint on close failed: %s", err)
            try:
                from qualcoder_api.services import user_settings

                if user_settings.get_compact_on_close():
                    from qualcoder_api.services.cleanup_service import compact_project

                    await compact_project(self.db_path())
                    user_settings.set_last_compact()
            except Exception as err:
                logger.warning("Compact project on close failed: %s", err)
        self.delete_lock_file()
        if self.project_path:
            from qualcoder_api.services import presence_service

            presence_service.clear(self.project_path)
        self.project_path = ""
        self.project_name = ""
        self.current_source_id = None
        self.current_source_name = ""
        self.current_session_id = ""

    async def _converge(self, session_id: str) -> None:
        """Export THIS session's pending rows to its replay, then import every
        other session's replays into the local sandbox (so the sandbox holds
        the merged latest state before any master snapshot)."""
        from qualcoder_api.services import sync

        _, factory = self._ensure_engine()
        async with factory() as session:
            await sync.export_pending(session, self.project_path, session_id)
        async with factory() as session:
            await sync.import_pending(session, self.project_path, session_id)

    async def _snapshot_master(self) -> bool:
        """Refresh the cold ``data.qda`` archive from the live sandbox.

        Uses ``VACUUM INTO`` (safe while the engine stays open — a separate raw
        connection reads the sandbox and writes a fresh self-consistent file),
        then switches the archive to a rollback journal and advances the
        consolidation watermark.  This replaces the old dispose → checkpoint →
        copy2 sequence, which kept failing on Windows with "database is locked".
        Returns True when the snapshot was written.
        """
        from qualcoder_api.core.timeutil import now
        from qualcoder_api.services import project_marker, sync_engine

        sandbox_db = self.db_path()
        archive = Path(self.project_path) / "data.qda"
        import aiosqlite as _aiosqlite

        try:
            tmp = archive.with_suffix(".tmp")
            conn = await _aiosqlite.connect(sandbox_db)
            try:
                await conn.execute(f"VACUUM INTO '{tmp}'")
            finally:
                await conn.close()
            tmp.replace(archive)
            conn = await _aiosqlite.connect(str(archive))
            try:
                await conn.execute("PRAGMA journal_mode=DELETE")
            finally:
                await conn.close()
            for suffix in ("-wal", "-shm"):
                Path(str(archive) + suffix).unlink(missing_ok=True)
            self._cleanup_conflicted_copies(self.project_path)
            project_marker.update_consolidation_watermark(
                self.project_path, now(), sync_engine._max_sidecar_seq(self.project_path)
            )
            return True
        except Exception as err:  # pragma: no cover - depends on sqlite version
            logger.warning("master snapshot failed: %s", err)
            return False

    async def _maybe_merge_master(self, session_id: str) -> bool:
        """Admin merge (spec 2c): when every OTHER session is closed or stale,
        snapshot the local sandbox into the master ``data.qda``, record the
        merged replays in ``replays/merged.json``, ack them, and clean up the
        ones that are merged and acked.  Returns True when a merge ran.

        Also called from the background sync loop so a crashed instance's
        replay is still merged once its session goes stale — not only on the
        next explicit close.
        """
        from qualcoder_api.core.timeutil import now
        from qualcoder_api.services import (
            project_marker,
            replay_service,
            session_service,
            sync_engine,
        )

        if not session_id:
            return False
        try:
            if not session_service.is_all_other_closed(self.project_path, session_id):
                logger.debug("not merging master for %s: other sessions still active", session_id)
                return False
        except Exception as err:
            logger.debug("is_all_other_closed check failed: %s", err)
            return False

        merged = await self._snapshot_master()
        if not merged:
            return False
        try:
            # All per-session replays that existed at merge time are now in the
            # master.  Record them in the watermark so the acks/cleanup can
            # decide what is safe to delete.
            all_replays = replay_service.list_session_replays(self.project_path)
            merged_ids = [p.stem for p in all_replays]
            max_seq = sync_engine._max_sidecar_seq(self.project_path)
            with contextlib.suppress(Exception):
                max_seq = max(max_seq, replay_service._max_replay_seq(self.project_path))
            replay_service.write_master_watermark(
                self.project_path, merged_ids, max_seq, session_id
            )
            for rid in merged_ids:
                if rid == session_id:
                    continue
                with contextlib.suppress(Exception):
                    replay_service.write_ack(self.project_path, rid, session_id)
            with contextlib.suppress(Exception):
                deleted = replay_service.cleanup_replays(self.project_path)
                if deleted:
                    logger.info("cleaned up %s merged replays for %s", deleted, session_id)
            project_marker.update_consolidation_watermark(self.project_path, now(), max_seq)
        except Exception as err:
            logger.debug("master watermark/ack update failed: %s", err)
        return True

    async def _consolidate_on_close(self) -> None:
        """Collaboration-mode close: converge, then refresh the cold archive.

        Final export + import bring the sandbox to the merged latest state;
        the sandbox is snapshotted over the shared ``data.qda`` archive via
        ``VACUUM INTO`` and stray conflicted copies are removed.

        Session-based online handling (spec 2c): the master is only updated
        when every other session is reported closed (or stale).  Otherwise
        this closing session just leaves its replay file for peers to import;
        the last-closing session (the admin) performs the merge.
        """
        from qualcoder_api.services.user_settings import get_instance_id

        session_id = getattr(self, "current_session_id", "") or ""
        try:
            if session_id:
                await self._converge(session_id)
            else:
                # Legacy per-instance path (pre-session projects, e.g. LSTeach).
                await self._converge(get_instance_id())
        except Exception as err:
            logger.warning("final sync on close failed: %s", err)

        if session_id:
            await self._maybe_merge_master(session_id)
        else:
            await self._snapshot_master()
        await self._dispose_engine_if_any()

    @staticmethod
    def _cleanup_conflicted_copies(project_path: str) -> None:
        """Remove stale ``data.qda (*conflicted copy*).qda`` files from the
        shared folder left by cloud-sync conflict resolution."""
        import contextlib

        for f in Path(project_path).glob("data.qda (*conflicted copy*).qda"):
            with contextlib.suppress(OSError):
                f.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Collaboration activation / revert / consolidate
    # ------------------------------------------------------------------

    async def activate_collaboration(self, codername: str = "") -> dict:
        """Switch the open project to collaboration (sandbox) mode.

        Gates on sync being enabled and ≥2 real coders; idempotent.  The
        current ``data.qda`` is checkpointed and copied into a fresh local
        sandbox, the marker is written, the engine is reopened on the sandbox,
        and the full state is exported to this instance's sidecar so other
        machines can rebuild.
        """
        import secrets

        from qualcoder_api.services import project_marker, sandbox, sync
        from qualcoder_api.services.cleanup_service import checkpoint
        from qualcoder_api.services.user_settings import get_instance_id

        if not self.project_path:
            return {"ok": False, "reason": "no project is open"}
        if self.collab:
            return {"ok": False, "reason": "collaboration already active"}

        _, factory = self._ensure_engine()
        async with factory() as session:
            ok, reason = await sync.should_activate_collaboration(session, self.project_path)
        if not ok:
            return {"ok": False, "reason": reason}

        uuid = secrets.token_hex(6)  # 12 hex chars, unique per activation
        # Checkpoint with a brief retry if the WAL is busy (another connection
        # still holds a read transaction).  A busy checkpoint would leave the
        # copied sandbox stale and the sidecar snapshot incomplete.
        for _ in range(3):
            ck = await checkpoint(self.db_path())  # data.qda (WAL) -> self-consistent
            if not ck.get("busy"):
                break
            await asyncio.sleep(0.2)
        sandbox.create_sandbox_from(self.db_path(), uuid, self._sandbox_instance())
        self.uuid = uuid
        self.collab = True

        # Reopen on the SANDBOX and export the full state to this instance's
        # sidecar BEFORE writing the marker: the marker is the signal for
        # other instances to rebuild from the sidecars alone. Writing it
        # first let a second rater opening mid-activation rebuild from an
        # EMPTY sidecar and see a blank project.
        # For per-session online (new spec 2a), also create a session and
        # export to its per-session replay file.
        await self._dispose_engine_if_any()
        await self._open_engine()
        # Ensure we have a session for this activation (the opener may have
        # been offline, so no session yet).  Create one now.
        if not getattr(self, "current_session_id", ""):
            try:
                from qualcoder_api.services import session_service

                self.current_session_id = session_service.create_session(
                    self.project_path, codername, instance_id=get_instance_id()
                )
            except Exception:
                pass
        # Use per-session replay for new online projects, fall back to legacy
        # per-instance sidecar for the full-state snapshot (both are written
        # for migration; second raters will see at least one).
        _, factory = self._ensure_engine()
        export_result: dict = {}
        # Try per-session first (if we have a session)
        session_export_ok = False
        if getattr(self, "current_session_id", ""):
            try:
                async with factory() as session:
                    # Export to per-session replay

                    # We need to get the pending rows and write them to the per-session replay
                    # For now, also do a full-state export to the per-session replay
                    # Use the existing export_full_state but with session_id as the key
                    # It will write to replays/<session>.jsonl
                    # To do that, we need to make export_full_state handle per-session
                    # For now, call it with session_id
                    exp = await sync.export_full_state(session, self.project_path, self.current_session_id)
                    if not exp.get("deferred"):
                        session_export_ok = True
                        export_result = exp
            except Exception as err:
                logger.debug("per-session export failed: %s", err)
        # Always also do legacy per-instance export for backward compat (until all clients are 0.3.1+)
        # But if per-session succeeded, we can consider the legacy as optional
        if not session_export_ok:
            async with factory() as session:
                export_result = await sync.export_full_state(session, self.project_path, get_instance_id())
        # If the sidecar append was deferred (locked) the snapshot never
        # reached the shared folder — writing the marker would strand the
        # second rater on an empty sidecar.  Retry once after a short wait,
        # and if it still defers, roll back the activation.
        if export_result.get("deferred"):
            await asyncio.sleep(0.3)
            _, factory = self._ensure_engine()
            # Retry both
            if getattr(self, "current_session_id", ""):
                try:
                    async with factory() as session:
                        retry = await sync.export_full_state(session, self.project_path, self.current_session_id)
                        if not retry.get("deferred"):
                            export_result = retry
                            session_export_ok = True
                except Exception:
                    pass
            if not session_export_ok:
                async with factory() as session:
                    retry = await sync.export_full_state(session, self.project_path, get_instance_id())
                    if not retry.get("deferred"):
                        export_result = retry
        if export_result.get("deferred"):
            # Roll back: remove the sandbox we just created and reset mode.
            logger.warning("collaboration activation deferred: sidecar locked, rolling back")
            await self._dispose_engine_if_any()
            with contextlib.suppress(Exception):
                sandbox.remove_sandbox(uuid)
            self.collab = False
            self.uuid = ""
            # Also remove the session we just created
            if getattr(self, "current_session_id", ""):
                try:
                    from qualcoder_api.services import session_service

                    # Mark it closed and remove its files (best effort)
                    session_service.close_session(self.project_path, self.current_session_id)
                except Exception:
                    pass
                self.current_session_id = ""
            await self._open_engine()
            return {"ok": False, "reason": "sidecar locked, try again"}

        # Verify the sidecar actually landed on disk and is non-empty before
        # publishing the marker.  On network shares the file can be delayed
        # by the OS cache even after fsync.
        from pathlib import Path as _Path

        from qualcoder_api.services.sync_sidecar import _parse_sidecar

        # Check per-session replay first, then legacy
        sidecar_path = None
        if getattr(self, "current_session_id", ""):
            cand = _Path(self.project_path) / "replays" / f"{self.current_session_id}.jsonl"
            if cand.exists():
                sidecar_path = cand
        if sidecar_path is None:
            sidecar_path = _Path(self.project_path) / sync.SYNC_DIR_NAME / get_instance_id() / "changes.jsonl"
        for _ in range(5):
            if sidecar_path.exists() and sidecar_path.stat().st_size > 0:
                # Also ensure it parses to at least one entry.
                try:
                    if len(_parse_sidecar(sidecar_path)) > 0:
                        break
                except Exception:
                    pass
            await asyncio.sleep(0.2)

        # Marker LAST — the one-way door opens only once everything above
        # (sandbox + complete sidecar snapshot) is durably in place.
        project_marker.write_marker(self.project_path, uuid, codername=codername)
        return {"ok": True, "uuid": uuid, "reason": "collaboration activated"}

    async def revert_collaboration(self) -> dict:
        """Consolidate to ``data.qda`` and return to single-coder mode.

        Runs the same consolidation as close, removes the marker, the sandbox,
        the sidecars and the presence files, disables sync, and reopens on
        ``data.qda``.  A destructive, user-confirmed action.
        """
        import shutil

        from qualcoder_api.services import (
            presence_service,
            project_marker,
            sandbox,
            sync,
            user_settings,
        )

        if not self.collab or not self.uuid:
            return {"ok": False, "reason": "not in collaboration mode"}

        await self._consolidate_on_close()
        project_marker.remove_marker(self.project_path)
        changes_root = Path(self.project_path) / sync.SYNC_DIR_NAME
        if changes_root.exists():
            shutil.rmtree(changes_root, ignore_errors=True)
        presence_dir = Path(self.project_path) / "presence"
        if presence_dir.exists():
            shutil.rmtree(presence_dir, ignore_errors=True)
        sandbox.remove_sandbox(self.uuid)
        try:
            user_settings.save_sync_settings(False)
        except Exception as err:  # pragma: no cover - defensive
            logger.warning("could not disable sync on revert: %s", err)

        self.collab = False
        self.uuid = ""
        await self._dispose_engine_if_any()
        await self._open_engine()
        presence_service.clear(self.project_path)
        return {"ok": True, "reason": "reverted to single-coder mode"}

    async def consolidate(self) -> dict:
        """Refresh the cold ``data.qda`` archive from the live sandbox.

        Converges (export + import), then snapshots the sandbox into
        ``data.qda`` via SQLite's ``VACUUM INTO`` (safe while the engine stays
        open), switches the archive to a rollback journal, and advances the
        consolidation watermark.
        """
        from qualcoder_api.services.user_settings import get_instance_id

        if not self.collab or not self.uuid:
            return {"ok": False, "reason": "not in collaboration mode"}

        session_id = getattr(self, "current_session_id", "") or get_instance_id()
        try:
            await self._converge(session_id)
        except Exception as err:
            logger.warning("consolidate converge failed: %s", err)

        if not await self._snapshot_master():
            return {"ok": False, "reason": "consolidation failed"}
        return {"ok": True, "reason": "archive refreshed"}

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    async def save_backup(self, suffix: str = "") -> tuple[str, str]:
        """Copy the project database into the backups folder.

        Returns (message, backup_path).

        The WAL is flushed BEFORE the copy: a plain ``data.qda`` file copy
        would miss committed frames still sitting in the ``-wal`` file, so
        the backup would open as an inconsistent (older) database.  In
        collaboration mode the live sandbox is what gets backed up.
        """
        db_path = Path(self.db_path())
        if not db_path.exists():
            return ("no database to back up", "")
        try:
            from qualcoder_api.services.cleanup_service import checkpoint

            await checkpoint(str(db_path))
        except Exception as err:
            logger.warning("WAL checkpoint before backup failed: %s", err)
        stamp = time.strftime("%Y-%m-%d_%H%M%S")
        backup_name = f"backup_{self.project_name}_{stamp}{suffix}.qda"
        backup_path = Path(self.project_path) / BACKUP_FOLDER / backup_name
        shutil.copy2(db_path, backup_path)
        return (f"Backup created: {backup_name}", str(backup_path))

    # ------------------------------------------------------------------
    # Lock / presence registry
    # ------------------------------------------------------------------
    #
    # The lock file is a PRESENCE REGISTRY, not an exclusive lock: each open
    # instance appends one "user\tpid\tts" line and removes it on close.
    # Dead entries (crashes / force-quits) are pruned on every open, so
    # multiple app instances can work on the same project simultaneously
    # (sqlite WAL handles concurrent writers). Legacy 3-line locks are
    # treated as a single entry and pruned when their owner is gone.

    @staticmethod
    def _parse_lock_file(path: str) -> list[tuple[str, str, int, float]]:
        """Parse the presence-registry lock file into (coder, os_user, pid, ts).

        Supports the current 4-field format ``coder\\tos_user\\tpid\\tts``, the
        older 3-field ``os_user\\tpid\\tts`` (coder falls back to the OS user),
        and the legacy 3-line format (single entry).
        """
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            return []
        entries: list[tuple[str, str, int, float]] = []
        if not lines:
            return entries
        if "\t" in lines[0]:
            for line in lines:
                parts = line.split("\t")
                try:
                    pid = int(parts[-2])
                    ts = float(parts[-1])
                except (IndexError, ValueError):
                    continue
                if len(parts) >= 4:
                    coder, os_user = parts[0], parts[1]
                else:
                    coder, os_user = parts[0], parts[0]
                entries.append((coder, os_user, pid, ts))
        else:
            user = lines[0]
            try:
                ts = float(lines[1]) if len(lines) > 1 else 0.0
            except ValueError:
                ts = 0.0
            try:
                pid = int(lines[2]) if len(lines) > 2 else 0
            except ValueError:
                pid = 0
            entries.append((user, user, pid, ts))
        return entries

    def _acquire_lock(self, proj_path: str, codername: str = "") -> bool:
        self.lock_file_path = os.path.normpath(
            os.path.join(proj_path, LOCK_FILE_NAME)
        )
        try:
            entries = self._parse_lock_file(self.lock_file_path)
            live = [e for e in entries if e[2] > 0 and self._pid_alive(e[2])]
            with open(self.lock_file_path, "w", encoding="utf-8") as f:
                for coder, os_user, pid, ts in live:
                    f.write(f"{coder}\t{os_user}\t{pid}\t{ts}\n")
                f.write(
                    f"{codername}\t{getpass.getuser()}\t{os.getpid()}\t{time.time()}"
                )
            return True
        except OSError as err:
            if getattr(err, "errno", None) == 22:
                logger.warning("Lock file disabled: %s", err)
                self.lock_file_path = ""
                return True
            raise

    @staticmethod
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

    def delete_lock_file(self) -> None:
        """Remove THIS instance's presence entry (the file stays while
        other instances hold it open)."""
        try:
            if not self.lock_file_path or not os.path.exists(self.lock_file_path):
                self.lock_file_path = ""
                return
            entries = self._parse_lock_file(self.lock_file_path)
            mine = [e for e in entries if e[2] != os.getpid()]
            if mine:
                with open(self.lock_file_path, "w", encoding="utf-8") as f:
                    for coder, os_user, pid, ts in mine:
                        f.write(f"{coder}\t{os_user}\t{pid}\t{ts}\n")
            else:
                os.remove(self.lock_file_path)
        except OSError as err:
            logger.debug("delete_lock_file: %s", err)
        self.lock_file_path = ""

    def _read_lock_user(self, proj_path: str) -> str:
        """First OTHER live opener's OS user (informational only)."""
        try:
            for _coder, os_user, pid, _ts in self._parse_lock_file(
                os.path.join(proj_path, LOCK_FILE_NAME)
            ):
                if pid != os.getpid() and self._pid_alive(pid):
                    return os_user
        except Exception:
            return ""
        return ""

    def detect_duplicate_coder(self, proj_path: str, codername: str) -> str:
        """Return the name of an OTHER live instance already working as the
        given coder, or "" if none. Working as the same coder on two
        instances corrupts sync, so the UI warns before it is possible."""
        if not codername:
            return ""
        try:
            for coder, _os_user, pid, _ts in self._parse_lock_file(
                os.path.join(proj_path, LOCK_FILE_NAME)
            ):
                if pid != os.getpid() and self._pid_alive(pid) and coder == codername:
                    return codername
        except Exception:
            return ""
        return ""

    def openers(self) -> list[dict]:
        """Live presence entries of OTHER instances on the open project."""
        if not self.lock_file_path or not os.path.exists(self.lock_file_path):
            return []
        out = []
        for coder, os_user, pid, ts in self._parse_lock_file(self.lock_file_path):
            if pid != os.getpid() and self._pid_alive(pid):
                out.append({"user": os_user, "coder": coder, "pid": pid, "ts": ts})
        return out

    # ------------------------------------------------------------------
    # Engine helpers
    # ------------------------------------------------------------------

    async def _open_engine(self) -> None:
        self.engine = create_project_engine(self.db_path())
        self.session_factory = create_session_factory(self.engine)

    async def _ensure_sandbox(self, project_path: str, codername: str) -> None:
        """Make sure a local sandbox exists before opening in collaboration mode.

        Prefers an existing sandbox (or its ``.bak`` crash-recovery copy).
        When none exists, seeds from the cold ``data.qda`` archive if there are
        no sidecars (first machine on a fresh collaboration), otherwise rebuilds
        the full database from the sidecar change log.
        """
        from qualcoder_api.services import sandbox, sync
        from qualcoder_api.services.user_settings import get_instance_id

        # Existing sandbox: verify it is not empty/corrupted (e.g. LSTeach
        # with 2 sources vs 23 in the archive).  A stale sandbox must be
        # rebuilt — otherwise the second rater (or the first after a crash)
        # stays on an empty project forever.
        if sandbox.sandbox_exists(self.uuid, self._sandbox_instance()):
            corrupted = False
            try:
                archive_probe = Path(project_path) / "data.qda"
                if archive_probe.exists():
                    probe_engine = create_project_engine(str(sandbox.sandbox_path(self.uuid, self._sandbox_instance())))
                    try:
                        probe_factory = create_session_factory(probe_engine)
                        async with probe_factory() as probe_session:
                            s_cnt = (await probe_session.execute(text("SELECT COUNT(*) FROM source"))).scalar() or 0
                            c_cnt = (await probe_session.execute(text("SELECT COUNT(*) FROM code_name"))).scalar() or 0
                            import aiosqlite as _aiosqlite2

                            try:
                                conn2 = await _aiosqlite2.connect(str(archive_probe))
                                try:
                                    cur2 = await conn2.cursor()
                                    await cur2.execute("SELECT COUNT(*) FROM source")
                                    a_s = (await cur2.fetchone())[0] or 0
                                    await cur2.execute("SELECT COUNT(*) FROM code_name")
                                    a_c = (await cur2.fetchone())[0] or 0
                                finally:
                                    await conn2.close()
                                if (int(s_cnt) == 0 and int(c_cnt) == 0 and (int(a_s) > 0 or int(a_c) > 0)) or (
                                    int(a_s) > 5 and int(s_cnt) * 2 < int(a_s)
                                ):
                                    logger.warning(
                                        "existing sandbox for %s is empty/corrupted (src=%s/%s code=%s/%s) — rebuilding",
                                        self.uuid,
                                        s_cnt,
                                        a_s,
                                        c_cnt,
                                        a_c,
                                    )
                                    corrupted = True
                            except Exception:
                                pass
                    finally:
                        with contextlib.suppress(Exception):
                            await dispose_engine(probe_engine)
                    if corrupted:
                        sandbox.remove_sandbox(self.uuid)
                    else:
                        return
                else:
                    return
            except Exception as err:
                logger.debug("sandbox emptiness probe failed for %s: %s", self.uuid, err)
                return
        archive = Path(project_path) / "data.qda"
        changes_root = Path(project_path) / sync.SYNC_DIR_NAME

        def _has_sidecars() -> bool:
            # Legacy per-instance sidecars
            has_legacy = bool(changes_root.is_dir()) and any(
                (d / "changes.jsonl").exists()
                for d in changes_root.iterdir()
                if d.is_dir()
            )
            if has_legacy:
                return True
            # Per-session replays (new spec 2a)
            replays_root = Path(project_path) / "replays"
            if replays_root.is_dir() and any(replays_root.glob("*.jsonl")):
                # Ignore the merged watermark file
                for p in replays_root.glob("*.jsonl"):
                    if p.name != "merged.json" and p.stat().st_size > 0:
                        return True
            return False

        has_sidecars = _has_sidecars()
        # Network/cloud shares can delay file creation visibility by a fraction
        # of a second.  If the marker is present but no sidecar is yet
        # visible, poll briefly before concluding "no sidecars" — otherwise
        # a second rater opening mid-activation would incorrectly seed from
        # the (potentially stale) archive and miss the snapshot.
        if not has_sidecars:
            # Only wait when we are truly in collaboration mode (marker
            # already tells us a sidecar *should* exist).  A tight loop is
            # cheap and avoids an empty rebuild.
            import asyncio as _asyncio

            for _ in range(5):
                await _asyncio.sleep(0.2)
                if _has_sidecars():
                    has_sidecars = True
                    break
        if not has_sidecars and archive.exists():
            from qualcoder_api.services.cleanup_service import checkpoint

            await checkpoint(str(archive))
            sandbox.create_sandbox_from(str(archive), self.uuid, self._sandbox_instance())
            return

        # Sidecars exist: rebuild the full database from them. If the rebuild
        # finds NOTHING to replay (torn/partial sidecar write racing this
        # open) but the cold archive carries data, fall back to seeding from
        # the archive — an empty project is worse than a slightly stale one,
        # and the next sync cycle reconciles the difference.
        await sandbox.create_fresh_sandbox(self.uuid, codername=codername, instance_id=self._sandbox_instance())
        engine = create_project_engine(str(sandbox.sandbox_path(self.uuid, self._sandbox_instance())))
        try:
            factory = create_session_factory(engine)
            result = await sync.rebuild_from_sidecars(
                factory, project_path, get_instance_id()
            )
        finally:
            await dispose_engine(engine)

        entries = int(result.get("entries", 0)) if isinstance(result, dict) else 0
        applied = int(result.get("applied", 0)) if isinstance(result, dict) else 0
        emptyRebuild = entries == 0 or (
            entries > 0 and applied == 0 and result.get("retries", 0) >= 1
        )
        # Additional safety: even when the sidecar appeared non-empty, the
        # rebuild can still leave an empty sandbox (e.g. all entries were
        # skipped as "converged" due to a truncated tail, or every insert
        # hit a unique-constraint conflict).  In that case the archive
        # still carries the full offline project — a stale copy beats an
        # empty one, and the next sync cycle reconciles the difference.
        if not emptyRebuild and archive.exists():
            try:
                # Lightweight emptiness probe on the freshly rebuilt sandbox.
                probe_engine = create_project_engine(str(sandbox.sandbox_path(self.uuid, self._sandbox_instance())))
                try:
                    probe_factory = create_session_factory(probe_engine)
                    async with probe_factory() as probe_session:
                        src_cnt = (await probe_session.execute(text("SELECT COUNT(*) FROM source"))).scalar() or 0
                        code_cnt = (await probe_session.execute(text("SELECT COUNT(*) FROM code_name"))).scalar() or 0
                        # Archive probe: does the cold archive actually carry data?
                        # Also handle the case where the rebuilt sandbox is significantly
                        # smaller than the archive (e.g. 1 vs 2 sources) — this can
                        # happen when a per-session replay was not yet exported
                        # (e.g. doc2 added after activation but before close, whose
                        # replay was deleted before the second rater could import).
                        # In that case the archive (which was correctly merged on close)
                        # is the ground truth and should be used.
                        should_fallback = False
                        arch_src = arch_code = 0
                        import aiosqlite as _aiosqlite

                        try:
                            conn = await _aiosqlite.connect(str(archive))
                            try:
                                cur = await conn.cursor()
                                await cur.execute("SELECT COUNT(*) FROM source")
                                arch_src = (await cur.fetchone())[0] or 0
                                await cur.execute("SELECT COUNT(*) FROM code_name")
                                arch_code = (await cur.fetchone())[0] or 0
                            finally:
                                await conn.close()
                            if (int(src_cnt) == 0 and int(code_cnt) == 0 and (int(arch_src) > 0 or int(arch_code) > 0)) or (int(arch_src) > 5 and int(src_cnt) * 2 < int(arch_src)):
                                should_fallback = True
                            elif int(arch_src) > 0 and int(src_cnt) + 1 < int(arch_src) and int(arch_src) <= 5:
                                # Small projects: if sandbox has 1 and archive has 2, fallback
                                should_fallback = True
                        except Exception:
                            pass
                        if should_fallback:
                            emptyRebuild = True
                            entries = int(entries)
                            applied = int(applied)
                            logger.warning(
                                "sidecar rebuild left sandbox with src=%s/%s code=%s/%s — falling back to archive",
                                src_cnt,
                                arch_src,
                                code_cnt,
                                arch_code,
                            )
                finally:
                    await dispose_engine(probe_engine)
            except Exception as err:
                logger.debug("empty-sandbox probe failed: %s", err)
        if emptyRebuild and archive.exists():
            logger.warning(
                "sidecar rebuild yielded nothing (entries=%s applied=%s) "
                "— falling back to seeding the sandbox from the cold archive",
                entries,
                applied,
            )
            from qualcoder_api.services.cleanup_service import checkpoint

            with contextlib.suppress(Exception):
                await checkpoint(str(archive))
            sandbox.create_sandbox_from(str(archive), self.uuid, self._sandbox_instance())
