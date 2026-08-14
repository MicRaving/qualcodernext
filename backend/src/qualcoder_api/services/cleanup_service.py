"""Project maintenance — WAL checkpoints and full compaction (VACUUM).

Connection handling
-------------------
The open project runs on a SQLAlchemy async engine (aiosqlite, WAL mode)
whose pool may hold idle connections. Compaction deliberately opens a
SEPARATE raw ``aiosqlite`` connection with autocommit (``isolation_level=None``)
so the engine pool is never disturbed:

* ``PRAGMA wal_checkpoint(TRUNCATE)`` runs FIRST: it flushes every committed
  WAL frame into ``data.qda`` (and blocks new writers while it works), so
  VACUUM starts from a clean baseline and the reported size delta is honest.
* Pooled engine connections are checked-in and idle while compaction runs —
  they hold no open transaction and no statement in progress, so SQLite's
  only VACUUM constraint (no other connection inside a transaction) is met.
  QCnext is the sole writer of a project database; if an external process
  ever holds a write transaction, the checkpoint returns ``busy`` and VACUUM
  raises, the error surfaces from the endpoint, and the project is untouched.
* WAL mode routes VACUUM's rewrite through the WAL — the checkpoint right
  AFTER VACUUM is what physically moves the rebuilt pages into ``data.qda``
  and shrinks it. A final checkpoint after the index re-creation leaves the
  main file self-consistent with an empty WAL.

The checkpoint-on-close path in ``project_service`` runs after the engine is
disposed, so there are no other connections at all at that point.
"""

from __future__ import annotations

import logging
import os

import aiosqlite

from qualcoder_api.persistence.schema import _INDEX_SQL

logger = logging.getLogger(__name__)

#: Probe for the app's own rebuildable indexes. The ``idx\_`` prefix never
#: matches PRIMARY KEY / UNIQUE constraint indexes (``sqlite_autoindex_*``),
#: so those are left untouched.
_DROP_INDEX_SQL = (
    "SELECT name, sql FROM sqlite_master "
    "WHERE type = 'index' AND name LIKE 'idx\\_%' ESCAPE '\\'"
)


def _index_statements() -> list[str]:
    """The rebuildable CREATE INDEX statements from ``schema._INDEX_SQL``.

    ``_INDEX_SQL`` only contains ``CREATE INDEX ... IF NOT EXISTS`` lines;
    the drop step above removes them, so re-applying the exact statements is
    safe (the ``IF NOT EXISTS`` clause is simply a no-op).
    """
    return [sql for sql in _INDEX_SQL if sql.strip().upper().startswith("CREATE INDEX")]


async def checkpoint(db_path: str) -> dict:
    """Flush the WAL into the main database file (best-effort).

    ``TRUNCATE`` mode waits for readers to finish, blocks new writers and
    truncates the ``-wal`` file to zero, leaving a self-consistent
    ``data.qda`` that is safe to copy. Returns the PRAGMA result row
    (``busy``, ``log_frames``, ``checkpointed_frames``).
    """
    conn = await aiosqlite.connect(db_path)
    try:
        cur = await conn.cursor()
        await cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        row = await cur.fetchone()
        result = {
            "busy": int(row[0]) if row else 0,
            "log_frames": int(row[1]) if row else 0,
            "checkpointed_frames": int(row[2]) if row else 0,
        }
        if result["busy"]:
            logger.warning(
                "wal_checkpoint(TRUNCATE) on %s partially busy: %s", db_path, result
            )
        return result
    finally:
        await conn.close()


async def compact_project(db_path: str) -> dict:
    """Full maintenance pass on a project database.

    Steps (all on one raw autocommit connection — see the module docstring
    for the connection/VACUUM safety reasoning):

    1. ``PRAGMA wal_checkpoint(TRUNCATE)`` — flush the WAL first so the main
       file reflects everything committed; ``before_bytes`` is measured only
       now, so the reported delta is the honest pre-compaction size.
    2. Drop every ``idx_*`` index found in ``sqlite_master`` (the app's own
       rebuildable indexes; constraint indexes are never matched).
    3. ``VACUUM`` — rebuild the file, reclaiming deleted-row space.
    4. Checkpoint again: WAL mode routes VACUUM's rewrite through the WAL,
       so this TRUNCATE is what physically shrinks ``data.qda``.
    5. Recreate the indexes from ``schema._INDEX_SQL``; any dropped index not
       covered there (legacy ``idx_*`` extras from old QualCoder builds) is
       restored from its stored ``CREATE INDEX`` SQL.

    Returns ``{before_bytes, after_bytes, freed_bytes, indexes_dropped,
    indexes_recreated}``.
    """
    conn = await aiosqlite.connect(db_path, isolation_level=None)
    try:
        cur = await conn.cursor()

        await cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await cur.fetchone()
        before = os.path.getsize(db_path)

        dropped_sql: dict[str, str | None] = {}
        await cur.execute(_DROP_INDEX_SQL)
        for name, sql in await cur.fetchall():
            dropped_sql[str(name)] = str(sql) if sql else None
        for name in dropped_sql:
            await cur.execute(f'DROP INDEX "{name}"')

        await cur.execute("VACUUM")
        await cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await cur.fetchone()

        recreate_sql = _index_statements()
        recreated_names = {sql.split()[5] for sql in recreate_sql}
        recreated = 0
        for sql in recreate_sql:
            await cur.execute(sql)
            recreated += 1

        # Safety net: legacy idx_* indexes that schema._INDEX_SQL does not
        # know about would otherwise be dropped forever. Their stored CREATE
        # INDEX statement (if any) rebuilds them exactly as they were.
        restored = 0
        for name, sql in dropped_sql.items():
            if name in recreated_names:
                continue
            if sql and sql.strip().upper().startswith("CREATE INDEX"):
                await cur.execute(sql)
                restored += 1

        await cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await cur.fetchone()
    finally:
        await conn.close()

    after = os.path.getsize(db_path)
    if restored:
        logger.warning(
            "compact of %s restored %s legacy index(es) not in _INDEX_SQL",
            db_path,
            restored,
        )
    return {
        "before_bytes": before,
        "after_bytes": after,
        "freed_bytes": before - after,
        "indexes_dropped": len(dropped_sql),
        "indexes_recreated": recreated + restored,
    }
