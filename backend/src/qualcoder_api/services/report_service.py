"""Aggregation queries for the reports module.

Each function takes an ``AsyncSession`` and returns plain dicts/lists —
no Pydantic models, no API types. Aggregates span the three coding tables
(``code_text``, ``code_image``, ``code_av``) and follow the legacy
QualCoder report semantics. Coding tables are read through the ``*_visible``
views so hidden coders' segments are excluded everywhere (upstream
coder-visibility semantics).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.enums import MediaType

CODING_TABLES = ("code_text_visible", "code_image_visible", "code_av_visible")


async def code_frequencies(session: AsyncSession) -> list[dict]:
    """One row per code: total coding segments across all media types."""
    counts: dict[int, int] = defaultdict(int)
    for sql in (
        "SELECT cid, COUNT(*) FROM code_text_visible GROUP BY cid",
        "SELECT cid, COUNT(*) FROM code_image_visible GROUP BY cid",
        "SELECT cid, COUNT(*) FROM code_av_visible GROUP BY cid",
    ):
        rows = await session.execute(text(sql))
        for cid, n in rows:
            counts[cid] += n

    rows = await session.execute(
        text(
            "SELECT cn.cid, cn.name, COALESCE(cn.color, ''), cc.name "
            "FROM code_name cn LEFT JOIN code_cat cc ON cc.catid = cn.catid"
        )
    )
    result = [
        {"cid": cid, "name": name, "color": color, "category": category or "", "count": counts[cid]}
        for cid, name, color, category in rows
    ]
    result.sort(key=lambda r: (-r["count"], r["name"].lower()))
    return result


async def codes_by_segments(session: AsyncSession) -> list[dict]:
    """One row per ``code_text`` segment with file/code/category names."""
    rows = await session.execute(
        text(
            "SELECT ct.ctid, s.name, cn.name, COALESCE(cc.name, ''), ct.seltext, "
            "COALESCE(ct.owner, ''), COALESCE(ct.date, '') "
            "FROM code_text_visible ct "
            "JOIN source s ON s.id = ct.fid "
            "JOIN code_name cn ON cn.cid = ct.cid "
            "LEFT JOIN code_cat cc ON cc.catid = cn.catid "
            "ORDER BY s.name, ct.pos0"
        )
    )
    return [
        {
            "ctid": ctid,
            "file_name": file_name,
            "code_name": code_name,
            "category": category or "",
            "seltext": seltext or "",
            "owner": owner,
            "date": date,
        }
        for ctid, file_name, code_name, category, seltext, owner, date in rows
    ]


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


async def attributes_report(session: AsyncSession) -> list[dict]:
    """All attribute values with the owning entity's name."""
    rows = await session.execute(
        text(
            "SELECT a.name, COALESCE(a.value, ''), a.attr_type, "
            "COALESCE(s.name, c.name) AS entity_name "
            "FROM attribute a "
            "LEFT JOIN source s ON a.attr_type = 'file' AND s.id = a.id "
            "LEFT JOIN cases c ON a.attr_type = 'case' AND c.caseid = a.id "
            "WHERE (a.attr_type = 'file' AND s.id IS NOT NULL) "
            "OR (a.attr_type = 'case' AND c.caseid IS NOT NULL) "
            "ORDER BY a.name, entity_name"
        )
    )
    return [
        {
            "name": name,
            "value": value,
            "attr_type": attr_type,
            "entity_kind": attr_type,
            "entity_name": entity_name,
        }
        for name, value, attr_type, entity_name in rows
    ]


