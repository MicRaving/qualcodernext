"""Speaker-turn detection and marking (port of upstream ``speakers.py``).

Detects speaker turns in interview/focus-group transcripts from configurable
markers (``Name:``, ``#Name:``, ``@Name:``, ``[Name]``, ``{Name}``, custom
regex) and codes each turn with a code named after the speaker inside a
"📌 Speakers" category. The codings are owned by the legacy pseudo-coder
name ``📌 Speaker coding`` so they stay out of the regular coders' counts.
"""

from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.models import Code
from qualcoder_api.core.timeutil import now as _now
from qualcoder_api.persistence import tables

SPEAKER_CODER_NAME = "📌 Speaker coding"
SPEAKERS_CATEGORY_NAME = "📌 " + "Speakers"
SPEAKER_CODE_COLOR = "#B8B8B8"
MAX_NAME_LEN = 63

# Uppercase letters (ASCII + accented Latin-1) for mid-paragraph "Name:"
# detection; re has no \\p{Lu}.
_UPPER = "A-ZÀ-ÖØ-Þ"

http_scheme_tail_re = re.compile(r"(?:^|\s)https?$", flags=re.IGNORECASE)


def identifier_regex(key: str, anchored: bool = True):
    """Compiled pattern for a marker key; the speaker name is group 1.

    ``anchored=False`` drops the leading anchor so the marker can be found
    anywhere in the line (multi-identifier mode).
    """
    m = str(MAX_NAME_LEN)
    a = r"^\s*" if anchored else r""
    if key == "name":
        return re.compile(a + r"(.{1," + m + r"}?)\s*:\s*", flags=re.UNICODE)
    if key == "hash":
        return re.compile(a + r"#\s*(.{1," + m + r"}?)\s*:\s*", flags=re.UNICODE)
    if key == "at":
        return re.compile(a + r"@\s*(.{1," + m + r"}?)\s*:\s*", flags=re.UNICODE)
    if key == "bracket":
        return re.compile(a + r"\[([^\]\r\n]{1," + m + r"})\]\s*", flags=re.UNICODE)
    if key == "brace":
        return re.compile(a + r"\{([^}\r\n]{1," + m + r"})\}\s*", flags=re.UNICODE)
    return None


def _looks_like_url(code_as: str, line: str, marker_end: int) -> bool:
    rest = line[marker_end:]
    return http_scheme_tail_re.search(code_as) is not None and rest.lstrip().startswith("//")


def iter_speaker_turns(pattern, line: str, anywhere: bool = False):
    """Yield (name, marker_start, marker_end) for every valid marker.

    ``pattern`` may be a single compiled pattern or a list of patterns
    (mixed mode: the earliest-starting marker wins at each position).
    """
    patterns = list(pattern) if isinstance(pattern, (list, tuple)) else None
    is_multi = patterns is not None
    scan_anywhere = anywhere or is_multi
    pos = 0
    while pos <= len(line):
        if is_multi:
            m = None
            for pat in patterns or []:
                cand = pat.search(line, pos)
                if cand is None or cand.end() == cand.start():
                    continue
                if m is None or cand.start() < m.start() or (
                    cand.start() == m.start() and cand.end() > m.end()
                ):
                    m = cand
        else:
            m = pattern.search(line, pos) if scan_anywhere else pattern.match(line)
        if m is None:
            return
        if m.end() == m.start():
            if not scan_anywhere:
                return
            pos = m.end() + 1
            continue
        raw = m.group(1) if m.re.groups >= 1 else m.group(0)
        code_as = re.sub(r"\s+", " ", raw or "").strip()
        if code_as and not _looks_like_url(code_as, line, m.end()):
            yield code_as, m.start(), m.end()
        pos = m.end()
        if not scan_anywhere:
            return


def _name_patterns(delimiter_safe: bool):
    """Patterns for the bare ``Name:`` identifier (line start + mid-paragraph)."""
    mlen = str(MAX_NAME_LEN)
    if delimiter_safe:
        line_start = re.compile(
            r"^\s*([^.,#@\[{\r\n]{1," + mlen + r"}?)\s*:\s*", flags=re.UNICODE
        )
    else:
        line_start = re.compile(
            r"^\s*([^.,\r\n]{1," + mlen + r"}?)\s*:\s*", flags=re.UNICODE
        )
    mid_paragraph = re.compile(
        r"(?<=[.,])\s+([" + _UPPER + r"][^\W\d_]*(?:[ \t]+[^\W\d_]+){0,5}):",
        flags=re.UNICODE,
    )
    return [line_start, mid_paragraph]


