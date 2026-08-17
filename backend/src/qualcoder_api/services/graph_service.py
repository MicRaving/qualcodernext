"""Graph / code-map service — CRUD for graphs, their nodes and lines, plus
the six analytical model generators (upstream ``view_graph`` /
``view_graph_models`` / ``view_graph_relations`` port).

Graphs live in the legacy v6+ tables (``graph``, ``gr_cdct_text_item``,
``gr_case_text_item``, ``gr_file_text_item``, ``gr_free_text_item``,
``gr_memo_item``, ``gr_cdct_line_item``, ``gr_free_line_item``, ``gr_pix_item``,
``gr_av_item``). Node positions are scene coordinates; lines carry the
relation ``label`` and ``arrow_mode`` (v17 columns).
"""

from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from typing import Any

from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.timeutil import now as _now
from qualcoder_api.persistence import tables


def _row_dict(row) -> dict:
    return dict(row._mapping)


async def _insert(session: AsyncSession, table, values: dict) -> int:
    from qualcoder_api.persistence.repositories import _capture

    result = await session.execute(insert(table).values(**values))
    await session.commit()
    from qualcoder_api.persistence.repositories import _inserted_pk

    pk = int(_inserted_pk(result))
    await _capture(session, table.name, "insert", table.primary_key.columns.keys()[0], pk, dict(values))
    await session.commit()
    return pk


async def _capture_row(session: AsyncSession, table, pk_name: str, pk_value: int, action: str) -> None:
    """Capture the current state of a graph row after an update."""
    from qualcoder_api.persistence.repositories import _capture, _rowdict

    row = (await session.execute(select(table).where(table.c[pk_name] == pk_value))).first()
    if row is not None:
        await _capture(session, table.name, action, pk_name, pk_value, _rowdict(row))
    await session.commit()


async def _capture_delete(session: AsyncSession, table, pk_name: str, pk_value: int, row) -> None:
    """Capture a graph row that is about to be deleted (the row is gone by
    the time a post-delete re-select runs, which silently skipped deletes)."""
    from qualcoder_api.persistence.repositories import _capture, _rowdict

    if row is not None:
        await _capture(session, table.name, "delete", pk_name, pk_value, _rowdict(row))
    await session.commit()


async def _record_audit(session: AsyncSession, action: str, entity: str, entity_id: int, detail: dict) -> None:
    """Record a graph item/line mutation in the audit log."""
    from qualcoder_api.services import audit
    from qualcoder_api.services.user_settings import get_codername

    await audit.record(
        session, user=get_codername(), action=action, entity=entity,
        entity_id=entity_id, detail=detail,
    )


# ----------------------------------------------------------------------
# Graph CRUD
# ----------------------------------------------------------------------

async def list_graphs(session: AsyncSession) -> list[dict]:
    rows = await session.execute(
        select(tables.graph).order_by(tables.graph.c.name)
    )
    return [_row_dict(r) for r in rows]


async def get_graph(session: AsyncSession, grid: int) -> dict | None:
    row = (
        await session.execute(select(tables.graph).where(tables.graph.c.grid == grid))
    ).first()
    if row is None:
        return None
    graph = _row_dict(row)

    cdct = await session.execute(
        select(tables.gr_cdct_text_item).where(tables.gr_cdct_text_item.c.grid == grid)
    )
    case_items = await session.execute(
        select(tables.gr_case_text_item).where(tables.gr_case_text_item.c.grid == grid)
    )
    file_items = await session.execute(
        select(tables.gr_file_text_item).where(tables.gr_file_text_item.c.grid == grid)
    )
    free_items = await session.execute(
        select(tables.gr_free_text_item).where(tables.gr_free_text_item.c.grid == grid)
    )
    memo_items = await session.execute(
        select(tables.gr_memo_item).where(tables.gr_memo_item.c.grid == grid)
    )
    cdct_lines = await session.execute(
        select(tables.gr_cdct_line_item).where(tables.gr_cdct_line_item.c.grid == grid)
    )
    free_lines = await session.execute(
        select(tables.gr_free_line_item).where(tables.gr_free_line_item.c.grid == grid)
    )

    categories = [
        _row_dict(r)
        for r in await session.execute(select(tables.code_cat).order_by(tables.code_cat.c.name))
    ]
    codes = [
        _row_dict(r)
        for r in await session.execute(select(tables.code_name).order_by(tables.code_name.c.name))
    ]
    cases = [
        _row_dict(r) for r in await session.execute(select(tables.cases).order_by(tables.cases.c.name))
    ]
    sources = [
        _row_dict(r)
        for r in await session.execute(select(tables.source).order_by(tables.source.c.name))
    ]

    return {
        "graph": graph,
        "cdct_items": [_row_dict(r) for r in cdct],
        "case_items": [_row_dict(r) for r in case_items],
        "file_items": [_row_dict(r) for r in file_items],
        "free_items": [_row_dict(r) for r in free_items],
        "memo_items": [_row_dict(r) for r in memo_items],
        "cdct_lines": [_row_dict(r) for r in cdct_lines],
        "free_lines": [_row_dict(r) for r in free_lines],
        "categories": categories,
        "codes": codes,
        "cases": cases,
        "sources": sources,
    }


