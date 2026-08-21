"""Literal/regex full-text search across project entities.

Supported entity types (each a distinct searchable scope):

* ``files`` — sources: name, memo, fulltext
* ``codes`` — ``code_name``: name, memo
* ``categories`` — ``code_cat``: name, memo
* ``cases`` — ``cases``: name, memo
* ``journal`` — ``journal``: name, jentry
* ``memos`` — the memo/jentry fields of the named entities (a hit names the
  owning entity via ``ref_kind``/``ref_id``)
* ``attributes`` — ``attribute``: name, value
* ``comments`` — ``comment``: body

The optional category filter restricts **file** results to sources carrying a
text coding under the selected category subtree (the category id itself plus
all descendant ``code_cat`` ids). It does not apply to the other entity
types.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import CodeRepository

HITS_PER_SOURCE = 5
CONTEXT_BEFORE = 60
CONTEXT_AFTER = 120

#: The supported entity types, in stable display order.
ALL_ENTITIES = (
    "files",
    "codes",
    "categories",
    "cases",
    "journal",
    "memos",
    "attributes",
    "comments",
)


async def category_subtree_ids(db: AsyncSession, category_id: int) -> set[int]:
    """Category id plus every descendant ``code_cat`` id (via ``supercatid``)."""
    categories = await CodeRepository(db).list_categories()
    subtree = {category_id}
    changed = True
    while changed:
        changed = False
        for cat in categories:
            if cat.supercatid in subtree and cat.catid not in subtree:
                subtree.add(cat.catid)
                changed = True
    return subtree


async def category_source_ids(
    db: AsyncSession, category_id: int, restrict: list[int] | None = None
) -> list[int]:
    """Source ids with a text coding under the category subtree.

    ``restrict`` narrows the result to a caller-provided id list (used by the
    semantic-search category filter to intersect with a files selection).
    """
    subtree = await category_subtree_ids(db, category_id)
    rows = await db.execute(
        select(tables.code_text.c.fid)
        .join(tables.code_name, tables.code_name.c.cid == tables.code_text.c.cid)
        .where(tables.code_name.c.catid.in_(subtree))
    )
    allowed = {row[0] for row in rows}
    if restrict is not None:
        allowed &= set(restrict)
    return sorted(allowed)


def _scan_text(compiled: re.Pattern[str], text: str) -> tuple[int, list[dict]]:
    """Count matches and collect (capped) context hits for one text field."""
    hits: list[dict] = []
    match_count = 0
    for m in compiled.finditer(text):
        match_count += 1
        if len(hits) < HITS_PER_SOURCE:
            start = max(0, m.start() - CONTEXT_BEFORE)
            end = min(len(text), m.end() + CONTEXT_AFTER)
            hits.append(
                {
                    "pos0": m.start(),
                    "pos1": m.end(),
                    # Match offsets relative to the context string — the
                    # frontend highlights the exact matched part in yellow.
                    "rel0": m.start() - start,
                    "rel1": m.end() - start,
                    "context": text[start:end],
                }
            )
    return match_count, hits


def _scan_fields(compiled: re.Pattern[str], fields: dict[str, str]) -> tuple[int, list[dict]]:
    """Scan several named text fields; hit positions/context stay per field."""
    match_count = 0
    hits: list[dict] = []
    for text in fields.values():
        count, field_hits = _scan_text(compiled, text)
        match_count += count
        hits.extend(field_hits)
    return match_count, hits[:HITS_PER_SOURCE]


async def _search_files(
    db: AsyncSession, compiled: re.Pattern[str], category_id: int | None
) -> list[dict]:
    rows = await db.execute(
        select(
            tables.source.c.id,
            tables.source.c.name,
            tables.source.c.mediapath,
            tables.source.c.fulltext,
            tables.source.c.memo,
        )
    )
    allowed = (
        set(await category_source_ids(db, category_id))
        if category_id is not None
        else None
    )
    results: list[dict] = []
    for sid, name, mediapath, fulltext, memo in rows:
        count, hits = _scan_fields(
            compiled, {"name": name or "", "memo": memo or "", "fulltext": fulltext or ""}
        )
        if count == 0:
            continue
        if allowed is not None and sid not in allowed:
            continue
        results.append(
            {
                "kind": "file",
                "id": sid,
                "name": name,
                "mediapath": mediapath or "",
                "match_count": count,
                "hits": hits,
                "source_id": sid,
                "ref_kind": None,
                "ref_id": None,
            }
        )
    return results


async def _search_codes(db: AsyncSession, compiled: re.Pattern[str]) -> list[dict]:
    rows = await db.execute(
        select(tables.code_name.c.cid, tables.code_name.c.name, tables.code_name.c.memo)
    )
    results: list[dict] = []
    for cid, name, memo in rows:
        count, hits = _scan_fields(compiled, {"name": name or "", "memo": memo or ""})
        if count == 0:
            continue
        results.append(
            {
                "kind": "code",
                "id": cid,
                "name": name,
                "mediapath": "",
                "match_count": count,
                "hits": hits,
                "source_id": None,
                "ref_kind": None,
                "ref_id": None,
            }
        )
    return results


async def _search_categories(db: AsyncSession, compiled: re.Pattern[str]) -> list[dict]:
    rows = await db.execute(
        select(tables.code_cat.c.catid, tables.code_cat.c.name, tables.code_cat.c.memo)
    )
    results: list[dict] = []
    for catid, name, memo in rows:
        count, hits = _scan_fields(compiled, {"name": name or "", "memo": memo or ""})
        if count == 0:
            continue
        results.append(
            {
                "kind": "category",
                "id": catid,
                "name": name,
                "mediapath": "",
                "match_count": count,
                "hits": hits,
                "source_id": None,
                "ref_kind": None,
                "ref_id": None,
            }
        )
    return results


async def _search_cases(db: AsyncSession, compiled: re.Pattern[str]) -> list[dict]:
    rows = await db.execute(
        select(tables.cases.c.caseid, tables.cases.c.name, tables.cases.c.memo)
    )
    results: list[dict] = []
    for caseid, name, memo in rows:
        count, hits = _scan_fields(compiled, {"name": name or "", "memo": memo or ""})
        if count == 0:
            continue
        results.append(
            {
                "kind": "case",
                "id": caseid,
                "name": name,
                "mediapath": "",
                "match_count": count,
                "hits": hits,
                "source_id": None,
                "ref_kind": None,
                "ref_id": None,
            }
        )
    return results


async def _search_journal(db: AsyncSession, compiled: re.Pattern[str]) -> list[dict]:
    rows = await db.execute(
        select(tables.journal.c.jid, tables.journal.c.name, tables.journal.c.jentry)
    )
    results: list[dict] = []
    for jid, name, jentry in rows:
        count, hits = _scan_fields(compiled, {"name": name or "", "jentry": jentry or ""})
        if count == 0:
            continue
        results.append(
            {
                "kind": "journal",
                "id": jid,
                "name": name,
                "mediapath": "",
                "match_count": count,
                "hits": hits,
                "source_id": None,
                "ref_kind": None,
                "ref_id": None,
            }
        )
    return results


async def _search_memos(db: AsyncSession, compiled: re.Pattern[str]) -> list[dict]:
    """Search memo/jentry fields; each hit names its owning entity."""
    results: list[dict] = []
    memos: list[tuple[str, int, str, dict]] = []

    source_rows = await db.execute(
        select(tables.source.c.id, tables.source.c.name, tables.source.c.memo)
    )
    for sid, name, memo in source_rows:
        if memo:
            memos.append(("file", sid, name, {"memo": memo or ""}))

    code_rows = await db.execute(
        select(tables.code_name.c.cid, tables.code_name.c.name, tables.code_name.c.memo)
    )
    for cid, name, memo in code_rows:
        if memo:
            memos.append(("code", cid, name, {"memo": memo or ""}))

    cat_rows = await db.execute(
        select(tables.code_cat.c.catid, tables.code_cat.c.name, tables.code_cat.c.memo)
    )
    for catid, name, memo in cat_rows:
        if memo:
            memos.append(("category", catid, name, {"memo": memo or ""}))

    case_rows = await db.execute(
        select(tables.cases.c.caseid, tables.cases.c.name, tables.cases.c.memo)
    )
    for caseid, name, memo in case_rows:
        if memo:
            memos.append(("case", caseid, name, {"memo": memo or ""}))

    journal_rows = await db.execute(
        select(tables.journal.c.jid, tables.journal.c.name, tables.journal.c.jentry)
    )
    for jid, name, jentry in journal_rows:
        if jentry:
            memos.append(("journal", jid, name, {"jentry": jentry or ""}))

    for ref_kind, owner_id, owner_name, fields in memos:
        count, hits = _scan_fields(compiled, fields)
        if count == 0:
            continue
        results.append(
            {
                "kind": "memo",
                "id": owner_id,
                "name": f"{owner_name} (memo)",
                "mediapath": "",
                "match_count": count,
                "hits": hits,
                "source_id": owner_id if ref_kind == "file" else None,
                "ref_kind": ref_kind,
                "ref_id": owner_id,
            }
        )
    return results


async def _search_attributes(db: AsyncSession, compiled: re.Pattern[str]) -> list[dict]:
    rows = await db.execute(
        select(tables.attribute.c.attrid, tables.attribute.c.name, tables.attribute.c.value)
    )
    results: list[dict] = []
    for attrid, name, value in rows:
        count, hits = _scan_fields(compiled, {"name": name or "", "value": value or ""})
        if count == 0:
            continue
        results.append(
            {
                "kind": "attribute",
                "id": attrid,
                "name": f"{name}: {value}" if value else name,
                "mediapath": "",
                "match_count": count,
                "hits": hits,
                "source_id": None,
                "ref_kind": None,
                "ref_id": None,
            }
        )
    return results


async def _search_comments(db: AsyncSession, compiled: re.Pattern[str]) -> list[dict]:
    rows = await db.execute(
        select(
            tables.comment.c.id,
            tables.comment.c.target_kind,
            tables.comment.c.target_id,
            tables.comment.c.body,
        )
    )
    results: list[dict] = []
    for cid, target_kind, target_id, body in rows:
        count, hits = _scan_fields(compiled, {"body": body or ""})
        if count == 0:
            continue
        results.append(
            {
                "kind": "comment",
                "id": cid,
                "name": (body or "")[:80] or f"comment #{cid}",
                "mediapath": "",
                "match_count": count,
                "hits": hits,
                "source_id": None,
                "ref_kind": target_kind,
                "ref_id": target_id,
            }
        )
    return results


EntitySearcher = Callable[[AsyncSession, "re.Pattern[str]"], Awaitable[list[dict]]]

_SEARCHERS: dict[str, EntitySearcher] = {
    "codes": _search_codes,
    "categories": _search_categories,
    "cases": _search_cases,
    "journal": _search_journal,
    "memos": _search_memos,
    "attributes": _search_attributes,
    "comments": _search_comments,
}


async def search_text(
    db: AsyncSession,
    query: str,
    *,
    regex: bool = False,
    category_id: int | None = None,
    entities: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Scan the selected entity types for ``query`` (literal or regex).

    Returns ``{"total": ..., "results": [...]}`` where ``total`` counts the
    matching entities before pagination. Hits per entity are capped at
    ``HITS_PER_SOURCE``; ``match_count`` carries the full match count. Results
    are ordered by entity type (stable display order) then entity id.
    """
    try:
        if regex:
            from qualcoder_api.core.pattern import compile_user_pattern

            compiled = compile_user_pattern(query)
        else:
            compiled = re.compile(re.escape(query))
    except re.error as err:
        raise ValueError(f"invalid regex: {err}") from err

    selected = list(entities) if entities else list(ALL_ENTITIES)
    unknown = [e for e in selected if e not in ALL_ENTITIES]
    if unknown:
        raise ValueError(f"unknown entity type: {unknown[0]}")

    results: list[dict] = []
    for entity in selected:
        if entity == "files":
            results.extend(await _search_files(db, compiled, category_id))
        else:
            searcher = _SEARCHERS[entity]
            results.extend(await searcher(db, compiled))

    rank = {name: i for i, name in enumerate(ALL_ENTITIES)}
    results.sort(key=lambda item: (rank.get(item["kind"], 99), item["id"]))
    total = len(results)
    return {"total": total, "results": results[offset : offset + limit]}
