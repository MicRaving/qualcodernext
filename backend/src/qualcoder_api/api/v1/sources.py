"""Sources API — list, get, import (upload), link, update, delete."""

from __future__ import annotations

import bisect
import logging
import os
import re
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from qualcoder_api.api.v1.deps import DbDep, ServiceDep
from qualcoder_api.core.models import Source
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import SourceRepository
from qualcoder_api.services import audit
from qualcoder_api.services.user_settings import get_codername, resolve_owner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sources", tags=["sources"])


class SourceUpdate(BaseModel):
    name: str | None = None
    memo: str | None = None
    memo_type: str | None = Field(None, max_length=200)
    owner: str | None = None


class LinkRequest(BaseModel):
    path: str
    owner: str | None = None


class TranscriptCreateRequest(BaseModel):
    """Optional companion name for the empty-transcript endpoint."""

    name: str | None = None


class CodesUsedItem(BaseModel):
    cid: int
    name: str
    color: str
    count: int


class SourceCaseItem(BaseModel):
    caseid: int
    name: str


class SourceAttributeItem(BaseModel):
    name: str
    value: str
    attr_type: str


class SourceDetails(BaseModel):
    """Aggregated details for a single source file."""

    source: Source
    text_codings: int
    image_codings: int
    av_codings: int
    codes_used: list[CodesUsedItem]
    cases: list[SourceCaseItem]
    attributes: list[SourceAttributeItem]


class SourceWithTranscript(Source):
    """Source plus a ``has_transcript`` flag for the file list.

    ``has_transcript`` is true only when the source links to a companion
    transcript (``av_text_id``) whose fulltext is non-empty. Imported AV
    files get an empty companion immediately, so empty companions keep the
    media file eligible for (re-)transcription.
    """

    has_transcript: bool = False


@router.get("", response_model=list[SourceWithTranscript])
async def list_sources(db: DbDep) -> list[SourceWithTranscript]:
    sources = await SourceRepository(db).list_sources()
    # One extra query: companion fulltext lengths for every av_text_id the
    # list references (the list itself omits fulltext, so we only ship a
    # boolean per source — never the megabytes of text).
    av_ids = {s.av_text_id for s in sources if s.av_text_id is not None}
    nonempty: set[int] = set()
    if av_ids:
        rows = await db.execute(
            select(
                tables.source.c.id,
                # SQLite trim() defaults to spaces only; pass a whitespace
                # charlist so "\n\t " -only companions count as empty, like
                # Python's str.strip().
                func.length(func.trim(tables.source.c.fulltext, " \n\t\r\v\f")),
            ).where(tables.source.c.id.in_(av_ids))
        )
        nonempty = {r[0] for r in rows if (r[1] or 0) > 0}
    # The list query omits memo_type (the repository selects explicit
    # columns); fetch the per-source type ids in one extra pass.
    memo_type_rows = await db.execute(
        select(tables.source.c.id, tables.source.c.memo_type)
    )
    memo_types = {r[0]: (r[1] or "") for r in memo_type_rows}
    return [
        SourceWithTranscript(
            **{**s.model_dump(), "memo_type": memo_types.get(s.id, "")},
            has_transcript=s.av_text_id is not None and s.av_text_id in nonempty,
        )
        for s in sources
    ]


@router.get("/{source_id}", response_model=Source)
async def get_source(source_id: int, db: DbDep) -> Source:
    source = await SourceRepository(db).get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    return source


