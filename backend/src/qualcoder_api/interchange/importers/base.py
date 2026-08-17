"""Shared types, constants and helper functions for interchange importers."""

from __future__ import annotations

import aiosqlite
from sqlalchemy import select

# Known Transana table names (lowercased — the schema differs between
# Transana 3.x/4.x, so detection and import match case-insensitively).
TRANSANA_TABLES = frozenset(
    {
        "mediafiles",
        "media",
        "episodes",
        "episodefiles",
        "transcripts",
        "episodetranscripts",
        "keywords",
        "keywordtypes",
        "transcriptkeywordassignments",
        "keywordassignments",
        "episodekeywordassignments",
        "collections",
        "collectionmembers",
        "collectionepisodemembers",
    }
)


# ----------------------------------------------------------------------
# Shared helpers
# ----------------------------------------------------------------------

async def _fetch(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
    """Run a SELECT against the source database and return all rows."""
    cur = await db.execute(sql, params)
    return list(await cur.fetchall())


async def _table_names(db: aiosqlite.Connection) -> set[str]:
    """Names of the tables present in the source database."""
    rows = await _fetch(db, "SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in rows}


async def _columns(db: aiosqlite.Connection, table: str) -> set[str]:
    """Column names of ``table`` in the source database (empty when absent)."""
    cur = await db.execute(f'PRAGMA table_info("{table}")')
    rows = await cur.fetchall()
    return {row[1] for row in rows}


def _pick(cols: set[str], *candidates: str | None) -> list[str]:
    """The candidates present in ``cols``, in order — builds adaptive SELECTs."""
    return [c for c in candidates if c is not None and c in cols]


def _first(cols: set[str], *candidates: str | None) -> str | None:
    """The first candidate column present in ``cols`` (or ``None``)."""
    for candidate in candidates:
        if candidate is not None and candidate in cols:
            return candidate
    return None


async def _existing_names(session, table, name_col: str) -> set[str]:
    """Names already present in ``table`` (used for deduplication)."""
    rows = await session.execute(select(table.c[name_col]))
    return {r[0] for r in rows if r[0] is not None}
