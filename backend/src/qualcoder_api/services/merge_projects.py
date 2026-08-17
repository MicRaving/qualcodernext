"""Merge another QualCoder project into the open project (upstream port).

Copies categories, codes (with sub-code parents), sources, codings,
annotations, cases, case links, journals, stored SQL, attribute types and
values from a source ``data.qda`` into the destination database, and copies
the source project's media folders into the destination project folder.
Deduplication is by name; existing names are left untouched (codings of
existing same-named sources are imported under the existing ids).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import aiosqlite
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.core.palette import CODE_COLORS
from qualcoder_api.core.timeutil import now as _now
from qualcoder_api.persistence import tables

logger = logging.getLogger(__name__)


def _pick(cols: set[str], *candidates: str | None) -> list[str]:
    return [c for c in candidates if c is not None and c in cols]


async def _fetch(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
    cur = await db.execute(sql, params)
    return list(await cur.fetchall())


async def _columns(db: aiosqlite.Connection, table: str) -> set[str]:
    cur = await db.execute(f'PRAGMA table_info("{table}")')
    return {row[1] for row in await cur.fetchall()}


async def merge_projects(
    session_factory: async_sessionmaker,
    destination_path: str,
    source_path: str,
    codername: str,
) -> dict:
    """Merge the project at ``source_path`` into the open (destination) project.

    ``source_path`` is the project folder whose ``data.qda`` will be read.
    Raises ``ValueError`` when the source is not a QualCoder database.
    """
    if not (Path(source_path) / "data.qda").exists():
        raise ValueError("source project has no data.qda database")
    summary: list[str] = []
    try:
        async with aiosqlite.connect(str(Path(source_path) / "data.qda")) as src:
            tables_present = {
                row[0]
                for row in await _fetch(src, "SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "code_name" not in tables_present or "source" not in tables_present:
                raise ValueError("Not a QualCoder project database")
            return await _merge(src, tables_present, session_factory, destination_path, source_path, codername, summary)
    except aiosqlite.Error as err:
        raise ValueError(f"Invalid project database: {err}") from err


async def _merge(
    src: aiosqlite.Connection,
    tables_present: set[str],
    session_factory: async_sessionmaker,
    destination_path: str,
    source_path: str,
    codername: str,
    summary: list[str],
) -> dict:
    async with session_factory() as session:
        # Merged rows must reach collaborators: capture each insert/update
        # into sync_log exactly like every other mutation path does.
        from sqlalchemy import select as sa_select

        from qualcoder_api.persistence.repositories import _capture, _rowdict

        async def _capture_insert(entity: str, pk_name: str, pk_value, values: dict) -> None:
            table = getattr(tables, entity)
            row = (
                await session.execute(
                    sa_select(table).where(getattr(table.c, pk_name) == pk_value)
                )
            ).first()
            if row is not None:
                await _capture(session, entity, "insert", pk_name, pk_value, _rowdict(row))

        async def _capture_matched(entity: str, keys: list[str], values: dict) -> None:
            """Capture an OR IGNORE insert whose pk is unknown: look the row
            back up by its natural key."""
            table = getattr(tables, entity)
            pk_name = table.primary_key.columns.keys()[0]
            cond = [getattr(table.c, k) == values[k] for k in keys if k in values]
            if not cond:
                return
            row = (await session.execute(sa_select(table).where(*cond))).first()
            if row is not None:
                await _capture(
                    session, entity, "insert", pk_name, getattr(row, pk_name), _rowdict(row)
                )

        async def _capture_update_matched(entity: str, keys: list[str], values: dict) -> None:
            """Capture a merge UPDATE (e.g. attribute values) after the fact."""
            table = getattr(tables, entity)
            pk_name = table.primary_key.columns.keys()[0]
            cond = [getattr(table.c, k) == values[k] for k in keys if k in values]
            if not cond:
                return
            row = (await session.execute(sa_select(table).where(*cond))).first()
            if row is not None:
                await _capture(
                    session, entity, "update", pk_name, getattr(row, pk_name), _rowdict(row)
                )

        # ---- categories --------------------------------------------------
        cat_cols = await _columns(src, "code_cat") if "code_cat" in tables_present else set()
        cat_map: dict[int, int] = {}
        cats: list[dict] = []
        rows = await session.execute(text("SELECT name FROM code_cat"))
        existing_cats = {r[0] for r in rows}
        if "code_cat" in tables_present and {"catid", "name"} <= cat_cols:
            pick = _pick(cat_cols, "catid", "name", "memo", "owner", "date", "supercatid")
            cats = [
                dict(zip(pick, row, strict=True))
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM code_cat")
            ]
            for cat in cats:
                if cat["name"] in existing_cats:
                    row = await session.execute(
                        text("SELECT catid FROM code_cat WHERE name = :n"), {"n": cat["name"]}
                    )
                    first = row.first()
                    if first is not None:
                        cat_map[cat["catid"]] = first[0]
                    continue
                # resolve supercatid by name of the parent catid
                parent_name = None
                for other in cats:
                    if other["catid"] == cat.get("supercatid"):
                        parent_name = other["name"]
                        break
                supercatid = None
                if parent_name:
                    row = await session.execute(
                        text("SELECT catid FROM code_cat WHERE name = :n"), {"n": parent_name}
                    )
                    first = row.first()
                    if first is not None:
                        supercatid = first[0]
                await session.execute(
                    text(
                        "INSERT INTO code_cat (name, memo, owner, date, supercatid) "
                        "VALUES (:name, :memo, :owner, :date, :supercatid)"
                    ),
                    {
                        "name": cat["name"],
                        "memo": cat.get("memo") or "",
                        "owner": cat.get("owner") or codername,
                        "date": cat.get("date") or _now(),
                        "supercatid": supercatid,
                    },
                )
                row = await session.execute(
                    text("SELECT catid FROM code_cat WHERE name = :n"), {"n": cat["name"]}
                )
                cat_map[cat["catid"]] = row.first()[0]
                await _capture_insert(
                    "code_cat", "catid", cat_map[cat["catid"]],
                    {"name": cat["name"], "supercatid": supercatid},
                )
                existing_cats.add(cat["name"])
                summary.append(f"Adding category: {cat['name']}")
        await session.commit()

        # ---- codes --------------------------------------------------------
        code_cols = await _columns(src, "code_name") if "code_name" in tables_present else set()
        code_map: dict[int, int] = {}
        rows = await session.execute(text("SELECT name FROM code_name"))
        existing_codes = {r[0] for r in rows}
        if "code_name" in tables_present and {"cid", "name"} <= code_cols:
            pick = _pick(code_cols, "cid", "name", "memo", "owner", "date", "catid", "color", "supercid")
            codes = [
                dict(zip(pick, row, strict=True))
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM code_name")
            ]
            catid_by_name = {
                name: catid for catid, name in await session.execute(text("SELECT catid, name FROM code_cat"))
            }
            # ``cats`` is always defined (possibly empty when the source has
            # code_name but no code_cat).
            src_cats: list[dict] = cats
            name_to_cid: dict[str, int] = {}
            for code in codes:
                if code["name"] in existing_codes:
                    row = await session.execute(
                        text("SELECT cid FROM code_name WHERE name = :n"), {"n": code["name"]}
                    )
                    first = row.first()
                    if first is not None:
                        name_to_cid[code["name"]] = first[0]
                        # Map the source cid too, so the source project's
                        # codings for this already-existing code are merged
                        # instead of dropped.
                        code_map[code["cid"]] = first[0]
                    continue
                catid = None
                if code.get("catid") is not None:
                    src_cat = next((c for c in src_cats if c["catid"] == code["catid"]), None)
                    if src_cat is not None:
                        catid = catid_by_name.get(src_cat["name"])
                await session.execute(
                    text(
                        "INSERT INTO code_name (name, memo, owner, date, catid, color) "
                        "VALUES (:name, :memo, :owner, :date, :catid, :color)"
                    ),
                    {
                        "name": code["name"],
                        "memo": code.get("memo") or "",
                        "owner": code.get("owner") or codername,
                        "date": code.get("date") or _now(),
                        "catid": catid,
                        "color": code.get("color") or CODE_COLORS[0],
                    },
                )
                row = await session.execute(
                    text("SELECT cid FROM code_name WHERE name = :n"), {"n": code["name"]}
                )
                new_cid = row.first()[0]
                await _capture_insert(
                    "code_name", "cid", new_cid,
                    {"name": code["name"], "catid": catid, "supercid": code.get("supercid")},
                )
                code_map[code["cid"]] = new_cid
                name_to_cid[code["name"]] = new_cid
                existing_codes.add(code["name"])
                summary.append(f"Adding code: {code['name']}")
            # Resolve sub-code parents by name.
            if "supercid" in code_cols:
                for code in codes:
                    if code["name"] not in name_to_cid:
                        continue
                    parent_cid = code.get("supercid")
                    parent = next((c for c in codes if c["cid"] == parent_cid), None)
                    if parent is None or parent["name"] not in name_to_cid:
                        continue
                    await session.execute(
                        text(
                            "UPDATE code_name SET supercid = :sup, catid = NULL WHERE cid = :cid"
                        ),
                        {"sup": name_to_cid[parent["name"]], "cid": name_to_cid[code["name"]]},
                    )
                    updated = (
                        await session.execute(
                            sa_select(tables.code_name).where(
                                tables.code_name.c.cid == name_to_cid[code["name"]]
                            )
                        )
                    ).first()
                    if updated is not None:
                        await _capture(
                            session, "code_name", "update", "cid",
                            name_to_cid[code["name"]], _rowdict(updated),
                        )
            await session.commit()

        # ---- sources ------------------------------------------------------
        src_cols = await _columns(src, "source") if "source" in tables_present else set()
        source_map: dict[int, int] = {}
        if "source" in tables_present and {"id", "name"} <= src_cols:
            pick = _pick(src_cols, "id", "name", "fulltext", "mediapath", "memo", "owner", "date", "av_text_id")
            sources = [
                dict(zip(pick, row, strict=True))
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM source")
            ]
            for source in sources:
                row = await session.execute(
                    text("SELECT id, length(fulltext) FROM source WHERE name = :n"),
                    {"n": source["name"]},
                )
                existing = row.first()
                if existing is not None:
                    source_map[source["id"]] = existing[0]
                    if (source.get("fulltext") is not None and existing[1] is not None
                            and len(source["fulltext"]) != existing[1]):
                        summary.append(
                            f"Warning: text lengths differ for same file {source['name']} "
                            "- coding positions may be inaccurate"
                        )
                    continue
                await session.execute(
                    text(
                        "INSERT INTO source (name, fulltext, mediapath, memo, owner, date) "
                        "VALUES (:name, :fulltext, :mediapath, :memo, :owner, :date)"
                    ),
                    {
                        "name": source["name"],
                        "fulltext": source.get("fulltext"),
                        "mediapath": source.get("mediapath"),
                        "memo": source.get("memo") or "",
                        "owner": source.get("owner") or codername,
                        "date": source.get("date") or _now(),
                    },
                )
                row = await session.execute(
                    text("SELECT id FROM source WHERE name = :n"), {"n": source["name"]}
                )
                new_id = row.first()[0]
                source_map[source["id"]] = new_id
                await _capture_insert(
                    "source", "id", new_id,
                    {"name": source["name"], "mediapath": source.get("mediapath")},
                )
                summary.append(f"Adding file: {source['name']}")
                # Attribute placeholders for destination file attributes.
                attr_rows = await session.execute(
                    text("SELECT name FROM attribute_type WHERE caseOrFile = 'file'")
                )
                for (attr_name,) in attr_rows:
                    await session.execute(
                        text(
                            "INSERT INTO attribute (name, attr_type, value, id, date, owner) "
                            "VALUES (:n, 'file', '', :id, :d, :o)"
                        ),
                        {"n": attr_name, "id": new_id, "d": _now(), "o": codername},
                    )
                    await _capture_matched(
                        "attribute", ["name", "attr_type", "id"],
                        {"name": attr_name, "attr_type": "file", "id": new_id},
                    )
            # av_text_id linking by transcript filename.
            if "av_text_id" in src_cols:
                for source in sources:
                    if source.get("av_text_id") is None:
                        continue
                    transcript = next(
                        (s for s in sources if s["id"] == source["av_text_id"]), None
                    )
                    if transcript is None:
                        continue
                    row = await session.execute(
                        text("SELECT id FROM source WHERE name = :n"), {"n": transcript["name"]}
                    )
                    first = row.first()
                    if first is not None:
                        await session.execute(
                            text("UPDATE source SET av_text_id = :t WHERE id = :id"),
                            {"t": first[0], "id": source_map.get(source["id"])},
                        )
                        media_after = (
                            await session.execute(
                                sa_select(tables.source).where(
                                    tables.source.c.id == source_map.get(source["id"])
                                )
                            )
                        ).first()
                        if media_after is not None:
                            await _capture(
                                session, "source", "update", "id",
                                source_map.get(source["id"]), _rowdict(media_after),
                            )
            await session.commit()

        # ---- codings / annotations / journals / stored sql ---------------
        if "code_text" in tables_present:
            ct_cols = await _columns(src, "code_text")
            pick = _pick(ct_cols, "cid", "fid", "seltext", "pos0", "pos1", "owner", "memo", "date", "important")
            if {"cid", "fid", "seltext", "pos0", "pos1"} <= ct_cols:
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM code_text"):
                    values = dict(zip(pick, row, strict=True))
                    new_cid = code_map.get(values["cid"])
                    new_fid = source_map.get(values["fid"])
                    if new_cid is None or new_fid is None:
                        continue
                    try:
                        await session.execute(
                            text(
                                "INSERT OR IGNORE INTO code_text (cid, fid, seltext, pos0, pos1, "
                                "owner, memo, date, important) VALUES (:cid, :fid, :seltext, :pos0, "
                                ":pos1, :owner, :memo, :date, :important)"
                            ),
                            {
                                "cid": new_cid, "fid": new_fid, "seltext": values["seltext"],
                                "pos0": values["pos0"], "pos1": values["pos1"],
                                "owner": values.get("owner") or codername,
                                "memo": values.get("memo") or "",
                                "date": values.get("date") or _now(),
                                "important": values.get("important") or 0,
                            },
                        )
                        await _capture_matched(
                            "code_text", ["cid", "fid", "pos0", "pos1", "owner"],
                            {"cid": new_cid, "fid": new_fid, "pos0": values["pos0"],
                             "pos1": values["pos1"], "owner": values.get("owner") or codername},
                        )
                    except Exception as err:
                        logger.debug("merge code_text: %s", err)
        if "annotation" in tables_present:
            an_cols = await _columns(src, "annotation")
            pick = _pick(an_cols, "fid", "pos0", "pos1", "memo", "owner", "date")
            if {"fid", "pos0", "pos1"} <= an_cols:
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM annotation"):
                    values = dict(zip(pick, row, strict=True))
                    new_fid = source_map.get(values["fid"])
                    if new_fid is None:
                        continue
                    try:
                        await session.execute(
                            text(
                                "INSERT OR IGNORE INTO annotation (fid, pos0, pos1, memo, owner, date) "
                                "VALUES (:fid, :pos0, :pos1, :memo, :owner, :date)"
                            ),
                            {
                                "fid": new_fid, "pos0": values["pos0"], "pos1": values["pos1"],
                                "memo": values.get("memo") or "",
                                "owner": values.get("owner") or codername,
                                "date": values.get("date") or _now(),
                            },
                        )
                        await _capture_matched(
                            "annotation", ["fid", "pos0", "pos1"],
                            {"fid": new_fid, "pos0": values["pos0"], "pos1": values["pos1"]},
                        )
                    except Exception as err:
                        logger.debug("merge annotation: %s", err)
        if "code_image" in tables_present:
            ci_cols = await _columns(src, "code_image")
            pick = _pick(ci_cols, "cid", "id", "x1", "y1", "width", "height", "memo", "owner", "date", "important", "pdf_page")
            if {"cid", "id", "x1", "y1", "width", "height"} <= ci_cols:
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM code_image"):
                    values = dict(zip(pick, row, strict=True))
                    new_cid = code_map.get(values["cid"])
                    new_fid = source_map.get(values["id"])
                    if new_cid is None or new_fid is None:
                        continue
                    try:
                        await session.execute(
                            text(
                                "INSERT OR IGNORE INTO code_image (cid, id, x1, y1, width, height, "
                                "memo, owner, date, important, pdf_page) VALUES (:cid, :id, :x1, :y1, "
                                ":width, :height, :memo, :owner, :date, :important, :pdf_page)"
                            ),
                            {
                                "cid": new_cid, "id": new_fid, "x1": values["x1"], "y1": values["y1"],
                                "width": values["width"], "height": values["height"],
                                "memo": values.get("memo") or "", "owner": values.get("owner") or codername,
                                "date": values.get("date") or _now(),
                                "important": values.get("important") or 0,
                                "pdf_page": values.get("pdf_page"),
                            },
                        )
                        await _capture_matched(
                            "code_image", ["cid", "id", "x1", "y1", "width", "height"],
                            {"cid": new_cid, "id": new_fid, "x1": values["x1"], "y1": values["y1"],
                             "width": values["width"], "height": values["height"]},
                        )
                    except Exception as err:
                        logger.debug("merge code_image: %s", err)
        if "code_av" in tables_present:
            ca_cols = await _columns(src, "code_av")
            pick = _pick(ca_cols, "cid", "id", "pos0", "pos1", "memo", "owner", "date", "important")
            if {"cid", "id", "pos0", "pos1"} <= ca_cols:
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM code_av"):
                    values = dict(zip(pick, row, strict=True))
                    new_cid = code_map.get(values["cid"])
                    new_fid = source_map.get(values["id"])
                    if new_cid is None or new_fid is None:
                        continue
                    try:
                        await session.execute(
                            text(
                                "INSERT OR IGNORE INTO code_av (cid, id, pos0, pos1, memo, owner, date, "
                                "important) VALUES (:cid, :id, :pos0, :pos1, :memo, :owner, :date, :important)"
                            ),
                            {
                                "cid": new_cid, "id": new_fid, "pos0": values["pos0"], "pos1": values["pos1"],
                                "memo": values.get("memo") or "", "owner": values.get("owner") or codername,
                                "date": values.get("date") or _now(), "important": values.get("important") or 0,
                            },
                        )
                        await _capture_matched(
                            "code_av", ["cid", "id", "pos0", "pos1"],
                            {"cid": new_cid, "id": new_fid, "pos0": values["pos0"], "pos1": values["pos1"]},
                        )
                    except Exception as err:
                        logger.debug("merge code_av: %s", err)
        if "journal" in tables_present:
            jo_cols = await _columns(src, "journal")
            pick = _pick(jo_cols, "name", "jentry", "date", "owner")
            if "name" in jo_cols:
                rows = await session.execute(text("SELECT name FROM journal"))
                existing = {r[0] for r in rows}
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM journal"):
                    values = dict(zip(pick, row, strict=True))
                    if values["name"] in existing:
                        continue
                    await session.execute(
                        text(
                            "INSERT INTO journal (name, jentry, date, owner) VALUES (:name, :jentry, :date, :owner)"
                        ),
                        {
                            "name": values["name"],
                            "jentry": values.get("jentry") or "",
                            "date": values.get("date") or _now(),
                            "owner": values.get("owner") or codername,
                        },
                    )
                    existing.add(values["name"])
        if "stored_sql" in tables_present:
            sq_cols = await _columns(src, "stored_sql")
            pick = _pick(sq_cols, "title", "description", "grouper", "ssql")
            if "title" in sq_cols:
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM stored_sql"):
                    values = dict(zip(pick, row, strict=True))
                    try:
                        await session.execute(
                            text(
                                "INSERT OR IGNORE INTO stored_sql (title, description, grouper, ssql) "
                                "VALUES (:title, :description, :grouper, :ssql)"
                            ),
                            {
                                "title": values["title"],
                                "description": values.get("description") or "",
                                "grouper": values.get("grouper") or "",
                                "ssql": values.get("ssql") or "",
                            },
                        )
                        await _capture_matched(
                            "stored_sql", ["title"], {"title": values["title"]}
                        )
                    except Exception as err:
                        logger.debug("merge stored_sql: %s", err)
        await session.commit()

        # ---- cases --------------------------------------------------------
        case_map: dict[int, int] = {}
        if "cases" in tables_present:
            cs_cols = await _columns(src, "cases")
            pick = _pick(cs_cols, "caseid", "name", "memo", "owner", "date")
            if {"caseid", "name"} <= cs_cols:
                rows = await session.execute(text("SELECT name FROM cases"))
                existing = {r[0] for r in rows}
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM cases"):
                    values = dict(zip(pick, row, strict=True))
                    if values["name"] in existing:
                        continue
                    await session.execute(
                        text(
                            "INSERT INTO cases (name, memo, owner, date) VALUES (:name, :memo, :owner, :date)"
                        ),
                        {
                            "name": values["name"],
                            "memo": values.get("memo") or "",
                            "owner": values.get("owner") or codername,
                            "date": values.get("date") or _now(),
                        },
                    )
                    row = await session.execute(
                        text("SELECT caseid FROM cases WHERE name = :n"), {"n": values["name"]}
                    )
                    case_map[values["caseid"]] = row.first()[0]
                    await _capture_insert(
                        "cases", "caseid", case_map[values["caseid"]],
                        {"name": values["name"], "memo": values.get("memo") or ""},
                    )
                    existing.add(values["name"])
                    summary.append(f"Adding case: {values['name']}")
                    # Case attribute placeholders.
                    attr_rows = await session.execute(
                        text("SELECT name FROM attribute_type WHERE caseOrFile = 'case'")
                    )
                    for (attr_name,) in attr_rows:
                        await session.execute(
                            text(
                                "INSERT INTO attribute (name, attr_type, value, id, date, owner) "
                                "VALUES (:n, 'case', '', :id, :d, :o)"
                            ),
                            {
                                "n": attr_name,
                                "id": case_map[values["caseid"]],
                                "d": _now(),
                                "o": codername,
                            },
                        )
                        await _capture_matched(
                            "attribute", ["name", "attr_type", "id"],
                            {"name": attr_name, "attr_type": "case", "id": case_map[values["caseid"]]},
                        )
            if "case_text" in tables_present:
                ctxt_cols = await _columns(src, "case_text")
                pick = _pick(ctxt_cols, "caseid", "fid", "pos0", "pos1", "memo", "owner", "date")
                if {"caseid", "fid", "pos0", "pos1"} <= ctxt_cols:
                    for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM case_text"):
                        values = dict(zip(pick, row, strict=True))
                        new_caseid = case_map.get(values["caseid"])
                        new_fid = source_map.get(values["fid"])
                        if new_caseid is None or new_fid is None:
                            continue
                        try:
                            await session.execute(
                                text(
                                    "INSERT OR IGNORE INTO case_text (caseid, fid, pos0, pos1, memo, owner, date) "
                                    "VALUES (:caseid, :fid, :pos0, :pos1, :memo, :owner, :date)"
                                ),
                                {
                                    "caseid": new_caseid, "fid": new_fid,
                                    "pos0": values["pos0"], "pos1": values["pos1"],
                                    "memo": values.get("memo") or "",
                                    "owner": values.get("owner") or codername,
                                    "date": values.get("date") or _now(),
                                },
                            )
                            await _capture_matched(
                                "case_text", ["caseid", "fid", "pos0", "pos1"],
                                {"caseid": new_caseid, "fid": new_fid,
                                 "pos0": values["pos0"], "pos1": values["pos1"]},
                            )
                        except Exception as err:
                            logger.debug("merge case_text: %s", err)
        await session.commit()

        # ---- attribute types + values -------------------------------------
        if "attribute_type" in tables_present:
            at_cols = await _columns(src, "attribute_type")
            pick = _pick(at_cols, "name", "date", "owner", "memo", "caseOrFile", "valuetype")
            if "name" in at_cols:
                rows = await session.execute(text("SELECT name FROM attribute_type"))
                existing = {r[0] for r in rows}
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM attribute_type"):
                    values = dict(zip(pick, row, strict=True))
                    if values["name"] in existing:
                        continue
                    await session.execute(
                        text(
                            "INSERT INTO attribute_type (name, date, owner, memo, caseOrFile, valuetype) "
                            "VALUES (:name, :date, :owner, :memo, :caseOrFile, :valuetype)"
                        ),
                        {
                            "name": values["name"],
                            "date": values.get("date") or _now(),
                            "owner": values.get("owner") or codername,
                            "memo": values.get("memo") or "",
                            "caseOrFile": values.get("caseOrFile") or "case",
                            "valuetype": values.get("valuetype") or "text",
                        },
                    )
                    await _capture_matched(
                        "attribute_type", ["name"], {"name": values["name"]}
                    )
                    existing.add(values["name"])
        if "attribute" in tables_present:
            at_cols = await _columns(src, "attribute")
            pick = _pick(at_cols, "name", "attr_type", "value", "id", "date", "owner")
            if {"name", "attr_type", "value", "id"} <= at_cols:
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM attribute"):
                    values = dict(zip(pick, row, strict=True))
                    if values["attr_type"] == "file":
                        new_id = source_map.get(values["id"])
                    else:
                        new_id = case_map.get(values["id"])
                    if new_id is None:
                        continue
                    # Update only when the destination value is still a placeholder.
                    await session.execute(
                        text(
                            "UPDATE attribute SET value = :value WHERE name = :name "
                            "AND id = :id AND attr_type = :attr_type AND value = ''"
                        ),
                        {
                            "value": values["value"],
                            "name": values["name"],
                            "id": new_id,
                            "attr_type": values["attr_type"],
                        },
                    )
                    await _capture_update_matched(
                        "attribute", ["name", "attr_type", "id"],
                        {"name": values["name"], "attr_type": values["attr_type"], "id": new_id},
                    )
        await session.commit()

    # ---- media files -----------------------------------------------------
    copied = 0
    import asyncio

    for folder_name in ("audio", "documents", "images", "video"):
        source_dir = Path(source_path) / folder_name
        if not source_dir.is_dir():
            continue
        dest_dir = Path(destination_path) / folder_name
        for file_ in source_dir.iterdir():
            dest_path = dest_dir / file_.name
            if not dest_path.exists():
                try:
                    # Media copies can be large — keep them off the loop.
                    await asyncio.to_thread(shutil.copyfile, file_, dest_path)
                    copied += 1
                except (OSError, shutil.SameFileError) as err:
                    summary.append(f"{file_.name} NOT copied: {err}")
    if copied:
        summary.append(f"Files copied: {copied}")

    message = "\n".join(summary) if summary else "Nothing new to merge"
    return {
        "ok": True,
        "message": f"Project merged:\n{message}",
        "categories": sum(1 for s in summary if s.startswith("Adding category")),
        "codes": sum(1 for s in summary if s.startswith("Adding code")),
        "files": sum(1 for s in summary if s.startswith("Adding file")),
        "cases": sum(1 for s in summary if s.startswith("Adding case")),
        "files_copied": copied,
    }
