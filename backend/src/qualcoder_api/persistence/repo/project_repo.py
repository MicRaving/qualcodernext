"""Project metadata repository (``project`` table)."""

from __future__ import annotations

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.models import Project
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repo.base import _capture, _rowdict


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
        """Refresh the ``coder_names`` table from all owner columns.

        Only derives rows from SYNCED content (owner columns) plus the
        constant ``system`` entry, so every instance computes the same
        registry.  The opener's own identity (``current_coder`` / last
        opener) is deliberately NOT inserted here: that used to be a local,
        uncaptured write, so a fresh joiner opening as ``default`` — or a
        rename victim reopening under its stale name — permanently diverged
        its roster from peers with no sync event to ever heal it.  Joining
        the registry is an explicit, captured act (create/switch coder).
        """
        _ = current_coder
        union_sql = "\nUNION ".join(
            f"SELECT owner AS name FROM {t} WHERE owner IS NOT NULL"
            for t in tables.OWNER_TABLES
        )
        await self.session.execute(
            text(f"INSERT OR IGNORE INTO coder_names (name) {union_sql}")
        )
        await self.session.execute(
            text("INSERT OR IGNORE INTO coder_names (name) VALUES (:name)"),
            {"name": tables.SYSTEM_CODER_NAME},
        )
        await self.session.commit()
