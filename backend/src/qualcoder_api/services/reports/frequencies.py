"""Frequency and summary reports: code counts, word clouds, code summary."""

from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.services.reports._shared import _STOPWORDS


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
