"""SQLAlchemy async engine and session helpers for project databases.

Projects are SQLite files (``<name>.qda``). Each open project gets its own
engine. WAL mode is enabled for concurrent read/write from API threads.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from qualcoder_api.persistence import tables

__all__ = [
    "create_all_tables",
    "create_project_engine",
    "create_session_factory",
    "dispose_engine",
    "tables",
]


def create_project_engine(project_path: str | Path) -> AsyncEngine:
    """Create an async engine for a project database file.

    The file must exist; callers are responsible for creating the project
    directory first (see ``services.project_service``).
    """
    url = f"sqlite+aiosqlite:///{Path(project_path).as_posix()}"
    engine = create_async_engine(url, echo=False, future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory bound to a project engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def create_all_tables(engine: AsyncEngine) -> None:
    """Create all v14 tables (and indexes/constraints) in the database.

    Used for new projects and by the Alembic baseline revision. The
    ``coder_names`` table and the visibility views are created here too.
    """
    async with engine.begin() as conn:
        await conn.run_sync(tables.metadata.create_all)
    # coder_names table + views are created via SQL (they reference the
    # coding tables which must already exist).
    await create_coder_names_and_views(engine)


async def dispose_engine(engine: AsyncEngine) -> None:
    """Dispose an engine, closing pooled connections."""
    await engine.dispose()


async def create_coder_names_and_views(engine: AsyncEngine) -> None:
    """Create the ``coder_names`` table and the four visibility views."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """CREATE TABLE IF NOT EXISTS coder_names (
                       name TEXT UNIQUE NOT NULL,
                       visibility INTEGER NOT NULL DEFAULT 1 CHECK (visibility IN (0, 1))
                   )"""
            )
        )
        for view_name in tables.VISIBILITY_VIEWS:
            tbl = view_name.replace("_visible", "")
            await conn.execute(
                text(
                    f"""CREATE VIEW IF NOT EXISTS {view_name} AS
                        SELECT t.*
                        FROM {tbl} t
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM coder_names c
                            WHERE c.name = t.owner AND c.visibility = 0
                        )"""
                )
            )
