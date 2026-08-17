"""Graph item CRUD — add / update / delete for the five item kinds:
cdct, case, file, free, and memo nodes.
"""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.persistence import tables
from qualcoder_api.services.graph_base import (
    _capture_delete,
    _capture_row,
    _insert,
    _row_dict,
)


async def add_cdct_item(
    session: AsyncSession,
    grid: int,
    kind: str,
    ref_id: int,
    x: int,
    y: int,
    displaytext: str | None = None,
    font_size: int = 12,
    bold: int = 0,
    isvisible: int = 1,
) -> dict:
    """Add a category or code node (``kind`` in {"category", "code"})."""
    supercatid = catid = cid = None
    if kind == "category":
        catid = ref_id
        if displaytext is None:
            row = (
                await session.execute(
                    select(tables.code_cat.c.name).where(tables.code_cat.c.catid == ref_id)
                )
            ).first()
            displaytext = row[0] if row else f"Category {ref_id}"
    else:
        cid = ref_id
        if displaytext is None:
            row = (
                await session.execute(
                    select(tables.code_name.c.name).where(tables.code_name.c.cid == ref_id)
                )
            ).first()
            displaytext = row[0] if row else f"Code {ref_id}"
    gtextid = await _insert(
        session,
        tables.gr_cdct_text_item,
        {
            "grid": grid,
            "x": int(x),
            "y": int(y),
            "supercatid": supercatid,
            "catid": catid,
            "cid": cid,
            "font_size": font_size,
            "bold": bold,
            "isvisible": isvisible,
            "displaytext": displaytext or "",
        },
    )
    return {"gtextid": gtextid, "grid": grid, "kind": kind, "ref_id": ref_id,
            "x": int(x), "y": int(y), "displaytext": displaytext or "",
            "font_size": font_size, "bold": bold, "isvisible": isvisible}


async def update_cdct_item(session: AsyncSession, gtextid: int, **fields) -> dict | None:
    allowed = {"x", "y", "font_size", "bold", "isvisible", "displaytext"}
    values = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if values:
        await session.execute(
            update(tables.gr_cdct_text_item).where(tables.gr_cdct_text_item.c.gtextid == gtextid).values(**values)
        )
        await session.commit()
    row = (
        await session.execute(
            select(tables.gr_cdct_text_item).where(tables.gr_cdct_text_item.c.gtextid == gtextid)
        )
    ).first()
    if row is not None:
        await _capture_row(session, tables.gr_cdct_text_item, 'gtextid', gtextid, 'update')
    return _row_dict(row) if row else None


async def delete_cdct_item(session: AsyncSession, gtextid: int) -> None:
    """Delete a cdct node; also remove cdct lines touching its entity."""
    row = (
        await session.execute(
            select(tables.gr_cdct_text_item).where(tables.gr_cdct_text_item.c.gtextid == gtextid)
        )
    ).first()
    if row is not None:
        catid, cid = row.catid, row.cid
        await session.execute(
            delete(tables.gr_cdct_line_item).where(
                (tables.gr_cdct_line_item.c.fromcatid == catid)
                | (tables.gr_cdct_line_item.c.fromcid == cid)
                | (tables.gr_cdct_line_item.c.tocatid == catid)
                | (tables.gr_cdct_line_item.c.tocid == cid)
            )
        )
    await session.execute(
        delete(tables.gr_cdct_text_item).where(tables.gr_cdct_text_item.c.gtextid == gtextid)
    )
    if row is not None:
        await _capture_delete(session, tables.gr_cdct_text_item, "gtextid", gtextid, row)
    await session.commit()


async def add_case_item(session: AsyncSession, grid: int, caseid: int, x: int, y: int,
                        color: str = "#5882FA", font_size: int = 12, bold: int = 0) -> dict:
    row = (
        await session.execute(select(tables.cases.c.name).where(tables.cases.c.caseid == caseid))
    ).first()
    displaytext = row[0] if row else f"Case {caseid}"
    gcaseid = await _insert(
        session,
        tables.gr_case_text_item,
        {"grid": grid, "x": int(x), "y": int(y), "caseid": caseid,
         "font_size": font_size, "bold": bold, "color": color, "displaytext": displaytext},
    )
    return {"gcaseid": gcaseid, "grid": grid, "caseid": caseid, "x": int(x), "y": int(y),
            "color": color, "displaytext": displaytext}


