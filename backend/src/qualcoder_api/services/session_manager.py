"""Project-session pool (SERVER_PLAN.md §7.1).

One process owns every project (horizontal scaling is rejected at
startup), so the per-project ``asyncio.Lock`` here IS the single-writer
guarantee: exactly one open ``ProjectService`` per project id, shared by
all requests of all members of that project.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from fastapi import HTTPException

from qualcoder_api.core.server_config import load_server_config
from qualcoder_api.persistence import metadata_db
from qualcoder_api.services.project_service import ProjectService

logger = logging.getLogger(__name__)


class SessionEntry:
    """A live project session: its service, its lock, its last-use clock."""

    def __init__(self) -> None:
        self.service: ProjectService | None = None
        self.lock = asyncio.Lock()
        self.last_used = time.monotonic()


class SessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionEntry] = {}

    async def acquire(
        self,
        user: dict,
        project_id: str,
    ) -> tuple[ProjectService, str]:
        """Resolve + open the session for ``(user, project)``.

        Returns ``(service, role)``. Raises 404/403/409 per the plan."""
        project = await metadata_db.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        member = await metadata_db.get_member(project_id, int(user["id"]))
        if member is None and user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="not a member of this project")
        role = member["role"] if member else "owner"  # admin without membership acts as owner

        entry = self.sessions.setdefault(project_id, SessionEntry())
        # The lock serializes open-vs-close; concurrent REQUESTS share the
        # already-open service without waiting on it.
        async with entry.lock:
            entry.last_used = time.monotonic()
            if entry.service is None:
                username = str(user["username"])
                service = ProjectService()
                data_path = str(project["data_path"])
                result = await service.open_project(data_path, codername=username)
                if not result.ok:
                    raise HTTPException(status_code=409, detail=result.error or "open failed")
                entry.service = service
                logger.info("session opened: project=%s coder=%s", project_id, username)
            else:
                entry.last_used = time.monotonic()
        return entry.service, role

    async def close(self, project_id: str) -> None:
        entry = self.sessions.pop(project_id, None)
        if entry is None:
            return
        async with entry.lock:
            if entry.service is not None:
                await entry.service.close_project()
                entry.service = None

    async def release_idle(self) -> int:
        """Close sessions idle longer than QC_SESSION_IDLE_SECS."""
        idle_secs = load_server_config().session_idle_secs
        now = time.monotonic()
        closed = 0
        for pid, entry in list(self.sessions.items()):
            if now - entry.last_used < idle_secs:
                continue
            await self.close(pid)
            closed += 1
            logger.info("idle session closed: project=%s", pid)
        return closed


manager = SessionManager()


def new_project_id() -> str:
    return uuid.uuid4().hex
