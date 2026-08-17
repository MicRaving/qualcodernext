"""Comparison reports: file x code matrix, coder comparisons, group analysis."""

from __future__ import annotations

from collections import defaultdict
from typing import cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.services.reports._shared import (
    _attr_scope,
    _sorted_values,
    _unit_coding_counts,
    _unit_coding_sets,
    _units_with_values,
)


async def comparison_table(session: AsyncSession) -> dict:
    """File x code matrix of text-coding counts."""
    files = [
        {"fid": fid, "name": name}
        for fid, name in await session.execute(
            text(
                "SELECT s.id, s.name FROM source s "
                "WHERE s.id IN (SELECT DISTINCT fid FROM code_text_visible) "
                "ORDER BY s.name"
            )
        )
    ]
    codes = [
        {"cid": cid, "name": name, "color": color or ""}
        for cid, name, color in await session.execute(
            text("SELECT cid, name, COALESCE(color, '') FROM code_name ORDER BY name")
        )
    ]

    pairs: dict[tuple[int, int], int] = defaultdict(int)
    rows = await session.execute(
        text("SELECT fid, cid, COUNT(*) FROM code_text_visible GROUP BY fid, cid")
    )
    for fid, cid, n in rows:
        pairs[(fid, cid)] = n

    counts = [
        [pairs.get((f["fid"], c["cid"]), 0) for c in codes] for f in files
    ]
    return {"files": files, "codes": codes, "counts": counts}


async def coder_comparison(session: AsyncSession) -> list[dict]:
    """Coding counts and distinct files per coder across all media types."""
    codings: dict[str, int] = defaultdict(int)
    files: dict[str, set[int]] = defaultdict(set)
    for tbl, file_col in (
        ("code_text_visible", "fid"),
        ("code_image_visible", "id"),
        ("code_av_visible", "id"),
    ):
        rows = await session.execute(
            text(
                f"SELECT COALESCE(owner, ''), COUNT(*) FROM {tbl} "
                f"WHERE owner IS NOT NULL GROUP BY owner"
            )
        )
        for owner, n in rows:
            codings[owner] += n
        pairs = await session.execute(
            text(
                f"SELECT DISTINCT COALESCE(owner, ''), {file_col} FROM {tbl} "
                f"WHERE owner IS NOT NULL AND {file_col} IS NOT NULL"
            )
        )
        for owner, fid in pairs:
            files[owner].add(fid)

    result = [
        {"owner": owner, "codings_count": n, "files_count": len(files[owner])}
        for owner, n in codings.items()
        if n > 0
    ]
    result.sort(key=lambda r: (-cast(int, r["codings_count"]), str(cast(str, r["owner"])).lower()))
    return result


async def coder_file_comparison(session: AsyncSession, coder_a: str, coder_b: str) -> dict:
    """Compare two coders' text codings file by file (report_compare_coder_file).

    One row per file: each coder's segment count and the list of segments
    (with code names) for both.
    """
    if coder_a == coder_b:
        raise ValueError("choose two different coders")
    rows = await session.execute(
        text(
            "SELECT s.name, ct.cid, cn.name, ct.seltext, ct.pos0, ct.pos1, ct.owner "
            "FROM code_text_visible ct "
            "JOIN source s ON s.id = ct.fid "
            "JOIN code_name cn ON cn.cid = ct.cid "
            "WHERE ct.owner IN (:a, :b) ORDER BY s.name, ct.pos0"
        ),
        {"a": coder_a, "b": coder_b},
    )
    by_file: dict[str, dict] = {}
    for file_name, cid, code_name, seltext, pos0, pos1, owner in rows:
        entry = by_file.setdefault(
            file_name or "", {"file_name": file_name or "", "a": [], "b": []}
        )
        segment = {"cid": cid, "code_name": code_name or "", "seltext": seltext or "",
                   "pos0": pos0, "pos1": pos1}
        if owner == coder_a:
            entry["a"].append(segment)
        else:
            entry["b"].append(segment)
    result = [
        {
            "file_name": entry["file_name"],
            "coder_a_count": len(entry["a"]),
            "coder_b_count": len(entry["b"]),
            "segments_a": entry["a"],
            "segments_b": entry["b"],
        }
        for entry in by_file.values()
    ]
    result.sort(key=lambda r: r["file_name"].lower())
    return {
        "coder_a": coder_a,
        "coder_b": coder_b,
        "files": result,
        "total_a": sum(r["coder_a_count"] for r in result),
        "total_b": sum(r["coder_b_count"] for r in result),
    }


