"""Autocode subsystem — pattern and AI-driven automatic coding.

Split out of ``coding_service``: ``autocode`` ports the legacy
``CodeText.auto_code`` pattern matcher; ``ai_autocode`` drives the LLM
autocoder; ``_ai_code_spans`` and ``_suggest_and_create_codes`` are the AI
helpers; ``_emoji_list`` adjusts match offsets for emoji width.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import CodingRepository


def _emoji_list(text: str) -> list[dict]:
    try:
        import emoji
    except ImportError:  # pragma: no cover - optional dependency
        return []
    return [dict(m) for m in emoji.emoji_list(text)]


async def autocode(
    session: AsyncSession,
    *,
    fid: int | None,
    cids: list[int],
    find_texts: list[str],
    mode: str = "all",
    use_regex: bool = False,
    owner: str,
    suggest: bool = False,
) -> dict:
    """Autocode matching text spans in one source (or all text sources) for
    ANY of the given codes. ``mode`` is "all", "first", "last" or
    ``"code_within_code <cid>"``. Regex compile errors raise ValueError;
    duplicate inserts are skipped silently.

    With ``suggest`` enabled and the AI assistant configured, the service
    additionally scans the NOT-yet-coded text for important content that no
    existing code covers and creates new codes for it ("AI suggested").
    """
    within_cid: int | None = None
    if mode.startswith("code_within_code"):
        parts = mode.split()
        if len(parts) != 2:
            raise ValueError("invalid code_within_code mode")
        try:
            within_cid = int(parts[1])
        except ValueError:
            raise ValueError("invalid code_within_code mode") from None
        mode = "all"
    patterns = [t.strip() for t in find_texts if t.strip()]
    regexes: list[re.Pattern[str]] = []
    if use_regex:
        for pattern in patterns:
            try:
                regexes.append(re.compile(pattern))
            except re.error as err:
                raise ValueError("invalid regex") from err

    if fid is None:
        rows = (
            await session.execute(
                select(tables.source.c.id, tables.source.c.fulltext).where(
                    or_(
                        tables.source.c.mediapath.is_(None),
                        tables.source.c.mediapath.like("/docs/%"),
                        tables.source.c.mediapath.like("docs:%"),
                    )
                )
            )
        ).all()
    else:
        row = (
            await session.execute(
                select(tables.source.c.id, tables.source.c.fulltext).where(
                    tables.source.c.id == fid
                )
            )
        ).first()
        rows = [row] if row is not None else []

    # code_within_code: (fid) -> sorted list of (pos0, pos1) coded segments.
    within_spans: dict[int, list[tuple[int, int]]] = {}
    if within_cid is not None:
        span_rows = (
            await session.execute(
                select(tables.code_text.c.fid, tables.code_text.c.pos0, tables.code_text.c.pos1)
                .where(
                    tables.code_text.c.cid == within_cid,
                    tables.code_text.c.owner == owner,
                )
                .order_by(tables.code_text.c.pos0)
            )
        ).all()
        for span_fid, pos0, pos1 in span_rows:
            within_spans.setdefault(span_fid, []).append((pos0, pos1))

    def _inside(pos0: int, pos1: int, fid: int) -> bool:
        return any(pos0 >= s0 and pos1 <= s1 for s0, s1 in within_spans.get(fid, []))

    created: list[dict] = []
    repo = CodingRepository(session)
    coded_spans: dict[int, list[tuple[int, int]]] = {}
    for cid in cids:
        for index, find_txt in enumerate(patterns):
            for file_id, file_text in rows:
                if file_text is None:
                    continue
                emojis = _emoji_list(file_text)
                if use_regex:
                    matches = [(m.start(), m.end()) for m in regexes[index].finditer(file_text)]
                else:
                    matches = [(m.start(), m.end()) for m in re.finditer(re.escape(find_txt), file_text)]
                if mode == "first" and len(matches) > 1:
                    matches = matches[:1]
                if mode == "last" and len(matches) > 1:
                    matches = matches[-1:]
                for start, end in matches:
                    if within_cid is not None and not _inside(start, end, file_id):
                        continue
                    pos0, pos1 = start, end
                    seltext = file_text[start:end] if use_regex else find_txt
                    # Emoji positions from the Qt UI count UTF-16 code units;
                    # add each preceding emoji's extra length to pos0/pos1.
                    for emo in emojis:
                        if emo["match_end"] < pos0:
                            pos0 += emo["match_end"] - emo["match_start"]
                            pos1 += emo["match_end"] - emo["match_start"]
                    try:
                        coding = await repo.add_text_coding(
                            cid=cid,
                            fid=file_id,
                            seltext=seltext,
                            pos0=pos0,
                            pos1=pos1,
                            owner=owner,
                            memo="",
                        )
                    except IntegrityError:
                        # Possible a duplicate entry (unique cid,fid,pos0,pos1,owner)
                        continue
                    coded_spans.setdefault(file_id, []).append((pos0, pos1))
                    created.append(
                        {
                            "ctid": coding.ctid,
                            "cid": coding.cid,
                            "fid": coding.fid,
                            "seltext": coding.seltext,
                            "pos0": coding.pos0,
                            "pos1": coding.pos1,
                            "owner": coding.owner,
                            "memo": coding.memo,
                            "date": coding.date,
                            "important": coding.important,
                        }
                    )

    suggested: list[dict] = []
    if suggest:
        suggested = await _suggest_and_create_codes(session, rows, coded_spans, owner)

    return {"created": created, "count": len(created), "suggested": suggested}


async def ai_autocode(
    session: AsyncSession,
    *,
    fid: int,
    cids: list[int],
    prompt: str,
    suggest: bool,
    owner: str,
) -> dict:
    """AI-driven autocoding: the LLM applies the coding prompt to the source
    text and returns coded spans (exact code name + character offsets), which
    are created as text codings. When the AI assistant is disabled, falls
    back to literal matches of the selected code names. With ``suggest`` the
    LLM may propose NEW codes for content that fits none of the selected
    ones — those are created on the fly.
    """
    from qualcoder_api.persistence.repositories import CodeRepository
    from qualcoder_api.services import user_settings
    from qualcoder_api.services.ai_service import AiUnavailable

    row = (
        await session.execute(select(tables.source.c.fulltext).where(tables.source.c.id == fid))
    ).first()
    if row is None or not row[0]:
        return {"created": [], "count": 0, "suggested": []}
    text = row[0]

    code_rows = (
        await session.execute(
            select(tables.code_name.c.cid, tables.code_name.c.name).where(
                tables.code_name.c.cid.in_(cids)
            )
        )
    ).all()
    names: dict[int, str] = {row[0]: row[1] for row in code_rows}

    spans: list[tuple[int, int, str, str]] = []
    # Fallback pins: (start, end) -> the exact code id (deterministic path).
    created_spans_cid: dict[tuple[int, int], int] = {}
    ai = user_settings.get_ai_settings()
    if ai.get("enabled"):
        try:
            spans = await _ai_code_spans(session, ai, text, list(names.values()), prompt, suggest)
        except AiUnavailable:
            spans = []
    if not spans:
        # Fallback without AI: literal matches of the selected code names
        # plus any quoted terms in the prompt ("…passages about \"family\"…"),
        # which are coded with the first selected code.
        first_cid = cids[0] if cids else None
        terms: list[tuple[str, int]] = [(n, c) for c, n in names.items() if n]
        terms += [(term, first_cid) for term in re.findall(r'"([^"]{2,})"', prompt) if first_cid is not None]
        for term, term_cid in terms:
            if term_cid is None:
                continue
            for m in re.finditer(re.escape(term), text):
                spans.append((m.start(), m.end(), term, ""))
                created_spans_cid.setdefault((m.start(), m.end()), term_cid)

    repo = CodingRepository(session)
    code_repo = CodeRepository(session)
    created: list[dict] = []
    suggested: list[dict] = []
    for start, end, code_name, reason in spans:
        start = max(0, min(start, len(text)))
        end = max(0, min(end, len(text)))
        if end <= start or not code_name:
            continue
        # The deterministic fallback pins the exact target code; the AI path
        # resolves by name.
        target_cid = created_spans_cid.get((start, end))
        if target_cid is None:
            target_cid = next((c for c, n in names.items() if n == code_name), None)
        if target_cid is None:
            if suggest:
                new = await code_repo.add_code(name=code_name, owner=owner)
                if new is None:
                    continue
                target_cid = new.cid
                names[target_cid] = code_name
                suggested.append({"cid": target_cid, "name": code_name, "reason": reason})
            else:
                continue
        seltext = text[start:end]
        try:
            coding = await repo.add_text_coding(
                cid=target_cid, fid=fid, seltext=seltext, pos0=start, pos1=end, owner=owner, memo=""
            )
        except IntegrityError:
            continue
        created.append(
            {
                "ctid": coding.ctid,
                "cid": coding.cid,
                "fid": coding.fid,
                "seltext": coding.seltext,
                "pos0": coding.pos0,
                "pos1": coding.pos1,
                "owner": coding.owner,
                "memo": coding.memo,
                "date": coding.date,
                "important": coding.important,
            }
        )
    return {"created": created, "count": len(created), "suggested": suggested}


async def _ai_code_spans(
    session: AsyncSession,
    ai: dict,
    text: str,
    code_names: list[str],
    prompt: str,
    suggest: bool,
) -> list[tuple[int, int, str, str]]:
    """Ask the LLM for coded spans in the (chunked) text. Returns
    (start, end, code_name, reason) tuples. Raises AiUnavailable when the
    provider is unreachable."""
    import json

    from qualcoder_api.services.ai_service import AiService

    # LLM context is limited: autocode the first 6000 characters.
    chunk = text[:6000]
    code_list = ", ".join(code_names) if code_names else "(no codes selected)"
    instruction = (
        "You are a qualitative coding assistant. Apply the researcher's coding "
        f"instruction to the text.\n\nCODING INSTRUCTION:\n{prompt}\n\n"
        f"CODES:\n{code_list}\n\nTEXT:\n{chunk}\n\n"
        "Return ONLY a JSON array of the coded segments, one per coded span, "
        'in the form [{"code": "<exact code name>", "start": <character '
        'offset>, "end": <character offset>, "reason": "<short reason>"}]. '
        "Offsets are character positions in the TEXT above (start is inclusive, "
        "end exclusive). Use the listed codes for every span."
    )
    if suggest:
        instruction += (
            " If some important content clearly fits NONE of the listed codes, "
            "you MAY add one extra entry with a NEW short code name instead."
        )

    reply = await AiService(session).chat(ai, instruction, context="", mode="general")
    text_reply = (reply.get("reply") or "").strip()
    start = text_reply.find("[")
    end = text_reply.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        parsed = json.loads(text_reply[start : end + 1])
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []

    out: list[tuple[int, int, str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("code") or "").strip()
        raw_start = item.get("start")
        raw_end = item.get("end")
        if not isinstance(raw_start, int) or not isinstance(raw_end, int):
            continue
        s0, s1 = raw_start, raw_end
        reason = str(item.get("reason") or "").strip()
        if s1 <= s0 or s0 < 0:
            continue
        out.append((s0, s1, name, reason))
    return out


async def _suggest_and_create_codes(
    session: AsyncSession,
    rows: Sequence[Any],
    coded_spans: dict[int, list[tuple[int, int]]],
    owner: str,
) -> list[dict]:
    """Ask the AI for important topics in the still-uncoded text and create
    a new code for each. Returns [{cid, name, reason}] (empty when the AI
    assistant is disabled/unconfigured or nothing important is found)."""
    from qualcoder_api.persistence.repositories import CodeRepository
    from qualcoder_api.services import user_settings
    from qualcoder_api.services.ai_service import AiService

    ai = user_settings.get_ai_settings()
    if not ai.get("enabled"):
        return []

    # Existing code names (the AI must not propose duplicates).
    existing_rows = (
        await session.execute(select(tables.code_name.c.name))
    ).all()
    existing = {str(r[0]).strip().lower() for r in existing_rows if r[0]}

    # The still-uncoded text: cut out everything a pattern already coded.
    chunks: list[str] = []
    for file_id, file_text in rows:
        if not file_text:
            continue
        text = file_text
        parts: list[str] = []
        pos = 0
        for s0, s1 in sorted(coded_spans.get(file_id, [])):
            if s0 > pos:
                parts.append(text[pos:s0])
            pos = max(pos, s1)
        if pos < len(text):
            parts.append(text[pos:])
        chunk = "\n".join(parts).strip()
        if chunk:
            chunks.append(chunk[:6000])
    if not chunks:
        return []

    prompt = (
        "You are helping a qualitative researcher with coding. Below is a text "
        "excerpt and the names of the codes that already exist in the project.\n\n"
        "EXISTING CODES:\n"
        + (", ".join(sorted(existing)) if existing else "(none)")
        + "\n\nTEXT:\n"
        + "\n---\n".join(chunks)[:8000]
        + "\n\nFind the up to THREE most important topics in the text that are "
        "NOT covered by any existing code. For each, propose a short new code "
        "name (2-4 words max) and a one-line reason. Reply with ONLY a JSON "
        "array, no markdown: [{\"name\": \"...\", \"reason\": \"...\"}]"
    )
    try:
        service = AiService(session)
        reply = await service.chat(ai, prompt, context="", mode="general")
    except Exception:  # any AI failure degrades to no suggestions
        return []

    import json

    text = (reply.get("reply") or "").strip()
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        proposals = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(proposals, list):
        return []

    suggested: list[dict] = []
    for item in proposals:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not name or name.lower() in existing:
            continue
        try:
            code = await CodeRepository(session).add_code(
                name=name, owner=owner, catid=None, supercid=None
            )
            existing.add(name.lower())
        except Exception:
            continue
        if code is None:
            continue
        suggested.append({"cid": code.cid, "name": code.name, "reason": reason})
        if len(suggested) >= 3:
            break
    return suggested
