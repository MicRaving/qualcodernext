"""Coding segment repositories (``code_text``/``code_image``/``code_av``)."""

from __future__ import annotations

from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.models import AVCoding, Coding, ImageCoding
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repo.base import _capture, _coding_row, _inserted_pk, _now, _rowdict


class CodingRepository:
    """CRUD for text/image/AV coding segments."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_text_coding(
        self,
        *,
        cid: int,
        fid: int,
        seltext: str,
        pos0: int,
        pos1: int,
        owner: str,
        memo: str = "",
        avid: int | None = None,
        important: int = 0,
        weight: int = 0,
    ) -> Coding:
        result = await self.session.execute(
            insert(tables.code_text).values(
                cid=cid,
                fid=fid,
                seltext=seltext,
                pos0=pos0,
                pos1=pos1,
                owner=owner,
                date=_now(),
                memo=memo,
                avid=avid,
                important=important,
                weight=weight,
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.code_text).where(
                    tables.code_text.c.ctid == _inserted_pk(result)
                )
            )
        ).first()
        assert row is not None
        await _capture(
            self.session, "code_text", "insert", "ctid", row.ctid, _rowdict(row)
        )
        await self.session.commit()
        return Coding.model_validate(row._mapping)

    async def list_text_codings_for_file(self, fid: int) -> list[Coding]:
        """Text codings of one file, excluding hidden coders' rows (view)."""
        rows = await self.session.execute(
            text(
                "SELECT * FROM code_text_visible WHERE fid = :fid ORDER BY pos0"
            ),
            {"fid": fid},
        )
        return [Coding.model_validate(_coding_row(r._mapping)) for r in rows]

    async def list_text_codings_for_code(self, cid: int) -> list[Coding]:
        """Text codings of one code, excluding hidden coders' rows (view)."""
        rows = await self.session.execute(
            text(
                "SELECT * FROM code_text_visible WHERE cid = :cid ORDER BY pos0"
            ),
            {"cid": cid},
        )
        return [Coding.model_validate(_coding_row(r._mapping)) for r in rows]

    async def update_text_coding(self, ctid: int, **fields) -> Coding | None:
        allowed = {"seltext", "pos0", "pos1", "memo", "important", "avid", "cid", "weight"}
        values = {k: v for k, v in fields.items() if k in allowed}
        if values:
            await self.session.execute(
                update(tables.code_text)
                .where(tables.code_text.c.ctid == ctid)
                .values(**values)
            )
            await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.code_text).where(tables.code_text.c.ctid == ctid)
            )
        ).first()
        if row is not None:
            await _capture(
                self.session, "code_text", "update", "ctid", ctid, _rowdict(row)
            )
            await self.session.commit()
        return Coding.model_validate(row._mapping) if row else None

    async def delete_text_coding(self, ctid: int) -> None:
        row = (
            await self.session.execute(
                select(tables.code_text).where(tables.code_text.c.ctid == ctid)
            )
        ).first()
        await self.session.execute(
            delete(tables.code_text).where(tables.code_text.c.ctid == ctid)
        )
        if row is not None:
            await _capture(
                self.session, "code_text", "delete", "ctid", ctid, _rowdict(row)
            )
        await self.session.commit()

    async def add_image_coding(
        self,
        *,
        id: int,
        x1: int,
        y1: int,
        width: int,
        height: int,
        cid: int,
        owner: str,
        memo: str = "",
        important: int = 0,
        pdf_page: int | None = None,
        weight: int = 0,
    ) -> ImageCoding:
        result = await self.session.execute(
            insert(tables.code_image).values(
                id=id,
                x1=x1,
                y1=y1,
                width=width,
                height=height,
                cid=cid,
                memo=memo,
                date=_now(),
                owner=owner,
                important=important,
                pdf_page=pdf_page,
                weight=weight,
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.code_image).where(
                    tables.code_image.c.imid == _inserted_pk(result)
                )
            )
        ).first()
        assert row is not None
        await _capture(
            self.session, "code_image", "insert", "imid", row.imid, _rowdict(row)
        )
        await self.session.commit()
        return ImageCoding.model_validate(row._mapping)

    async def list_image_codings_for_file(self, source_id: int) -> list[ImageCoding]:
        # The visibility view keeps hidden coders' segments out (parity with
        # the text list and every report).
        rows = await self.session.execute(
            text("SELECT * FROM code_image_visible WHERE id = :sid ORDER BY imid"),
            {"sid": source_id},
        )
        return [ImageCoding.model_validate(_coding_row(r._mapping)) for r in rows]

    async def update_image_coding(self, imid: int, **fields) -> ImageCoding | None:
        """Update a coded image rectangle (position/size/memo/important/cid).

        Port of the legacy ``move_resize_rectangle`` behaviour.
        """
        allowed = {"x1", "y1", "width", "height", "cid", "memo", "important", "pdf_page", "weight"}
        values = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if values:
            await self.session.execute(
                update(tables.code_image)
                .where(tables.code_image.c.imid == imid)
                .values(**values)
            )
            await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.code_image).where(tables.code_image.c.imid == imid)
            )
        ).first()
        if row is not None:
            await _capture(
                self.session, "code_image", "update", "imid", imid, _rowdict(row)
            )
            await self.session.commit()
        return ImageCoding.model_validate(row._mapping) if row else None

    async def delete_image_coding(self, imid: int) -> None:
        row = (
            await self.session.execute(
                select(tables.code_image).where(tables.code_image.c.imid == imid)
            )
        ).first()
        await self.session.execute(
            delete(tables.code_image).where(tables.code_image.c.imid == imid)
        )
        if row is not None:
            await _capture(
                self.session, "code_image", "delete", "imid", imid, _rowdict(row)
            )
        await self.session.commit()

    async def add_av_coding(
        self,
        *,
        id: int,
        pos0: int,
        pos1: int,
        cid: int,
        owner: str,
        memo: str = "",
        important: int = 0,
        weight: int = 0,
    ) -> AVCoding:
        result = await self.session.execute(
            insert(tables.code_av).values(
                id=id,
                pos0=pos0,
                pos1=pos1,
                cid=cid,
                memo=memo,
                date=_now(),
                owner=owner,
                important=important,
                weight=weight,
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.code_av).where(
                    tables.code_av.c.avid == _inserted_pk(result)
                )
            )
        ).first()
        assert row is not None
        await _capture(
            self.session, "code_av", "insert", "avid", row.avid, _rowdict(row)
        )
        await self.session.commit()
        return AVCoding.model_validate(row._mapping)

    async def list_av_codings_for_file(self, source_id: int) -> list[AVCoding]:
        # The visibility view keeps hidden coders' segments out (parity with
        # the text list and every report).
        rows = await self.session.execute(
            text("SELECT * FROM code_av_visible WHERE id = :sid ORDER BY pos0"),
            {"sid": source_id},
        )
        return [AVCoding.model_validate(_coding_row(r._mapping)) for r in rows]

    async def update_av_coding(self, avid: int, **fields) -> AVCoding | None:
        """Update an AV time-range coding (memo/weight)."""
        allowed = {"memo", "important", "weight"}
        values = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if values:
            await self.session.execute(
                update(tables.code_av)
                .where(tables.code_av.c.avid == avid)
                .values(**values)
            )
            await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.code_av).where(tables.code_av.c.avid == avid)
            )
        ).first()
        if row is not None:
            await _capture(
                self.session, "code_av", "update", "avid", avid, _rowdict(row)
            )
            await self.session.commit()
        return AVCoding.model_validate(row._mapping) if row else None

    async def delete_av_coding(self, avid: int) -> None:
        row = (
            await self.session.execute(
                select(tables.code_av).where(tables.code_av.c.avid == avid)
            )
        ).first()
        await self.session.execute(
            delete(tables.code_av).where(tables.code_av.c.avid == avid)
        )
        if row is not None:
            await _capture(
                self.session, "code_av", "delete", "avid", avid, _rowdict(row)
            )
        await self.session.commit()