async def create_graph(
    session: AsyncSession,
    name: str,
    description: str = "",
    scene_width: int = 1600,
    scene_height: int = 1000,
    owner: str = "",
) -> dict:
    grid = await _insert(
        session,
        tables.graph,
        {
            "name": name,
            "description": description,
            "date": _now(),
            "scene_width": scene_width,
            "scene_height": scene_height,
        },
    )
    return {
        "grid": grid,
        "name": name,
        "description": description,
        "date": _now(),
        "scene_width": scene_width,
        "scene_height": scene_height,
    }


async def update_graph(session: AsyncSession, grid: int, **fields) -> dict | None:
    allowed = {"name", "description", "scene_width", "scene_height"}
    values = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if values:
        await session.execute(update(tables.graph).where(tables.graph.c.grid == grid).values(**values))
        await session.commit()
    row = (await session.execute(select(tables.graph).where(tables.graph.c.grid == grid))).first()
    return _row_dict(row) if row else None


async def delete_graph(session: AsyncSession, grid: int) -> None:
    for table in (
        tables.gr_cdct_text_item,
        tables.gr_case_text_item,
        tables.gr_file_text_item,
        tables.gr_free_text_item,
        tables.gr_memo_item,
        tables.gr_cdct_line_item,
        tables.gr_free_line_item,
        tables.gr_pix_item,
        tables.gr_av_item,
        tables.graph,
    ):
        await session.execute(delete(table).where(table.c.grid == grid))
    await session.commit()


# ----------------------------------------------------------------------
# Items
# ----------------------------------------------------------------------

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


# ----------------------------------------------------------------------
# Lines
# ----------------------------------------------------------------------

async def add_cdct_line(
    session: AsyncSession,
    grid: int,
    from_node: int,
    to_node: int,
    color: str = "#888888",
    linewidth: float = 1.0,
    linetype: str = "solid",
    isvisible: int = 1,
    label: str = "",
    arrow_mode: str = "solid_with_arrow",
) -> dict:
    """Line between two cdct items (nodes referenced by their gtextid)."""
    from_row = (
        await session.execute(
            select(
                tables.gr_cdct_text_item.c.supercatid,
                tables.gr_cdct_text_item.c.catid,
                tables.gr_cdct_text_item.c.cid,
            ).where(tables.gr_cdct_text_item.c.gtextid == from_node)
        )
    ).first()
    to_row = (
        await session.execute(
            select(
                tables.gr_cdct_text_item.c.supercatid,
                tables.gr_cdct_text_item.c.catid,
                tables.gr_cdct_text_item.c.cid,
            ).where(tables.gr_cdct_text_item.c.gtextid == to_node)
        )
    ).first()
    if from_row is None or to_row is None:
        raise ValueError("both line endpoints must be graph nodes")
    glineid = await _insert(
        session,
        tables.gr_cdct_line_item,
        {
            "grid": grid,
            "fromcatid": from_row[1],
            "fromcid": from_row[2],
            "tocatid": to_row[1],
            "tocid": to_row[2],
            "color": color,
            "linewidth": linewidth,
            "linetype": linetype,
            "isvisible": isvisible,
            "label": label,
            "arrow_mode": arrow_mode,
        },
    )
    return {"glineid": glineid, "grid": grid, "from_node": from_node, "to_node": to_node,
            "color": color, "linewidth": linewidth, "linetype": linetype,
            "isvisible": isvisible, "label": label, "arrow_mode": arrow_mode}


async def update_cdct_line(session: AsyncSession, glineid: int, **fields) -> dict | None:
    allowed = {"color", "linewidth", "linetype", "isvisible", "label", "arrow_mode"}
    values = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if values:
        await session.execute(
            update(tables.gr_cdct_line_item).where(tables.gr_cdct_line_item.c.glineid == glineid).values(**values)
        )
        await session.commit()
    row = (
        await session.execute(
            select(tables.gr_cdct_line_item).where(tables.gr_cdct_line_item.c.glineid == glineid)
        )
    ).first()
    if row is not None:
        await _capture_row(session, tables.gr_cdct_line_item, 'glineid', glineid, 'update')
    return _row_dict(row) if row else None


