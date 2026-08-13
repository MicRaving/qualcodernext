"""Alembic integration tests — baseline revision produces the v14 schema."""

from __future__ import annotations

from pathlib import Path

import aiosqlite
from alembic import command
from alembic.config import Config

from qualcoder_api.persistence import tables

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return cfg


async def _objects(db_path: Path) -> tuple[set[str], set[str]]:
    conn = await aiosqlite.connect(db_path)
    cur = await conn.cursor()
    await cur.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') "
        "AND name NOT LIKE 'sqlite_%'"
    )
    objs = await cur.fetchall()
    await conn.close()
    return (
        {o[0] for o in objs if o[1] == "table"},
        {o[0] for o in objs if o[1] == "view"},
    )


async def test_upgrade_head_creates_v14_schema(tmp_path):
    db = tmp_path / "fresh.qda"
    cfg = _alembic_config(db)
    command.upgrade(cfg, "head")

    tables_, views = await _objects(db)
    expected = {t.name for t in tables.metadata.tables.values()}
    assert expected <= tables_
    assert {"code_image_visible", "code_text_visible", "code_av_visible",
            "annotation_visible"} <= views

    conn = await aiosqlite.connect(db)
    cur = await conn.cursor()
    await cur.execute("SELECT databaseversion, codername FROM project")
    assert await cur.fetchone() == ("v19", "default")
    await cur.execute("SELECT version_num FROM alembic_version")
    assert (await cur.fetchone())[0] == "0001_baseline_v14"
    await conn.close()


async def test_migrated_legacy_can_be_stamped(tmp_path):
    from tests.test_migration import LEGACY_TABLES

    db = tmp_path / "legacy.qda"
    conn = await aiosqlite.connect(db)
    cur = await conn.cursor()
    for sql in LEGACY_TABLES:
        await cur.execute(sql)
    await cur.execute("INSERT INTO project VALUES ('v2', '2020-01-01', '', 'QualCoder 1.0')")
    await conn.commit()
    await conn.close()

    # migrate to v14 with the legacy chain, then stamp at head
    from qualcoder_api.persistence.migration import MigrationChain

    conn = await aiosqlite.connect(db)
    await MigrationChain(conn).run_all("QualCoder 4.0", "tester")
    await conn.close()

    command.stamp(_alembic_config(db), "head")

    conn = await aiosqlite.connect(db)
    cur = await conn.cursor()
    await cur.execute("SELECT databaseversion FROM project")
    assert (await cur.fetchone())[0] == "v30"
    await cur.execute("SELECT version_num FROM alembic_version")
    assert (await cur.fetchone())[0] == "0001_baseline_v14"
    await conn.close()
