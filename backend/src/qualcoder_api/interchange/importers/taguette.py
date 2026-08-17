"""Taguette importer — import a Taguette ``.taguette.sqlite3`` database."""

from __future__ import annotations

import html
import re
import sqlite3

import aiosqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.interchange.importers.base import (
    _columns,
    _existing_names,
    _fetch,
    _pick,
    _table_names,
)
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import (
    CodeRepository,
    CodingRepository,
    SourceRepository,
)


def _html_to_plain_text(raw_html: str) -> str:
    """Clean Taguette HTML content to flat plain text (ported from legacy)."""
    if not raw_html:
        return ""
    text = raw_html.replace("\r\n", "\n")
    text = re.sub(r"</?(p|br|div|li|ul|ol|h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<.*?>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _find_best_match(
    clean_doc: str, snippet_html: str, original_start: int, original_end: int
) -> tuple[int, int, str]:
    """Locate the highlighted snippet inside the cleaned document (ported from legacy)."""
    clean_snip = _html_to_plain_text(snippet_html).strip()
    if not clean_snip:
        safe_start = min(max(0, original_start), len(clean_doc))
        safe_end = min(max(0, original_end), len(clean_doc))
        return safe_start, safe_end, clean_doc[safe_start:safe_end]
    matches = [m.start() for m in re.finditer(re.escape(clean_snip), clean_doc)]
    if matches:
        best = min(matches, key=lambda x: abs(x - original_start))
        return best, best + len(clean_snip), clean_snip
    words = clean_snip.split()
    if words:
        regex_snip = r"\s+".join(re.escape(w) for w in words)
        flex_matches = [(m.start(), m.end()) for m in re.finditer(regex_snip, clean_doc)]
        if flex_matches:
            best_match = min(flex_matches, key=lambda x: abs(x[0] - original_start))
            return best_match[0], best_match[1], clean_doc[best_match[0]:best_match[1]]
    safe_start = min(max(0, original_start), len(clean_doc))
    safe_end = min(max(0, original_end), len(clean_doc))
    return safe_start, safe_end, clean_doc[safe_start:safe_end]


async def import_taguette(
    session_factory: async_sessionmaker, taguette_path: str, codername: str
) -> dict:
    """Import a Taguette ``.taguette.sqlite3`` database into the open project.

    Documents (``documents`` table; ``name`` or ``title`` column, HTML
    ``contents``) become sources with cleaned plain text; ``tags`` become
    codes (``path`` or ``name``, ``color`` when present, else the legacy
    yellow-green); highlights — joined through ``highlight_tags`` or read
    directly via a ``tag`` column — become text codings whose positions are
    re-anchored into the cleaned text with the legacy best-match logic.
    Raises ``ValueError`` when the file is not a Taguette database.
    """
    try:
        async with aiosqlite.connect(taguette_path) as src:
            return await _import_taguette(src, session_factory, codername)
    except sqlite3.Error as err:
        raise ValueError(f"Invalid Taguette file: {err}") from err


