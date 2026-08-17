"""RQDA importer — import a QualCoder v3 ``.rqda`` SQLite database."""

from __future__ import annotations

import sqlite3

import aiosqlite
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.interchange.importers.base import (
    _columns,
    _existing_names,
    _fetch,
    _pick,
    _table_names,
)
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import (
    AttributeRepository,
    CaseRepository,
    CodeRepository,
    CodingRepository,
    SourceRepository,
)


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