@router.get("/{source_id}/details", response_model=SourceDetails)
async def source_details(source_id: int, db: DbDep) -> SourceDetails:
    """Aggregate details for one source: codings, codes, cases, attributes."""
    source = await SourceRepository(db).get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")

    text_codings = 0
    image_codings = 0
    av_codings = 0
    for tbl, col, name in (
        ("code_text_visible", "fid", "text"),
        ("code_image_visible", "id", "image"),
        ("code_av_visible", "id", "av"),
    ):
        count = (
            await db.execute(
                text(f"SELECT COUNT(*) FROM {tbl} WHERE {col} = :sid"), {"sid": source_id}
            )
        ).scalar_one()
        if name == "text":
            text_codings = count
        elif name == "image":
            image_codings = count
        else:
            av_codings = count

    counts: dict[int, int] = {}
    for tbl, col in (
        ("code_text_visible", "fid"),
        ("code_image_visible", "id"),
        ("code_av_visible", "id"),
    ):
        rows = await db.execute(
            text(f"SELECT cid FROM {tbl} WHERE {col} = :sid"), {"sid": source_id}
        )
        for r in rows:
            cid = r[0]
            counts[cid] = counts.get(cid, 0) + 1
    codes_used: list[CodesUsedItem] = []
    if counts:
        code_rows = await db.execute(
            select(tables.code_name.c.cid, tables.code_name.c.name, tables.code_name.c.color).where(
                tables.code_name.c.cid.in_(counts.keys())
            )
        )
        by_cid = {r[0]: (r[1] or "", r[2] or "#ffffff") for r in code_rows}
        for cid, count in sorted(counts.items(), key=lambda item: item[1], reverse=True):
            name, color = by_cid.get(cid, ("", "#ffffff"))
            codes_used.append(CodesUsedItem(cid=cid, name=name, color=color, count=count))

    case_rows = await db.execute(
        select(tables.cases.c.caseid, tables.cases.c.name)
        .select_from(
            tables.case_text.join(tables.cases, tables.cases.c.caseid == tables.case_text.c.caseid)
        )
        .where(tables.case_text.c.fid == source_id)
        .distinct()
    )
    cases = [SourceCaseItem(caseid=r[0], name=r[1] or "") for r in case_rows]

    attr_rows = await db.execute(
        select(tables.attribute.c.name, tables.attribute.c.value, tables.attribute.c.attr_type).where(
            tables.attribute.c.id == source_id,
            tables.attribute.c.attr_type == "file",
        )
    )
    attributes = [
        SourceAttributeItem(name=r[0] or "", value=r[1] or "", attr_type=r[2] or "")
        for r in attr_rows
    ]

    return SourceDetails(
        source=source,
        text_codings=text_codings,
        image_codings=image_codings,
        av_codings=av_codings,
        codes_used=codes_used,
        cases=cases,
        attributes=attributes,
    )


@router.get("/{source_id}/file")
async def source_file(source_id: int, db: DbDep, svc: ServiceDep) -> FileResponse:
    """Serve the raw bytes of a source file (internal or external link)."""
    from qualcoder_api.services.source_files import content_type_for, resolve_source_path

    source = await SourceRepository(db).get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    path = resolve_source_path(svc.project_path, source.mediapath, source.name)
    if path is None or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path, media_type=content_type_for(source.name), filename=source.name)


# ----------------------------------------------------------------------
# HTML -> PDF export
# ----------------------------------------------------------------------

#: Applied on top of PyMuPDF's default stylesheet (keeps captured pages
#: readable without fighting their own styling).
_PDF_USER_CSS = (
    "body { font-family: sans-serif; font-size: 10pt; line-height: 1.5; "
    "color: #1a1a1a; }"
)


def _is_html_name(name: str) -> bool:
    """True for the raw-file names the capture modes store (``*.html``)."""
    lower = (name or "").lower()
    return lower.endswith((".html", ".htm"))


def _story_render(html: str, css: str | None) -> bytes:
    """Render an HTML string to PDF bytes through PyMuPDF's Story engine.

    The pagination callback receives ``(page_number, filled)`` and returns
    the ``(mediabox, content rect, transform)`` for the next page; the
    DocumentWriter creates pages automatically as the content overflows.
    MuPDF substitutes its embedded fallback fonts for characters the page's
    own fonts cannot cover, so arbitrary unicode round-trips intact.
    """
    from io import BytesIO

    import fitz

    buf = BytesIO()
    writer = fitz.DocumentWriter(buf)
    rect = fitz.paper_rect("a4")
    story = fitz.Story(html=html, user_css=css)
    story.write(writer, lambda _number, _filled: (rect, rect, fitz.Identity))
    writer.close()
    return buf.getvalue()


def _story_pdf(html: str) -> bytes:
    """Primary export path: the captured HTML with its inline styles."""
    return _story_render(html, _PDF_USER_CSS)


def _text_pdf(text: str) -> bytes:
    """Fallback export: the extracted plain text as a simple document.

    The text is escaped and rendered through the same Story engine WITHOUT
    any CSS, so it cannot fail on unsupported styles and keeps unicode via
    MuPDF's fallback fonts — plain ``insert_text`` with a base-14 font would
    corrupt non-WinAnsi characters, so it is avoided here.
    """
    import html as html_module

    paragraphs: list[str] = []
    for block in (text or "").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        paragraphs.append(html_module.escape(block).replace("\n", "<br/>"))
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return _story_render(f"<html><body>{body}</body></html>", None)


def _render_source_pdf(path: str, fulltext: str | None) -> bytes:
    """Read the stored ``.html`` file and render it to PDF bytes.

    Falls back to a text-only PDF from the extracted fulltext when the
    HTML layout render fails (unsupported CSS/markup), so the export always
    produces a parseable document.
    """
    from qualcoder_api.services.import_service import (
        decode_text_with_best_encoding,
        html_to_text,
    )

    with open(path, "rb") as sourcefile:
        raw = sourcefile.read()
    html = decode_text_with_best_encoding(raw)
    try:
        return _story_pdf(html)
    except Exception as err:  # any render failure -> text fallback
        logger.warning("HTML -> PDF render failed for %s: %s", path, err)
        return _text_pdf(fulltext or html_to_text(html))


