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

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.timeutil import now as _now
from qualcoder_api.persistence import tables
from qualcoder_api.services.graph_base import _insert, _row_dict
from qualcoder_api.services.graph_items import (  # noqa: F401
    add_case_item,
    add_cdct_item,
    add_file_item,
    add_free_item,
    add_memo_item,
    delete_case_item,
    delete_cdct_item,
    delete_file_item,
    delete_free_item,
    delete_memo_item,
    update_case_item,
    update_cdct_item,
    update_file_item,
    update_free_item,
    update_memo_item,
)
from qualcoder_api.services.graph_lines import (  # noqa: F401
    add_cdct_line,
    add_entity_line,
    delete_cdct_line,
    delete_free_line,
    update_cdct_line,
    update_free_line,
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
