"""Project lifecycle service — create, open, close, backup, lock.

Pure backend: no Qt, no UI. The FastAPI layer wraps these methods.
"""

from __future__ import annotations

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


class ProjectService:
    """Encapsulates project lifecycle operations for the v4 backend."""

    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker | None = None
        self.project_path: str = ""
        self.project_name: str = ""
        self.lock_file_path: str = ""

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
        if not project_path.endswith(".qda"):
            project_path += ".qda"

        counter = 0
        extension = ""
        while os.path.exists(project_path + extension):
            counter += 1
            extension = f"_{counter}"

        self.project_path = project_path + extension
        root = Path(self.project_path)
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
        await self._open_engine(root)
        from qualcoder_api.services import user_settings

        user_settings.append_recent_project(self.project_path)
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
        # Parse recent-projects format: "date|path"
        actual_path = proj_path.split("|")[-1]
        if not (len(actual_path) > 3 and actual_path[-4:] == ".qda"):
            return OpenResult(ok=False, error="not a .qda project path")

        root = Path(actual_path)
        if not root.is_dir():
            return OpenResult(ok=False, error="project directory missing")

        # Presence registry: never blocks; other live openers are reported
        # for the UI (simultaneous work is supported).
        self._acquire_lock(actual_path)
        lock_user = self._read_lock_user(actual_path)

        try:
            await self._dispose_engine_if_any()
            await self._open_engine(root)
            header = await self._get_header()
            if header is None or "QualCoder" not in (header.about or ""):
                await self.close_project()
                return OpenResult(ok=False, error="not a QualCoder database")
        except Exception as err:
            await self.close_project()
            logger.debug("Not a QualCoder database: %s", err)
            return OpenResult(ok=False, error=str(err))

        self.project_name = root.name
        self.project_path = actual_path
        conn = await aiosqlite.connect(root / "data.qda")
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
        return os.path.join(self.project_path, "data.qda")

    # ------------------------------------------------------------------
    # Close / dispose
    # ------------------------------------------------------------------

    async def close_project(self) -> None:
        """Close the project: dispose engine, remove lock file."""
        await self._dispose_engine_if_any()
        self.delete_lock_file()
        self.project_path = ""
        self.project_name = ""

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    async def save_backup(self, suffix: str = "") -> tuple[str, str]:
        """Copy the project database into the backups folder.

        Returns (message, backup_path).
        """
        db_path = Path(self.project_path) / "data.qda"
        if not db_path.exists():
            return ("no database to back up", "")
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
    def _parse_lock_file(path: str) -> list[tuple[str, int, float]]:
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            return []
        entries: list[tuple[str, int, float]] = []
        if not lines:
            return entries
        if "\t" in lines[0]:
            for line in lines:
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                try:
                    pid = int(parts[1])
                    ts = float(parts[2])
                except ValueError:
                    continue
                entries.append((parts[0], pid, ts))
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
            entries.append((user, pid, ts))
        return entries

    def _acquire_lock(self, proj_path: str) -> bool:
        self.lock_file_path = os.path.normpath(
            os.path.join(proj_path, LOCK_FILE_NAME)
        )
        try:
            entries = self._parse_lock_file(self.lock_file_path)
            live = [e for e in entries if e[1] > 0 and self._pid_alive(e[1])]
            with open(self.lock_file_path, "w", encoding="utf-8") as f:
                for user, pid, ts in live:
                    f.write(f"{user}\t{pid}\t{ts}\n")
                f.write(f"{getpass.getuser()}\t{os.getpid()}\t{time.time()}")
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
            mine = [e for e in entries if e[1] != os.getpid()]
            if mine:
                with open(self.lock_file_path, "w", encoding="utf-8") as f:
                    for user, pid, ts in mine:
                        f.write(f"{user}\t{pid}\t{ts}\n")
            else:
                os.remove(self.lock_file_path)
        except OSError as err:
            logger.debug("delete_lock_file: %s", err)
        self.lock_file_path = ""

    def _read_lock_user(self, proj_path: str) -> str:
        """First OTHER live opener's user (informational only)."""
        try:
            for user, pid, _ts in self._parse_lock_file(
                os.path.join(proj_path, LOCK_FILE_NAME)
            ):
                if pid != os.getpid() and self._pid_alive(pid):
                    return user
        except Exception:
            return ""
        return ""

    def openers(self) -> list[dict]:
        """Live presence entries of OTHER instances on the open project."""
        if not self.lock_file_path or not os.path.exists(self.lock_file_path):
            return []
        out = []
        for user, pid, ts in self._parse_lock_file(self.lock_file_path):
            if pid != os.getpid() and self._pid_alive(pid):
                out.append({"user": user, "pid": pid, "ts": ts})
        return out

    # ------------------------------------------------------------------
    # Engine helpers
    # ------------------------------------------------------------------

    async def _open_engine(self, root: Path) -> None:
        self.engine = create_project_engine(root / "data.qda")
        self.session_factory = create_session_factory(self.engine)