def _krippendorff_alpha(cell_sets: list[set[tuple[int, int]]]) -> float | None:
    """Krippendorff's alpha for binary nominal ratings, any number of raters.

    Units are the sources, categories the codes: every rater rates each
    cell of the (sources x codes) grid present/absent — a rater "marks"
    exactly the cells they coded, absent everywhere else. Uses the standard
    coincidence-matrix definition (Krippendorff 2011): coincidences are
    pairable-value counts normalized by (m_u - 1) per unit, and expected
    coincidences come from the value marginals with the (n - 1) correction.

    With two raters the formula reduces to the classical two-rater alpha,
    so a pair entry and the all-coders alpha agree.

    Returns None when the data cannot support the computation: fewer than
    two raters, an empty grid, or a degenerate margin (no expected
    disagreement).
    """
    cells: set[tuple[int, int]] = set()
    for cell_set in cell_sets:
        cells |= cell_set
    n_coders = len(cell_sets)
    fids = {fid for fid, _ in cells}
    cids = {cid for _, cid in cells}
    if n_coders < 2 or not fids or not cids:
        return None

    # Unnormalized coincidence counts over the full grid: o11/o00 count
    # same-value rater pairs, o01 counts discordant pairs (o10 = o01).
    o11 = o00 = o01 = 0
    for fid in fids:
        for cid in cids:
            ones = sum(1 for cell_set in cell_sets if (fid, cid) in cell_set)
            zeros = n_coders - ones
            o11 += ones * (ones - 1)
            o00 += zeros * (zeros - 1)
            o01 += ones * zeros
    total = o11 + o00 + 2 * o01
    if total == 0:
        return None

    # Every unit carries n_coders ratings, so the pairable normalization
    # divides by (n_coders - 1): the coincidence matrix sums to n (the
    # number of ratings) and the value marginals are o0/(m-1), o1/(m-1).
    # alpha = 1 - Do/De with
    #   Do = 2*o01/(m-1) and De = 2*n0*n1/(n-1), n = total/(m-1)
    # which simplifies to the closed form below.
    o0 = o00 + o01
    o1 = o01 + o11
    if o0 == 0 or o1 == 0:
        return None
    n = total / (n_coders - 1)
    do = 2 * o01 / (n_coders - 1)
    de = 2 * (o0 / (n_coders - 1)) * (o1 / (n_coders - 1)) / (n - 1)
    if de == 0:
        return None
    return 1 - do / de


def _pair_report(
    cells_a: set[tuple[int, int]], cells_b: set[tuple[int, int]]
) -> dict:
    """Cohen's Kappa, Krippendorff's Alpha and Gwet's AC1 for two coders.

    The unit space is the union of both coders' (source, code) cells; each
    cell is rated present/absent by each coder. Returns the contingency
    counts (both/only_a/only_b/neither) plus the three measures, all None
    when there is no data.
    """
    file_ids = {fid for fid, _ in cells_a} | {fid for fid, _ in cells_b}
    code_ids = {cid for _, cid in cells_a} | {cid for _, cid in cells_b}
    n_units = len(file_ids)
    n_categories = len(code_ids)
    n_pairs = n_units * n_categories
    if n_units == 0 or n_categories == 0:
        return {
            "n_units": n_units,
            "n_categories": n_categories,
            "n_pairs": 0,
            "both": 0,
            "only_a": 0,
            "only_b": 0,
            "neither": 0,
            "kappa": None,
            "krippendorff": None,
            "gwet_ac1": None,
        }

    both = len(cells_a & cells_b)
    only_a = len(cells_a - cells_b)
    only_b = len(cells_b - cells_a)
    neither = n_pairs - both - only_a - only_b

    po = (both + neither) / n_pairs
    # Cohen's kappa, chance agreement from the marginals.
    a_marked = both + only_a
    b_marked = both + only_b
    pe = (a_marked * b_marked + (n_pairs - a_marked) * (n_pairs - b_marked)) / (n_pairs * n_pairs)
    kappa = (po - pe) / (1 - pe) if pe != 1 else None

    # Krippendorff's alpha, binary nominal, via the coincidence matrix —
    # identical to the all-coders alpha restricted to this pair.
    krippendorff = _krippendorff_alpha([cells_a, cells_b])

    # Gwet's AC1: chance agreement from the mean rating probability.
    p_plus = (a_marked + b_marked) / (2 * n_pairs)
    pe_gwet = 2 * p_plus * (1 - p_plus)
    gwet_ac1 = (po - pe_gwet) / (1 - pe_gwet) if pe_gwet != 1 else None

    return {
        "n_units": n_units,
        "n_categories": n_categories,
        "n_pairs": n_pairs,
        "both": both,
        "only_a": only_a,
        "only_b": only_b,
        "neither": neither,
        "kappa": round(kappa, 4) if kappa is not None else None,
        "krippendorff": round(krippendorff, 4) if krippendorff is not None else None,
        "gwet_ac1": round(gwet_ac1, 4) if gwet_ac1 is not None else None,
    }


