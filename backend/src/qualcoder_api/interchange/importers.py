"""Interchange importers: RQDA, Taguette, RIS, Survey CSV.

Pure async module: no FastAPI imports. ``session_factory`` is an
``async_sessionmaker`` bound to the open project's engine. The source files
(RQDA/Taguette SQLite databases, RIS text, Survey CSV) are read directly
with aiosqlite / the stdlib csv module; every write goes through the
repositories in ``qualcoder_api.persistence.repositories``.

Importers deduplicate by name against the target project (existing rows are
skipped) and return a result dict. Unreadable or malformed files raise
``ValueError``, which the API layer maps to HTTP 422.
"""

from __future__ import annotations

import csv
import html
import io
import re
import sqlite3
from pathlib import Path

import aiosqlite
import rispy
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import (
    AttributeRepository,
    CaseRepository,
    CodeRepository,
    CodingRepository,
    SourceRepository,
)

# ----------------------------------------------------------------------
# Shared helpers
# ----------------------------------------------------------------------

async def _fetch(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
    """Run a SELECT against the source database and return all rows."""
    cur = await db.execute(sql, params)
    return list(await cur.fetchall())


async def _table_names(db: aiosqlite.Connection) -> set[str]:
    """Names of the tables present in the source database."""
    rows = await _fetch(db, "SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in rows}


async def _columns(db: aiosqlite.Connection, table: str) -> set[str]:
    """Column names of ``table`` in the source database (empty when absent)."""
    cur = await db.execute(f'PRAGMA table_info("{table}")')
    rows = await cur.fetchall()
    return {row[1] for row in rows}


def _pick(cols: set[str], *candidates: str | None) -> list[str]:
    """The candidates present in ``cols``, in order — builds adaptive SELECTs."""
    return [c for c in candidates if c is not None and c in cols]


async def _existing_names(session, table, name_col: str) -> set[str]:
    """Names already present in ``table`` (used for deduplication)."""
    rows = await session.execute(select(table.c[name_col]))
    return {r[0] for r in rows if r[0] is not None}


# ----------------------------------------------------------------------
# RQDA
# ----------------------------------------------------------------------

async def import_rqda(session_factory: async_sessionmaker, rqda_path: str, codername: str) -> dict:
    """Import an RQDA ``.rqda`` SQLite database into the open project.

    Mirrors the legacy ``rqda.py`` importer: sources from ``source`` (or a
    ``file`` table with ``fulltext``), categories from ``codecat``, codes
    from ``freecode`` (category membership via ``treecode`` or a direct
    ``category`` column), codings from ``coding``/``coding2`` (positions in
    ``selfirst``/``selend`` or ``pos0``/``pos1``), cases from ``cases`` (or
    ``casename``) with ``caselinkage`` case-text links, and attribute
    types/values from ``attributes``/``caseAttr``/``fileAttr``. Every read
    adapts to whichever columns exist. RQDA codes keep their source color
    when present, otherwise a random palette color is assigned. Rows whose
    name already exists in the project are skipped. Raises ``ValueError``
    when the file is not a readable RQDA SQLite database.
    """
    try:
        async with aiosqlite.connect(rqda_path) as src:
            return await _import_rqda(src, session_factory, codername)
    except sqlite3.Error as err:
        raise ValueError(f"Invalid RQDA file: {err}") from err


async def _import_rqda(src: aiosqlite.Connection, session_factory, codername: str) -> dict:
    counts: dict[str, int] = {
        "codes": 0,
        "categories": 0,
        "codings": 0,
        "sources": 0,
        "cases": 0,
        "attributes": 0,
    }
    tables_present = await _table_names(src)
    if not {"source", "file", "codecat", "freecode"} & tables_present:
        raise ValueError("Not an RQDA database")

    async with session_factory() as session:
        source_repo = SourceRepository(session)
        code_repo = CodeRepository(session)
        coding_repo = CodingRepository(session)
        case_repo = CaseRepository(session)
        attr_repo = AttributeRepository(session)

        if "project" in tables_present and "memo" in await _columns(src, "project"):
            rows = await _fetch(src, "SELECT memo FROM project")
            if rows and rows[0][0]:
                await session.execute(update(tables.project).values(memo=rows[0][0]))
                await session.commit()

        # -- sources -----------------------------------------------------
        fid_map: dict[int, int] = {}
        existing = await _existing_names(session, tables.source, "name")
        source_tables: list[tuple[str, set[str]]] = []
        if "source" in tables_present:
            source_tables.append(("source", await _columns(src, "source")))
        if "file" in tables_present and "source" not in tables_present:
            source_tables.append(("file", await _columns(src, "file")))
        for table, cols in source_tables:
            pick = _pick(cols, "id", "name", "file", "fulltext", "memo")
            if not {"id", "name"} <= set(pick):
                continue
            for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM {table}"):
                values = dict(zip(pick, row, strict=True))
                name = values["name"]
                if not name or name in existing:
                    continue
                source = await source_repo.add_source(
                    name=name,
                    mediapath=None,
                    fulltext=values.get("file") or values.get("fulltext"),
                    memo=values.get("memo") or "",
                    owner=codername,
                )
                fid_map[values["id"]] = source.id
                existing.add(name)
                counts["sources"] += 1

        # -- categories --------------------------------------------------
        cat_map: dict[int, int] = {}
        if "codecat" in tables_present:
            cols = await _columns(src, "codecat")
            id_col = "catid" if "catid" in cols else ("id" if "id" in cols else None)
            name_col = "catname" if "catname" in cols else ("name" if "name" in cols else None)
            parent_col = "parent" if "parent" in cols else None
            if id_col and name_col:
                existing = await _existing_names(session, tables.code_cat, "name")
                for rqda_id, name in await _fetch(
                    src, f"SELECT {id_col}, {name_col} FROM codecat"
                ):
                    if not name or name in existing:
                        continue
                    category = await code_repo.add_category(name=name, owner=codername)
                    if category is not None:
                        cat_map[rqda_id] = category.catid
                        existing.add(name)
                        counts["categories"] += 1
                if parent_col:
                    for rqda_id, parent_id in await _fetch(
                        src, f"SELECT {id_col}, {parent_col} FROM codecat"
                    ):
                        new_catid = cat_map.get(rqda_id)
                        parent_catid = cat_map.get(parent_id)
                        if (
                            new_catid is not None
                            and parent_catid is not None
                            and new_catid != parent_catid
                        ):
                            await session.execute(
                                update(tables.code_cat)
                                .where(tables.code_cat.c.catid == new_catid)
                                .values(supercatid=parent_catid)
                            )
                    await session.commit()

        # -- codes -------------------------------------------------------
        code_map: dict[int, int] = {}
        if "freecode" in tables_present:
            cols = await _columns(src, "freecode")
            id_col = "id" if "id" in cols else ("cid" if "cid" in cols else None)
            name_col = "name" if "name" in cols else None
            color_col = "color" if "color" in cols else None
            category_col = "category" if "category" in cols else None
            if id_col and name_col:
                tree: dict[int, int] = {}
                if "treecode" in tables_present:
                    tcols = await _columns(src, "treecode")
                    if {"cid", "catid"} <= tcols:
                        tree = {r[0]: r[1] for r in await _fetch(src, "SELECT cid, catid FROM treecode")}
                pick = _pick(cols, id_col, name_col, color_col, category_col)
                existing = await _existing_names(session, tables.code_name, "name")
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM freecode"):
                    values = dict(zip(pick, row, strict=True))
                    name = values[name_col]
                    if not name or name in existing:
                        continue
                    catid = None
                    if category_col is not None:
                        raw_catid = values.get(category_col)
                        if raw_catid is not None:
                            catid = cat_map.get(raw_catid)
                    if catid is None:
                        tree_catid = tree.get(values[id_col])
                        if tree_catid is not None:
                            catid = cat_map.get(tree_catid)
                    code = await code_repo.add_code(
                        name=name,
                        owner=codername,
                        catid=catid,
                        color=values.get(color_col) if color_col is not None else None,
                    )
                    if code is not None:
                        code_map[values[id_col]] = code.cid
                        existing.add(name)
                        counts["codes"] += 1

        # -- codings -----------------------------------------------------
        for table in ("coding", "coding2"):
            if table not in tables_present:
                continue
            cols = await _columns(src, table)
            cid_col = "cid" if "cid" in cols else None
            fid_col = "fid" if "fid" in cols else None
            sel_col = "seltext" if "seltext" in cols else None
            pos0_col = "selfirst" if "selfirst" in cols else ("pos0" if "pos0" in cols else None)
            pos1_col = "selend" if "selend" in cols else ("pos1" if "pos1" in cols else None)
            if not {cid_col, fid_col, sel_col, pos0_col, pos1_col} <= cols:
                continue
            rows = await _fetch(
                src,
                f"SELECT {cid_col}, {fid_col}, {sel_col}, {pos0_col}, {pos1_col} FROM {table}",
            )
            for cid, fid, seltext, pos0, pos1 in rows:
                if not seltext:
                    continue
                new_cid = code_map.get(cid)
                new_fid = fid_map.get(fid)
                if new_cid is None or new_fid is None:
                    continue
                try:
                    await coding_repo.add_text_coding(
                        cid=new_cid,
                        fid=new_fid,
                        seltext=seltext,
                        pos0=int(pos0 or 0),
                        pos1=int(pos1 or 0),
                        owner=codername,
                    )
                    counts["codings"] += 1
                except IntegrityError:
                    await session.rollback()

        # -- cases -------------------------------------------------------
        case_map: dict[int, int] = {}
        case_tables = [t for t in ("cases", "casename") if t in tables_present]
        if case_tables:
            table = case_tables[0]
            cols = await _columns(src, table)
            id_col = "id" if "id" in cols else ("caseid" if "caseid" in cols else None)
            name_col = "name" if "name" in cols else None
            if id_col and name_col:
                existing = await _existing_names(session, tables.cases, "name")
                for rqda_id, name in await _fetch(
                    src, f"SELECT {id_col}, {name_col} FROM {table}"
                ):
                    if not name or name in existing:
                        continue
                    case = await case_repo.add_case(name=name, owner=codername)
                    if case is not None:
                        case_map[rqda_id] = case.caseid
                        existing.add(name)
                        counts["cases"] += 1

        # -- case-file links ---------------------------------------------
        if "caselinkage" in tables_present:
            cols = await _columns(src, "caselinkage")
            caseid_col = "caseid" if "caseid" in cols else None
            fid_col = "fid" if "fid" in cols else None
            pos0_col = "selfirst" if "selfirst" in cols else ("pos0" if "pos0" in cols else None)
            pos1_col = "selend" if "selend" in cols else ("pos1" if "pos1" in cols else None)
            if caseid_col and fid_col:
                pick = _pick(cols, caseid_col, fid_col, pos0_col, pos1_col)
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM caselinkage"):
                    values = dict(zip(pick, row, strict=True))
                    new_caseid = case_map.get(values[caseid_col])
                    new_fid = fid_map.get(values[fid_col])
                    if new_caseid is None or new_fid is None:
                        continue
                    if pos0_col and pos1_col:
                        await case_repo.link_text_span(
                            caseid=new_caseid,
                            fid=new_fid,
                            pos0=int(values[pos0_col] or 0),
                            pos1=int(values[pos1_col] or 0),
                            owner=codername,
                        )
                    else:
                        await case_repo.link_file(caseid=new_caseid, fid=new_fid, owner=codername)

        # -- attribute types & values ------------------------------------
        if "caseAttr" in tables_present:
            case_attr_names = {
                r[0] for r in await _fetch(src, "SELECT DISTINCT variable FROM caseAttr")
            }
        else:
            case_attr_names = set()
        if "attributes" in tables_present:
            cols = await _columns(src, "attributes")
            name_col = "name" if "name" in cols else ("variable" if "variable" in cols else None)
            class_col = "class" if "class" in cols else None
            if name_col:
                pick = _pick(cols, name_col, class_col)
                existing = await _existing_names(session, tables.attribute_type, "name")
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM attributes"):
                    values = dict(zip(pick, row, strict=True))
                    if not values[name_col] or values[name_col] in existing:
                        continue
                    await attr_repo.add_type(
                        name=values[name_col],
                        owner=codername,
                        case_or_file="case" if values[name_col] in case_attr_names else "file",
                        value_type={"character": "text", "numeric": "number"}.get(
                            values.get(class_col or "") or "", "text"
                        ),
                    )
                    existing.add(values[name_col])
        if "caseAttr" in tables_present:
            cols = await _columns(src, "caseAttr")
            variable_col = (
                "variable" if "variable" in cols else ("name" if "name" in cols else None)
            )
            caseid_col = "caseID" if "caseID" in cols else ("caseid" if "caseid" in cols else None)
            if variable_col and caseid_col:
                for variable, value, rqda_caseid in await _fetch(
                    src, f"SELECT {variable_col}, value, {caseid_col} FROM caseAttr"
                ):
                    new_caseid = case_map.get(rqda_caseid)
                    if not variable or new_caseid is None:
                        continue
                    await attr_repo.set_value(
                        name=variable,
                        attr_type="case",
                        value=value or "",
                        entity_id=new_caseid,
                        owner=codername,
                    )
                    counts["attributes"] += 1
        if "fileAttr" in tables_present:
            cols = await _columns(src, "fileAttr")
            variable_col = (
                "variable" if "variable" in cols else ("name" if "name" in cols else None)
            )
            fileid_col = "fileID" if "fileID" in cols else ("fid" if "fid" in cols else None)
            if variable_col and fileid_col:
                for variable, value, rqda_fid in await _fetch(
                    src, f"SELECT {variable_col}, value, {fileid_col} FROM fileAttr"
                ):
                    new_fid = fid_map.get(rqda_fid)
                    if not variable or new_fid is None:
                        continue
                    await attr_repo.set_value(
                        name=variable,
                        attr_type="file",
                        value=value or "",
                        entity_id=new_fid,
                        owner=codername,
                    )
                    counts["attributes"] += 1

    message = (
        f"RQDA import complete: {counts['sources']} sources, "
        f"{counts['categories']} categories, {counts['codes']} codes, "
        f"{counts['codings']} codings, {counts['cases']} cases, "
        f"{counts['attributes']} attribute values"
    )
    return {"ok": True, "message": message, **counts}


# ----------------------------------------------------------------------
# Taguette
# ----------------------------------------------------------------------

def _html_to_plain_text(raw_html: str) -> str:
    """Clean Taguette HTML content to flat plain text (ported from legacy)."""
    if not raw_html:
        return ""
    text = raw_html.replace("\r\n", "\n")
    text = re.sub(r"</?(p|br|div|li|ul|ol|h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<.*?>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _find_best_match(
    clean_doc: str, snippet_html: str, original_start: int, original_end: int
) -> tuple[int, int, str]:
    """Locate the highlighted snippet inside the cleaned document (ported from legacy)."""
    clean_snip = _html_to_plain_text(snippet_html).strip()
    if not clean_snip:
        safe_start = min(max(0, original_start), len(clean_doc))
        safe_end = min(max(0, original_end), len(clean_doc))
        return safe_start, safe_end, clean_doc[safe_start:safe_end]
    matches = [m.start() for m in re.finditer(re.escape(clean_snip), clean_doc)]
    if matches:
        best = min(matches, key=lambda x: abs(x - original_start))
        return best, best + len(clean_snip), clean_snip
    words = clean_snip.split()
    if words:
        regex_snip = r"\s+".join(re.escape(w) for w in words)
        flex_matches = [(m.start(), m.end()) for m in re.finditer(regex_snip, clean_doc)]
        if flex_matches:
            best_match = min(flex_matches, key=lambda x: abs(x[0] - original_start))
            return best_match[0], best_match[1], clean_doc[best_match[0]:best_match[1]]
    safe_start = min(max(0, original_start), len(clean_doc))
    safe_end = min(max(0, original_end), len(clean_doc))
    return safe_start, safe_end, clean_doc[safe_start:safe_end]


async def import_taguette(
    session_factory: async_sessionmaker, taguette_path: str, codername: str
) -> dict:
    """Import a Taguette ``.taguette.sqlite3`` database into the open project.

    Documents (``documents`` table; ``name`` or ``title`` column, HTML
    ``contents``) become sources with cleaned plain text; ``tags`` become
    codes (``path`` or ``name``, ``color`` when present, else the legacy
    yellow-green); highlights — joined through ``highlight_tags`` or read
    directly via a ``tag`` column — become text codings whose positions are
    re-anchored into the cleaned text with the legacy best-match logic.
    Raises ``ValueError`` when the file is not a Taguette database.
    """
    try:
        async with aiosqlite.connect(taguette_path) as src:
            return await _import_taguette(src, session_factory, codername)
    except sqlite3.Error as err:
        raise ValueError(f"Invalid Taguette file: {err}") from err


async def _import_taguette(src: aiosqlite.Connection, session_factory, codername: str) -> dict:
    counts: dict[str, int] = {"codes": 0, "sources": 0, "codings": 0}
    tables_present = await _table_names(src)
    if not {"documents", "tags", "highlights"} <= tables_present:
        raise ValueError("Not a Taguette database")

    async with session_factory() as session:
        source_repo = SourceRepository(session)
        code_repo = CodeRepository(session)
        coding_repo = CodingRepository(session)

        # -- documents -> sources ---------------------------------------
        doc_cols = await _columns(src, "documents")
        name_col = "name" if "name" in doc_cols else ("title" if "title" in doc_cols else None)
        text_col = "contents" if "contents" in doc_cols else None
        memo_col = "description" if "description" in doc_cols else None
        fid_map: dict[int, int] = {}
        clean_by_doc: dict[int, str] = {}
        existing = await _existing_names(session, tables.source, "name")
        if name_col and "id" in doc_cols:
            pick = _pick(doc_cols, "id", name_col, memo_col, text_col)
            for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM documents"):
                values = dict(zip(pick, row, strict=True))
                name = values[name_col]
                clean_text = _html_to_plain_text(values.get(text_col or "") or "")
                clean_by_doc[values["id"]] = clean_text
                if not name or name in existing:
                    continue
                source = await source_repo.add_source(
                    name=name,
                    mediapath=None,
                    fulltext=clean_text,
                    memo=values.get(memo_col or "") or "",
                    owner=codername,
                )
                fid_map[values["id"]] = source.id
                existing.add(name)
                counts["sources"] += 1

        # -- highlights (raw, anchored after codes are mapped) ------------
        hcols = await _columns(src, "highlights")
        doc_col = (
            "document_id" if "document_id" in hcols else ("document" if "document" in hcols else None)
        )
        start_col = "start_offset" if "start_offset" in hcols else ("start" if "start" in hcols else None)
        end_col = "end_offset" if "end_offset" in hcols else ("end" if "end" in hcols else None)
        snippet_col = "snippet" if "snippet" in hcols else ("text" if "text" in hcols else None)
        raw_codings: list[tuple[int, int, int, int, str]] = []
        if doc_col and start_col and end_col and snippet_col:
            if "highlight_tags" in tables_present:
                rows = await _fetch(
                    src,
                    f"SELECT h.{doc_col}, ht.tag_id, h.{start_col}, h.{end_col}, h.{snippet_col} "
                    "FROM highlights h JOIN highlight_tags ht ON h.id = ht.highlight_id",
                )
            elif "tag" in hcols:
                rows = await _fetch(
                    src,
                    f"SELECT {doc_col}, tag, {start_col}, {end_col}, {snippet_col} FROM highlights",
                )
            else:
                rows = []
            for doc_id, tag_id, start, end, snippet in rows:
                raw_codings.append((doc_id, tag_id, start, end, snippet))
        codings_by_doc: dict[int, list[tuple[int, int, int, str]]] = {}
        for doc_id, tag_id, start, end, snippet in raw_codings:
            codings_by_doc.setdefault(doc_id, []).append((tag_id, start, end, snippet))

        # -- tags -> codes ------------------------------------------------
        tag_cols = await _columns(src, "tags")
        name_col = "name" if "name" in tag_cols else ("path" if "path" in tag_cols else None)
        color_col = "color" if "color" in tag_cols else None
        memo_col = "description" if "description" in tag_cols else None
        code_map: dict[int, int] = {}
        if name_col and "id" in tag_cols:
            pick = _pick(tag_cols, "id", name_col, memo_col, color_col)
            existing = await _existing_names(session, tables.code_name, "name")
            for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM tags"):
                values = dict(zip(pick, row, strict=True))
                name = values[name_col]
                if not name or name in existing:
                    continue
                code = await code_repo.add_code(
                    name=name,
                    owner=codername,
                    color=values.get(color_col or "") or "#DDE600",
                    memo=values.get(memo_col or "") or "",
                )
                if code is not None:
                    code_map[values["id"]] = code.cid
                    existing.add(name)
                    counts["codes"] += 1

        # -- codings ------------------------------------------------------
        for doc_id, coding_list in codings_by_doc.items():
            new_fid = fid_map.get(doc_id)
            clean_text = clean_by_doc.get(doc_id, "")
            if new_fid is None:
                continue
            for tag_id, start, end, snippet in coding_list:
                new_cid = code_map.get(tag_id)
                if new_cid is None:
                    continue
                pos0, pos1, seltext = _find_best_match(
                    clean_text, snippet, int(start or 0), int(end or 0)
                )
                try:
                    await coding_repo.add_text_coding(
                        cid=new_cid,
                        fid=new_fid,
                        seltext=seltext,
                        pos0=pos0,
                        pos1=pos1,
                        owner=codername,
                    )
                    counts["codings"] += 1
                except IntegrityError:
                    await session.rollback()

    message = (
        f"Taguette import complete: {counts['sources']} sources, "
        f"{counts['codes']} codes, {counts['codings']} codings"
    )
    return {"ok": True, "message": message, **counts}


# ----------------------------------------------------------------------
# RIS
# ----------------------------------------------------------------------

async def import_ris(session_factory: async_sessionmaker, ris_path: str, codername: str) -> dict:
    """Import a .ris bibliography file into the ``ris`` table.

    Each RIS record becomes one ``risid``; every tag occurrence becomes a
    ``ris`` row (risid, tag, longtag, value) using the ``rispy`` tag mapping.
    ``codername`` is accepted for signature symmetry only (RIS rows carry no
    owner column). The ``ris`` table has no unique constraint, so rows are
    inserted as-is: ``references`` counts the tag rows inserted and
    ``entries`` the RIS records.
    """
    longtag_to_tag = {v: k for k, v in rispy.TAG_KEY_MAPPING.items()}
    with open(ris_path, encoding="utf-8", errors="surrogateescape") as ris_file:  # noqa: ASYNC230 - small local text read
        entries = rispy.load(ris_file)

    inserted = 0
    async with session_factory() as session:
        row = (await session.execute(select(func.max(tables.ris.c.risid)))).first()
        max_risid = row[0] if row is not None and row[0] is not None else 0
        for entry in entries:
            entry.pop("id", None)
            max_risid += 1
            for longtag, value in entry.items():
                if isinstance(value, list):
                    data = "; ".join(str(v) for v in value if v is not None)
                elif value is None:
                    continue
                else:
                    data = str(value)
                await session.execute(
                    insert(tables.ris).values(
                        risid=max_risid,
                        tag=longtag_to_tag.get(longtag, longtag),
                        longtag=longtag,
                        value=data,
                    )
                )
                inserted += 1
        await session.commit()
    return {
        "ok": True,
        "message": f"Imported {len(entries)} references ({inserted} tag rows)",
        "references": inserted,
        "entries": len(entries),
    }


# ----------------------------------------------------------------------
# Survey CSV
# ----------------------------------------------------------------------

async def import_survey(
    session_factory: async_sessionmaker,
    csv_path: str,
    codername: str,
    qualitative_headers: list[str] | None = None,
) -> dict:
    """Import a survey CSV: one row = one case, columns = case attributes.

    ``qualitative_headers`` names the columns whose free text becomes one
    text file per row (``<case name>_<field>``), linked to the case and
    coded with a code named after the field (upstream survey importer).
    The CSV is read as UTF-8 (BOM tolerated) and a ``;`` delimiter is
    accepted when ``,`` yields single-column rows.
    """
    raw = Path(csv_path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("utf-8")

    try:
        rows = [
            row for row in csv.reader(io.StringIO(text)) if any(cell.strip() for cell in row)
        ]
        if rows and all(len(row) == 1 for row in rows):
            rows = [
                row
                for row in csv.reader(io.StringIO(text), delimiter=";")
                if any(cell.strip() for cell in row)
            ]
    except csv.Error as err:
        raise ValueError(f"Invalid survey CSV: {err}") from err

    if not rows:
        return {"ok": True, "message": "Survey CSV is empty", "cases": 0, "attributes": 0,
                "qualitative_files": 0, "qualitative_codings": 0}
    headers = [h.strip() for h in rows[0]]
    data = rows[1:]
    qualitative = {h for h in (qualitative_headers or []) if h in headers}

    from qualcoder_api.services import pseudonyms

    cases = 0
    attributes = 0
    qualitative_files = 0
    qualitative_codings = 0
    async with session_factory() as session:
        case_repo = CaseRepository(session)
        attr_repo = AttributeRepository(session)
        source_repo = SourceRepository(session)
        code_repo = CodeRepository(session)
        coding_repo = CodingRepository(session)

        existing_types = await _existing_names(session, tables.attribute_type, "name")
        for header in headers[1:]:
            if header and header not in qualitative and header not in existing_types:
                await attr_repo.add_type(
                    name=header, owner=codername, case_or_file="case", value_type="text"
                )
                existing_types.add(header)

        # Qualitative column codes (one code per column, gray, no category).
        existing_codes = await _existing_names(session, tables.code_name, "name")
        qual_cid: dict[str, int] = {}
        for header in qualitative:
            if header not in existing_codes:
                code = await code_repo.add_code(
                    name=header, owner=codername, color="#B8B8B8"
                )
                if code is not None:
                    qual_cid[header] = code.cid
                    existing_codes.add(header)
            else:
                row = (
                    await session.execute(
                        select(tables.code_name.c.cid).where(tables.code_name.c.name == header)
                    )
                ).first()
                if row is not None:
                    qual_cid[header] = row[0]

        for row in data:
            name = row[0].strip() if row else ""
            if not name:
                continue
            existing = (
                await session.execute(
                    select(tables.cases.c.caseid).where(tables.cases.c.name == name)
                )
            ).first()
            if existing is not None:
                caseid = existing[0]
            else:
                case = await case_repo.add_case(name=name, owner=codername)
                if case is None:
                    continue
                caseid = case.caseid
                cases += 1
            for col, header in enumerate(headers[1:], start=1):
                if not header:
                    continue
                value = row[col].strip() if col < len(row) else ""
                if header in qualitative:
                    if not value:
                        continue
                    qual_name = f"{name}_{header}"
                    existing_file = (
                        await session.execute(
                            select(tables.source.c.id).where(tables.source.c.name == qual_name)
                        )
                    ).first()
                    fulltext = pseudonyms.apply_pseudonyms(value, str(Path(csv_path).parent))
                    if existing_file is not None:
                        fid = existing_file[0]
                    else:
                        source = await source_repo.add_source(
                            name=qual_name,
                            mediapath=None,
                            fulltext=fulltext,
                            memo="",
                            owner=codername,
                        )
                        fid = source.id
                        qualitative_files += 1
                        await case_repo.link_file(caseid=caseid, fid=fid, owner=codername)
                    cid = qual_cid.get(header)
                    if cid is not None:
                        try:
                            await coding_repo.add_text_coding(
                                cid=cid, fid=fid, seltext=fulltext,
                                pos0=0, pos1=max(0, len(fulltext) - 1),
                                owner=codername,
                            )
                            qualitative_codings += 1
                        except IntegrityError:
                            await session.rollback()
                else:
                    await attr_repo.set_value(
                        name=header, attr_type="case", value=value,
                        entity_id=caseid, owner=codername,
                    )
                    attributes += 1

    message = (
        f"Survey import complete: {cases} cases, {attributes} attribute values, "
        f"{qualitative_files} qualitative files, {qualitative_codings} qualitative codings"
    )
    return {
        "ok": True,
        "message": message,
        "cases": cases,
        "attributes": attributes,
        "qualitative_files": qualitative_files,
        "qualitative_codings": qualitative_codings,
    }