async def update_case_item(session: AsyncSession, gcaseid: int, **fields) -> dict | None:
    allowed = {"x", "y", "font_size", "bold", "color", "displaytext"}
    values = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if values:
        await session.execute(
            update(tables.gr_case_text_item).where(tables.gr_case_text_item.c.gcaseid == gcaseid).values(**values)
        )
        await session.commit()
    row = (
        await session.execute(
            select(tables.gr_case_text_item).where(tables.gr_case_text_item.c.gcaseid == gcaseid)
        )
    ).first()
    if row is not None:
        await _capture_row(session, tables.gr_case_text_item, 'gcaseid', gcaseid, 'update')
    return _row_dict(row) if row else None


async def delete_case_item(session: AsyncSession, gcaseid: int) -> None:
    row = (await session.execute(select(tables.gr_case_text_item).where(tables.gr_case_text_item.c.gcaseid == gcaseid))).first()
    await session.execute(
        delete(tables.gr_case_text_item).where(tables.gr_case_text_item.c.gcaseid == gcaseid)
    )
    if row is not None:
        await _capture_delete(session, tables.gr_case_text_item, 'gcaseid', gcaseid, row)
    await session.commit()


async def add_file_item(session: AsyncSession, grid: int, fid: int, x: int, y: int,
                        color: str = "#6B6BDA", font_size: int = 12, bold: int = 0) -> dict:
    row = (
        await session.execute(select(tables.source.c.name).where(tables.source.c.id == fid))
    ).first()
    displaytext = row[0] if row else f"File {fid}"
    gfileid = await _insert(
        session,
        tables.gr_file_text_item,
        {"grid": grid, "x": int(x), "y": int(y), "fid": fid,
         "font_size": font_size, "bold": bold, "color": color, "displaytext": displaytext},
    )
    return {"gfileid": gfileid, "grid": grid, "fid": fid, "x": int(x), "y": int(y),
            "color": color, "displaytext": displaytext}


async def update_file_item(session: AsyncSession, gfileid: int, **fields) -> dict | None:
    allowed = {"x", "y", "font_size", "bold", "color", "displaytext"}
    values = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if values:
        await session.execute(
            update(tables.gr_file_text_item).where(tables.gr_file_text_item.c.gfileid == gfileid).values(**values)
        )
        await session.commit()
    row = (
        await session.execute(
            select(tables.gr_file_text_item).where(tables.gr_file_text_item.c.gfileid == gfileid)
        )
    ).first()
    if row is not None:
        await _capture_row(session, tables.gr_file_text_item, 'gfileid', gfileid, 'update')
    return _row_dict(row) if row else None


async def delete_file_item(session: AsyncSession, gfileid: int) -> None:
    row = (await session.execute(select(tables.gr_file_text_item).where(tables.gr_file_text_item.c.gfileid == gfileid))).first()
    await session.execute(
        delete(tables.gr_file_text_item).where(tables.gr_file_text_item.c.gfileid == gfileid)
    )
    if row is not None:
        await _capture_delete(session, tables.gr_file_text_item, 'gfileid', gfileid, row)
    await session.commit()


async def add_free_item(session: AsyncSession, grid: int, x: int, y: int, free_text: str,
                        color: str = "#1d1d23", font_size: int = 12, bold: int = 0) -> dict:
    row = (
        await session.execute(
            select(tables.gr_free_text_item.c.freetextid)
            .where(tables.gr_free_text_item.c.grid == grid)
            .order_by(tables.gr_free_text_item.c.freetextid.desc())
        )
    ).first()
    freetextid = (row[0] if row and row[0] is not None else 0) + 1
    gfreeid = await _insert(
        session,
        tables.gr_free_text_item,
        {"grid": grid, "freetextid": freetextid, "x": int(x), "y": int(y),
         "free_text": free_text, "font_size": font_size, "bold": bold, "color": color,
         "tooltip": "", "ctid": None, "memo_ctid": None, "memo_imid": None, "memo_avid": None},
    )
    return {"gfreeid": gfreeid, "grid": grid, "freetextid": freetextid, "x": int(x), "y": int(y),
            "free_text": free_text, "color": color, "font_size": font_size, "bold": bold}


