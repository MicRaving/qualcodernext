"""PDF text-locate engine: map pdf.js selections to fulltext offsets.

Pure functions and request/response models extracted from the sources API
router so the endpoint delegates to this self-contained module. No FastAPI
router lives here — only pydantic models and the locate fallback chain.
"""

from __future__ import annotations

import bisect
import re

from pydantic import BaseModel


class PdfTextLocateRequest(BaseModel):
    page: int
    text: str
    # Approximate character offset of the selection start within the page's
    # extracted text (from the frontend's pdf.js item order). When supplied
    # the engine picks the occurrence of the selection nearest this hint
    # instead of the first occurrence on the page — this disambiguates
    # duplicate phrases that otherwise always mapped to the first match.
    hint: int | None = None


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


def _word_seq_span(
    page_text: str, sel: str, hint: int | None = None
) -> tuple[int, int] | None:
    """Whitespace-insensitive word-sequence match (the historical fallback):
    the selection's words must appear verbatim, in order, in the page text.
    When ``hint`` (approx. start offset within the page) is given the
    occurrence nearest the hint is returned; otherwise the first match wins."""
    words = re.findall(r"\S+", sel)
    if not words:
        return None
    page_words = list(re.finditer(r"\S+", page_text))
    candidates: list[tuple[int, int]] = []
    for i in range(len(page_words) - len(words) + 1):
        if [m.group(0) for m in page_words[i : i + len(words)]] == words:
            candidates.append(
                (page_words[i].start(), page_words[i + len(words) - 1].end())
            )
    if not candidates:
        return None
    if hint is None:
        return candidates[0]
    # Pick the span whose start is closest to the hint (disambiguates
    # duplicate phrases — e.g. the same sentence appearing twice on one
    # page — so dragging the second copy no longer snaps to the first).
    return min(candidates, key=lambda s: abs(s[0] - hint))


def _normalized_match(
    page_text: str, sel: str, hint: int | None = None
) -> tuple[int, int] | None:
    """Locate the selection in the page text after normalization (case,
    whitespace, ligatures, soft hyphens, line-break hyphens), returning the
    RAW page-text span of the match.  With ``hint`` the occurrence nearest
    the hint is returned instead of the first occurrence."""
    norm_page, spans = _normalize_with_spans(page_text)
    norm_sel = _normalize_text(sel)
    if not norm_sel:
        return None
    # Gather every occurrence of the normalized selection in the normalized
    # page so duplicates can be disambiguated by the hint.
    candidates: list[tuple[int, int]] = []
    start = 0
    while True:
        idx = norm_page.find(norm_sel, start)
        if idx < 0:
            break
        candidates.append((spans[idx][0], spans[idx + len(norm_sel) - 1][1]))
        start = idx + 1
    if not candidates:
        return None
    if hint is None:
        return candidates[0]
    return min(candidates, key=lambda s: abs(s[0] - hint))


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
    page_text: str,
    sel: str,
    fulltext: str,
    expected: int,
    hint: int | None = None,
) -> tuple[int, int, str] | None:
    """Map a pdf.js selection to ``(pos0, pos1, confidence)`` offsets in the
    fulltext.  ``hint`` is the approximate start offset of the selection
    within ``page_text`` (from the frontend's item order) — when supplied
    the occurrence nearest the hint is returned instead of the first match,
    so duplicate phrases no longer snap to the wrong copy."""

    # Exact matches: collect every occurrence, pick the one nearest the hint
    # so the second copy of a repeated sentence does not snap to the first.
    if hint is not None:
        candidates: list[int] = []
        start = 0
        while True:
            idx = page_text.find(sel, start)
            if idx < 0:
                break
            candidates.append(idx)
            start = idx + 1
        if candidates:
            best = min(candidates, key=lambda i: abs(i - hint))
            return expected + best, expected + best + len(sel), "exact"
    else:
        idx = page_text.find(sel)
        if idx >= 0:
            return expected + idx, expected + idx + len(sel), "exact"
    seq = _word_seq_span(page_text, sel, hint)
    if seq is not None:
        return expected + seq[0], expected + seq[1], "normalized"
    norm = _normalized_match(page_text, sel, hint)
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