async def _import_taguette(src: aiosqlite.Connection, session_factory, codername: str) -> dict:
    counts: dict[str, int] = {"codes": 0, "sources": 0, "codings": 0}
    tables_present = await _table_names(src)
    if not {"documents", "tags", "highlights"} <= tables_present:
        raise ValueError("Not a Taguette database")

    async with session_factory() as session:
        source_repo = SourceRepository(session)
        code_repo = CodeRepository(session)
        coding_repo = CodingRepository(session)

        # -- documents -> sources ---------------------------------------
        doc_cols = await _columns(src, "documents")
        name_col = "name" if "name" in doc_cols else ("title" if "title" in doc_cols else None)
        text_col = "contents" if "contents" in doc_cols else None
        memo_col = "description" if "description" in doc_cols else None
        fid_map: dict[int, int] = {}
        clean_by_doc: dict[int, str] = {}
        existing = await _existing_names(session, tables.source, "name")
        if name_col and "id" in doc_cols:
            pick = _pick(doc_cols, "id", name_col, memo_col, text_col)
            for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM documents"):
                values = dict(zip(pick, row, strict=True))
                name = values[name_col]
                clean_text = _html_to_plain_text(values.get(text_col or "") or "")
                clean_by_doc[values["id"]] = clean_text
                if not name or name in existing:
                    continue
                source = await source_repo.add_source(
                    name=name,
                    mediapath=None,
                    fulltext=clean_text,
                    memo=values.get(memo_col or "") or "",
                    owner=codername,
                )
                fid_map[values["id"]] = source.id
                existing.add(name)
                counts["sources"] += 1

        # -- highlights (raw, anchored after codes are mapped) ------------
        hcols = await _columns(src, "highlights")
        doc_col = (
            "document_id" if "document_id" in hcols else ("document" if "document" in hcols else None)
        )
        start_col = "start_offset" if "start_offset" in hcols else ("start" if "start" in hcols else None)
        end_col = "end_offset" if "end_offset" in hcols else ("end" if "end" in hcols else None)
        snippet_col = "snippet" if "snippet" in hcols else ("text" if "text" in hcols else None)
        raw_codings: list[tuple[int, int, int, int, str]] = []
        if doc_col and start_col and end_col and snippet_col:
            if "highlight_tags" in tables_present:
                rows = await _fetch(
                    src,
                    f"SELECT h.{doc_col}, ht.tag_id, h.{start_col}, h.{end_col}, h.{snippet_col} "
                    "FROM highlights h JOIN highlight_tags ht ON h.id = ht.highlight_id",
                )
            elif "tag" in hcols:
                rows = await _fetch(
                    src,
                    f"SELECT {doc_col}, tag, {start_col}, {end_col}, {snippet_col} FROM highlights",
                )
            else:
                rows = []
            for doc_id, tag_id, start, end, snippet in rows:
                raw_codings.append((doc_id, tag_id, start, end, snippet))
        codings_by_doc: dict[int, list[tuple[int, int, int, str]]] = {}
        for doc_id, tag_id, start, end, snippet in raw_codings:
            codings_by_doc.setdefault(doc_id, []).append((tag_id, start, end, snippet))

        # -- tags -> codes ------------------------------------------------
        tag_cols = await _columns(src, "tags")
        name_col = "name" if "name" in tag_cols else ("path" if "path" in tag_cols else None)
        color_col = "color" if "color" in tag_cols else None
        memo_col = "description" if "description" in tag_cols else None
        code_map: dict[int, int] = {}
        if name_col and "id" in tag_cols:
            pick = _pick(tag_cols, "id", name_col, memo_col, color_col)
            existing = await _existing_names(session, tables.code_name, "name")
            for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM tags"):
                values = dict(zip(pick, row, strict=True))
                name = values[name_col]
                if not name or name in existing:
                    continue
                code = await code_repo.add_code(
                    name=name,
                    owner=codername,
                    color=values.get(color_col or "") or "#DDE600",
                    memo=values.get(memo_col or "") or "",
                )
                if code is not None:
                    code_map[values["id"]] = code.cid
                    existing.add(name)
                    counts["codes"] += 1

        # -- codings ------------------------------------------------------
        for doc_id, coding_list in codings_by_doc.items():
            new_fid = fid_map.get(doc_id)
            clean_text = clean_by_doc.get(doc_id, "")
            if new_fid is None:
                continue
            for tag_id, start, end, snippet in coding_list:
                new_cid = code_map.get(tag_id)
                if new_cid is None:
                    continue
                pos0, pos1, seltext = _find_best_match(
                    clean_text, snippet, int(start or 0), int(end or 0)
                )
                try:
                    await coding_repo.add_text_coding(
                        cid=new_cid,
                        fid=new_fid,
                        seltext=seltext,
                        pos0=pos0,
                        pos1=pos1,
                        owner=codername,
                    )
                    counts["codings"] += 1
                except IntegrityError:
                    await session.rollback()

    message = (
        f"Taguette import complete: {counts['sources']} sources, "
        f"{counts['codes']} codes, {counts['codings']} codings"
    )
    return {"ok": True, "message": message, **counts}
