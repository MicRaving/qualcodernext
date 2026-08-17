"""Summary reports: file summary, code segments, summary table."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.enums import MediaType


async def file_summary(session: AsyncSession) -> list[dict]:
    """One row per source: coding counts, linked cases, word count."""
    sources = [
        {"fid": fid, "name": name, "mediapath": mediapath, "fulltext": fulltext}
        for fid, name, mediapath, fulltext in await session.execute(
            text("SELECT id, name, mediapath, fulltext FROM source ORDER BY name")
        )
    ]

    seg_counts: dict[int, int] = defaultdict(int)
    code_counts: dict[int, set[int]] = defaultdict(set)
    for tbl, file_col in (("code_text_visible", "fid"), ("code_image_visible", "id"), ("code_av_visible", "id")):
        rows = await session.execute(
            text(f"SELECT {file_col}, COUNT(*), cid FROM {tbl} GROUP BY {file_col}, cid")
        )
        for fid, n, cid in rows:
            seg_counts[fid] += n
            if cid is not None:
                code_counts[fid].add(cid)

    cases: dict[int, set[str]] = defaultdict(set)
    rows = await session.execute(
        text(
            "SELECT DISTINCT ct.fid, c.name FROM case_text ct "
            "JOIN cases c ON c.caseid = ct.caseid"
        )
    )
    for fid, name in rows:
        cases[fid].add(name)

    return [
        {
            "fid": source["fid"],
            "name": source["name"],
            "media_type": MediaType.from_mediapath(source["mediapath"]).value,
            "codes_count": len(code_counts[source["fid"]]),
            "segments_count": seg_counts[source["fid"]],
            "cases": sorted(cases[source["fid"]]),
            "words": len((source["fulltext"] or "").split()),
        }
        for source in sources
    ]


async def code_segments(session: AsyncSession, cid: int) -> list[dict]:
    """All coded segments of one code across text/image/AV (code-in-all-files).

    Text rows carry ``pos0/pos1`` and the segment text; image rows carry the
    rectangle; AV rows carry millisecond positions.
    """
    rows = await session.execute(
        text(
            "SELECT ct.ctid, ct.seltext, ct.pos0, ct.pos1, COALESCE(ct.owner, ''), "
            "COALESCE(ct.memo, ''), s.name AS file_name "
            "FROM code_text_visible ct JOIN source s ON s.id = ct.fid "
            "WHERE ct.cid = :cid ORDER BY s.name, ct.pos0"
        ),
        {"cid": cid},
    )
    out = []
    for ctid, seltext, pos0, pos1, owner, memo, file_name in rows:
        out.append(
            {
                "kind": "text",
                "id": ctid,
                "file_name": file_name or "",
                "seltext": seltext or "",
                "pos0": pos0,
                "pos1": pos1,
                "owner": owner,
                "memo": memo,
                "date": "",
            }
        )
    img_rows = await session.execute(
        text(
            "SELECT ci.imid, ci.x1, ci.y1, ci.width, ci.height, ci.pdf_page, "
            "COALESCE(ci.memo, ''), COALESCE(ci.owner, ''), s.name AS file_name "
            "FROM code_image_visible ci JOIN source s ON s.id = ci.id "
            "WHERE ci.cid = :cid ORDER BY s.name, ci.imid"
        ),
        {"cid": cid},
    )
    for imid, x1, y1, width, height, pdf_page, memo, owner, file_name in img_rows:
        out.append(
            {
                "kind": "image",
                "id": imid,
                "file_name": file_name or "",
                "x1": x1, "y1": y1, "width": width, "height": height,
                "pdf_page": pdf_page,
                "owner": owner,
                "memo": memo,
                "date": "",
            }
        )
    av_rows = await session.execute(
        text(
            "SELECT ca.avid, ca.pos0, ca.pos1, COALESCE(ca.memo, ''), "
            "COALESCE(ca.owner, ''), s.name AS file_name "
            "FROM code_av_visible ca JOIN source s ON s.id = ca.id "
            "WHERE ca.cid = :cid ORDER BY s.name, ca.pos0"
        ),
        {"cid": cid},
    )
    for avid, pos0, pos1, memo, owner, file_name in av_rows:
        out.append(
            {
                "kind": "av",
                "id": avid,
                "file_name": file_name or "",
                "pos0": pos0,
                "pos1": pos1,
                "owner": owner,
                "memo": memo,
                "date": "",
            }
        )
    out.sort(key=lambda r: (r["file_name"].lower(), r.get("pos0") or 0))
    return out


async def summary_table(
    session: AsyncSession,
    scope: str,
    fids: list[int] | None = None,
    cids: list[int] | None = None,
) -> dict:
    """Doc/case x code grid whose cells hold the coding memos.

    Rows are the sources (``scope='file'``) or cases (``scope='case'``);
    columns are codes. A cell concatenates the memos of that code's codings
    in that unit (first memo of each coding, joined with ' — ') and carries
    a ``memo_count`` plus the individual items (kind + id + memo) so the
    frontend can edit a memo through the regular coding PATCH endpoints.
    """
    if scope not in ("file", "case"):
        raise ValueError("scope must be 'file' or 'case'")
    fids_set = set(fids) if fids else None
    cids_set = set(cids) if cids else None

    if scope == "case":
        unit_rows = await session.execute(
            text("SELECT caseid, name FROM cases ORDER BY name")
        )
        units = [{"id": caseid, "name": name} for caseid, name in unit_rows]
    else:
        unit_rows = await session.execute(
            text("SELECT id, name FROM source ORDER BY name")
        )
        units = [
            {"id": fid, "name": name}
            for fid, name in unit_rows
            if fids_set is None or fid in fids_set
        ]

    code_rows = await session.execute(
        text("SELECT cid, name, COALESCE(color, '') FROM code_name ORDER BY name")
    )
    codes = [
        {"cid": cid, "name": name, "color": color}
        for cid, name, color in code_rows
        if cids_set is None or cid in cids_set
    ]

    if scope == "case":
        queries = (
            "SELECT ct.ctid AS coding_id, cst.caseid AS unit_id, ct.cid, "
            "COALESCE(ct.memo, '') AS memo FROM code_text_visible ct "
            "JOIN case_text cst ON cst.fid = ct.fid",
            "SELECT ci.imid AS coding_id, cst.caseid AS unit_id, ci.cid, "
            "COALESCE(ci.memo, '') AS memo FROM code_image_visible ci "
            "JOIN case_text cst ON cst.fid = ci.id",
            "SELECT ca.avid AS coding_id, cst.caseid AS unit_id, ca.cid, "
            "COALESCE(ca.memo, '') AS memo FROM code_av_visible ca "
            "JOIN case_text cst ON cst.fid = ca.id",
        )
    else:
        queries = (
            "SELECT ct.ctid AS coding_id, ct.fid AS unit_id, ct.cid, "
            "COALESCE(ct.memo, '') AS memo FROM code_text_visible ct",
            "SELECT ci.imid AS coding_id, ci.id AS unit_id, ci.cid, "
            "COALESCE(ci.memo, '') AS memo FROM code_image_visible ci",
            "SELECT ca.avid AS coding_id, ca.id AS unit_id, ca.cid, "
            "COALESCE(ca.memo, '') AS memo FROM code_av_visible ca",
        )
    kinds = ("text", "image", "av")

    cells: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for sql, kind in zip(queries, kinds, strict=False):
        where = []
        params: dict[str, object] = {}
        if cids_set is not None:
            placeholders = [f":cid_{i}" for i in range(len(cids_set))]
            where.append(f"cid IN ({', '.join(placeholders)})")
            params.update({f"cid_{i}": c for i, c in enumerate(sorted(cids_set))})
        if scope == "case" and fids_set is not None:
            placeholders = [f":fid_{i}" for i in range(len(fids_set))]
            where.append(f"cst.fid IN ({', '.join(placeholders)})")
            params.update({f"fid_{i}": f for i, f in enumerate(sorted(fids_set))})
        if where:
            sql = f"{sql} WHERE {' AND '.join(where)}"
        for coding_id, unit_id, cid, memo in await session.execute(text(sql), params):
            if unit_id is None or cid is None:
                continue
            if scope == "file" and fids_set is not None and unit_id not in fids_set:
                continue
            cells[(unit_id, cid)].append(
                {"kind": kind, "id": coding_id, "memo": memo or ""}
            )

    rows = []
    for unit in units:
        unit_cells = []
        for code in codes:
            items = sorted(
                cells[(unit["id"], code["cid"])], key=lambda item: item["id"]
            )
            memos = [item["memo"] for item in items if item["memo"]]
            unit_cells.append(
                {
                    "memo": " — ".join(memos),
                    "memo_count": len(memos),
                    "items": items,
                }
            )
        rows.append({"id": unit["id"], "name": unit["name"], "cells": unit_cells})

    return {"scope": scope, "codes": codes, "rows": rows}
