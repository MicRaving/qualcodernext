"""Annotation repository (``annotation`` table)."""

from __future__ import annotations

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.models import Annotation
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repo.base import _capture, _inserted_pk, _now, _rowdict


class AnnotationRepository:
    """CRUD for text annotations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_for_file(self, fid: int) -> list[Annotation]:
        rows = await self.session.execute(
            select(tables.annotation)
            .where(tables.annotation.c.fid == fid)
            .order_by(tables.annotation.c.pos0)
        )
        return [Annotation.model_validate(r._mapping) for r in rows]

    async def add_annotation(self, *, fid: int, pos0: int, pos1: int,
                             memo: str, owner: str) -> Annotation:
        result = await self.session.execute(
            insert(tables.annotation).values(
                fid=fid, pos0=pos0, pos1=pos1, memo=memo, owner=owner, date=_now()
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.annotation).where(
                    tables.annotation.c.anid == _inserted_pk(result)
                )
            )
        ).first()
        assert row is not None
        await _capture(
            self.session, "annotation", "insert", "anid", row.anid, _rowdict(row)
        )
        await self.session.commit()
        return Annotation.model_validate(row._mapping)

    async def update_annotation(self, anid: int, *, memo: str | None = None,
                                pos0: int | None = None, pos1: int | None = None) -> Annotation | None:
        values: dict = {}
        if memo is not None:
            values["memo"] = memo
        if pos0 is not None:
            values["pos0"] = pos0
        if pos1 is not None:
            values["pos1"] = pos1
        if values:
            await self.session.execute(
                update(tables.annotation)
                .where(tables.annotation.c.anid == anid)
                .values(**values)
            )
            await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.annotation).where(tables.annotation.c.anid == anid)
            )
        ).first()
        if row is not None:
            await _capture(
                self.session, "annotation", "update", "anid", anid, _rowdict(row)
            )
            await self.session.commit()
        return Annotation.model_validate(row._mapping) if row else None

    async def delete_annotation(self, anid: int) -> None:
        row = (
            await self.session.execute(
                select(tables.annotation).where(tables.annotation.c.anid == anid)
            )
        ).first()
        await self.session.execute(
            delete(tables.annotation).where(tables.annotation.c.anid == anid)
        )
        if row is not None:
            await _capture(
                self.session, "annotation", "delete", "anid", anid, _rowdict(row)
            )
        await self.session.commit()