@router.get("/{source_id}/pdf")
async def source_pdf(source_id: int, db: DbDep, svc: ServiceDep) -> Response:
    """Export an HTML source as a PDF document.

    The captured webpage (the stored ``.html`` file) is rendered through
    PyMuPDF's Story layout engine, which applies the page's inline styles;
    the text-fallback path kicks in when that fails. 422 for non-HTML
    sources, 404 when the source has no file on disk.
    """
    import asyncio

    from qualcoder_api.services.source_files import resolve_source_path

    source = await SourceRepository(db).get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    if not _is_html_name(source.name):
        raise HTTPException(status_code=422, detail="not an HTML source")
    path = resolve_source_path(svc.project_path, source.mediapath, source.name)
    if path is None or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="file not found")
    pdf = await asyncio.to_thread(_render_source_pdf, path, source.fulltext)
    stem = os.path.splitext(source.name)[0]
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{stem}.pdf"'},
    )


@router.get("/{source_id}/thumbnail")
async def source_thumbnail(
    source_id: int, db: DbDep, svc: ServiceDep, max_size: int = 300
) -> Response:
    """Serve a PNG thumbnail for image sources and PDFs."""
    from qualcoder_api.services.source_files import build_thumbnail, resolve_source_path

    max_size = min(1024, max(64, max_size))
    source = await SourceRepository(db).get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    path = resolve_source_path(svc.project_path, source.mediapath, source.name)
    if path is None or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="file not found")
    png = await build_thumbnail(path, source.media_type, source.name, max_size)
    if png is None:
        raise HTTPException(status_code=404, detail="thumbnail not available")
    return Response(content=png, media_type="image/png")


class PdfTextLocateRequest(BaseModel):
    page: int
    text: str


class PdfTextLocateResponse(BaseModel):
    pos0: int
    pos1: int
    seltext: str
    #: How the selection was mapped onto the fulltext: ``"exact"`` (raw
    #: substring), ``"normalized"`` (whitespace/case/ligature/soft-hyphen/
    #: hyphenation tolerant), or ``"fuzzy"`` (best-effort positional
    #: estimate — accept only when a precise span matters less than having
    #: a span at all). Absent for old clients via the default.
    confidence: str = "exact"


#: Unicode ligature chars -> the letter pairs they stand for. pdf.js text
#: items can carry the ligature glyphs (U+FB00..FB04) while PyMuPDF's
#: ``get_text()`` — and therefore the extracted fulltext — expands them.
_LIGATURE_EXPANSION: dict[int, str] = {
    0xFB00: "ff",
    0xFB01: "fi",
    0xFB02: "fl",
    0xFB03: "ffi",
    0xFB04: "ffl",
}


