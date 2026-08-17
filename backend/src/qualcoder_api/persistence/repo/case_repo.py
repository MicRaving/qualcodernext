"""Case and case-text link repository (``cases``/``case_text`` tables)."""

from __future__ import annotations

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.models import Case, CaseText
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repo.base import _capture, _inserted_pk, _now, _rowdict


class CaseRepository:
    """CRUD for cases and case-text span links."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_cases(self) -> list[Case]:
        rows = await self.session.execute(
            select(tables.cases).order_by(func.lower(tables.cases.c.name))
        )
        return [Case.model_validate(r._mapping) for r in rows]

    async def get_case(self, caseid: int) -> Case | None:
        row = (
            await self.session.execute(
                select(tables.cases).where(tables.cases.c.caseid == caseid)
            )
        ).first()
        return Case.model_validate(row._mapping) if row else None

    async def add_case(self, *, name: str, owner: str, memo: str = "") -> Case | None:
        result = await self.session.execute(
            insert(tables.cases).values(
                name=name, memo=memo, owner=owner, date=_now()
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.cases).where(
                    tables.cases.c.caseid == _inserted_pk(result)
                )
            )
        ).first()
        case = Case.model_validate(row._mapping) if row else None
        if row is not None:
            await _capture(
                self.session, "cases", "insert", "caseid", row.caseid, _rowdict(row)
            )
            await self.session.commit()
        return case

    async def update_case(self, caseid: int, **fields) -> Case | None:
        allowed = {"name", "memo", "owner", "date"}
        values = {k: v for k, v in fields.items() if k in allowed}
        if values:
            await self.session.execute(
                update(tables.cases)
                .where(tables.cases.c.caseid == caseid)
                .values(**values)
            )
            await self.session.commit()
        case = await self.get_case(caseid)
        if case is not None:
            row = (
                await self.session.execute(
                    select(tables.cases).where(tables.cases.c.caseid == caseid)
                )
            ).first()
            await _capture(
                self.session, "cases", "update", "caseid", caseid, _rowdict(row)
            )
            await self.session.commit()
        return case

    async def delete_case(self, caseid: int) -> None:
        """Delete a case and its case_text links."""
        rows = (
            await self.session.execute(
                select(tables.case_text).where(tables.case_text.c.caseid == caseid)
            )
        ).all()
        await self.session.execute(
            delete(tables.case_text).where(tables.case_text.c.caseid == caseid)
        )
        for row in rows:
            data = _rowdict(row)
            await _capture(
                self.session, "case_text", "delete", "id", data.get("id"), data
            )
        case_row = (
            await self.session.execute(
                select(tables.cases).where(tables.cases.c.caseid == caseid)
            )
        ).first()
        await self.session.execute(
            delete(tables.cases).where(tables.cases.c.caseid == caseid)
        )
        if case_row is not None:
            await _capture(
                self.session, "cases", "delete", "caseid", caseid, _rowdict(case_row)
            )
        await self.session.commit()

    async def link_file(self, *, caseid: int, fid: int, owner: str, memo: str = "") -> CaseText:
        result = await self.session.execute(
            insert(tables.case_text).values(
                caseid=caseid,
                fid=fid,
                pos0=0,
                pos1=0,
                owner=owner,
                date=_now(),
                memo=memo,
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.case_text).where(
                    tables.case_text.c.id == _inserted_pk(result)
                )
            )
        ).first()
        assert row is not None
        await _capture(
            self.session, "case_text", "insert", "id", row.id, _rowdict(row)
        )
        await self.session.commit()
        return CaseText.model_validate(row._mapping)

    async def link_text_span(
        self, *, caseid: int, fid: int, pos0: int, pos1: int, owner: str, memo: str = ""
    ) -> CaseText:
        result = await self.session.execute(
            insert(tables.case_text).values(
                caseid=caseid,
                fid=fid,
                pos0=pos0,
                pos1=pos1,
                owner=owner,
                date=_now(),
                memo=memo,
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.case_text).where(
                    tables.case_text.c.id == _inserted_pk(result)
                )
            )
        ).first()
        assert row is not None
        await _capture(
            self.session, "case_text", "insert", "id", row.id, _rowdict(row)
        )
        await self.session.commit()
        return CaseText.model_validate(row._mapping)

    async def unlink_file(self, *, caseid: int, fid: int) -> None:
        rows = (
            await self.session.execute(
                select(tables.case_text).where(
                    tables.case_text.c.caseid == caseid,
                    tables.case_text.c.fid == fid,
                )
            )
        ).all()
        await self.session.execute(
            delete(tables.case_text).where(
                tables.case_text.c.caseid == caseid, tables.case_text.c.fid == fid
            )
        )
        for row in rows:
            data = _rowdict(row)
            await _capture(
                self.session, "case_text", "delete", "id", data.get("id"), data
            )
        await self.session.commit()

    async def case_files(self, caseid: int) -> list[dict]:
        """Return source rows linked to a case (deduplicated by fid)."""
        rows = await self.session.execute(
            select(
                tables.source.c.id,
                tables.source.c.name,
                tables.source.c.mediapath,
                tables.source.c.memo,
                tables.source.c.date,
            )
            .select_from(tables.case_text.join(tables.source, tables.source.c.id == tables.case_text.c.fid))
            .where(tables.case_text.c.caseid == caseid)
            .distinct()
            .order_by(func.lower(tables.source.c.name))
        )
        return [
            {"id": r[0], "name": r[1], "mediapath": r[2], "memo": r[3], "date": r[4]}
            for r in rows
        ]