def _pairwise_summary(pairs: list[dict]) -> dict:
    """Mean/min/max of each agreement measure across coder pairs."""
    keys = ("kappa", "krippendorff", "gwet_ac1")
    mean: dict[str, float | None] = {}
    minimum: dict[str, float | None] = {}
    maximum: dict[str, float | None] = {}
    for key in keys:
        values = [pair[key] for pair in pairs if pair[key] is not None]
        mean[key] = round(sum(values) / len(values), 4) if values else None
        minimum[key] = min(values) if values else None
        maximum[key] = max(values) if values else None
    return {"mean": mean, "min": minimum, "max": maximum}


async def interrater(
    session: AsyncSession,
    coder_a: str,
    coder_b: str,
    coders: list[str] | None = None,
) -> dict:
    """Interrater reliability over any number of coders.

    Each selected coder rates every (source, code) cell present/absent.
    ``coders`` (optional) restricts the comparison — default: every coder
    in the project with codings. ``coder_a``/``coder_b`` anchor the
    backward-compatible contingency fields (the frontend passes the first
    two selected coders).

    Returns Krippendorff's Alpha over ALL selected coders plus, per
    unordered coder pair, Cohen's Kappa, Krippendorff's Alpha and Gwet's
    AC1 with the contingency detail, and the mean/min/max of each measure
    across pairs.
    """
    if coder_a == coder_b:
        raise ValueError("choose two different coders")

    # owner → set of coded (source, code) cells per coder.
    cells_by_coder: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for tbl, file_col in (
        ("code_text_visible", "fid"),
        ("code_image_visible", "id"),
        ("code_av_visible", "id"),
    ):
        rows = await session.execute(
            text(
                f"SELECT {file_col}, cid, COALESCE(owner, '') FROM {tbl} "
                f"WHERE {file_col} IS NOT NULL AND cid IS NOT NULL"
            )
        )
        for fid, cid, owner in rows:
            cells_by_coder[owner].add((fid, cid))

    if coders is not None:
        selected = list(dict.fromkeys(coders))
        if len(selected) < 2:
            raise ValueError("choose at least two coders")
    else:
        # Default: all project coders with codings (null-owner codings
        # belong to no coder, mirroring the coder-comparison report).
        selected = sorted(name for name in cells_by_coder if name != "")

    pairs = [
        {
            "coder_a": selected[i],
            "coder_b": selected[j],
            **_pair_report(cells_by_coder[selected[i]], cells_by_coder[selected[j]]),
        }
        for i in range(len(selected))
        for j in range(i + 1, len(selected))
    ]
    summary = _pairwise_summary(pairs)
    alpha = _krippendorff_alpha([cells_by_coder[c] for c in selected])

    return {
        "coders": selected,
        "n_coders": len(selected),
        "alpha": round(alpha, 4) if alpha is not None else None,
        # Anchor pair: backward-compatible contingency fields.
        "coder_a": coder_a,
        "coder_b": coder_b,
        **_pair_report(cells_by_coder[coder_a], cells_by_coder[coder_b]),
        "pairs": pairs,
        "pairwise_mean": summary["mean"],
        "pairwise_min": summary["min"],
        "pairwise_max": summary["max"],
    }


