"""Async repositories over the v14 project schema.

Each repository wraps an ``AsyncSession`` and returns Pydantic domain models
(``qualcoder_api.core.models``). SQL follows the legacy behavior exactly;
business-rule quirks (unique-constraint conflicts during merge, orphan
supercatid cleanup) are preserved deliberately.
"""

from __future__ import annotations

import datetime
import json
import logging
import random
from typing import Any, cast

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.engine import CursorResult, Result
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.models import (
    Annotation,
    Attribute,
    AttributeType,
    AVCoding,
    Case,
    CaseText,
    Category,
    Code,
    Coding,
    ImageCoding,
    Journal,
    Project,
    Source,
)
from qualcoder_api.persistence import tables

logger = logging.getLogger(__name__)


def _coding_row(mapping) -> dict:
    """Normalize a raw coding row for model validation.

    Legacy data may carry ``important = NULL``; the models require an int,
    so NULL is coerced to 0 (the column default).
    """
    data = dict(mapping)
    if data.get("important") is None:
        data["important"] = 0
    return data


def _inserted_pk(result: Result[Any]) -> int:
    """First inserted primary key from an INSERT statement result.

    ``AsyncSession.execute`` is statically typed as returning ``Result``,
    but for INSERT/DML statements the runtime type is ``CursorResult``
    which carries ``inserted_primary_key``.
    """
    pk = cast(CursorResult[Any], result).inserted_primary_key
    if pk is None:  # pragma: no cover - inserts always return a pk here
        raise RuntimeError("insert returned no primary key")
    return int(pk[0])

# Legacy 120-color code palette (color_selector.py, ported verbatim).
CODE_COLORS = [
    "#F5F6CE", "#F2F5A9", "#F4FA58", "#F7FE2E", "#DDE600", "#F8ECE0", "#F6E3CE", "#F5D0A9", "#F7BE81", "#FAAC58",
    "#F5ECCE", "#F3E2A9", "#F5DA81", "#F7D358", "#FACC2E", "#FFE2CC", "#FFC599", "#FFA866", "#FF8B33", "#FF6F00",
    "#F8E6E0", "#F6D8CE", "#F5BCA9", "#F79F81", "#FA8258", "#FADCCC", "#F5B999", "#F09666", "#EB7333", "#E65100",
    "#F8E0E0", "#F6CECE", "#F5A9A9", "#F78181", "#FA5858", "#F0D1D1", "#E2A4A4", "#D37676", "#C54949", "#B71C1C",
    "#F2D6CE", "#E5AE9D", "#D8866D", "#CB5E3C", "#BF360C", "#E7CEDB", "#CF9EB8", "#B76E95", "#9F3E72", "#880E4F",
    "#F8E0E6", "#F6CED8", "#F5A9BC", "#F7819F", "#FA5882", "#F8E0F7", "#F6CEF5", "#F5A9F2", "#F781F3", "#FA58F4",
    "#D1DED2", "#A3BEA5", "#769E78", "#487E4B", "#1B5E20", "#DEE9E4", "#BED3C9", "#9EBDAE", "#7EA793", "#5E9179",
    "#CEF6E3", "#A9F5D0", "#81F7BE", "#58FAAC", "#00FF7F", "#E0F8E0", "#CEF6CE", "#A9F5A9", "#81F781", "#58FA58",
    "#D0F5A9", "#BEF781", "#ACFA58", "#9AFE2E", "#80FF00", "#CEF6F5", "#A9F5F2", "#81F7F3", "#58FAF4", "#00F0F0",
    "#E4D3F5", "#CAA8EB", "#B07CE1", "#9651D7", "#7D26CD", "#ECE0F8", "#E3CEF6", "#D0A9F5", "#BE81F7", "#AC58FA",
    "#DADAF5", "#B5B5EC", "#9090E3", "#6B6BDA", "#4646D1", "#CEE3F6", "#A9D0F5", "#81BEF7", "#3498DB", "#5882FA",
    "#CEDAEC", "#9EB5D9", "#6D91C6", "#3D6CB3", "#0D47A1", "#E8E8E8", "#D8D8D8", "#C8C8C8", "#B8B8B8", "#A8A8A8",
]

