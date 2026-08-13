"""Database migration chain — v2→v5 and v6→v14 upgrade paths (async port).

Behavior is a faithful port of the legacy ``MigrationChain``: each step is
defensive (probe for a column/table; add it only if missing), so any
intermediate legacy version converges to v14.
"""

from __future__ import annotations

import logging

import aiosqlite

from qualcoder_api.persistence import tables

logger = logging.getLogger(__name__)


class MigrationChain:
    """Handles schema migrations from legacy versions to the current v14."""

    def __init__(self, conn: aiosqlite.Connection | None):
        self.conn = conn

    async def _has_column(self, cur: aiosqlite.Cursor, table: str, column: str) -> bool:
        await cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if await cur.fetchone() is None:
            return False
        await cur.execute(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in await cur.fetchall())

    async def _has_table(self, cur: aiosqlite.Cursor, table: str) -> bool:
        await cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
        return await cur.fetchone() is not None

    async def migrate_v2_to_v5(self, app_version: str, codername: str) -> list[str]:
        """Apply database migrations v2-v5 and return applied version labels."""
        if self.conn is None:
            return []

        applied_updates: list[str] = []
        cur = await self.conn.cursor()

        # --- v2 ---
        if not await self._has_column(cur, "code_text", "avid"):
            await cur.execute("ALTER TABLE code_text ADD avid integer")
            await self.conn.commit()
        if not await self._has_column(cur, "project", "bookmarkfile"):
            await cur.execute("ALTER TABLE project ADD bookmarkfile integer")
            await cur.execute("ALTER TABLE project ADD bookmarkpos integer")
            await self.conn.commit()
            applied_updates.append("v2")

        # --- v3 ---
        if not await self._has_column(cur, "code_text", "important"):
            await cur.execute("ALTER TABLE code_text ADD important integer")
            await self.conn.commit()
        if not await self._has_column(cur, "code_av", "important"):
            await cur.execute("ALTER TABLE code_av ADD important integer")
            await self.conn.commit()
        if not await self._has_column(cur, "code_image", "important"):
            await cur.execute("ALTER TABLE code_image ADD important integer")
            await self.conn.commit()
            applied_updates.append("v3")

        # --- v4 (code_text rebuild with ctid primary key) ---
        await cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='code_text2'"
        )
        code_text2_exists = await cur.fetchone() is not None
        if not code_text2_exists and not await self._has_column(cur, "code_text", "ctid"):
            await cur.execute(
                "CREATE TABLE code_text2 (ctid integer primary key, cid integer, fid integer,seltext text, "
                "pos0 integer, pos1 integer, owner text, date text, memo text, avid integer, important integer, "
                "unique(cid,fid,pos0,pos1, owner))"
            )
            await self.conn.commit()
            await cur.execute(
                "insert into code_text2 (cid, fid, seltext, pos0, pos1, owner, date, memo, avid, important) "
                "select cid, fid, seltext, pos0, pos1, owner, date, memo, avid, important from code_text"
            )
            await self.conn.commit()
            await cur.execute("drop table code_text")
            await cur.execute("alter table code_text2 rename to code_text")
            await cur.execute('update project set databaseversion="v4", about=?', [app_version])
            await self.conn.commit()
            applied_updates.append("v4")

        # --- v5 ---
        if not await self._has_column(cur, "project", "codername"):
            await cur.execute("ALTER TABLE project ADD codername text")
            await self.conn.commit()
            await cur.execute(
                'update project set databaseversion="v5", about=?, codername=?',
                [app_version, codername],
            )
            await self.conn.commit()
        if not await self._has_column(cur, "source", "av_text_id"):
            await cur.execute("ALTER TABLE source ADD av_text_id integer")
            await self.conn.commit()
            await cur.execute(
                """
                UPDATE source AS av
                SET av_text_id = (
                    SELECT t.id FROM source AS t
                    WHERE t.name = av.name || '.transcribed'
                    LIMIT 1
                )
                WHERE (
                    av.mediapath LIKE '/audio/%' OR av.mediapath LIKE 'audio:%' OR
                    av.mediapath LIKE '/video/%' OR av.mediapath LIKE 'video:%'
                )
                """
            )
            await self.conn.commit()
            applied_updates.append("v5")
        if not await self._has_table(cur, "stored_sql"):
            await cur.execute(
                "CREATE TABLE stored_sql (title text, description text, grouper text, ssql text, unique(title));"
            )
            await self.conn.commit()

        return applied_updates

    async def migrate_v6_to_v14(self, app_version: str) -> list[str]:
        """Apply database migrations v6-v14 and return applied version labels."""
        if self.conn is None:
            return []

        applied_updates: list[str] = []
        cur = await self.conn.cursor()

        # --- v6: Graph tables ---
        if not await self._has_table(cur, "graph"):
            await cur.execute("CREATE TABLE graph (grid integer primary key, name text, description text, "
                              "date text, scene_width integer, scene_height integer, unique(name));")
            await self.conn.commit()
        if not await self._has_table(cur, "gr_cdct_text_item"):
            await cur.execute(
                "CREATE TABLE gr_cdct_text_item (gtextid integer primary key, grid integer, x integer, y integer, "
                "supercatid integer, catid integer, cid integer, font_size integer, bold integer, "
                "isvisible integer, displaytext text);")
            await self.conn.commit()
        if not await self._has_table(cur, "gr_case_text_item"):
            await cur.execute("CREATE TABLE gr_case_text_item (gcaseid integer primary key, grid integer, x integer, "
                              "y integer, caseid integer, font_size integer, bold integer, color text, displaytext text);")
            await self.conn.commit()
        if not await self._has_table(cur, "gr_file_text_item"):
            await cur.execute("CREATE TABLE gr_file_text_item (gfileid integer primary key, grid integer, x integer, "
                              "y integer, fid integer, font_size integer, bold integer, color text, displaytext text);")
            await self.conn.commit()
        if not await self._has_table(cur, "gr_free_text_item"):
            await cur.execute("CREATE TABLE gr_free_text_item (gfreeid integer primary key, grid integer, freetextid integer,"
                              "x integer, y integer, free_text text, font_size integer, bold integer, color text,"
                              "tooltip text, ctid integer);")
            await self.conn.commit()
        if not await self._has_table(cur, "gr_cdct_line_item"):
            await cur.execute("CREATE TABLE gr_cdct_line_item (glineid integer primary key, grid integer, "
                              "fromcatid integer, fromcid integer, tocatid integer, tocid integer, color text, "
                              "linewidth real, linetype text, isvisible integer);")
            await self.conn.commit()
        if not await self._has_table(cur, "gr_free_line_item"):
            await cur.execute("CREATE TABLE gr_free_line_item (gflineid integer primary key, grid integer, "
                              "fromfreetextid integer, fromcatid integer, fromcid integer, fromcaseid integer,"
                              "fromfileid integer, fromimid integer, fromavid integer, tofreetextid integer, tocatid integer,"
                              "tocid integer, tocaseid integer, tofileid integer, toimid integer, toavid integer, color text,"
                              " linewidth real, linetype text);")
            await self.conn.commit()
        if not await self._has_table(cur, "gr_pix_item"):
            await cur.execute("CREATE TABLE gr_pix_item (grpixid integer primary key, grid integer, imid integer,"
                              "x integer, y integer, px integer, py integer, w integer, h integer, filepath text,"
                              "tooltip text);")
            await self.conn.commit()
        if not await self._has_table(cur, "gr_av_item"):
            await cur.execute("CREATE TABLE gr_av_item (gr_avid integer primary key, grid integer, avid integer,"
                              "x integer, y integer, pos0 integer, pos1 integer, filepath text, tooltip text, color text);")
            await self.conn.commit()
            await cur.execute('update project set databaseversion="v6", about=?', [app_version])
            await self.conn.commit()
            applied_updates.append("v6")

        # --- v7 ---
        db7_update = False
        if not await self._has_column(cur, "gr_free_text_item", "memo_ctid"):
            await cur.execute("ALTER TABLE gr_free_text_item ADD memo_ctid integer")
            await self.conn.commit()
            db7_update = True
        if not await self._has_column(cur, "gr_free_text_item", "memo_imid"):
            await cur.execute("ALTER TABLE gr_free_text_item ADD memo_imid integer")
            await self.conn.commit()
            db7_update = True
        if not await self._has_column(cur, "gr_free_text_item", "memo_avid"):
            await cur.execute("ALTER TABLE gr_free_text_item ADD memo_avid integer")
            await self.conn.commit()
            db7_update = True
        if db7_update:
            await cur.execute('update project set databaseversion="v7", about=?', [app_version])
            await self.conn.commit()
            applied_updates.append("v7")

        # --- v8 ---
        if not await self._has_table(cur, "ris"):
            await cur.execute("CREATE TABLE ris (risid integer, tag text, longtag text, value text);")
            await cur.execute('update project set databaseversion="v8", about=?', [app_version])
            await self.conn.commit()
            applied_updates.append("v8")
        if not await self._has_column(cur, "source", "risid"):
            await cur.execute("ALTER TABLE source ADD risid integer")
            await self.conn.commit()

        # --- v9 ---
        if not await self._has_column(cur, "project", "recently_used_codes"):
            await cur.execute("ALTER TABLE project ADD recently_used_codes text")
            await cur.execute('update project set databaseversion="v9", about=?', [app_version])
            await self.conn.commit()
            applied_updates.append("v9")

        # --- v10 ---
        if not await self._has_column(cur, "code_image", "pdf_page"):
            await cur.execute("ALTER TABLE code_image ADD pdf_page integer")
            await cur.execute('update project set databaseversion="v10", about=?', [app_version])
            await self.conn.commit()
            applied_updates.append("v10")

        # --- v11 ---
        if not await self._has_column(cur, "gr_pix_item", "pdf_page"):
            await cur.execute("ALTER TABLE gr_pix_item ADD pdf_page integer")
            await cur.execute('update project set databaseversion="v11", about=?', [app_version])
            await self.conn.commit()
            applied_updates.append("v11")

        # --- v12 ---
        if not await self._has_table(cur, "manage_files_display"):
            await cur.execute(
                "CREATE TABLE manage_files_display (mfid integer primary key, name text, tblrows text, tblcolumns text, owner text);")
            await cur.execute('update project set databaseversion="v12", about=?', [app_version])
            await self.conn.commit()
            applied_updates.append("v12")

        # --- v13 ---
        if not await self._has_table(cur, "files_filter"):
            await cur.execute("CREATE TABLE files_filter (filterid integer primary key, name text, filter text, owner text);")
            await cur.execute('update project set databaseversion="v13", about=?', [app_version])
            await self.conn.commit()
            applied_updates.append("v13")

        # --- v14 ---
        coder_names_created = False
        if not await self._has_table(cur, "coder_names"):
            await cur.execute(
                "CREATE TABLE coder_names (name TEXT UNIQUE NOT NULL, "
                "visibility INTEGER NOT NULL DEFAULT 1 CHECK (visibility IN (0, 1)));"
            )
            await self.conn.commit()
            coder_names_created = True
        for view_name in tables.VISIBILITY_VIEWS:
            await cur.execute(self._view_sql(view_name))
        if coder_names_created:
            await cur.execute('update project set databaseversion="v14", about=?', [app_version])
            await self.conn.commit()
            applied_updates.append("v14")

        return applied_updates

    @staticmethod
    def _view_sql(view_name: str) -> str:
        tbl = view_name.replace("_visible", "")
        return (
            f"CREATE VIEW IF NOT EXISTS {view_name} AS "
            f"SELECT t.* FROM {tbl} t WHERE NOT EXISTS ("
            f"SELECT 1 FROM coder_names c WHERE c.name = t.owner AND c.visibility = 0)"
        )

    async def run_all(self, app_version: str, codername: str) -> list[str]:
        """Run the full legacy chain v2-v19 plus the v20 index step."""
        applied = await self.migrate_v2_to_v5(app_version, codername)
        applied += await self.migrate_v6_to_v14(app_version)
        applied += await self.migrate_v15()
        applied += await self.migrate_v16_to_v18(app_version)
        applied += await self.migrate_v19(app_version)
        applied += await self.migrate_v20()
        applied += await self.migrate_v21(app_version)
        applied += await self.migrate_v22(app_version)
        applied += await self.migrate_v23(app_version)
        applied += await self.migrate_v24(app_version)
        applied += await self.migrate_v25(app_version)
        return applied

    async def migrate_v21(self, app_version: str) -> list[str]:
        """v21: the ``link`` table — segment hyperlinks between source spans."""
        if self.conn is None:
            return []
        cur = await self.conn.cursor()
        if not await self._has_table(cur, "link"):
            await cur.execute(
                "CREATE TABLE link (id integer primary key autoincrement, from_fid integer, "
                "from_pos0 integer, from_pos1 integer, to_fid integer, to_pos0 integer, "
                "to_pos1 integer, memo text, owner text, date text)"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_link_from_fid ON link(from_fid)"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_link_to_fid ON link(to_fid)"
            )
            await cur.execute('update project set databaseversion="v21", about=?', [app_version])
            await self.conn.commit()
            return ["v21"]
        return []

    async def migrate_v22(self, app_version: str) -> list[str]:
        """v22: value_labels — the JSON map of raw value → display label on
        attribute types (MAXQDA-style value lists)."""
        if self.conn is None:
            return []
        cur = await self.conn.cursor()
        if await self._has_table(cur, "attribute_type") and not await self._has_column(
            cur, "attribute_type", "value_labels"
        ):
            await cur.execute("ALTER TABLE attribute_type ADD value_labels text")
            await cur.execute('update project set databaseversion="v22", about=?', [app_version])
            await self.conn.commit()
            return ["v22"]
        return []

    async def migrate_v23(self, app_version: str) -> list[str]:
        """v23: word dictionaries (MAXDictio-style) — ``dictionary`` and
        ``dictionary_entry`` tables."""
        if self.conn is None:
            return []
        cur = await self.conn.cursor()
        changed = False
        if not await self._has_table(cur, "dictionary"):
            await cur.execute(
                "CREATE TABLE dictionary (id integer primary key autoincrement, name text, "
                "owner text, created text, unique(name))"
            )
            await self.conn.commit()
            changed = True
        if not await self._has_table(cur, "dictionary_entry"):
            await cur.execute(
                "CREATE TABLE dictionary_entry (id integer primary key autoincrement, dict_id integer, "
                "code_name text, term text, unique(dict_id, term))"
            )
            await self.conn.commit()
            changed = True
        if changed:
            await cur.execute('update project set databaseversion="v23", about=?', [app_version])
            await self.conn.commit()
            return ["v23"]
        return []

    async def migrate_v24(self, app_version: str) -> list[str]:
        """v24: ``creative_item`` — the creative-coding scratchpad
        (MAXQDA-style): free-text ideas and quotes with an optional source
        span reference (``source_fid``/``pos0``/``pos1`` all nullable —
        unsourced items have no span)."""
        if self.conn is None:
            return []
        cur = await self.conn.cursor()
        if not await self._has_table(cur, "creative_item"):
            await cur.execute(
                "CREATE TABLE creative_item (id integer primary key autoincrement, text text, "
                "source_fid integer, pos0 integer, pos1 integer, note text, owner text, date text)"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_creative_item_source_fid "
                "ON creative_item(source_fid)"
            )
            await cur.execute('update project set databaseversion="v24", about=?', [app_version])
            await self.conn.commit()
            return ["v24"]
        return []

    async def migrate_v25(self, app_version: str) -> list[str]:
        """v25: the QTT workspace (MAXQDA-style Questions-Themes-Theories
        worksheets): ``qtt_sheet`` holds the worksheet (name, kind, the
        section list as JSON, research question / purpose / framework) and
        ``qtt_item`` holds per-section items (segments, notes, charts,
        links) with their payload as JSON."""
        if self.conn is None:
            return []
        cur = await self.conn.cursor()
        changed = False
        if not await self._has_table(cur, "qtt_sheet"):
            await cur.execute(
                "CREATE TABLE qtt_sheet (id integer primary key autoincrement, name text, "
                "kind text, sections_json text, research_question text, purpose text, "
                "framework text, owner text, date text)"
            )
            await self.conn.commit()
            changed = True
        if not await self._has_table(cur, "qtt_item"):
            await cur.execute(
                "CREATE TABLE qtt_item (id integer primary key autoincrement, sheet_id integer, "
                "section text, kind text, payload_json text, owner text, date text)"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_qtt_item_sheet_id ON qtt_item(sheet_id)"
            )
            await self.conn.commit()
            changed = True
        if changed:
            await cur.execute('update project set databaseversion="v25", about=?', [app_version])
            await self.conn.commit()
            return ["v25"]
        return []

    async def migrate_v20(self) -> list[str]:
        """v20: hot-path indexes (only reports work when something was
        actually created, so a fully indexed database gets no v20 tag)."""
        if self.conn is None:
            return []
        cur = await self.conn.cursor()
        from qualcoder_api.persistence.schema import _INDEX_SQL

        created = 0
        for sql in _INDEX_SQL:
            # "CREATE INDEX IF NOT EXISTS <name> ON <table>(...)" — probe
            # sqlite_master (rowcount is unreliable for DDL). The index name
            # is token 5; the table token 7. Tables created later in the
            # chain (e.g. ``link`` by v21) must not break the index step —
            # their indexes are created by their own migration.
            index_name = sql.split()[5]
            table_name = sql.split()[7].split("(")[0]
            if table_name and not await self._has_table(cur, table_name):
                continue
            await cur.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?", (index_name,)
            )
            if await cur.fetchone() is None:
                await cur.execute(sql)
                created += 1
        await self.conn.commit()
        return ["v20"] if created else []

    async def migrate_v19(self, app_version: str) -> list[str]:
        """v19: sync_log — the change journal used by the collaboration sync
        (Option B: sidecar change files exchanged via folder-sync tools)."""
        if self.conn is None:
            return []
        cur = await self.conn.cursor()
        if not await self._has_table(cur, "sync_log"):
            await cur.execute(
                "CREATE TABLE sync_log (id integer primary key autoincrement, ts text, "
                "user text, seq integer, entity text, action text, pk_name text, "
                "pk_value text, row_json text)"
            )
            await cur.execute('update project set databaseversion="v19", about=?', [app_version])
            await self.conn.commit()
            return ["v19"]
        return []

    async def migrate_v15(self) -> list[str]:
        """v15: audit_log table + legacy-data backfill (idempotent)."""
        if self.conn is None:
            return []
        cur = await self.conn.cursor()
        changed = False
        # Legacy rows may carry important = NULL; the API models require an
        # int, so NULL is backfilled to 0 (also handled defensively in the
        # repository layer for rows written by other tools).
        for table in ("code_text", "code_image", "code_av"):
            if await self._has_table(cur, table) and await self._has_column(
                cur, table, "important"
            ):
                await cur.execute(
                    f"UPDATE {table} SET important = 0 WHERE important IS NULL"
                )
                if cur.rowcount:
                    changed = True
        await self.conn.commit()
        if not await self._has_table(cur, "audit_log"):
            await cur.execute(
                "CREATE TABLE audit_log (id integer primary key autoincrement, ts text, user text, "
                "action text, entity text, entity_id integer, source_id integer, detail text)"
            )
            await self.conn.commit()
            changed = True
        return ["v15"] if changed else []

    async def migrate_v16_to_v18(self, app_version: str) -> list[str]:
        """v16 sub-codes, v17 graph label/arrows + gr_memo_item, v18 AV bookmarks.

        Mirrors upstream v15 (avbookmarks), v16 (supercid) and v17 (graph
        items). The rework numbers them 16-18 because its own v15 step
        (audit_log) already shipped.
        """
        if self.conn is None:
            return []
        cur = await self.conn.cursor()
        applied: list[str] = []

        # --- v16: sub-codes (code nested under a code) ---
        if await self._has_table(cur, "code_name") and not await self._has_column(
            cur, "code_name", "supercid"
        ):
            await cur.execute("ALTER TABLE code_name ADD supercid integer")
            await cur.execute('update project set databaseversion="v16", about=?', [app_version])
            await self.conn.commit()
            applied.append("v16")

        # --- v17: graph line labels/arrow modes + memo nodes ---
        v17_changed = False
        if await self._has_table(cur, "gr_cdct_line_item") and not await self._has_column(
            cur, "gr_cdct_line_item", "label"
        ):
            await cur.execute("ALTER TABLE gr_cdct_line_item ADD label text")
            await cur.execute("ALTER TABLE gr_cdct_line_item ADD arrow_mode text")
            v17_changed = True
        if await self._has_table(cur, "gr_free_line_item") and not await self._has_column(
            cur, "gr_free_line_item", "label"
        ):
            await cur.execute("ALTER TABLE gr_free_line_item ADD label text")
            await cur.execute("ALTER TABLE gr_free_line_item ADD arrow_mode text")
            v17_changed = True
        if not await self._has_table(cur, "gr_memo_item"):
            await cur.execute(
                "CREATE TABLE gr_memo_item (gmemoid integer primary key, grid integer, "
                "memo_source_type text, memo_source_id integer, x integer, y integer, "
                "color text, font_size integer)"
            )
            v17_changed = True
        if v17_changed:
            await cur.execute('update project set databaseversion="v17", about=?', [app_version])
            await self.conn.commit()
            applied.append("v17")

        # --- v18: audio/video bookmarks ---
        if await self._has_table(cur, "project") and not await self._has_column(
            cur, "project", "avbookmarkfile"
        ):
            await cur.execute("ALTER TABLE project ADD avbookmarkfile integer")
            await cur.execute("ALTER TABLE project ADD avbookmarkmsec integer")
            await cur.execute("ALTER TABLE project ADD avbookmarktextpos integer")
            await cur.execute('update project set databaseversion="v18", about=?', [app_version])
            await self.conn.commit()
            applied.append("v18")

        return applied
