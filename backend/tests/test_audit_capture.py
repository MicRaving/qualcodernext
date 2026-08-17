"""Audit-capture tests — sync_log per-user sequence atomicity.

The (user, seq) unique constraint guarantees the per-user monotonic counter
can never collide under concurrent writes (A3).
"""

from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualcoder_api.persistence import tables
from qualcoder_api.services import sync
from qualcoder_api.services.project_service import ProjectService


@pytest.fixture
async def rater(tmp_path):
    svc = ProjectService()
    await svc.create_project(str(tmp_path / "A.qda"), codername="anna")
    assert svc.session_factory is not None
    yield svc
    await svc.close_project()


async def test_capture_seq_contiguous_and_unique(rater):
    """A burst of captures for one user yields contiguous, unique seqs."""
    sync.set_current_user("anna")
    seqs: list[int] = []
    async with rater.session_factory() as session:
        for i in range(10):
            await sync.capture_insert(
                session, entity="code_name", pk_name="cid", pk_value=i + 1,
                row={"cid": i + 1, "name": f"c{i}", "owner": "anna"},
            )
            row = (
                await session.execute(
                    tables.sync_log.select()
                    .where(tables.sync_log.c.entity == "code_name")
                    .order_by(tables.sync_log.c.id.desc())
                )
            ).first()
            seqs.append(row.seq)
        await session.commit()
    assert sorted(seqs) == list(range(1, 11))
    assert len(set(seqs)) == 10


async def test_capture_seq_unique_under_concurrency(rater):
    """Concurrent captures on separate sessions never collide on seq (the
    unique constraint + savepoint retry makes this safe)."""
    sync.set_current_user("anna")

    async def one(i: int) -> int:
        async with rater.session_factory() as session:
            await sync.capture_insert(
                session, entity="code_name", pk_name="cid", pk_value=1000 + i,
                row={"cid": 1000 + i, "name": f"c{i}", "owner": "anna"},
            )
            await session.commit()
        return i

    await asyncio.gather(*[one(i) for i in range(20)])

    async with rater.session_factory() as session:
        rows = (
            await session.execute(
                tables.sync_log.select().where(tables.sync_log.c.user == "anna")
            )
        ).all()
        seqs = [r.seq for r in rows]
        assert len(seqs) == 20
        assert sorted(seqs) == list(range(1, 21))


async def test_unique_constraint_blocks_duplicate_user_seq(rater):
    """A manual insert with a duplicate (user, seq) is rejected."""
    sync.set_current_user("anna")
    async with rater.session_factory() as session:
        await sync.capture_insert(
            session, entity="code_name", pk_name="cid", pk_value=1,
            row={"cid": 1, "name": "a", "owner": "anna"},
        )
        await session.commit()
    async with rater.session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO sync_log (ts, user, seq, entity, action, pk_name, pk_value, row_json) "
                    "VALUES ('t', 'anna', 1, 'code_name', 'insert', 'cid', '2', :rj)"
                ),
                {"rj": json.dumps({"cid": 2})},
            )
            await session.flush()
        await session.rollback()