# ----------------------------------------------------------------------
# Upstream parity reports (code-in-all-files, summaries, comparisons,
# relations, word cloud data, charts, codebook)
# ----------------------------------------------------------------------

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


async def code_summary(session: AsyncSession, cid: int) -> dict:
    """Summary report for one code: counts, files, memo (report_code_summary)."""
    row = (
        await session.execute(
            text("SELECT name, COALESCE(memo, ''), color FROM code_name WHERE cid = :cid"),
            {"cid": cid},
        )
    ).first()
    if row is None:
        raise KeyError("code not found")
    name, memo, color = row

    per_media: dict[str, int] = {}
    for tbl, key, _col in (
        ("code_text_visible", "text", "fid"),
        ("code_image_visible", "image", "id"),
        ("code_av_visible", "av", "id"),
    ):
        n = (
            await session.execute(
                text(f"SELECT COUNT(*) FROM {tbl} WHERE cid = :cid"), {"cid": cid}
            )
        ).scalar_one()
        per_media[key] = n

    files = (
        await session.execute(
            text(
                "SELECT s.name FROM source s WHERE s.id IN ("
                "SELECT fid FROM code_text_visible WHERE cid = :cid "
                "UNION SELECT id FROM code_image_visible WHERE cid = :cid "
                "UNION SELECT id FROM code_av_visible WHERE cid = :cid"
                ") ORDER BY s.name"
            ),
            {"cid": cid},
        )
    ).all()

    categories = (
        await session.execute(
            text(
                "SELECT cc.name FROM code_cat cc "
                "JOIN code_name cn ON cn.catid = cc.catid WHERE cn.cid = :cid"
            ),
            {"cid": cid},
        )
    ).all()

    return {
        "cid": cid,
        "name": name,
        "memo": memo,
        "color": color or "",
        "categories": [c[0] for c in categories],
        "counts": per_media,
        "total": sum(per_media.values()),
        "files": [f[0] for f in files],
        "file_count": len(files),
    }


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


# English stopword list for the word-frequency report (subset of the legacy
# stopwords.py; enough for the word cloud without shipping the full dataset).
_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "can", "could", "did", "do", "does", "doing",
    "down", "during", "each", "few", "for", "from", "further", "had", "has", "have",
    "having", "he", "her", "here", "hers", "herself", "him", "himself", "his", "how",
    "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more",
    "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once",
    "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own", "same",
    "she", "should", "so", "some", "such", "than", "that", "the", "their", "theirs",
    "them", "themselves", "then", "there", "these", "they", "this", "those",
    "through", "to", "too", "under", "until", "up", "very", "was", "we", "were",
    "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with",
    "you", "your", "yours", "yourself", "yourselves",
}


async def word_frequencies(
    session: AsyncSession,
    source_id: int | None = None,
    limit: int = 100,
    use_stopwords: bool = True,
) -> list[dict]:
    """Word frequency list for the word cloud (simple_wordcloud).

    Text sources only; ``source_id`` restricts to one file. Words are
    lowercased and stripped of punctuation; a built-in English stopword list
    filters function words unless ``use_stopwords`` is false.
    """
    rows = await session.execute(
        text(
            "SELECT id, name, fulltext FROM source WHERE fulltext IS NOT NULL AND "
            "(mediapath IS NULL OR mediapath LIKE '/docs/%' OR mediapath LIKE 'docs:%')"
        )
    )
    counts: dict[str, int] = defaultdict(int)
    for fid, _name, fulltext in rows:
        if source_id is not None and fid != source_id:
            continue
        for word in re.findall(r"[^\W\d_]+(?:[''-][^\W\d_]+)*", (fulltext or "").lower()):
            if use_stopwords and word in _STOPWORDS:
                continue
            counts[word] += 1
    result = [
        {"word": word, "count": count}
        for word, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return result[: max(1, min(limit, 5000))]


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
