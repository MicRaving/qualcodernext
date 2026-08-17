"""Chart data queries and codebook export."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def charts_data(session: AsyncSession, kind: str) -> dict:
    """Chart datasets (view_charts.py data queries).

    ``kind`` is one of: ``cumulative``, ``stacked-files``, ``stacked-cases``,
    ``bar-frequency``, ``bar-volume``, ``heatmap-file-code``, ``heatmap-case``.
    """
    codes = [
        {"cid": cid, "name": name, "color": color or ""}
        for cid, name, color in await session.execute(
            text("SELECT cid, name, COALESCE(color, '') FROM code_name ORDER BY name")
        )
    ]

    if kind == "cumulative":
        # Total segments per code, accumulated over the ordered code list.
        freq_counts: dict[int, int] = defaultdict(int)
        for tbl in ("code_text_visible", "code_image_visible", "code_av_visible"):
            for cid, n in await session.execute(
                text(f"SELECT cid, COUNT(*) FROM {tbl} GROUP BY cid")
            ):
                freq_counts[cid] += n
        running = 0
        cumulative_series: list[dict] = []
        for code in sorted(codes, key=lambda c: -freq_counts.get(c["cid"], 0)):
            running += freq_counts.get(code["cid"], 0)
            cumulative_series.append(
                {"cid": code["cid"], "name": code["name"], "color": code["color"],
                 "count": freq_counts.get(code["cid"], 0), "cumulative": running}
            )
        return {"kind": kind, "codes": cumulative_series}

    if kind in ("stacked-files", "stacked-cases", "bar-frequency", "bar-volume"):
        if kind == "stacked-files":
            labels = [
                {"fid": fid, "name": name}
                for fid, name in await session.execute(
                    text("SELECT s.id, s.name FROM source s ORDER BY s.name")
                )
            ]
            file_counts: dict[tuple[int, int], int] = defaultdict(int)
            for fid, cid, n in await session.execute(
                text(
                    "SELECT fid, cid, COUNT(*) FROM code_text_visible "
                    "GROUP BY fid, cid"
                )
            ):
                file_counts[(fid, cid)] += n
            file_series: list[list[dict]] = [
                [
                    {"cid": code["cid"], "count": file_counts.get((label["fid"], code["cid"]), 0)}
                    for code in codes
                ]
                for label in labels
            ]
            return {"kind": kind, "labels": labels, "codes": codes, "series": file_series}
        if kind == "stacked-cases":
            labels = [
                {"caseid": caseid, "name": name}
                for caseid, name in await session.execute(
                    text("SELECT caseid, name FROM cases ORDER BY name")
                )
            ]
            # One grouped join instead of a per-case query: case -> files ->
            # per-file coding counts, all in a single pass.
            case_fids: dict[int, list[int]] = defaultdict(list)
            for caseid, fid in await session.execute(text("SELECT caseid, fid FROM case_text")):
                case_fids[caseid].append(fid)
            case_counts: dict[tuple[int, int], int] = defaultdict(int)
            for fid, cid, n in await session.execute(
                text(
                    "SELECT ct.fid, ct.cid, COUNT(*) FROM code_text_visible ct "
                    "JOIN case_text cst ON cst.fid = ct.fid GROUP BY ct.fid, ct.cid"
                )
            ):
                case_counts[(fid, cid)] += n
            case_series: list[list[dict]] = []
            for label in labels:
                fids = case_fids.get(label["caseid"], [])
                case_series.append(
                    [
                        {
                            "cid": code["cid"],
                            "count": sum(case_counts.get((fid, code["cid"]), 0) for fid in fids),
                        }
                        for code in codes
                    ]
                )
            return {"kind": kind, "labels": labels, "codes": codes, "series": case_series}
        # bar-frequency / bar-volume: single-row-per-code totals.
        freq: dict[int, int] = defaultdict(int)
        volume: dict[int, int] = defaultdict(int)
        for cid, n in await session.execute(
            text("SELECT cid, COUNT(*) FROM code_text_visible GROUP BY cid")
        ):
            freq[cid] += n
        for cid, pos0, pos1 in await session.execute(
            text("SELECT cid, pos0, pos1 FROM code_text_visible WHERE pos1 > pos0")
        ):
            volume[cid] += int(pos1 or 0) - int(pos0 or 0)
        for cid, n in await session.execute(
            text("SELECT cid, COUNT(*) FROM code_image_visible GROUP BY cid")
        ):
            freq[cid] += n
        for cid, w, h in await session.execute(
            text("SELECT cid, width, height FROM code_image_visible WHERE width > 0 AND height > 0")
        ):
            volume[cid] += int(w or 0) * int(h or 0)
        for cid, n in await session.execute(
            text("SELECT cid, COUNT(*) FROM code_av_visible GROUP BY cid")
        ):
            freq[cid] += n
        for cid, pos0, pos1 in await session.execute(
            text("SELECT cid, pos0, pos1 FROM code_av_visible WHERE pos1 > pos0")
        ):
            volume[cid] += int(pos1 or 0) - int(pos0 or 0)
        rows = [
            {
                "cid": code["cid"],
                "name": code["name"],
                "color": code["color"],
                "value": freq.get(code["cid"], 0) if kind == "bar-frequency"
                else volume.get(code["cid"], 0),
            }
            for code in codes
        ]
        rows.sort(key=lambda r: -r["value"])
        return {"kind": kind, "rows": rows[:200]}

    if kind == "heatmap-file-code":
        files = [
            {"fid": fid, "name": name}
            for fid, name in await session.execute(
                text(
                    "SELECT s.id, s.name FROM source s "
                    "WHERE s.id IN (SELECT DISTINCT fid FROM code_text_visible) ORDER BY s.name"
                )
            )
        ]
        file_code_counts: dict[tuple[int, int], int] = defaultdict(int)
        for fid, cid, n in await session.execute(
            text("SELECT fid, cid, COUNT(*) FROM code_text_visible GROUP BY fid, cid")
        ):
            file_code_counts[(fid, cid)] += n
        for fid, cid, n in await session.execute(
            text("SELECT id, cid, COUNT(*) FROM code_image_visible GROUP BY id, cid")
        ):
            file_code_counts[(fid, cid)] += n
        for fid, cid, n in await session.execute(
            text("SELECT id, cid, COUNT(*) FROM code_av_visible GROUP BY id, cid")
        ):
            file_code_counts[(fid, cid)] += n
        matrix_counts = [
            [file_code_counts.get((f["fid"], c["cid"]), 0) for c in codes] for f in files
        ]
        return {"kind": kind, "files": files, "codes": codes, "counts": matrix_counts}

    if kind == "heatmap-case":
        cases = [
            {"caseid": caseid, "name": name}
            for caseid, name in await session.execute(
                text("SELECT caseid, name FROM cases ORDER BY name")
            )
        ]
        # Single grouped join (case -> file -> coding counts) instead of a
        # per-case, per-file query.
        case_code_counts: dict[tuple[int, int], int] = defaultdict(int)
        for caseid, cid, n in await session.execute(
            text(
                "SELECT cst.caseid, ct.cid, COUNT(*) FROM code_text_visible ct "
                "JOIN case_text cst ON cst.fid = ct.fid GROUP BY cst.caseid, ct.cid"
            )
        ):
            case_code_counts[(caseid, cid)] += n
        matrix_counts = [
            [case_code_counts.get((case["caseid"], c["cid"]), 0) for c in codes] for case in cases
        ]
        return {"kind": kind, "cases": cases, "codes": codes, "counts": matrix_counts}

    raise ValueError(f"unknown chart kind: {kind}")


async def codebook_plain(session: AsyncSession, include_memos: bool = False) -> str:
    """Plain-text codebook export (``category>>subcategory>>code`` lines).

    Mirrors the legacy ImportPlainTextCodes round-trip format so the export
    can be imported back.
    """
    cats = [
        {"catid": catid, "name": name, "supercatid": supercatid}
        for catid, name, supercatid in await session.execute(
            text("SELECT catid, name, supercatid FROM code_cat")
        )
    ]
    codes = [
        {"cid": cid, "name": name, "memo": memo, "catid": catid, "supercid": supercid}
        for cid, name, memo, catid, supercid in await session.execute(
            text("SELECT cid, name, COALESCE(memo, ''), catid, supercid FROM code_name")
        )
    ]
    lines: list[str] = []

    def cat_path(catid: int | None) -> str:
        parts: list[str] = []
        seen: set[int] = set()
        current = catid
        while current is not None and current not in seen:
            seen.add(current)
            item = next((c for c in cats if c["catid"] == current), None)
            if item is None:
                break
            parts.append(item["name"])
            current = item["supercatid"]
        return ">>".join(reversed(parts))

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for code in codes:
        if code["supercid"] is not None:
            parent = next((c for c in codes if c["cid"] == code["supercid"]), None)
            path = f"{cat_path(code['catid'])}>>{parent['name']}" if parent else cat_path(code["catid"])
        else:
            path = cat_path(code["catid"])
        by_cat[path].append(code)

    for path in sorted(by_cat, key=lambda p: p.lower()):
        for code in sorted(by_cat[path], key=lambda c: c["name"].lower()):
            memo = f"\t{code['memo']}" if include_memos and code["memo"] else ""
            full = f"{path}>>{code['name']}" if path else code["name"]
            lines.append(f"{full}{memo}")
    return "\n".join(lines)