async def update_free_item(session: AsyncSession, gfreeid: int, **fields) -> dict | None:
    allowed = {"x", "y", "free_text", "color", "font_size", "bold", "tooltip"}
    values = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if values:
        await session.execute(
            update(tables.gr_free_text_item).where(tables.gr_free_text_item.c.gfreeid == gfreeid).values(**values)
        )
        await session.commit()
    row = (
        await session.execute(
            select(tables.gr_free_text_item).where(tables.gr_free_text_item.c.gfreeid == gfreeid)
        )
    ).first()
    if row is not None:
        await _capture_row(session, tables.gr_free_text_item, 'gfreeid', gfreeid, 'update')
    return _row_dict(row) if row else None


async def delete_free_item(session: AsyncSession, gfreeid: int) -> None:
    row = (await session.execute(select(tables.gr_free_text_item).where(tables.gr_free_text_item.c.gfreeid == gfreeid))).first()
    await session.execute(
        delete(tables.gr_free_text_item).where(tables.gr_free_text_item.c.gfreeid == gfreeid)
    )
    if row is not None:
        await _capture_delete(session, tables.gr_free_text_item, 'gfreeid', gfreeid, row)
    await session.commit()


async def add_memo_item(session: AsyncSession, grid: int, memo_source_type: str,
                        memo_source_id: int, x: int, y: int, color: str = "#E8E8E8",
                        font_size: int = 11) -> dict:
    """A memo node attached to a code or file (``memo_source_type`` in
    {"code", "file"})."""
    if memo_source_type == "code":
        row = (
            await session.execute(
                select(tables.code_name.c.memo).where(tables.code_name.c.cid == memo_source_id)
            )
        ).first()
    else:
        row = (
            await session.execute(
                select(tables.source.c.memo).where(tables.source.c.id == memo_source_id)
            )
        ).first()
    if row is None or not row[0]:
        raise ValueError("memo is empty for this entity")
    gmemoid = await _insert(
        session,
        tables.gr_memo_item,
        {"grid": grid, "memo_source_type": memo_source_type, "memo_source_id": memo_source_id,
         "x": int(x), "y": int(y), "color": color, "font_size": font_size},
    )
    return {"gmemoid": gmemoid, "grid": grid, "memo_source_type": memo_source_type,
            "memo_source_id": memo_source_id, "x": int(x), "y": int(y),
            "color": color, "font_size": font_size, "memo": row[0]}


async def update_memo_item(session: AsyncSession, gmemoid: int, **fields) -> dict | None:
    allowed = {"x", "y", "color", "font_size"}
    values = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if values:
        await session.execute(
            update(tables.gr_memo_item).where(tables.gr_memo_item.c.gmemoid == gmemoid).values(**values)
        )
        await session.commit()
    row = (
        await session.execute(select(tables.gr_memo_item).where(tables.gr_memo_item.c.gmemoid == gmemoid))
    ).first()
    if row is not None:
        await _capture_row(session, tables.gr_memo_item, 'gmemoid', gmemoid, 'update')
    return _row_dict(row) if row else None


async def delete_memo_item(session: AsyncSession, gmemoid: int) -> None:
    row = (
        await session.execute(
            select(tables.gr_memo_item).where(tables.gr_memo_item.c.gmemoid == gmemoid)
        )
    ).first()
    await session.execute(delete(tables.gr_memo_item).where(tables.gr_memo_item.c.gmemoid == gmemoid))
    if row is not None:
        await _capture_delete(session, tables.gr_memo_item, "gmemoid", gmemoid, row)
    await session.commit()
