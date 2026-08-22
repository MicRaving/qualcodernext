"""Metadata DB — engine, session factory, migrations (SERVER_PLAN.md §6.1).

Server mode only: the local desktop app never touches the metadata DB.
WAL + busy_timeout so admin/auth writes never block project work for
long; foreign keys ON (memberships cascade).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
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