async def group_compare(
    session: AsyncSession, attr_name: str, cid: int
) -> dict:
    """Numeric variable values split by presence of one code.

    Mann-Whitney U compares the two groups; each group gets its
    descriptives (count, mean, median, sd, min, max). Non-numeric values
    are skipped and reported.
    """
    scope = await _attr_scope(session, attr_name)
    _units, values = await _units_with_values(session, scope, attr_name)
    presence = await _unit_coding_sets(session, scope)

    numeric: dict[int, float] = {}
    skipped = 0
    for unit_id, value in values.items():
        try:
            numeric[unit_id] = float(value)
        except (TypeError, ValueError):
            skipped += 1

    code_row = (
        await session.execute(
            text(
                "SELECT name, COALESCE(color, '') FROM code_name WHERE cid = :cid"
            ),
            {"cid": cid},
        )
    ).first()
    code_name, code_color = code_row if code_row else ("", "")

    present = [
        numeric[unit_id] for unit_id in numeric
        if cid in presence.get(unit_id, set())
    ]
    absent = [
        numeric[unit_id] for unit_id in numeric
        if cid not in presence.get(unit_id, set())
    ]

    from qualcoder_api.services import stats_service

    u = (
        stats_service.mann_whitney_u(present, absent)
        if present and absent else None
    )
    return {
        "attr_name": attr_name,
        "scope": scope,
        "cid": cid,
        "code_name": code_name,
        "code_color": code_color,
        "n_values": len(numeric),
        "skipped_non_numeric": skipped,
        "present": stats_service.group_descriptives(present),
        "absent": stats_service.group_descriptives(absent),
        "u": u,
    }


async def code_by_variable(session: AsyncSession, attr_name: str) -> dict:
    """Mixed-methods matrix: coding counts per code and variable value.

    One column per distinct attribute value; each cell holds the total
    number of coding segments of that code in the units (cases or files)
    carrying that value. Also returns the data in the stacked-bars chart
    shape so the existing chart viewers can consume it.
    """
    scope = await _attr_scope(session, attr_name)
    units, values = await _units_with_values(session, scope, attr_name)
    counts = await _unit_coding_counts(session, scope)

    code_rows = await session.execute(
        text("SELECT cid, name, COALESCE(color, '') FROM code_name ORDER BY name")
    )
    codes = [
        {"cid": cid, "name": name, "color": color}
        for cid, name, color in code_rows
    ]
    columns = _sorted_values(set(values.values()))

    # Only codes that occur in a unit carrying the variable keep a row.
    in_scope = {cid for (_, cid) in counts}
    codes = [c for c in codes if c["cid"] in in_scope]

    matrix = []
    for column in columns:
        unit_ids = [u["id"] for u in units if values.get(u["id"]) == column]
        matrix.append(
            [
                sum(counts.get((uid, code["cid"]), 0) for uid in unit_ids)
                for code in codes
            ]
        )
    return {
        "attr_name": attr_name,
        "scope": scope,
        "values": columns,
        "codes": codes,
        "counts": matrix,
        "col_totals": [sum(row[ci] for row in matrix) for ci in range(len(codes))],
        "chart": {
            "kind": "stacked-values",
            "labels": [{"value": value} for value in columns],
            "codes": codes,
            "series": [
                [
                    {"cid": code["cid"], "count": matrix[vi][ci]}
                    for ci, code in enumerate(codes)
                ]
                for vi in range(len(columns))
            ],
        },
    }
