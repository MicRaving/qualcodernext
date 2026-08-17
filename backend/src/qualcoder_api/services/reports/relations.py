"""Relation reports: cooccurrence, code relations, exact matches."""

from __future__ import annotations

from collections import defaultdict
from typing import cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def cooccurrence(session: AsyncSession) -> dict:
    """Code x code matrix: distinct files shared by each code pair."""
    codes = [
        {"cid": cid, "name": name, "color": color or ""}
        for cid, name, color in await session.execute(
            text("SELECT cid, name, COALESCE(color, '') FROM code_name ORDER BY name")
        )
    ]

    files_per_code: dict[int, set[int]] = defaultdict(set)
    rows = await session.execute(text("SELECT DISTINCT fid, cid FROM code_text_visible"))
    for fid, cid in rows:
        files_per_code[cid].add(fid)

    file_sets = [files_per_code[c["cid"]] for c in codes]
    counts = [
        [len(file_sets[i] & file_sets[j]) for j in range(len(codes))] for i in range(len(codes))
    ]
    return {"codes": codes, "counts": counts}


async def code_relations(session: AsyncSession, owner: str | None = None) -> dict:
    """Code crossovers for one coder (report_relations).

    A crossover is a text segment of code X whose span overlaps a segment of
    code Y (same file, same owner). The owner defaults to the current coder;
    pass ``owner="*"`` for all coders.
    """
    rows = await session.execute(
        text(
            "SELECT ct.fid, ct.cid, cn.name, ct.pos0, ct.pos1, ct.owner "
            "FROM code_text_visible ct JOIN code_name cn ON cn.cid = ct.cid "
            "ORDER BY ct.fid, ct.pos0"
        )
    )
    segments: list[dict] = []
    for fid, cid, name, pos0, pos1, owner_ in rows:
        if owner and owner != "*" and owner_ != owner:
            continue
        segments.append(
            {"fid": fid, "cid": cid, "name": name or "", "pos0": pos0, "pos1": pos1,
             "owner": owner_ or ""}
        )
    by_file: dict[int, list[dict]] = defaultdict(list)
    for segment in segments:
        by_file[segment["fid"]].append(segment)

    relations: dict[tuple[str, str], dict] = {}
    for file_segments in by_file.values():
        file_segments.sort(key=lambda s: s["pos0"])
        for i, seg_a in enumerate(file_segments):
            for seg_b in file_segments[i + 1 :]:
                if seg_b["pos0"] >= seg_a["pos1"]:
                    break
                if seg_a["cid"] == seg_b["cid"]:
                    continue
                pair = (
                    (seg_a["name"], seg_b["name"])
                    if seg_a["name"] <= seg_b["name"]
                    else (seg_b["name"], seg_a["name"])
                )
                rel = relations.setdefault(
                    pair, {"code_a": pair[0], "code_b": pair[1], "count": 0}
                )
                rel["count"] += 1
    result = sorted(relations.values(), key=lambda r: (-r["count"], r["code_a"].lower()))
    return {"owner": owner or "", "relations": result}


async def exact_matches(session: AsyncSession) -> list[dict]:
    """Identical ``seltext`` coded at least twice, with distinct files."""
    counts: dict[str, int] = defaultdict(int)
    files: dict[str, set[str]] = defaultdict(set)
    rows = await session.execute(
        text(
            "SELECT ct.seltext, s.name FROM code_text_visible ct "
            "JOIN source s ON s.id = ct.fid"
        )
    )
    for seltext, file_name in rows:
        counts[seltext] += 1
        files[seltext].add(file_name)

    result = [
        {"seltext": seltext, "count": counts[seltext], "files": sorted(files[seltext])}
        for seltext in counts
        if counts[seltext] >= 2
    ]
    result.sort(key=lambda r: (-cast(int, r["count"]), str(cast(str, r["seltext"])).lower()))
    return result