async def delete_cdct_line(session: AsyncSession, glineid: int) -> None:
    row = (await session.execute(select(tables.gr_cdct_line_item).where(tables.gr_cdct_line_item.c.glineid == glineid))).first()
    await session.execute(
        delete(tables.gr_cdct_line_item).where(tables.gr_cdct_line_item.c.glineid == glineid)
    )
    if row is not None:
        await _capture_delete(session, tables.gr_cdct_line_item, 'glineid', glineid, row)
    await session.commit()


async def update_free_line(session: AsyncSession, gflineid: int, **fields) -> dict | None:
    allowed = {"color", "linewidth", "linetype", "label", "arrow_mode"}
    values = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if values:
        await session.execute(
            update(tables.gr_free_line_item).where(tables.gr_free_line_item.c.gflineid == gflineid).values(**values)
        )
        await session.commit()
    row = (
        await session.execute(
            select(tables.gr_free_line_item).where(tables.gr_free_line_item.c.gflineid == gflineid)
        )
    ).first()
    if row is not None:
        await _capture_row(session, tables.gr_free_line_item, 'gflineid', gflineid, 'update')
    return _row_dict(row) if row else None


async def delete_free_line(session: AsyncSession, gflineid: int) -> None:
    row = (await session.execute(select(tables.gr_free_line_item).where(tables.gr_free_line_item.c.gflineid == gflineid))).first()
    await session.execute(
        delete(tables.gr_free_line_item).where(tables.gr_free_line_item.c.gflineid == gflineid)
    )
    if row is not None:
        await _capture_delete(session, tables.gr_free_line_item, 'gflineid', gflineid, row)
    await session.commit()


async def add_entity_line(
    session: AsyncSession,
    grid: int,
    from_kind: str,
    from_id: int,
    to_kind: str,
    to_id: int,
    color: str = "#888888",
    linewidth: float = 1.0,
    linetype: str = "solid",
    label: str = "",
    arrow_mode: str = "solid_with_arrow",
) -> dict:
    """Line between arbitrary entity nodes using the ``gr_free_line_item``
    from*/to* columns. Kinds: free, case, file, code, category, imid, avid."""
    kind_cols = {
        "free": "freetextid",
        "case": "caseid",
        "file": "fileid",
        "code": "cid",
        "category": "catid",
        "imid": "imid",
        "avid": "avid",
    }
    if from_kind not in kind_cols or to_kind not in kind_cols:
        raise ValueError("invalid endpoint kind")
    values: dict[str, Any] = {
        "grid": grid,
        "color": color,
        "linewidth": linewidth,
        "linetype": linetype,
        "label": label,
        "arrow_mode": arrow_mode,
    }
    values[f"from{kind_cols[from_kind]}"] = from_id
    values[f"to{kind_cols[to_kind]}"] = to_id
    gflineid = await _insert(session, tables.gr_free_line_item, values)
    return {"gflineid": gflineid, "grid": grid, "from_kind": from_kind, "from_id": from_id,
            "to_kind": to_kind, "to_id": to_id, "color": color, "linewidth": linewidth,
            "linetype": linetype, "label": label, "arrow_mode": arrow_mode}


# ----------------------------------------------------------------------
# Model generator (view_graph_models.py)
# ----------------------------------------------------------------------

MODELS = (
    "category-hierarchy",
    "file-hierarchy",
    "file-comparison",
    "case-hierarchy",
    "case-comparison",
    "cooccurrence-network",
)


def _circle_layout(nodes: list[dict], width: int, height: int) -> list[tuple[int, int]]:
    cx, cy = width / 2, height / 2
    radius = min(width, height) / 2 - 120
    out = []
    for i, _node in enumerate(nodes):
        angle = 2 * math.pi * i / max(1, len(nodes))
        out.append((int(cx + radius * math.cos(angle)), int(cy + radius * math.sin(angle))))
    return out