def resolve_pattern(keys: list[str], custom_regex: str = "") -> tuple | None:
    """Build the pattern from the checked identifier keys.

    Returns ``None`` when nothing can be parsed; otherwise a compiled pattern
    or a list of patterns (mixed mode always scans anywhere).
    """
    keys = [k for k in keys if k in ("name", "hash", "at", "bracket", "brace", "custom")]
    if not keys:
        return None
    fixed = [k for k in keys if k != "custom"]
    custom = None
    if "custom" in keys:
        text = custom_regex.strip()
        if not text:
            return None
        try:
            custom = re.compile(text, flags=re.UNICODE)
        except re.error:
            return None
    total = len(fixed) + (1 if custom is not None else 0)
    if total == 0:
        return None
    if total == 1:
        if custom is not None:
            return (custom, True)
        key = fixed[0]
        if key == "name":
            return (_name_patterns(delimiter_safe=False), True)
        return (identifier_regex(key), False)
    patterns: list = []
    for key in fixed:
        if key == "name":
            patterns.extend(_name_patterns(delimiter_safe=True))
        else:
            patterns.append(identifier_regex(key, anchored=False))
    if custom is not None:
        patterns.append(custom)
    return (patterns, True)


def parse_transcript(
    fid: int, filename: str, transcript: str, pattern, anywhere: bool
) -> list[dict]:
    """Parse one transcript into speaker turns (upstream ``_parse_one_file``)."""
    turns: list[dict] = []
    current_name: str | None = None
    current_start: int | None = None
    current_end: int | None = None
    current_content_start: int | None = None

    def finalize() -> None:
        nonlocal current_name, current_start, current_end, current_content_start
        if current_name is None or current_start is None or current_end is None:
            return
        content_start = current_content_start or current_start
        seltext_full = transcript[current_start:current_end]
        seltext_response = transcript[content_start:current_end]
        turns.append(
            {
                "name": current_name,
                "fid": fid,
                "filename": filename,
                "seltext": seltext_full,
                "seltext_response": seltext_response.strip(),
                "pos0": current_start,
                "pos1": current_end,
                "content_pos0": content_start,
            }
        )
        current_name = None
        current_start = None
        current_end = None
        current_content_start = None

    offset = 0
    for line in transcript.splitlines(keepends=True):
        line_start = offset
        offset += len(line)
        if line.endswith("\r\n"):
            eol_len = 2
        elif line.endswith(("\n", "\r")):
            eol_len = 1
        else:
            eol_len = 0
        line_wo_eol = line[:-eol_len] if eol_len else line
        if line_wo_eol.strip() == "":
            continue

        markers = list(iter_speaker_turns(pattern, line_wo_eol, anywhere))
        if markers:
            prefix = line_wo_eol[: markers[0][1]]
            if current_name is not None and prefix.strip() != "":
                current_end = line_start + len(prefix.rstrip())
            for i, (code_as, marker_start, marker_end) in enumerate(markers):
                finalize()
                current_name = code_as
                current_start = line_start + marker_start
                current_content_start = line_start + marker_end
                if i + 1 < len(markers):
                    current_end = line_start + len(
                        line_wo_eol[: markers[i + 1][1]].rstrip()
                    )
                else:
                    current_end = line_start + len(line_wo_eol)
            continue
        if current_name is not None and current_start is not None:
            current_end = line_start + len(line_wo_eol)
    finalize()
    return turns


async def _text_sources(session: AsyncSession, fid: int | None = None) -> list[tuple[int, str, str]]:
    stmt = select(
        tables.source.c.id,
        tables.source.c.name,
        tables.source.c.fulltext,
    ).where(
        text(
            "fulltext IS NOT NULL AND "
            "(mediapath IS NULL OR mediapath LIKE '/docs/%' OR mediapath LIKE 'docs:%')"
        )
    )
    if fid is not None:
        stmt = stmt.where(tables.source.c.id == fid)
    rows = await session.execute(stmt)
    return [(r[0], r[1] or "", r[2] or "") for r in rows]


async def detect_speakers(
    session: AsyncSession,
    fid: int | None,
    keys: list[str],
    custom_regex: str = "",
) -> dict:
    """Detect speaker turns in one (or all) text source(s) without writing."""
    resolved = resolve_pattern(keys, custom_regex)
    if resolved is None:
        raise ValueError("select at least one identifier (or enter a valid custom regex)")
    pattern, anywhere = resolved
    turns: list[dict] = []
    for source_id, filename, fulltext in await _text_sources(session, fid):
        turns.extend(parse_transcript(source_id, filename, fulltext, pattern, anywhere))
    counts: dict[str, int] = defaultdict(int)
    files: dict[str, set[str]] = defaultdict(set)
    examples: dict[str, str] = {}
    for turn in turns:
        counts[turn["name"]] += 1
        files[turn["name"]].add(turn["filename"])
        if turn["name"] not in examples:
            examples[turn["name"]] = turn["seltext_response"][:120]
    summary = [
        {
            "name": name,
            "count": counts[name],
            "files": sorted(files[name]),
            "example": examples[name],
        }
        for name in sorted(counts, key=str.lower)
    ]
    return {"turns": turns, "speakers": summary}


