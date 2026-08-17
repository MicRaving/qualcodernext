"""Graph line CRUD — add / update / delete for the three line kinds:
cdct lines, free (entity) lines.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.persistence import tables
from qualcoder_api.services.graph_base import (
    _capture_delete,
    _capture_row,
    _insert,
    _row_dict,
)


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