async def generate_model(
    session: AsyncSession,
    model: str,
    name: str,
    owner: str = "",
    file_ids: list[int] | None = None,
    case_ids: list[int] | None = None,
) -> dict:
    """Create a new graph with nodes/edges from one of the six analytical
    models. Returns the created graph summary."""
    if model not in MODELS:
        raise ValueError(f"unknown model: {model}")
    width, height = 1600, 1000

    categories = [
        _row_dict(r)
        for r in await session.execute(select(tables.code_cat).order_by(tables.code_cat.c.name))
    ]
    codes = [
        _row_dict(r)
        for r in await session.execute(select(tables.code_name).order_by(tables.code_name.c.name))
    ]
    cases = [
        _row_dict(r)
        for r in await session.execute(select(tables.cases).order_by(tables.cases.c.name))
    ]
    sources = [
        _row_dict(r)
        for r in await session.execute(select(tables.source).order_by(tables.source.c.name))
    ]

    grid = (await create_graph(session, name, f"Model: {model}", width, height, owner))["grid"]

    # --- helpers -------------------------------------------------------
    async def add_cat(cat: dict, x: int, y: int) -> None:
        await add_cdct_item(session, grid, "category", cat["catid"], x, y)

    async def add_code(code: dict, x: int, y: int) -> dict:
        return await add_cdct_item(session, grid, "code", code["cid"], x, y)

    async def link_cdct(from_id: int, to_id: int) -> None:
        await add_cdct_line(session, grid, from_id, to_id)

    # --- category hierarchy ---------------------------------------------
    if model == "category-hierarchy":
        cat_children: dict[int | None, list[dict]] = defaultdict(list)
        for cat in categories:
            cat_children[cat.get("supercatid")].append(cat)
        code_children: dict[int | None, list[dict]] = defaultdict(list)
        for code in codes:
            parent = code.get("supercid") or code.get("catid")
            code_children[parent].append(code)
        node_ids: dict[tuple[str, int], int] = {}
        level: dict[int, int] = {}
        # BFS levels
        queue = deque(c["catid"] for c in categories if c.get("supercatid") is None)
        for cid in queue:
            level[cid] = 0
        while queue:
            cid = queue.popleft()
            for child in cat_children.get(cid, []):
                if child["catid"] not in level:
                    level[child["catid"]] = level[cid] + 1
                    queue.append(child["catid"])
        for cat in categories:
            node = await add_cdct_item(
                session, grid, "category", cat["catid"],
                60, 60 + level.get(cat["catid"], 0) * 120,
            )
            node_ids[("category", cat["catid"])] = node["gtextid"]
        for cat in categories:
            if cat.get("supercatid") is not None and ("category", cat["supercatid"]) in node_ids:
                await link_cdct(node_ids[("category", cat["supercatid"])], node_ids[("category", cat["catid"])])
        code_levels: dict[int, int] = {}
        for code in codes:
            parent = code.get("supercid") or code.get("catid")
            code_levels[code["cid"]] = (level.get(parent, 0) if parent is not None else 0) + 1
        idx_by_level: dict[int, int] = defaultdict(int)
        for code in codes:
            node = await add_code(code, 60 + idx_by_level[code_levels[code["cid"]]] * 190,
                                  60 + code_levels[code["cid"]] * 120)
            idx_by_level[code_levels[code["cid"]]] += 1
            node_ids[("code", code["cid"])] = node["gtextid"]
        for code in codes:
            parent = code.get("supercid") or code.get("catid")
            if parent is not None:
                key = ("code", parent) if code.get("supercid") is not None else ("category", parent)
                if key in node_ids:
                    await link_cdct(node_ids[key], node_ids[("code", code["cid"])])
        return {"grid": grid, "model": model}

    # --- file hierarchy / file comparison --------------------------------
    if model in ("file-hierarchy", "file-comparison"):
        selected = [f for f in sources if f["id"] in (file_ids or [])] if file_ids else sources
        case_text_rows = [
            _row_dict(r)
            for r in await session.execute(
                select(tables.case_text).where(tables.case_text.c.fid.in_([f["id"] for f in selected]))
            )
        ]
        file_node_ids: dict[tuple[str, int], int] = {}
        # Files across the top, cases below them (hierarchy) or codes below.
        for i, f in enumerate(selected):
            node = await add_file_item(session, grid, f["id"], 60 + i * 200, 60)
            file_node_ids[("file", f["id"])] = node["gfileid"]
        if model == "file-hierarchy":
            for i, c in enumerate(cases):
                node = await add_case_item(session, grid, c["caseid"], 60 + i * 200, 300)
                file_node_ids[("case", c["caseid"])] = node["gcaseid"]
            for row in case_text_rows:
                if row["caseid"] in file_node_ids and row["fid"] in file_node_ids:
                    await add_entity_line(
                        session, grid, "file", row["fid"], "case", row["caseid"]
                    )
        else:  # file-comparison: files + the codes used in them
            used: dict[int, set[int]] = defaultdict(set)
            code_rows = await session.execute(
                text(
                    "SELECT DISTINCT fid, cid FROM code_text WHERE fid IN (SELECT value FROM json_each(:ids))"
                ),
                {"ids": json.dumps([f["id"] for f in selected])},
            )
            for fid, cid in code_rows:
                used[fid].add(cid)
            all_used = sorted({c for ids in used.values() for c in ids})
            code_nodes: dict[int, int] = {}
            for i, cid in enumerate(all_used):
                node = await add_cdct_item(session, grid, "code", cid, 60 + i * 190, 300)
                code_nodes[cid] = node["gtextid"]
            for fid, cids in used.items():
                for cid in cids:
                    if cid in code_nodes:
                        await add_entity_line(session, grid, "file", fid, "code", cid)
        return {"grid": grid, "model": model}

    # --- case hierarchy / case comparison --------------------------------
    if model in ("case-hierarchy", "case-comparison"):
        selected_cases = [c for c in cases if c["caseid"] in (case_ids or [])] if case_ids else cases
        case_text_rows = [
            _row_dict(r)
            for r in await session.execute(
                select(tables.case_text).where(
                    tables.case_text.c.caseid.in_([c["caseid"] for c in selected_cases])
                )
            )
        ]
        case_node_ids: dict[tuple[str, int], int] = {}
        for i, c in enumerate(selected_cases):
            node = await add_case_item(session, grid, c["caseid"], 60 + i * 220, 60)
            case_node_ids[("case", c["caseid"])] = node["gcaseid"]
        known_files = {f["id"] for f in sources}
        case_used: dict[int, set[int]] = defaultdict(set)
        for row in case_text_rows:
            if row["fid"] in known_files:
                case_used[row["caseid"]].add(row["fid"])
        all_files = sorted({f for ids in case_used.values() for f in ids})
        if model == "case-hierarchy":
            file_nodes: dict[int, int] = {}
            for i, fid in enumerate(all_files):
                node = await add_file_item(session, grid, fid, 60 + i * 200, 300)
                file_nodes[fid] = node["gfileid"]
            for caseid, fids in case_used.items():
                for fid in fids:
                    if fid in file_nodes:
                        await add_entity_line(session, grid, "case", caseid, "file", fid)
        else:  # case-comparison: cases + codes used in their files
            case_code_nodes: dict[int, int] = {}
            all_codes: set[int] = set()
            code_usage: dict[int, set[int]] = defaultdict(set)
            code_rows = await session.execute(
                text("SELECT DISTINCT fid, cid FROM code_text WHERE fid IN (SELECT value FROM json_each(:ids))"),
                {"ids": json.dumps(list(all_files))},
            )
            for fid, cid in code_rows:
                all_codes.add(cid)
                for caseid, fids in case_used.items():
                    if fid in fids:
                        code_usage[caseid].add(cid)
            for i, cid in enumerate(sorted(all_codes)):
                node = await add_cdct_item(session, grid, "code", cid, 60 + i * 190, 300)
                case_code_nodes[cid] = node["gtextid"]
            for caseid, cids in code_usage.items():
                for cid in cids:
                    if cid in case_code_nodes:
                        await add_entity_line(session, grid, "case", caseid, "code", cid)
        return {"grid": grid, "model": model}

    # --- co-occurrence network -------------------------------------------
    pairs: dict[tuple[int, int], int] = defaultdict(int)
    by_file: dict[int, list[int]] = defaultdict(list)
    rows = await session.execute(text("SELECT fid, cid FROM code_text"))
    for fid, cid in rows:
        by_file[fid].append(cid)
    for file_cids in by_file.values():
        uniq = sorted(set(file_cids))
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                pairs[(uniq[i], uniq[j])] += 1
    used_codes: set[int] = {c for pair in pairs for c in pair}
    cooc_code_nodes: dict[int, int] = {}
    positions = _circle_layout(
        [{"cid": c} for c in sorted(used_codes)], width, height
    )
    for cid, (x, y) in zip(sorted(used_codes), positions, strict=False):
        node = await add_cdct_item(session, grid, "code", cid, x, y)
        cooc_code_nodes[cid] = node["gtextid"]
    for (a, b), count in pairs.items():
        await add_cdct_line(session, grid, cooc_code_nodes[a], cooc_code_nodes[b],
                            linewidth=1.0 + min(3.0, count / 3.0))
    return {"grid": grid, "model": model}