COLOUR_RANGES = [
    {"name": "yellow", "min": 0, "max": 5},
    {"name": "orange", "min": 6, "max": 30},
    {"name": "red", "min": 31, "max": 45},
    {"name": "pink", "min": 46, "max": 60},
    {"name": "green", "min": 61, "max": 85},
    {"name": "cyan", "min": 86, "max": 90},
    {"name": "purple", "min": 91, "max": 100},
    {"name": "blue", "min": 101, "max": 115},
    {"name": "gray", "min": 116, "max": 120},
    {"name": "all", "min": 0, "max": 120},
]


def _now() -> str:
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _rowdict(row) -> dict:
    """Raw table-column dict from a row mapping (sync-safe snapshot)."""
    from qualcoder_api.services import sync

    return sync.table_row(row._mapping)


async def _capture(
    session, entity: str, action: str, pk_name: str, pk_value: int | str | None, row: dict | None
) -> None:
    from qualcoder_api.services import sync

    await sync.capture(
        session, entity=entity, action=action, pk_name=pk_name, pk_value=pk_value, row=row
    )


def random_code_color() -> str:
    """Pick a random color from the code palette (custom scheme when set)."""
    try:
        from qualcoder_api.services.user_settings import get_color_scheme

        scheme = get_color_scheme()
        palette = scheme.get("colors") or CODE_COLORS
    except Exception:  # pragma: no cover - settings never raise here
        palette = CODE_COLORS
    return palette[random.randint(0, len(palette) - 1)]


