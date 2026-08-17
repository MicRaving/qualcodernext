"""Journal repository (``journal`` table)."""

from __future__ import annotations

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.models import Journal
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repo.base import _capture, _inserted_pk, _now, _rowdict


class JournalRepository:
    """CRUD for journal entries."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_journals(self) -> list[Journal]:
        rows = await self.session.execute(
            select(tables.journal).order_by(tables.journal.c.date.desc())
        )
        return [Journal.model_validate(r._mapping) for r in rows]

    async def add_journal(self, *, name: str, jentry: str, owner: str) -> Journal:
        result = await self.session.execute(
            insert(tables.journal).values(
                name=name, jentry=jentry, date=_now(), owner=owner
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.journal).where(
                    tables.journal.c.jid == _inserted_pk(result)
                )
            )
        ).first()
        assert row is not None
        await _capture(
            self.session, "journal", "insert", "jid", row.jid, _rowdict(row)
        )
        await self.session.commit()
        return Journal.model_validate(row._mapping)

    async def update_journal(self, jid: int, **fields) -> Journal | None:
        allowed = {"name", "jentry", "owner", "date"}
        values = {k: v for k, v in fields.items() if k in allowed}
        if values:
            await self.session.execute(
                update(tables.journal).where(tables.journal.c.jid == jid).values(**values)
            )
            await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.journal).where(tables.journal.c.jid == jid)
            )
        ).first()
        if row is not None:
            await _capture(
                self.session, "journal", "update", "jid", jid, _rowdict(row)
            )
            await self.session.commit()
        return Journal.model_validate(row._mapping) if row else None

    async def delete_journal(self, jid: int) -> None:
        row = (
            await self.session.execute(
                select(tables.journal).where(tables.journal.c.jid == jid)
            )
        ).first()
        await self.session.execute(
            delete(tables.journal).where(tables.journal.c.jid == jid)
        )
        if row is not None:
            await _capture(
                self.session, "journal", "delete", "jid", jid, _rowdict(row)
            )
        await self.session.commit()
