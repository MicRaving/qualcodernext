"""Source repository (``source`` table)."""

from __future__ import annotations

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.models import Source
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repo.base import _inserted_pk, _now


class SourceRepository:
    """CRUD for the ``source`` table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_sources(self) -> list[Source]:
        """All sources WITHOUT their fulltext — the coder fetches individual
        sources (``get_source``) when needed. Keeping megabytes of text out
        of the list keeps startup and the file manager fast for big projects."""
        rows = await self.session.execute(
            select(
                tables.source.c.id,
                tables.source.c.name,
                tables.source.c.mediapath,
                tables.source.c.memo,
                tables.source.c.owner,
                tables.source.c.date,
                tables.source.c.av_text_id,
                tables.source.c.risid,
            )
        )
        # Transcript companions (another source's av_text_id) stay hidden in
        # the file view - they are shown inside the AV coder instead.
        av_refs = await self.session.execute(select(tables.source.c.av_text_id))
        hidden_ids = {r[0] for r in av_refs if r[0] is not None}
        sources: list[Source] = []
        for row in rows:
            data = dict(row._mapping)
            if data["id"] in hidden_ids:
                continue
            data["fulltext"] = None
            sources.append(Source.model_validate(data))
        return sources

    async def get_source(self, source_id: int) -> Source | None:
        row = (
            await self.session.execute(
                select(tables.source).where(tables.source.c.id == source_id)
            )
        ).first()
        return Source.model_validate(row._mapping) if row else None

    async def add_source(
        self,
        *,
        name: str,
        mediapath: str | None = None,
        fulltext: str | None = None,
        memo: str = "",
        owner: str = "",
        av_text_id: int | None = None,
        risid: int | None = None,
    ) -> Source:
        values = {
            "name": name,
            "fulltext": fulltext,
            "mediapath": mediapath,
            "memo": memo,
            "owner": owner,
            "date": _now(),
            "av_text_id": av_text_id,
            "risid": risid,
        }
        result = await self.session.execute(
            insert(tables.source).values(**values)
        )
        new_id = _inserted_pk(result)
        await self.session.commit()
        source = await self.get_source(new_id)
        if source is None:  # pragma: no cover - defensive
            raise RuntimeError("source row vanished after insert")
        row = (
            await self.session.execute(
                select(tables.source).where(tables.source.c.id == new_id)
            )
        ).first()
        from qualcoder_api.persistence import audit_capture

        await audit_capture.capture_insert(
            self.session, entity="source", pk_name="id", pk_value=new_id,
            row=audit_capture.table_row(row._mapping) if row else None,
        )
        await self.session.commit()
        return source

    async def update_source(self, source_id: int, **fields) -> Source | None:
        allowed = {
            "name",
            "fulltext",
            "mediapath",
            "memo",
            "owner",
            "date",
            "av_text_id",
            "risid",
        }
        values = {k: v for k, v in fields.items() if k in allowed}
        if values:
            await self.session.execute(
                update(tables.source).where(tables.source.c.id == source_id).values(**values)
            )
            await self.session.commit()
        source = await self.get_source(source_id)
        from qualcoder_api.persistence import audit_capture

        if source is not None:
            row = (
                await self.session.execute(
                    select(tables.source).where(tables.source.c.id == source_id)
                )
            ).first()
            await audit_capture.capture_update(
                self.session, entity="source", pk_name="id", pk_value=source_id,
                row=audit_capture.table_row(row._mapping) if row else None,
            )
            await self.session.commit()
        return source

    async def delete_source(self, source_id: int) -> None:
        """Delete a source and all its codings/annotations/case links.

        Audio/video sources link a transcript companion through ``av_text_id``;
        the companion is deleted with the same cascade so it is never left
        orphaned. Companions themselves never link onward (their
        ``av_text_id`` is NULL), so the chain is at most one hop — the
        ``seen`` set still guards pathological pointer cycles (recursion
        guard). The whole cascade runs in one transaction.
        """
        pending = [source_id]
        seen: set[int] = set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            link_row = (
                await self.session.execute(
                    select(tables.source.c.av_text_id).where(tables.source.c.id == current)
                )
            ).first()
            companion_id = (
                int(link_row[0]) if link_row is not None and link_row[0] is not None else None
            )
            await self._delete_source_row(current)
            if companion_id is not None:
                pending.append(companion_id)
        await self.session.commit()

    async def _delete_source_row(self, source_id: int) -> None:
        """Delete ONE source row plus its codings/annotations/case links.

        Shared by the media source and its transcript companion; sync
        deletes are captured for both. Committed by the caller so the whole
        cascade is atomic.
        """
        from qualcoder_api.persistence import audit_capture

        async def _grab(table, col) -> list[dict]:
            rows = (
                await self.session.execute(select(table).where(col == source_id))
            ).all()
            return [audit_capture.table_row(r._mapping) for r in rows]

        for table, fk, pk in (
            (tables.code_text, tables.code_text.c.fid, "ctid"),
            (tables.code_image, tables.code_image.c.id, "imid"),
            (tables.code_av, tables.code_av.c.id, "avid"),
            (tables.annotation, tables.annotation.c.fid, "anid"),
            (tables.case_text, tables.case_text.c.fid, "id"),
            (tables.attribute, tables.attribute.c.id, "attrid"),
        ):
            rows = await _grab(table, fk)
            await self.session.execute(delete(table).where(fk == source_id))
            for row in rows:
                await audit_capture.capture_delete(
                    self.session, entity=table.name, pk_name=pk, pk_value=row.get(pk), row=row
                )
        src_rows = await _grab(tables.source, tables.source.c.id)
        await self.session.execute(
            delete(tables.source).where(tables.source.c.id == source_id)
        )
        # Clear any media source's transcript pointer to the deleted row so
        # re-transcription links a fresh transcript instead of folding into
        # a missing companion.
        await self.session.execute(
            update(tables.source)
            .where(tables.source.c.av_text_id == source_id)
            .values(av_text_id=None)
        )
        for row in src_rows:
            await audit_capture.capture_delete(
                self.session, entity="source", pk_name="id", pk_value=source_id, row=row
            )