class ProjectRepository:
    """Metadata operations on the ``project`` row and coder names."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_header(self) -> Project | None:
        """Return minimal project metadata (columns present in ALL versions).

        Legacy v2 databases only have (databaseversion, date, memo, about);
        the full column set is selected only after migration.
        """
        row = (
            await self.session.execute(
                select(
                    tables.project.c.databaseversion,
                    tables.project.c.date,
                    tables.project.c.memo,
                    tables.project.c.about,
                )
            )
        ).first()
        if row is None:
            return None
        return Project(
            databaseversion=row[0] or "",
            date=row[1] or "",
            memo=row[2] or "",
            about=row[3] or "",
        )

    async def get_last_coder(self) -> str:
        row = (
            await self.session.execute(select(tables.project.c.codername))
        ).first()
        return row[0] or "" if row else ""

    async def update_memo(self, memo: str) -> None:
        await self.session.execute(update(tables.project).values(memo=memo))
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.project).where(tables.project.c.databaseversion.is_not(None))
            )
        ).first()
        if row is not None:
            await _capture(
                self.session, "project", "update", "rowid", 1, _rowdict(row)
            )
            await self.session.commit()

    async def get_summary(self) -> dict:
        """Aggregate project statistics (files, codes, cases, ...)."""
        summary: dict = {}
        project = await self.get_header()
        if project is None:
            return summary
        summary.update(
            databaseversion=project.databaseversion,
            project_date=project.date,
            project_memo=project.memo,
            about=project.about,
            bookmark_file_id=project.bookmarkfile,
            bookmark_pos=project.bookmarkpos,
        )
        for key, table, col in (
            ("files_count", tables.source, tables.source.c.id),
            ("cases_count", tables.cases, tables.cases.c.caseid),
            ("code_categories_count", tables.code_cat, tables.code_cat.c.catid),
            ("codes_count", tables.code_name, tables.code_name.c.cid),
            ("attributes_count", tables.attribute_type, tables.attribute_type.c.name),
            ("journals_count", tables.journal, tables.journal.c.jid),
        ):
            count = (
                await self.session.execute(select(func.count(col)).select_from(table))
            ).scalar_one()
            summary[key] = count
        summary["bookmark_filename"] = None
        if project.bookmarkfile is not None:
            row = (
                await self.session.execute(
                    select(tables.source.c.name).where(tables.source.c.id == project.bookmarkfile)
                )
            ).first()
            if row is not None:
                summary["bookmark_filename"] = row[0]
        return summary

    async def get_bookmarks(self) -> dict:
        """Text + audio/video bookmarks from the project row."""
        row = (
            await self.session.execute(
                select(
                    tables.project.c.bookmarkfile,
                    tables.project.c.bookmarkpos,
                    tables.project.c.avbookmarkfile,
                    tables.project.c.avbookmarkmsec,
                    tables.project.c.avbookmarktextpos,
                )
            )
        ).first()
        if row is None:
            return {}
        return {
            "bookmark_file_id": row[0],
            "bookmark_pos": row[1],
            "av_bookmark_file_id": row[2],
            "av_bookmark_msec": row[3],
            "av_bookmark_textpos": row[4],
        }

    async def set_bookmark(self, *, file_id: int | None, pos: int | None) -> dict:
        """Set the text bookmark (legacy ``bookmarkfile``/``bookmarkpos``)."""
        values = {}
        if file_id is not None:
            values["bookmarkfile"] = file_id
        if pos is not None:
            values["bookmarkpos"] = pos
        if values:
            await self.session.execute(update(tables.project).values(**values))
            await self.session.commit()
        return await self.get_bookmarks()

    async def set_av_bookmark(
        self, *, file_id: int | None, msec: int | None, textpos: int | None
    ) -> dict:
        """Set the audio/video bookmark (upstream v15 columns)."""
        values = {}
        if file_id is not None:
            values["avbookmarkfile"] = file_id
        if msec is not None:
            values["avbookmarkmsec"] = msec
        if textpos is not None:
            values["avbookmarktextpos"] = textpos
        if values:
            await self.session.execute(update(tables.project).values(**values))
            await self.session.commit()
        return await self.get_bookmarks()

    async def update_coder_names(self, current_coder: str) -> None:
        """Refresh the ``coder_names`` table from all owner columns."""
        union_sql = "\nUNION ".join(
            f"SELECT owner AS name FROM {t} WHERE owner IS NOT NULL"
            for t in tables.OWNER_TABLES
        )
        await self.session.execute(
            text(f"INSERT OR IGNORE INTO coder_names (name) {union_sql}")
        )
        await self.session.execute(
            text(
                "INSERT INTO coder_names (name, visibility) VALUES (:name, 1) "
                "ON CONFLICT(name) DO UPDATE SET visibility = 1 "
                "WHERE coder_names.visibility <> 1"
            ),
            {"name": current_coder},
        )
        last_coder = await self.get_last_coder()
        if last_coder:
            await self.session.execute(
                text("INSERT OR IGNORE INTO coder_names (name) VALUES (:name)"),
                {"name": last_coder},
            )
        await self.session.execute(
            text("INSERT OR IGNORE INTO coder_names (name) VALUES (:name)"),
            {"name": tables.SYSTEM_CODER_NAME},
        )
        await self.session.commit()


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
        from qualcoder_api.services import sync

        await sync.capture_insert(
            self.session, entity="source", pk_name="id", pk_value=new_id,
            row=sync.table_row(row._mapping) if row else None,
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
        from qualcoder_api.services import sync

        if source is not None:
            row = (
                await self.session.execute(
                    select(tables.source).where(tables.source.c.id == source_id)
                )
            ).first()
            await sync.capture_update(
                self.session, entity="source", pk_name="id", pk_value=source_id,
                row=sync.table_row(row._mapping) if row else None,
            )
            await self.session.commit()
        return source

    async def delete_source(self, source_id: int) -> None:
        """Delete a source and all its codings/annotations/case links."""
        from qualcoder_api.services import sync

        async def _grab(table, col) -> list[dict]:
            rows = (
                await self.session.execute(select(table).where(col == source_id))
            ).all()
            return [sync.table_row(r._mapping) for r in rows]

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
                await sync.capture_delete(
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
            await sync.capture_delete(
                self.session, entity="source", pk_name="id", pk_value=source_id, row=row
            )
        await self.session.commit()


class CodeRepository:
    """CRUD for codes, categories, and the codebook tree."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_categories(self) -> list[Category]:
        rows = await self.session.execute(
            select(tables.code_cat).order_by(func.lower(tables.code_cat.c.name))
        )
        return [Category.model_validate(r._mapping) for r in rows]

    async def list_codes(self) -> list[Code]:
        rows = await self.session.execute(
            select(tables.code_name).order_by(func.lower(tables.code_name.c.name))
        )
        return [Code.model_validate(r._mapping) for r in rows]

    async def add_code(
        self,
        *,
        name: str,
        owner: str,
        catid: int | None = None,
        color: str | None = None,
        memo: str = "",
        supercid: int | None = None,
    ) -> Code | None:
        if color is None:
            color = random_code_color()
        result = await self.session.execute(
            insert(tables.code_name).values(
                name=name, memo=memo, owner=owner, date=_now(), catid=catid, color=color,
                supercid=supercid,
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.code_name).where(
                    tables.code_name.c.cid == _inserted_pk(result)
                )
            )
        ).first()
        code = Code.model_validate(row._mapping) if row else None
        from qualcoder_api.services import sync

        if row is not None:
            await sync.capture_insert(
                self.session, entity="code_name", pk_name="cid", pk_value=row.cid,
                row=sync.table_row(row._mapping),
            )
        await self.session.commit()
        return code

    async def add_category(
        self,
        *,
        name: str,
        owner: str,
        supercatid: int | None = None,
        memo: str = "",
    ) -> Category | None:
        result = await self.session.execute(
            insert(tables.code_cat).values(
                name=name, memo=memo, owner=owner, date=_now(), supercatid=supercatid
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.code_cat).where(
                    tables.code_cat.c.catid == _inserted_pk(result)
                )
            )
        ).first()
        category = Category.model_validate(row._mapping) if row else None
        from qualcoder_api.services import sync

        if row is not None:
            await sync.capture_insert(
                self.session, entity="code_cat", pk_name="catid", pk_value=row.catid,
                row=sync.table_row(row._mapping),
            )
        await self.session.commit()
        return category

    async def rename_code(self, cid: int, name: str) -> Code | None:
        await self.session.execute(
            update(tables.code_name).where(tables.code_name.c.cid == cid).values(name=name)
        )
        await self.session.commit()
        code = await self.get_code(cid)
        from qualcoder_api.services import sync

        if code is not None:
            row = (
                await self.session.execute(
                    select(tables.code_name).where(tables.code_name.c.cid == cid)
                )
            ).first()
            await sync.capture_update(
                self.session, entity="code_name", pk_name="cid", pk_value=cid,
                row=sync.table_row(row._mapping) if row else None,
            )
            await self.session.commit()
        return code

    async def set_supercid(self, cid: int, supercid: int | None) -> Code | None:
        """Nest ``cid`` under code ``supercid`` (sub-codes, upstream v16).

        Raises ``ValueError`` when nesting would create a cycle (a code
        cannot be its own ancestor).
        """
        if supercid is not None:
            if supercid == cid:
                raise ValueError("a code cannot be its own parent")
            # Walk up the parent chain from supercid; if we reach cid, cycle.
            seen: set[int] = set()
            current: int | None = supercid
            while current is not None and current not in seen:
                if current == cid:
                    raise ValueError("cannot nest a code under its own sub-code")
                seen.add(current)
                parent_row = (
                    await self.session.execute(
                        select(tables.code_name.c.supercid).where(
                            tables.code_name.c.cid == current
                        )
                    )
                ).first()
                current = int(parent_row[0]) if parent_row is not None and parent_row[0] is not None else None
        await self.session.execute(
            update(tables.code_name).where(tables.code_name.c.cid == cid).values(supercid=supercid)
        )
        await self.session.commit()
        code = await self.get_code(cid)
        from qualcoder_api.services import sync

        if code is not None:
            row = (
                await self.session.execute(
                    select(tables.code_name).where(tables.code_name.c.cid == cid)
                )
            ).first()
            await sync.capture_update(
                self.session, entity="code_name", pk_name="cid", pk_value=cid,
                row=sync.table_row(row._mapping) if row else None,
            )
            await self.session.commit()
        return code

    async def get_code(self, cid: int) -> Code | None:
        row = (
            await self.session.execute(
                select(tables.code_name).where(tables.code_name.c.cid == cid)
            )
        ).first()
        return Code.model_validate(row._mapping) if row else None

    async def get_category(self, catid: int) -> Category | None:
        row = (
            await self.session.execute(
                select(tables.code_cat).where(tables.code_cat.c.catid == catid)
            )
        ).first()
        return Category.model_validate(row._mapping) if row else None

    async def set_code_catid(self, cid: int, catid: int | None) -> Code | None:
        """Move a code between categories (or to the root with ``None``)."""
        await self.session.execute(
            update(tables.code_name).where(tables.code_name.c.cid == cid).values(catid=catid)
        )
        await self.session.commit()
        code = await self.get_code(cid)
        from qualcoder_api.services import sync

        if code is not None:
            row = (
                await self.session.execute(
                    select(tables.code_name).where(tables.code_name.c.cid == cid)
                )
            ).first()
            await sync.capture_update(
                self.session, entity="code_name", pk_name="cid", pk_value=cid,
                row=sync.table_row(row._mapping) if row else None,
            )
            await self.session.commit()
        return code

    async def move_category(self, catid: int, supercatid: int | None) -> Category | None:
        """Reparent a category under ``supercatid`` (promote/demote).

        Raises ``ValueError`` when the move would create a cycle (a
        category cannot be its own ancestor).
        """
        if supercatid is not None:
            if supercatid == catid:
                raise ValueError("a category cannot be its own parent")
            # Walk up the parent chain from supercatid; if we reach catid, cycle.
            seen: set[int] = set()
            current: int | None = supercatid
            while current is not None and current not in seen:
                if current == catid:
                    raise ValueError("cannot nest a category under its own sub-category")
                seen.add(current)
                parent_row = (
                    await self.session.execute(
                        select(tables.code_cat.c.supercatid).where(
                            tables.code_cat.c.catid == current
                        )
                    )
                ).first()
                current = int(parent_row[0]) if parent_row is not None and parent_row[0] is not None else None
        await self.session.execute(
            update(tables.code_cat).where(tables.code_cat.c.catid == catid).values(supercatid=supercatid)
        )
        await self.session.commit()
        category = await self.get_category(catid)
        from qualcoder_api.services import sync

        if category is not None:
            row = (
                await self.session.execute(
                    select(tables.code_cat).where(tables.code_cat.c.catid == catid)
                )
            ).first()
            await sync.capture_update(
                self.session, entity="code_cat", pk_name="catid", pk_value=catid,
                row=sync.table_row(row._mapping) if row else None,
            )
            await self.session.commit()
        return category

    async def previous_sibling_code(
        self, cid: int, *, catid: int | None, supercid: int | None
    ) -> int | None:
        """The code immediately before ``cid`` at the same level (demote target).

        Siblings share the same category and the same parent code (either
        can be NULL — matched NULL-safely); the previous sibling is the one
        with the largest cid below ``cid``.
        """
        stmt = (
            select(tables.code_name.c.cid)
            .where(
                tables.code_name.c.cid < cid,
                tables.code_name.c.catid.is_(catid)
                if catid is None
                else tables.code_name.c.catid == catid,
                tables.code_name.c.supercid.is_(supercid)
                if supercid is None
                else tables.code_name.c.supercid == supercid,
            )
            .order_by(tables.code_name.c.cid.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).first()
        return int(row[0]) if row is not None else None

    async def previous_sibling_category(self, catid: int, *, supercatid: int | None) -> int | None:
        """The category immediately before ``catid`` at the same level."""
        stmt = (
            select(tables.code_cat.c.catid)
            .where(
                tables.code_cat.c.catid < catid,
                tables.code_cat.c.supercatid.is_(supercatid)
                if supercatid is None
                else tables.code_cat.c.supercatid == supercatid,
            )
            .order_by(tables.code_cat.c.catid.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).first()
        return int(row[0]) if row is not None else None

    async def delete_code(self, cid: int) -> None:
        """Delete a code and all its codings (legacy order)."""
        from qualcoder_api.services import sync

        def _rowdict(row) -> dict:
            return sync.table_row(row._mapping)

        for tbl, col, pk in (
            (tables.code_name, tables.code_name.c.cid, "cid"),
            (tables.code_text, tables.code_text.c.cid, "ctid"),
            (tables.code_av, tables.code_av.c.cid, "avid"),
            (tables.code_image, tables.code_image.c.cid, "imid"),
        ):
            rows = (await self.session.execute(select(tbl).where(col == cid))).all()
            await self.session.execute(delete(tbl).where(col == cid))
            for row in rows:
                await sync.capture_delete(
                    self.session, entity=tbl.name, pk_name=pk,
                    pk_value=_rowdict(row).get(pk), row=_rowdict(row),
                )
        # Sub-codes of the deleted code are orphaned (reparented to null).
        sub_rows = (
            await self.session.execute(
                select(tables.code_name).where(tables.code_name.c.supercid == cid)
            )
        ).all()
        await self.session.execute(
            update(tables.code_name)
            .where(tables.code_name.c.supercid == cid)
            .values(supercid=None)
        )
        for row in sub_rows:
            data = _rowdict(row)
            data["supercid"] = None
            await sync.capture_update(
                self.session, entity="code_name", pk_name="cid",
                pk_value=data.get("cid"), row=data,
            )
        await self.session.commit()

    async def delete_category(self, catid: int) -> None:
        """Delete a category; reassign orphaned codes and children to null."""
        from qualcoder_api.services import sync

        def _rowdict(row) -> dict:
            return sync.table_row(row._mapping)

        code_rows = (
            await self.session.execute(
                select(tables.code_name).where(tables.code_name.c.catid == catid)
            )
        ).all()
        await self.session.execute(
            update(tables.code_name).where(tables.code_name.c.catid == catid).values(catid=None)
        )
        for row in code_rows:
            data = _rowdict(row)
            data["catid"] = None
            await sync.capture_update(
                self.session, entity="code_name", pk_name="cid",
                pk_value=data.get("cid"), row=data,
            )
        cat_rows = (
            await self.session.execute(
                select(tables.code_cat).where(tables.code_cat.c.supercatid == catid)
            )
        ).all()
        await self.session.execute(
            update(tables.code_cat).where(tables.code_cat.c.supercatid == catid).values(supercatid=None)
        )
        for row in cat_rows:
            data = _rowdict(row)
            data["supercatid"] = None
            await sync.capture_update(
                self.session, entity="code_cat", pk_name="catid",
                pk_value=data.get("catid"), row=data,
            )
        cat_row = (
            await self.session.execute(
                select(tables.code_cat).where(tables.code_cat.c.catid == catid)
            )
        ).first()
        await self.session.execute(
            delete(tables.code_cat).where(tables.code_cat.c.catid == catid)
        )
        if cat_row is not None:
            await sync.capture_delete(
                self.session, entity="code_cat", pk_name="catid", pk_value=catid,
                row=_rowdict(cat_row),
            )
        await self.session.execute(
            text(
                "UPDATE code_cat SET supercatid = NULL "
                "WHERE supercatid IS NOT NULL AND supercatid NOT IN (SELECT catid FROM code_cat)"
            )
        )
        await self.session.commit()

    async def merge_codes(self, old_cid: int, new_cid: int) -> None:
        """Merge code ``old_cid`` into ``new_cid`` (legacy semantics).

        ``code_text`` has a unique(cid,fid,pos0,pos1,owner) constraint: if the
        merged segment would collide with an existing one under ``new_cid``,
        the source row is DELETED (matching legacy ``merge_codes``). The
        ``code_av``/``code_image`` tables have no unique constraint, so their
        rows are reassigned unconditionally.
        """
        rows = (
            await self.session.execute(
                select(tables.code_text).where(tables.code_text.c.cid == old_cid)
            )
        ).all()
        from qualcoder_api.services import sync

        for row in rows:
            dup = (
                await self.session.execute(
                    select(tables.code_text.c.ctid).where(
                        tables.code_text.c.cid == new_cid,
                        tables.code_text.c.fid == row.fid,
                        tables.code_text.c.pos0 == row.pos0,
                        tables.code_text.c.pos1 == row.pos1,
                        tables.code_text.c.owner == row.owner,
                    )
                )
            ).first()
            if dup is not None:
                data = sync.table_row(row._mapping)
                await sync.capture_delete(
                    self.session, entity="code_text", pk_name="ctid",
                    pk_value=data.get("ctid"), row=data,
                )
                await self.session.execute(
                    delete(tables.code_text).where(tables.code_text.c.ctid == row.ctid)
                )
            else:
                await self.session.execute(
                    update(tables.code_text)
                    .where(tables.code_text.c.ctid == row.ctid)
                    .values(cid=new_cid)
                )
                data = sync.table_row(row._mapping)
                data["cid"] = new_cid
                await sync.capture_update(
                    self.session, entity="code_text", pk_name="ctid",
                    pk_value=data.get("ctid"), row=data,
                )
        for tbl, col in (
            (tables.code_av, tables.code_av.c.cid),
            (tables.code_image, tables.code_image.c.cid),
        ):
            rows = (await self.session.execute(select(tbl).where(col == old_cid))).all()
            await self.session.execute(
                update(tbl).where(col == old_cid).values(**{col.name: new_cid})
            )
            for row in rows:
                data = sync.table_row(row._mapping)
                data[col.name] = new_cid
                pk = "avid" if tbl is tables.code_av else "imid"
                await sync.capture_update(
                    self.session, entity=tbl.name, pk_name=pk,
                    pk_value=int(data[pk]), row=data,
                )
        # Sub-codes of the merged-away code move under the target code.
        sub_rows = (
            await self.session.execute(
                select(tables.code_name).where(tables.code_name.c.supercid == old_cid)
            )
        ).all()
        await self.session.execute(
            update(tables.code_name)
            .where(tables.code_name.c.supercid == old_cid)
            .values(supercid=new_cid)
        )
        for row in sub_rows:
            data = sync.table_row(row._mapping)
            data["supercid"] = new_cid
            await sync.capture_update(
                self.session, entity="code_name", pk_name="cid",
                pk_value=data.get("cid"), row=data,
            )
        old_row = (
            await self.session.execute(
                select(tables.code_name).where(tables.code_name.c.cid == old_cid)
            )
        ).first()
        await self.session.execute(
            delete(tables.code_name).where(tables.code_name.c.cid == old_cid)
        )
        if old_row is not None:
            await sync.capture_delete(
                self.session, entity="code_name", pk_name="cid", pk_value=old_cid,
                row=sync.table_row(old_row._mapping),
            )
        await self.session.commit()

    async def merge_category(self, catid: int, target_catid: int) -> None:
        """Merge category ``catid`` into ``target_catid``."""
        from qualcoder_api.services import sync

        code_rows = (
            await self.session.execute(
                select(tables.code_name).where(tables.code_name.c.catid == catid)
            )
        ).all()
        await self.session.execute(
            update(tables.code_name)
            .where(tables.code_name.c.catid == catid)
            .values(catid=target_catid)
        )
        for row in code_rows:
            data = sync.table_row(row._mapping)
            data["catid"] = target_catid
            await sync.capture_update(
                self.session, entity="code_name", pk_name="cid",
                pk_value=data.get("cid"), row=data,
            )
        cat_row = (
            await self.session.execute(
                select(tables.code_cat).where(tables.code_cat.c.catid == catid)
            )
        ).first()
        await self.session.execute(
            delete(tables.code_cat).where(tables.code_cat.c.catid == catid)
        )
        if cat_row is not None:
            await sync.capture_delete(
                self.session, entity="code_cat", pk_name="catid", pk_value=catid,
                row=sync.table_row(cat_row._mapping),
            )
        sub_rows = (
            await self.session.execute(
                select(tables.code_cat).where(tables.code_cat.c.supercatid == catid)
            )
        ).all()
        await self.session.execute(
            update(tables.code_cat)
            .where(tables.code_cat.c.supercatid == catid)
            .values(supercatid=target_catid)
        )
        for row in sub_rows:
            data = sync.table_row(row._mapping)
            data["supercatid"] = target_catid
            await sync.capture_update(
                self.session, entity="code_cat", pk_name="catid",
                pk_value=data.get("catid"), row=data,
            )
        await self.session.execute(
            text(
                "UPDATE code_cat SET supercatid = NULL "
                "WHERE supercatid IS NOT NULL AND supercatid NOT IN (SELECT catid FROM code_cat)"
            )
        )
        await self.session.commit()


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
        allowed = {"seltext", "pos0", "pos1", "memo", "important", "avid", "cid"}
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
        allowed = {"x1", "y1", "width", "height", "cid", "memo", "important", "pdf_page"}
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

class AttributeRepository:
    """CRUD for attribute types and values."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_types(self) -> list[AttributeType]:
        rows = await self.session.execute(
            select(tables.attribute_type).order_by(func.lower(tables.attribute_type.c.name))
        )
        return [AttributeType.model_validate(r._mapping) for r in rows]

    async def add_type(self, *, name: str, owner: str, case_or_file: str = "case",
                       value_type: str = "text", memo: str = "",
                       value_labels: dict[str, str] | None = None) -> AttributeType:
        labels = value_labels or {}
        await self.session.execute(
            insert(tables.attribute_type).values(
                name=name,
                date=_now(),
                owner=owner,
                memo=memo,
                caseOrFile=case_or_file,
                valuetype=value_type,
                value_labels=json.dumps(labels),
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.attribute_type).where(tables.attribute_type.c.name == name)
            )
        ).first()
        if row is not None:
            await _capture(
                self.session, "attribute_type", "insert", "name", name, _rowdict(row)
            )
            await self.session.commit()
        return AttributeType(
            name=name, date=_now(), owner=owner, memo=memo,
            case_or_file=case_or_file, value_type=value_type, value_labels=labels,
        )

    async def delete_type(self, name: str) -> None:
        """Delete an attribute type and all its values.

        ``attribute.name`` holds the attribute type name; ``attribute.attr_type``
        holds the scope ("case"/"file").
        """
        rows = (
            await self.session.execute(select(tables.attribute).where(tables.attribute.c.name == name))
        ).all()
        await self.session.execute(
            delete(tables.attribute).where(tables.attribute.c.name == name)
        )
        for row in rows:
            data = _rowdict(row)
            await _capture(
                self.session, "attribute", "delete", "attrid", data.get("attrid"), data
            )
        type_row = (
            await self.session.execute(
                select(tables.attribute_type).where(tables.attribute_type.c.name == name)
            )
        ).first()
        await self.session.execute(
            delete(tables.attribute_type).where(tables.attribute_type.c.name == name)
        )
        if type_row is not None:
            await _capture(
                self.session, "attribute_type", "delete", "name", name, _rowdict(type_row)
            )
        await self.session.commit()

    async def list_values(self, *, entity_id: int | None = None,
                          attr_type: str | None = None) -> list[Attribute]:
        stmt = select(tables.attribute)
        if entity_id is not None:
            stmt = stmt.where(tables.attribute.c.id == entity_id)
        if attr_type is not None:
            stmt = stmt.where(tables.attribute.c.attr_type == attr_type)
        rows = await self.session.execute(stmt.order_by(tables.attribute.c.name))
        return [Attribute.model_validate(r._mapping) for r in rows]

    async def set_value(self, *, name: str, attr_type: str, value: str,
                        entity_id: int, owner: str) -> Attribute:
        """Insert or replace an attribute value for an entity."""
        existing = (
            await self.session.execute(
                select(tables.attribute).where(
                    tables.attribute.c.name == name,
                    tables.attribute.c.attr_type == attr_type,
                    tables.attribute.c.id == entity_id,
                )
            )
        ).first()
        action = "update" if existing is not None else "insert"
        await self.session.execute(
            delete(tables.attribute).where(
                tables.attribute.c.name == name,
                tables.attribute.c.attr_type == attr_type,
                tables.attribute.c.id == entity_id,
            )
        )
        result = await self.session.execute(
            insert(tables.attribute).values(
                name=name,
                attr_type=attr_type,
                value=value,
                id=entity_id,
                date=_now(),
                owner=owner,
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.attribute).where(
                    tables.attribute.c.attrid == _inserted_pk(result)
                )
            )
        ).first()
        assert row is not None
        await _capture(
            self.session, "attribute", action, "attrid", row.attrid, _rowdict(row)
        )
        await self.session.commit()
        return Attribute.model_validate(row._mapping)


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