async def mark_speakers(
    session: AsyncSession,
    fid: int | None,
    keys: list[str],
    custom_regex: str,
    selected: list[str] | None,
    owner: str,
) -> dict:
    """Create speaker codes in the "📌 Speakers" category and code each turn.

    ``selected`` restricts to the given speaker names (None = all). The
    category and codes are created on demand; existing codes are reused.
    Codings are owned by the legacy pseudo-coder ``📌 Speaker coding``.
    """
    resolved = resolve_pattern(keys, custom_regex)
    if resolved is None:
        raise ValueError("select at least one identifier (or enter a valid custom regex)")
    pattern, anywhere = resolved

    selected_set = {s.strip() for s in (selected or []) if s.strip()}

    # Category "📌 Speakers" (create on demand).
    from qualcoder_api.persistence.repositories import _capture, _inserted_pk, _rowdict

    cat_row = (
        await session.execute(
            select(tables.code_cat.c.catid).where(
                tables.code_cat.c.name == SPEAKERS_CATEGORY_NAME
            )
        )
    ).first()
    if cat_row is not None:
        catid: int | None = cat_row[0]
    else:
        result = await session.execute(
            tables.code_cat.insert().values(
                name=SPEAKERS_CATEGORY_NAME, owner=owner, date=_now(),
                memo="",
                supercatid=None,
            )
        )
        catid = int(_inserted_pk(result))
        cat_after = (
            await session.execute(
                select(tables.code_cat).where(tables.code_cat.c.catid == catid)
            )
        ).first()
        if cat_after is not None:
            await _capture(session, "code_cat", "insert", "catid", catid, _rowdict(cat_after))

    # Speaker codes (create on demand).
    code_by_name: dict[str, Code] = {}
    existing = (
        await session.execute(
            select(tables.code_name).where(tables.code_name.c.catid == catid)
        )
    ).all()
    for row in existing:
        code = Code.model_validate(row._mapping)
        code_by_name[code.name] = code

    turns: list[dict] = []
    for source_id, filename, fulltext in await _text_sources(session, fid):
        turns.extend(parse_transcript(source_id, filename, fulltext, pattern, anywhere))

    created_codes = 0
    created_code_ids: list[int] = []
    marked = 0
    skipped_duplicates = 0
    created_ctids: list[int] = []

    # Create one code per speaker name (deterministic order).
    for name in sorted({t["name"] for t in turns}, key=str.lower):
        if selected_set and name not in selected_set:
            continue
        if name not in code_by_name:
            result = await session.execute(
                tables.code_name.insert().values(
                    name=name, memo="", catid=catid, owner=owner, date=_now(), color=SPEAKER_CODE_COLOR,
                    supercid=None,
                )
            )
            new_id = int(_inserted_pk(result))
            code_after = (
                await session.execute(
                    select(tables.code_name).where(tables.code_name.c.cid == new_id)
                )
            ).first()
            if code_after is not None:
                await _capture(session, "code_name", "insert", "cid", new_id, _rowdict(code_after))
            code_by_name[name] = Code.model_validate(
                {
                    "cid": new_id,
                    "name": name,
                    "memo": "",
                    "catid": catid,
                    "owner": owner,
                    "date": "",
                    "color": SPEAKER_CODE_COLOR,
                    "supercid": None,
                }
            )
            created_codes += 1
            created_code_ids.append(new_id)

    for turn in turns:
        if selected_set and turn["name"] not in selected_set:
            continue
        turn_code = code_by_name.get(turn["name"])
        if turn_code is None:
            continue
        try:
            result = await session.execute(
                tables.code_text.insert().values(
                    cid=turn_code.cid,
                    fid=turn["fid"],
                    seltext=turn["seltext"],
                    pos0=turn["pos0"],
                    pos1=turn["pos1"],
                    owner=SPEAKER_CODER_NAME,
                    memo="",
                    date=_now(),
                    important=0,
                    weight=0,
                )
            )
            ctid = int(_inserted_pk(result))
            coding_after = (
                await session.execute(
                    select(tables.code_text).where(tables.code_text.c.ctid == ctid)
                )
            ).first()
            if coding_after is not None:
                await _capture(session, "code_text", "insert", "ctid", ctid, _rowdict(coding_after))
            marked += 1
            created_ctids.append(ctid)
        except Exception:
            skipped_duplicates += 1
    await session.commit()
    return {
        "ok": True,
        "turns_marked": marked,
        "skipped_duplicates": skipped_duplicates,
        "codes_created": created_codes,
        "category": SPEAKERS_CATEGORY_NAME,
        "owner": SPEAKER_CODER_NAME,
        "created_code_ids": created_code_ids,
        "created_ctids": created_ctids,
    }
