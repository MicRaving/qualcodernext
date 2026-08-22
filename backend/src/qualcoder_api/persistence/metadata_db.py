"""Metadata DB — engine, session factory, migrations (SERVER_PLAN.md §6.1).

Server mode only: the local desktop app never touches the metadata DB.
WAL + busy_timeout so admin/auth writes never block project work for
long; foreign keys ON (memberships cascade).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from qualcoder_api.persistence.metadata_schema import MIGRATIONS

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_factory: async_sessionmaker | None = None


def _utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]


def metadata_db_path(db_path: Path) -> Path:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def init_metadata_engine(db_path: Path) -> AsyncEngine:
    """Create (or replace) the process-wide metadata engine + factory."""
    global _engine, _factory
    path = metadata_db_path(db_path)
    _engine = create_async_engine(
        f"sqlite+aiosqlite:///{path.as_posix()}",
        connect_args={"timeout": 5},
    )
    _factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def dispose_metadata_engine() -> None:
    global _engine, _factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _factory = None


def get_metadata_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("metadata engine not initialised — call init_metadata_engine()")
    return _engine


def metadata_factory() -> async_sessionmaker:
    if _factory is None:
        raise RuntimeError("metadata engine not initialised — call init_metadata_engine()")
    return _factory


async def migrate_metadata(db_path: Path) -> int:
    """Apply ordered migrations; returns the final schema version.

    Idempotent: re-running on a migrated DB applies nothing. The version
    bump happens in the SAME transaction as its DDL.
    """
    engine = init_metadata_engine(db_path)
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_version ("
                "version INTEGER NOT NULL, applied_at TEXT NOT NULL)"
            )
        )
        row = (await conn.execute(text("SELECT MAX(version) FROM schema_version"))).first()
        current = int(row[0]) if row and row[0] is not None else 0
        for version, ddl in MIGRATIONS:
            if version <= current:
                continue
            # sqlite3/aiosqlite execute ONE statement per call — split the
            # DDL batch on statement boundaries.
            for statement in ddl.split(";"):
                if statement.strip():
                    await conn.execute(text(statement))
            await conn.execute(
                text("INSERT INTO schema_version (version, applied_at) VALUES (:v, :ts)"),
                {"v": version, "ts": _utcnow()},
            )
            logger.info("metadata migration %s applied", version)
            current = version
    return current


# ── Minimal row helpers (Phase 1 scope: users + tokens) ────────────────


async def insert_user(
    username: str,
    password_hash: str,
    role: str = "user",
    display_name: str = "",
    email: str = "",
) -> dict:
    ts = _utcnow()
    factory = metadata_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "INSERT INTO users (username, display_name, email, password_hash, role,"
                " disabled, created_at, updated_at)"
                " VALUES (:u, :dn, :em, :ph, :role, 0, :ts, :ts)"
            ),
            {"u": username, "dn": display_name, "em": email, "ph": password_hash,
             "role": role, "ts": ts},
        )
        await session.commit()
        created = await get_user_by_id(result.lastrowid)
        if created is None:  # pragma: no cover - row just inserted
            raise RuntimeError("user row vanished after insert")
        return created


async def get_user_by_id(user_id: int) -> dict | None:
    factory = metadata_factory()
    async with factory() as session:
        row = (
            await session.execute(text("SELECT * FROM users WHERE id = :id"), {"id": user_id})
        ).mappings().first()
        return dict(row) if row else None


async def get_user_by_username(username: str) -> dict | None:
    factory = metadata_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT * FROM users WHERE username = :u COLLATE NOCASE"),
                {"u": username},
            )
        ).mappings().first()
        return dict(row) if row else None


async def count_users() -> int:
    factory = metadata_factory()
    async with factory() as session:
        row = (await session.execute(text("SELECT COUNT(*) FROM users"))).first()
        return int(row[0]) if row else 0


async def set_user_disabled(user_id: int, disabled: bool) -> None:
    factory = metadata_factory()
    async with factory() as session:
        await session.execute(
            text("UPDATE users SET disabled = :d, updated_at = :ts WHERE id = :id"),
            {"d": 1 if disabled else 0, "ts": _utcnow(), "id": user_id},
        )
        await session.commit()


# ── Tokens ──────────────────────────────────────────────────────────────


async def record_token(user_id: int, token_hash: str, expires_at: str, name: str = "") -> None:
    factory = metadata_factory()
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO auth_tokens (user_id, token_hash, name, expires_at,"
                " revoked, created_at, last_used_at)"
                " VALUES (:uid, :th, :name, :exp, 0, :ts, '')"
            ),
            {"uid": user_id, "th": token_hash, "name": name, "exp": expires_at, "ts": _utcnow()},
        )
        await session.commit()


async def lookup_token(token_hash: str) -> dict | None:
    """The auth_tokens row for a hash, unless expired/revoked/user-disabled."""
    factory = metadata_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT t.*, u.disabled FROM auth_tokens t"
                    " JOIN users u ON u.id = t.user_id"
                    " WHERE t.token_hash = :th AND t.revoked = 0 AND t.expires_at > :now"
                ),
                {"th": token_hash, "now": _utcnow()},
            )
        ).mappings().first()
        if not row or row["disabled"]:
            return None
        await session.execute(
            text("UPDATE auth_tokens SET last_used_at = :ts WHERE id = :id"),
            {"ts": _utcnow(), "id": row["id"]},
        )
        await session.commit()
        return dict(row)


async def revoke_token(token_hash: str) -> None:
    factory = metadata_factory()
    async with factory() as session:
        await session.execute(
            text("UPDATE auth_tokens SET revoked = 1 WHERE token_hash = :th"),
            {"th": token_hash},
        )
        await session.commit()


async def revoke_all_for_user(user_id: int) -> None:
    factory = metadata_factory()
    async with factory() as session:
        await session.execute(
            text("UPDATE auth_tokens SET revoked = 1 WHERE user_id = :uid"),
            {"uid": user_id},
        )
        await session.commit()


async def prune_expired_tokens() -> int:
    factory = metadata_factory()
    async with factory() as session:
        result = await session.execute(
            text("DELETE FROM auth_tokens WHERE expires_at < :now OR revoked = 1"),
            {"now": _utcnow()},
        )
        await session.commit()
        return result.rowcount or 0


# ── Projects registry + memberships (SERVER_PLAN.md Phase 2) ───────────


async def create_project(project_id: str, name: str, owner_id: int, data_path: str) -> dict:
    ts = _utcnow()
    factory = metadata_factory()
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO projects (id, name, owner_id, data_path, status, size_bytes,"
                " created_at, updated_at)"
                " VALUES (:id, :name, :oid, :path, 'active', 0, :ts, :ts)"
            ),
            {"id": project_id, "name": name, "oid": owner_id, "path": data_path, "ts": ts},
        )
        await session.execute(
            text(
                "INSERT INTO project_members (project_id, user_id, role)"
                " VALUES (:pid, :uid, 'owner')"
            ),
            {"pid": project_id, "uid": owner_id},
        )
        await session.commit()
    row = await get_project(project_id)
    assert row is not None
    return row


async def get_project(project_id: str) -> dict | None:
    factory = metadata_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT * FROM projects WHERE id = :id AND status = 'active'"),
                {"id": project_id},
            )
        ).mappings().first()
        return dict(row) if row else None


async def list_projects_for_user(user_id: int, is_admin: bool = False) -> list[dict]:
    """Active projects the user is a member of (admin: every project)."""
    factory = metadata_factory()
    async with factory() as session:
        if is_admin:
            rows = (
                await session.execute(
                    text(
                        "SELECT p.*, m.role FROM projects p"
                        " LEFT JOIN project_members m ON m.project_id = p.id"
                        " AND m.user_id = :uid WHERE p.status = 'active' ORDER BY p.updated_at DESC"
                    ),
                    {"uid": user_id},
                )
            ).mappings().all()
        else:
            rows = (
                await session.execute(
                    text(
                        "SELECT p.*, m.role FROM projects p"
                        " JOIN project_members m ON m.project_id = p.id"
                        " WHERE m.user_id = :uid AND p.status = 'active'"
                        " ORDER BY p.updated_at DESC"
                    ),
                    {"uid": user_id},
                )
            ).mappings().all()
        return [dict(r) for r in rows]


async def touch_project(project_id: str, size_bytes: int | None = None) -> None:
    factory = metadata_factory()
    async with factory() as session:
        if size_bytes is None:
            await session.execute(
                text("UPDATE projects SET updated_at = :ts WHERE id = :id"),
                {"ts": _utcnow(), "id": project_id},
            )
        else:
            await session.execute(
                text("UPDATE projects SET updated_at = :ts, size_bytes = :sz WHERE id = :id"),
                {"ts": _utcnow(), "sz": size_bytes, "id": project_id},
            )
        await session.commit()


async def delete_project_rows(project_id: str) -> None:
    factory = metadata_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM project_members WHERE project_id = :id"), {"id": project_id}
        )
        await session.execute(
            text("DELETE FROM backup_records WHERE project_id = :id"), {"id": project_id}
        )
        await session.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project_id})
        await session.commit()


async def add_member(project_id: str, user_id: int, role: str) -> None:
    factory = metadata_factory()
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO project_members (project_id, user_id, role)"
                " VALUES (:pid, :uid, :role)"
                " ON CONFLICT(project_id, user_id) DO UPDATE SET role = :role"
            ),
            {"pid": project_id, "uid": user_id, "role": role},
        )
        await session.commit()


async def get_member(project_id: str, user_id: int) -> dict | None:
    factory = metadata_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT * FROM project_members WHERE project_id = :pid AND user_id = :uid"
                ),
                {"pid": project_id, "uid": user_id},
            )
        ).mappings().first()
        return dict(row) if row else None


async def list_members(project_id: str) -> list[dict]:
    factory = metadata_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT m.user_id, m.role, u.username FROM project_members m"
                    " JOIN users u ON u.id = m.user_id WHERE m.project_id = :pid"
                    " ORDER BY u.username"
                ),
                {"pid": project_id},
            )
        ).mappings().all()
        return [dict(r) for r in rows]


async def remove_member(project_id: str, user_id: int) -> bool:
    factory = metadata_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "DELETE FROM project_members WHERE project_id = :pid AND user_id = :uid"
                " AND role != 'owner'"
            ),
            {"pid": project_id, "uid": user_id},
        )
        await session.commit()
        return (result.rowcount or 0) > 0


# ── Backup records + project sweep helpers (SERVER_PLAN.md Phase 4) ────


async def add_backup_record(
    project_id: str, kind: str, local_path: str, size_bytes: int, checksum: str
) -> int:
    factory = metadata_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "INSERT INTO backup_records (project_id, kind, local_path, size_bytes,"
                " checksum, cloud_status, created_at)"
                " VALUES (:pid, :kind, :path, :size, :sum, 'pending', :ts)"
            ),
            {
                "pid": project_id,
                "kind": kind,
                "path": local_path,
                "size": size_bytes,
                "sum": checksum,
                "ts": _utcnow(),
            },
        )
        await session.commit()
        return int(result.lastrowid)


async def get_backup_record(project_id: str, backup_id: int) -> dict | None:
    factory = metadata_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT * FROM backup_records WHERE id = :id AND project_id = :pid"
                ),
                {"id": backup_id, "pid": project_id},
            )
        ).mappings().first()
        return dict(row) if row else None


async def list_backup_records(project_id: str) -> list[dict]:
    factory = metadata_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, kind, local_path, size_bytes, checksum, cloud_status,"
                    " created_at FROM backup_records WHERE project_id = :pid"
                    " ORDER BY id DESC"
                ),
                {"pid": project_id},
            )
        ).mappings().all()
        return [dict(r) for r in rows]


async def delete_backup_record(backup_id: int) -> None:
    factory = metadata_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM backup_records WHERE id = :id"), {"id": backup_id}
        )
        await session.commit()


async def list_active_project_ids() -> list[str]:
    factory = metadata_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                text("SELECT id FROM projects WHERE status = 'active'")
            )
        ).all()
        return [r[0] for r in rows]


async def latest_backup_created(project_id: str) -> str | None:
    factory = metadata_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT MAX(created_at) AS latest FROM backup_records"
                    " WHERE project_id = :pid"
                ),
                {"pid": project_id},
            )
        ).first()
        return row[0] if row else None


# ── Passkeys (SERVER_PLAN.md Phase 1b) ──────────────────────────────────


async def add_passkey(
    user_id: int,
    credential_id: str,
    public_key: str,
    sign_count: int,
    transports: str,
    name: str,
) -> None:
    factory = metadata_factory()
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO passkeys (user_id, credential_id, public_key, sign_count,"
                " transports, name, created_at)"
                " VALUES (:uid, :cid, :pk, :sc, :tr, :name, :ts)"
            ),
            {"uid": user_id, "cid": credential_id, "pk": public_key, "sc": sign_count,
             "tr": transports, "name": name, "ts": _utcnow()},
        )
        await session.commit()


async def list_passkeys(user_id: int) -> list[dict]:
    factory = metadata_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, credential_id, name, created_at FROM passkeys"
                    " WHERE user_id = :uid ORDER BY id"
                ),
                {"uid": user_id},
            )
        ).mappings().all()
        return [dict(r) for r in rows]


async def get_passkey_by_credential_id(credential_id: str) -> dict | None:
    factory = metadata_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT * FROM passkeys WHERE credential_id = :cid"),
                {"cid": credential_id},
            )
        ).mappings().first()
        return dict(row) if row else None


async def update_passkey_sign_count(passkey_id: int, sign_count: int) -> None:
    factory = metadata_factory()
    async with factory() as session:
        await session.execute(
            text("UPDATE passkeys SET sign_count = :sc WHERE id = :id"),
            {"sc": sign_count, "id": passkey_id},
        )
        await session.commit()


async def delete_passkey(passkey_id: int, user_id: int) -> bool:
    """Delete an OWN passkey; True when a row was removed."""
    factory = metadata_factory()
    async with factory() as session:
        result = await session.execute(
            text("DELETE FROM passkeys WHERE id = :id AND user_id = :uid"),
            {"id": passkey_id, "uid": user_id},
        )
        await session.commit()
        return (result.rowcount or 0) > 0


# ── WebAuthn challenges (DB-persisted so restarts keep in-flight flows) ─


async def put_challenge(challenge: str, kind: str, user_id: int | None, ttl_secs: int) -> None:
    expires = (
        datetime.now(UTC) + timedelta(seconds=ttl_secs)
    ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    factory = metadata_factory()
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO webauthn_challenges (challenge, user_id, kind, expires_at)"
                " VALUES (:ch, :uid, :kind, :exp)"
            ),
            {"ch": challenge, "uid": user_id, "kind": kind, "exp": expires},
        )
        # opportunistic cleanup of dead challenges
        await session.execute(
            text("DELETE FROM webauthn_challenges WHERE expires_at < :now"),
            {"now": _utcnow()},
        )
        await session.commit()


async def take_challenge(challenge: str, kind: str) -> dict | None:
    """Consume a challenge (single use): returns its row, or None when
    unknown/expired/kind-mismatched. Deleted after read."""
    factory = metadata_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT * FROM webauthn_challenges"
                    " WHERE challenge = :ch AND kind = :kind AND expires_at > :now"
                ),
                {"ch": challenge, "kind": kind, "now": _utcnow()},
            )
        ).mappings().first()
        if not row:
            return None
        await session.execute(
            text("DELETE FROM webauthn_challenges WHERE id = :id"), {"id": row["id"]}
        )
        await session.commit()
        return dict(row)