def _normalize_with_spans(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Return ``text`` normalized for comparison plus, for every normalized
    char, the raw-text span it was produced from.

    Normalization levels the differences between pdf.js's rendered text and
    PyMuPDF's extraction: whitespace collapses to single spaces, case is
    folded, soft hyphens (U+00AD) vanish, a line-break hyphen ("some-\\nthing")
    merges its parts, and ligature chars expand to their letter pairs. The
    span map lets a match in the normalized text be translated back to the
    raw offsets even though normalization changes lengths.
    """
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "\u00ad":
            i += 1
            continue
        if text[i] == "-" and i + 1 < n and text[i + 1].isspace():
            i += 2
            while i < n and text[i].isspace():
                i += 1
            continue
        if text[i].isspace():
            start = i
            while i < n and text[i].isspace():
                i += 1
            out.append(" ")
            spans.append((start, i))
            continue
        expansion = _LIGATURE_EXPANSION.get(ord(text[i]))
        if expansion is not None:
            for ch in expansion:
                out.append(ch.casefold())
                spans.append((i, i + 1))
            i += 1
            continue
        out.append(text[i].casefold())
        spans.append((i, i + 1))
        i += 1
    return "".join(out), spans


def _normalize_text(text: str) -> str:
    """Normalize ``text`` the same way ``_normalize_with_spans`` does, for
    word-level comparisons where offsets are not needed."""
    norm, _ = _normalize_with_spans(text)
    return norm


def _word_seq_span(page_text: str, sel: str) -> tuple[int, int] | None:
    """Whitespace-insensitive word-sequence match (the historical fallback):
    the selection's words must appear verbatim, in order, in the page text.
    Returns the raw page-text span of the first to last matched word."""
    words = re.findall(r"\S+", sel)
    if not words:
        return None
    page_words = list(re.finditer(r"\S+", page_text))
    for i in range(len(page_words) - len(words) + 1):
        if [m.group(0) for m in page_words[i : i + len(words)]] == words:
            return page_words[i].start(), page_words[i + len(words) - 1].end()
    return None


def _normalized_match(page_text: str, sel: str) -> tuple[int, int] | None:
    """Locate the selection in the page text after normalization (case,
    whitespace, ligatures, soft hyphens, line-break hyphens), returning the
    RAW page-text span of the match."""
    norm_page, spans = _normalize_with_spans(page_text)
    norm_sel = _normalize_text(sel)
    if not norm_sel:
        return None
    idx = norm_page.find(norm_sel)
    if idx < 0:
        return None
    return spans[idx][0], spans[idx + len(norm_sel) - 1][1]


def _fuzzy_span(text: str, sel: str, max_mismatch: int) -> tuple[int, int] | None:
    """Best-effort span of the selection's (normalized) words in ``text``,
    tolerating up to ``max_mismatch`` word substitutions. Returns the span of
    the first window with the fewest mismatches, or None when no window fits."""
    tokens = list(re.finditer(r"\S+", text))
    sel_norm = [_normalize_text(w) for w in re.findall(r"\S+", sel)]
    n, m = len(tokens), len(sel_norm)
    if m == 0 or n < m:
        return None
    norms = [_normalize_text(t.group(0)) for t in tokens]
    best: tuple[int, int] | None = None
    best_mism = max_mismatch + 1
    for i in range(n - m + 1):
        mism = 0
        for j in range(m):
            if norms[i + j] != sel_norm[j]:
                mism += 1
                if mism >= best_mism:
                    break
        if mism < best_mism:
            best_mism = mism
            best = (tokens[i].start(), tokens[i + m - 1].end())
    return best


def _page_anchor(fulltext: str, page_text: str, expected: int) -> int | None:
    """Absolute offset at which the page's first word occurs in the
    fulltext, preferring the occurrence nearest ``expected`` (words repeat
    across pages). None when the page has no words or none occur verbatim."""
    first_match = re.search(r"\S+", page_text)
    if first_match is None:
        return None
    first_norm = _normalize_text(first_match.group(0))
    best_pos: int | None = None
    best_dist = 1 << 62
    for m in re.finditer(r"\S+", fulltext):
        if _normalize_text(m.group(0)) == first_norm:
            dist = abs(m.start() - expected)
            if dist < best_dist:
                best_dist = dist
                best_pos = m.start()
    if best_pos is None:
        return None
    return best_pos - first_match.start()


#: A run of at least this many consecutive selection words found verbatim in
#: the fulltext is accepted as an anchor on its own.
_MIN_RUN_WORDS = 3

#: Shorter runs are accepted only when the surrounding fulltext window
#: resembles the rest of the selection at least this well (difflib ratio).
_MIN_RUN_SIMILARITY = 0.6


def _best_run(
    fulltext: str,
    sel_words_norm: list[str],
    expected: int | None,
    window: int | None,
) -> tuple[int, int, int, int] | None:
    """Find the longest run of consecutive selection words that appears as
    consecutive words inside the fulltext.

    ``sel_words_norm`` is the selection's normalized word list; the run may
    start anywhere in the selection. Returns ``(abs_lo, abs_hi, run_len,
    sel_index)`` — the run's absolute span, how many selection words it
    covers, and the selection word index it starts at.

    Only words within ``window`` characters around ``expected`` are
    considered (``window=None`` searches the whole text). Among runs of
    equal length the one nearest ``expected`` wins. None when no run exists.
    """
    tokens = list(re.finditer(r"\S+", fulltext))
    n = len(tokens)
    if n == 0 or not sel_words_norm:
        return None
    lo, hi = 0, n
    if expected is not None and window is not None:
        starts = [t.start() for t in tokens]
        lo = bisect.bisect_left(starts, max(0, expected - window))
        hi = bisect.bisect_right(starts, min(len(fulltext), expected + window))
    token_norms = [_normalize_text(t.group(0)) for t in tokens]
    occurrences: dict[str, list[int]] = {}
    for i in range(lo, hi):
        occurrences.setdefault(token_norms[i], []).append(i)
    m = len(sel_words_norm)
    best: tuple[int, int, int, int] | None = None
    best_dist = 1 << 62
    for j in range(m):
        for k in occurrences.get(sel_words_norm[j], ()):
            run = 0
            while (
                j + run < m
                and k + run < hi
                and token_norms[k + run] == sel_words_norm[j + run]
            ):
                run += 1
            if run == 0:
                continue
            dist = abs(tokens[k].start() - expected) if expected is not None else 0
            if best is None or run > best[2] or (run == best[2] and dist < best_dist):
                best = (tokens[k].start(), tokens[k + run - 1].end(), run, j)
                best_dist = dist
    return best


def _similarity_with_context(
    fulltext: str, sel_words_norm: list[str], run_span: tuple[int, int]
) -> float:
    """How well the fulltext window of the same word count as the selection,
    centered on the matched run, resembles the selection. Each selection
    word may consume the region word most similar to it (difflib ratio >
    0.6); the score is the fraction of the selection's normalized length
    covered by matched words. Order-tolerant, so reordered text still scores
    well where a sequence matcher would not.
    """
    from difflib import SequenceMatcher

    m = len(sel_words_norm)
    if m == 0:
        return 0.0
    words = list(re.finditer(r"\S+", fulltext))
    start_i: int | None = None
    end_i: int | None = None
    for i, w in enumerate(words):
        if w.start() < run_span[1] and w.end() > run_span[0]:
            if start_i is None:
                start_i = i
            end_i = i
    if start_i is None:
        return 0.0
    assert end_i is not None
    run_words = end_i - start_i + 1
    left_pad = max(0, (m - run_words) // 2)
    wl = max(0, start_i - left_pad)
    wr = min(len(words), wl + m)
    wl = max(0, wr - m)
    region: list[str | None] = [
        _normalize_text(words[i].group(0)) for i in range(wl, wr)
    ]
    total = sum(len(w) for w in sel_words_norm)
    if total == 0:
        return 0.0
    matched = 0
    for sw in sorted(sel_words_norm, key=len, reverse=True):
        best_i = -1
        best_ratio = 0.6
        for i, rw in enumerate(region):
            if rw is None:
                continue
            ratio = SequenceMatcher(None, sw, rw).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_i = i
        if best_i >= 0:
            region[best_i] = None
            matched += len(sw)
    return matched / total


def _span_for_selection(
    fulltext: str,
    sel_words_norm: list[str],
    run_span: tuple[int, int],
    sel_index: int,
) -> tuple[int, int]:
    """Map the matched run's absolute span back onto the whole selection:
    pull ``pos0`` back past the selection words the run is missing at the
    start, then extend ``pos1`` until the span covers roughly the
    selection's normalized length (clamping at the text bounds)."""
    pos0, pos1 = run_span
    if sel_index > 0:
        wanted = len(" ".join(sel_words_norm[:sel_index]))
        acc = 0
        while pos0 > 0 and acc < wanted:
            while pos0 > 0 and fulltext[pos0 - 1].isspace():
                pos0 -= 1
            end = pos0
            while pos0 > 0 and not fulltext[pos0 - 1].isspace():
                pos0 -= 1
            acc += len(_normalize_text(fulltext[pos0:end])) + 1
    target = len(" ".join(sel_words_norm))
    if target > 0:
        cur = len(_normalize_text(fulltext[pos0:pos1]))
        while pos1 < len(fulltext) and cur < target:
            nxt = pos1
            while nxt < len(fulltext) and fulltext[nxt].isspace():
                nxt += 1
            if nxt >= len(fulltext):
                break
            wstart = nxt
            while nxt < len(fulltext) and not fulltext[nxt].isspace():
                nxt += 1
            pos1 = nxt
            cur += len(_normalize_text(fulltext[wstart:nxt])) + 1
    return pos0, pos1


def _run_locate(
    page_text: str, sel: str, fulltext: str, expected: int
) -> tuple[int, int] | None:
    """Run-based anchor: find the longest contiguous run of the selection's
    words directly inside the fulltext — first within a generous window
    around the page's expected offset, then anywhere in the text (preferring
    the match nearest the expected offset) — and map it back to a span
    covering the whole selection.

    A run of at least ``_MIN_RUN_WORDS`` words is accepted outright; a
    2-word run only when the surrounding fulltext window resembles the
    selection well enough (``_MIN_RUN_SIMILARITY``). This anchors pages
    whose extraction reordered or dropped the leading text, which the
    page-first-word anchor cannot.
    """
    sel_words_norm = [_normalize_text(w) for w in re.findall(r"\S+", sel)]
    if not sel_words_norm:
        return None
    window = max(4 * len(page_text), 8192)
    for search_window in (window, None):
        run = _best_run(fulltext, sel_words_norm, expected, search_window)
        if run is None:
            continue
        abs_lo, abs_hi, run_len, sel_index = run
        if run_len >= _MIN_RUN_WORDS or (
            run_len == 2
            and _similarity_with_context(fulltext, sel_words_norm, (abs_lo, abs_hi))
            >= _MIN_RUN_SIMILARITY
        ):
            return _span_for_selection(
                fulltext, sel_words_norm, (abs_lo, abs_hi), sel_index
            )
    return None


def _fuzzy_locate(
    page_text: str, sel: str, fulltext: str, expected: int
) -> tuple[int, int, str] | None:
    """Best-effort positional fallbacks: first the run-based anchor (see
    :func:`_run_locate`) that maps the longest run of the selection's words
    directly in the fulltext; when that finds nothing, the historical
    approach of fuzzy-matching the selection inside the page text anchored
    on the page's first word's position in the fulltext; finally a fuzzy
    match inside a window of the fulltext around the expected page offset."""
    sel_words = re.findall(r"\S+", sel)
    if not sel_words:
        return None
    run_span = _run_locate(page_text, sel, fulltext, expected)
    if run_span is not None:
        pos0, pos1 = run_span
        if 0 <= pos0 < pos1 <= len(fulltext):
            return pos0, pos1, "fuzzy"
    max_mismatch = max(1, len(sel_words) // 4)
    rel = _fuzzy_span(page_text, sel, max_mismatch)
    anchor = _page_anchor(fulltext, page_text, expected)
    if rel is not None and anchor is not None:
        pos0, pos1 = anchor + rel[0], anchor + rel[1]
        if 0 <= pos0 < pos1 <= len(fulltext):
            return pos0, pos1, "fuzzy"
    half = max(3 * len(page_text), 4096)
    lo = max(0, expected - half)
    hi = min(len(fulltext), expected + half)
    abs_span = _fuzzy_span(fulltext[lo:hi], sel, max_mismatch)
    if abs_span is not None:
        pos0, pos1 = lo + abs_span[0], lo + abs_span[1]
        if 0 <= pos0 < pos1 <= len(fulltext):
            return pos0, pos1, "fuzzy"
    return None


def _locate(
    page_text: str, sel: str, fulltext: str, expected: int
) -> tuple[int, int, str] | None:
    """Map a pdf.js selection to ``(pos0, pos1, confidence)`` offsets in the
    fulltext.

    Fallback chain:
    1. exact substring in the page text;
    2. word-sequence match (whitespace-insensitive);
    3. normalized match (case, whitespace, ligatures, soft hyphens,
       line-break hyphens);
    4. run-based anchor: the longest run of the selection's words found
       directly in the fulltext (tolerates reordered or dropped leading
       text);
    5. positional fuzzy estimate anchored on the page's first word.

    Only returns None when nothing can be anchored at all (e.g. the page
    has no extractable text).
    """
    idx = page_text.find(sel)
    if idx >= 0:
        return expected + idx, expected + idx + len(sel), "exact"
    seq = _word_seq_span(page_text, sel)
    if seq is not None:
        return expected + seq[0], expected + seq[1], "normalized"
    norm = _normalized_match(page_text, sel)
    if norm is not None:
        return expected + norm[0], expected + norm[1], "normalized"
    return _fuzzy_locate(page_text, sel, fulltext, expected)


_MSG_BLANK_PAGE = (
    "This PDF page has no extractable text (it may be a scanned image) — "
    "use the rectangle region tool to code it instead."
)

_MSG_UNANCHORABLE = (
    "Could not map the selection to the document text — the PDF's text "
    "layer differs from the extracted text; try selecting a shorter phrase "
    "or use the rectangle region tool."
)


@router.post("/{source_id}/pdf-text-locate", response_model=PdfTextLocateResponse)
async def pdf_text_locate(
    source_id: int, req: PdfTextLocateRequest, db: DbDep, svc: ServiceDep
) -> PdfTextLocateResponse:
    """Map a selection made over a RENDERED pdf.js page to offsets in the
    extracted plain text — the same text the plain-text mode codes against.

    The frontend sends the reconstructed selection (items joined with
    spaces/newlines); pdf.js's rendered text differs from PyMuPDF's
    extraction in whitespace, case, ligature glyphs and hyphenation, so the
    mapping walks a fallback chain (see :func:`_locate`) from the exact
    substring over normalized matching to a run-based anchor in the
    fulltext. The returned span always slices the fulltext exactly, so coded
    text equals the plain-text mode's slice. Pages without extractable text
    (scanned images) and selections that cannot be anchored at all 422 with
    messages explaining what to do instead.
    """
    import asyncio

    from qualcoder_api.services.source_files import resolve_source_path

    source = await SourceRepository(db).get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    if not (source.name or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="not a PDF source")
    path = resolve_source_path(svc.project_path, source.mediapath, source.name)
    if path is None or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="file not found")
    if not req.text.strip():
        raise HTTPException(status_code=422, detail="empty selection")

    def _run() -> PdfTextLocateResponse:
        import fitz

        with fitz.open(path) as doc:
            if not 1 <= req.page <= doc.page_count:
                raise HTTPException(status_code=422, detail="page out of range")
            page_texts = [page.get_text() for page in doc]
        page_text = page_texts[req.page - 1]
        if not page_text.strip():
            raise HTTPException(status_code=422, detail=_MSG_BLANK_PAGE)
        fulltext = "".join(page_texts)
        expected = sum(len(t) for t in page_texts[: req.page - 1])
        found = _locate(page_text, req.text, fulltext, expected)
        if found is None:
            raise HTTPException(status_code=422, detail=_MSG_UNANCHORABLE)
        pos0, pos1, confidence = found
        return PdfTextLocateResponse(
            pos0=pos0,
            pos1=pos1,
            seltext=fulltext[pos0:pos1],
            confidence=confidence,
        )

    return await asyncio.to_thread(_run)


@router.post("/import", response_model=Source)
async def import_source(
    db: DbDep,
    svc: ServiceDep,
    file: Annotated[UploadFile, File()],
    owner: str | None = Form(None),
) -> Source:
    """Upload a file; copies it into the project folder and registers it."""
    from qualcoder_api.services.import_service import ImportService

    if svc.project_path == "":
        raise HTTPException(status_code=409, detail="no project is open")
    session_factory = svc.session_factory
    if session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    tmp = svc.project_path + "/_upload_" + (file.filename or "upload")

    with open(tmp, "wb") as out:  # noqa: ASYNC230 - small local temp write
        while chunk := await file.read(1 << 20):
            out.write(chunk)
    try:
        service = ImportService(svc.project_path, session_factory)
        source = await service.import_file(
            tmp, owner=resolve_owner(owner), link=False, filename=file.filename
        )
    finally:
        os.remove(tmp)
    if source is None:
        raise HTTPException(status_code=409, detail="duplicate filename or import failed")
    await audit.record(
        db, user=resolve_owner(owner), action="source.import", entity="source",
        entity_id=source.id, detail={"name": source.name},
    )
    return source


@router.post("/link", response_model=Source)
async def link_source(req: LinkRequest, db: DbDep, svc: ServiceDep) -> Source:
    """Register an external file by path (no copy)."""
    from qualcoder_api.services.import_service import ImportService

    session_factory = svc.session_factory
    if session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    service = ImportService(svc.project_path, session_factory)
    source = await service.import_file(req.path, owner=resolve_owner(req.owner), link=True)
    if source is None:
        raise HTTPException(status_code=409, detail="duplicate filename")
    await audit.record(
        db, user=resolve_owner(req.owner), action="source.link", entity="source",
        entity_id=source.id, detail={"name": source.name},
    )
    return source


@router.patch("/{source_id}", response_model=Source)
async def update_source(source_id: int, req: SourceUpdate, db: DbDep) -> Source:
    from sqlalchemy import select
    from sqlalchemy import update as sa_update

    from qualcoder_api.persistence import tables

    old_row = (
        await db.execute(
            select(tables.source.c.name, tables.source.c.memo).where(
                tables.source.c.id == source_id
            )
        )
    ).first()
    old = dict(old_row._mapping) if old_row is not None else {}
    source = await SourceRepository(db).update_source(
        source_id, **req.model_dump(exclude_none=True, exclude={"memo_type"})
    )
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    # memo_type is not a repository field (yet) — anchor the update here.
    if req.memo_type is not None:
        await db.execute(
            sa_update(tables.source)
            .where(tables.source.c.id == source_id)
            .values(memo_type=req.memo_type)
        )
        await db.commit()
        source = await SourceRepository(db).get_source(source_id)
    if source is None:  # pragma: no cover - row vanished mid-update
        raise HTTPException(status_code=404, detail="source not found")
    await audit.record(
        db, user=get_codername(), action="source.update", entity="source",
        entity_id=source_id, source_id=source_id,
        detail={
            "before_name": old.get("name"),
            "after_name": source.name,
            "before_memo": old.get("memo"),
            "after_memo": source.memo,
        },
    )
    return source


@router.post("/{source_id}/transcript", response_model=Source)
async def create_transcript(
    source_id: int,
    db: DbDep,
    req: TranscriptCreateRequest | None = None,
) -> Source:
    """Create an EMPTY transcript companion for an audio/video source and
    link it through ``av_text_id`` — the target for manual transcription.

    Idempotent: when a companion already exists it is returned unchanged
    instead of creating a duplicate. The companion is registered like any
    imported transcript (hidden from the file list by ``av_text_id``), so
    manual transcription always has a save target even for projects that
    predate the import-time companion.
    """
    from qualcoder_api.core.enums import MediaType

    repo = SourceRepository(db)
    source = await repo.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    if source.media_type not in (MediaType.AUDIO, MediaType.VIDEO):
        raise HTTPException(status_code=422, detail="only audio/video sources have transcripts")
    if source.av_text_id is not None:
        existing = await repo.get_source(source.av_text_id)
        if existing is not None:
            # Idempotent: the companion already exists — return the media
            # source (the endpoint's contract) with the link intact.
            reloaded = await repo.get_source(source_id)
            if reloaded is None:  # pragma: no cover - row was just read
                raise HTTPException(status_code=404, detail="source not found")
            return reloaded
    # Source names are unique — pick a free variant when the companion name
    # is already taken (e.g. a leftover file with the same name).
    base_name = (req.name if req and req.name else "").strip() or f"{source.name}.txt"
    name = base_name
    counter = 2
    while (
        await db.execute(
            select(tables.source.c.id).where(tables.source.c.name == name)
        )
    ).first() is not None:
        stem, sep, ext = base_name.rpartition(".")
        name = f"{stem}-{counter}.{ext}" if sep else f"{base_name}-{counter}"
        counter += 1

    trans = await repo.add_source(
        name=name, mediapath=None, fulltext="", owner=resolve_owner(None)
    )
    await repo.update_source(source_id, av_text_id=trans.id)
    companion_row = (
        await db.execute(select(tables.source).where(tables.source.c.id == trans.id))
    ).first()
    await audit.record(
        db, user=get_codername(), action="transcript.create", entity="source",
        entity_id=trans.id, source_id=source_id,
        detail={"name": name, "companion": dict(companion_row._mapping) if companion_row is not None else None},
    )
    reloaded = await repo.get_source(source_id)
    if reloaded is None:  # pragma: no cover - row was just updated
        raise HTTPException(status_code=404, detail="source not found")
    return reloaded


@router.delete("/{source_id}/transcript", status_code=204)
async def delete_transcript(source_id: int, db: DbDep) -> None:
    """Delete the media source's transcript companion and clear the
    ``av_text_id`` link. 404 when the source has no transcript."""
    repo = SourceRepository(db)
    source = await repo.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    if source.av_text_id is None:
        raise HTTPException(status_code=404, detail="source has no transcript")
    companion = await repo.get_source(source.av_text_id)
    companion_name = companion.name if companion is not None else None
    trans_id = source.av_text_id
    companion_row = (
        await db.execute(select(tables.source).where(tables.source.c.id == trans_id))
    ).first()
    await repo.update_source(source_id, av_text_id=None)
    await repo.delete_source(trans_id)
    await audit.record(
        db, user=get_codername(), action="transcript.delete", entity="source",
        entity_id=trans_id, source_id=source_id,
        detail={"name": companion_name, "media": source.name,
                "companion": dict(companion_row._mapping) if companion_row is not None else None},
    )


@router.delete("/{source_id}", status_code=204)
async def delete_source(source_id: int, db: DbDep) -> None:
    from qualcoder_api.persistence.repositories import _rowdict

    async def _snapshot(table, col, sid: int) -> list[dict]:
        rows = (await db.execute(select(table).where(col == sid))).all()
        return [_rowdict(r) for r in rows]

    async def _source_snapshot(sid: int) -> dict:
        row = (
            await db.execute(select(tables.source).where(tables.source.c.id == sid))
        ).first()
        return dict(row._mapping) if row is not None else {}

    async def _delete_detail(sid: int) -> dict:
        return {
            "row": await _source_snapshot(sid),
            "code_text": await _snapshot(tables.code_text, tables.code_text.c.fid, sid),
            "code_image": await _snapshot(tables.code_image, tables.code_image.c.id, sid),
            "code_av": await _snapshot(tables.code_av, tables.code_av.c.id, sid),
            "annotation": await _snapshot(tables.annotation, tables.annotation.c.fid, sid),
            "case_text": await _snapshot(tables.case_text, tables.case_text.c.fid, sid),
            "attribute": await _snapshot(tables.attribute, tables.attribute.c.id, sid),
            "av_text_pointers": [
                r[0]
                for r in (
                    await db.execute(
                        select(tables.source.c.id).where(tables.source.c.av_text_id == sid)
                    )
                ).all()
            ],
        }

    media_row = await _source_snapshot(source_id)
    detail = await _delete_detail(source_id)
    # Audio/video sources delete their transcript companion (av_text_id) too —
    # snapshot it for the second audit row before the repository cascade.
    companion_id = media_row.get("av_text_id")
    companion_detail = None
    if companion_id is not None and await _source_snapshot(companion_id):
        companion_detail = await _delete_detail(companion_id)
    await SourceRepository(db).delete_source(source_id)
    await audit.record(
        db, user=get_codername(), action="source.delete", entity="source", entity_id=source_id,
        detail=detail,
    )
    if companion_detail is not None:
        await audit.record(
            db, user=get_codername(), action="source.delete", entity="source",
            entity_id=companion_id, source_id=source_id, detail=companion_detail,
        )
