"""Shared constants and helpers for the reports subpackage."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CODING_TABLES = ("code_text_visible", "code_image_visible", "code_av_visible")

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


async def _attr_definition(session: AsyncSession, attr_name: str) -> dict | None:
    """Declared scope/value type of an attribute type, if it exists."""
    row = (
        await session.execute(
            text(
                "SELECT caseOrFile, COALESCE(valuetype, 'text') FROM attribute_type "
                "WHERE name = :name"
            ),
            {"name": attr_name},
        )
    ).first()
    if row is None:
        return None
    return {"scope": row[0] or "file", "value_type": row[1] or "text"}


async def _attr_scope(session: AsyncSession, attr_name: str) -> str:
    """Scope ('case' or 'file') of an attribute: declared type first, else
    the scope its stored values use."""
    definition = await _attr_definition(session, attr_name)
    if definition is not None:
        return definition["scope"]
    row = (
        await session.execute(
            text("SELECT attr_type FROM attribute WHERE name = :name LIMIT 1"),
            {"name": attr_name},
        )
    ).first()
    return row[0] if row and row[0] in ("case", "file") else "file"


async def _units_with_values(
    session: AsyncSession, scope: str, attr_name: str
) -> tuple[list[dict], dict[int, str]]:
    """Units of the given scope plus their non-empty attribute values.

    Returns ``(units, values)`` where units is every case/file (id + name,
    sorted by name) and values maps unit id -> attribute value for the
    units that actually carry one.
    """
    if scope == "case":
        unit_rows = await session.execute(
            text("SELECT caseid, name FROM cases ORDER BY name")
        )
        units = [{"id": caseid, "name": name} for caseid, name in unit_rows]
    else:
        unit_rows = await session.execute(
            text("SELECT id, name FROM source ORDER BY name")
        )
        units = [{"id": fid, "name": name} for fid, name in unit_rows]
    rows = await session.execute(
        text(
            "SELECT id, value FROM attribute "
            "WHERE name = :name AND attr_type = :scope"
        ),
        {"name": attr_name, "scope": scope},
    )
    values: dict[int, str] = {}
    for entity_id, value in rows:
        if value and str(value).strip():
            values[entity_id] = str(value)
    return units, values


async def _unit_coding_sets(
    session: AsyncSession, scope: str
) -> dict[int, set[int]]:
    """Unit id -> set of code ids present in its codings (all media types).

    Case scope joins through ``case_text`` (a case is coded via its linked
    files); file scope counts the source's own codings.
    """
    sets: dict[int, set[int]] = defaultdict(set)
    if scope == "case":
        queries = (
            "SELECT cst.caseid, ct.cid FROM code_text_visible ct "
            "JOIN case_text cst ON cst.fid = ct.fid WHERE ct.cid IS NOT NULL",
            "SELECT cst.caseid, ci.cid FROM code_image_visible ci "
            "JOIN case_text cst ON cst.fid = ci.id WHERE ci.cid IS NOT NULL",
            "SELECT cst.caseid, ca.cid FROM code_av_visible ca "
            "JOIN case_text cst ON cst.fid = ca.id WHERE ca.cid IS NOT NULL",
        )
    else:
        queries = (
            "SELECT fid, cid FROM code_text_visible WHERE cid IS NOT NULL",
            "SELECT id, cid FROM code_image_visible WHERE cid IS NOT NULL",
            "SELECT id, cid FROM code_av_visible WHERE cid IS NOT NULL",
        )
    for sql in queries:
        for unit_id, cid in await session.execute(text(sql)):
            if unit_id is not None:
                sets[unit_id].add(cid)
    return sets


async def _unit_coding_counts(
    session: AsyncSession, scope: str
) -> dict[tuple[int, int], int]:
    """(unit id, cid) -> number of coding segments across all media types."""
    counts: dict[tuple[int, int], int] = defaultdict(int)
    if scope == "case":
        queries = (
            "SELECT cst.caseid, ct.cid, COUNT(*) FROM code_text_visible ct "
            "JOIN case_text cst ON cst.fid = ct.fid WHERE ct.cid IS NOT NULL "
            "GROUP BY cst.caseid, ct.cid",
            "SELECT cst.caseid, ci.cid, COUNT(*) FROM code_image_visible ci "
            "JOIN case_text cst ON cst.fid = ci.id WHERE ci.cid IS NOT NULL "
            "GROUP BY cst.caseid, ci.cid",
            "SELECT cst.caseid, ca.cid, COUNT(*) FROM code_av_visible ca "
            "JOIN case_text cst ON cst.fid = ca.id WHERE ca.cid IS NOT NULL "
            "GROUP BY cst.caseid, ca.cid",
        )
    else:
        queries = (
            "SELECT fid, cid, COUNT(*) FROM code_text_visible "
            "WHERE cid IS NOT NULL GROUP BY fid, cid",
            "SELECT id, cid, COUNT(*) FROM code_image_visible "
            "WHERE cid IS NOT NULL GROUP BY id, cid",
            "SELECT id, cid, COUNT(*) FROM code_av_visible "
            "WHERE cid IS NOT NULL GROUP BY id, cid",
        )
    for sql in queries:
        for unit_id, cid, n in await session.execute(text(sql)):
            if unit_id is not None:
                counts[(unit_id, cid)] += n
    return counts


def _sorted_values(values: set[str]) -> list[str]:
    """Distinct attribute values sorted; numeric-aware when all parse."""
    items = sorted(values, key=str.lower)
    try:
        parsed = sorted((float(v), v) for v in items)
        return [v for _, v in parsed]
    except (TypeError, ValueError):
        return items


def _crosstab_stats(
    matrix: list[list[int]], columns: list[str]
) -> dict:
    """chi-square + Cramér's V over a code-presence x value-count matrix.

    Zero rows/columns are dropped before computing (they make the expected
    counts degenerate); the result stays None when the table cannot support
    the test.
    """
    empty: dict[str, object] = {
        "chi2": None, "df": None, "p": None, "cramers_v": None,
        "yates": False, "expected": [], "n": None,
        "note": "need at least two codes and two attribute values",
    }
    if len(matrix) < 2 or len(columns) < 2:
        return empty
    n_cols = len(columns)
    zero_cols = {
        c for c in range(n_cols)
        if sum(row[c] for row in matrix) == 0
    }
    table = [
        [row[c] for c in range(n_cols) if c not in zero_cols]
        for row in matrix
        if sum(row) > 0
    ]
    if len(table) < 2 or (table and len(table[0]) < 2):
        return empty
    try:
        from qualcoder_api.services import stats_service

        result = stats_service.chi_square(table)
    except ValueError as err:
        return {
            "chi2": None, "df": None, "p": None, "cramers_v": None,
            "yates": False, "expected": [], "n": None, "note": str(err),
        }
    return {
        "chi2": result["chi2"],
        "df": result["df"],
        "p": result["p"],
        "yates": result["yates"],
        "expected": result["expected"],
        "cramers_v": stats_service.cramers_v(table, result["chi2"]),
        "n": result["n"],
        "note": None,
    }
