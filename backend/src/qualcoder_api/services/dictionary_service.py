"""Word dictionaries (MAXDictio-style) — CRUD helpers, dictionary autocoding
and the per-document x per-term frequency matrix.

A dictionary is a named list of entries; each entry maps one term to the
name of a project code (``dictionary_entry.code_name``). Dictionary autocode
reuses the regular ``coding_service.autocode`` engine: every term is matched
as a case-insensitive whole-word literal against the text sources and coded
with the entry's code. Frequencies count how often each term occurs per text
source, using the same tokenization the word-frequency report uses.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.timeutil import now as _now
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repo.base import _inserted_pk, _rowdict

# Same tokenization as the word-frequency report (report_service.py): words
# may carry one embedded apostrophe or hyphen (e.g. "don't", "e-mail").
_TOKEN_RE = re.compile(r"[^\W\d_]+(?:[''-][^\W\d_]+)*")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def _capture_dict(
    session: AsyncSession, entity: str, action: str, pk_name: str, pk_value
) -> None:
    """Journal a dictionary/dictionary_entry mutation for collaboration sync
    (replays carry these entities; without capture they never leave this
    instance, including deletes)."""
    from qualcoder_api.persistence.repositories import _capture, _rowdict

    table = getattr(tables, entity, None)
    if table is None:  # pragma: no cover - defensive
        return
    row = (
        await session.execute(
            select(table).where(table.c[pk_name] == pk_value)
        )
    ).first()
    if row is not None:
        await _capture(session, entity, action, pk_name, pk_value, _rowdict(row))


async def list_dictionaries(session: AsyncSession) -> list[dict]:
    """All dictionaries with their entries (id, name, owner, created)."""
    dict_rows = (
        await session.execute(
            select(tables.dictionary).order_by(func.lower(tables.dictionary.c.name))
        )
    ).all()
    entries = (
        await session.execute(
            select(tables.dictionary_entry).order_by(
                tables.dictionary_entry.c.dict_id, tables.dictionary_entry.c.id
            )
        )
    ).all()
    by_dict: dict[int, list[dict]] = defaultdict(list)
    for row in entries:
        by_dict[row.dict_id].append(_rowdict(row))
    result = []
    for row in dict_rows:
        item = _rowdict(row)
        item["entries"] = by_dict.get(item["id"], [])
        result.append(item)
    return result


async def get_dictionary(session: AsyncSession, dict_id: int) -> dict | None:
    row = (
        await session.execute(
            select(tables.dictionary).where(tables.dictionary.c.id == dict_id)
        )
    ).first()
    if row is None:
        return None
    item = _rowdict(row)
    entries = (
        await session.execute(
            select(tables.dictionary_entry)
            .where(tables.dictionary_entry.c.dict_id == dict_id)
            .order_by(tables.dictionary_entry.c.id)
        )
    ).all()
    item["entries"] = [_rowdict(e) for e in entries]
    return item


async def create_dictionary(session: AsyncSession, name: str, owner: str) -> dict | None:
    """Create a dictionary; returns None when the name is already taken."""
    name = name.strip()
    if not name:
        raise ValueError("dictionary name must not be empty")
    try:
        result = await session.execute(
            insert(tables.dictionary).values(name=name, owner=owner, created=_now())
        )
    except IntegrityError:
        await session.rollback()
        return None
    await session.commit()
    new_id = _inserted_pk(result)
    await _capture_dict(session, "dictionary", "insert", "id", new_id)
    await session.commit()
    item = await get_dictionary(session, new_id)
    assert item is not None
    return item


async def rename_dictionary(session: AsyncSession, dict_id: int, name: str) -> dict | None:
    """Rename a dictionary; returns None when it does not exist or the new
    name is taken."""
    name = name.strip()
    if not name:
        raise ValueError("dictionary name must not be empty")
    existing = (
        await session.execute(
            select(tables.dictionary).where(tables.dictionary.c.id == dict_id)
        )
    ).first()
    if existing is None:
        return None
    from sqlalchemy import update

    try:
        await session.execute(
            update(tables.dictionary).where(tables.dictionary.c.id == dict_id).values(name=name)
        )
    except IntegrityError:
        await session.rollback()
        return None
    await session.commit()
    await _capture_dict(session, "dictionary", "update", "id", dict_id)
    await session.commit()
    return await get_dictionary(session, dict_id)


async def delete_dictionary(session: AsyncSession, dict_id: int) -> bool:
    """Delete a dictionary and all its entries; False when it does not exist."""
    from qualcoder_api.persistence.repositories import _capture, _rowdict

    existing = (
        await session.execute(
            select(tables.dictionary).where(tables.dictionary.c.id == dict_id)
        )
    ).first()
    if existing is None:
        return False
    dict_data = _rowdict(existing)
    entry_rows = (
        await session.execute(
            select(tables.dictionary_entry).where(
                tables.dictionary_entry.c.dict_id == dict_id
            )
        )
    ).all()
    entry_data = [_rowdict(r) for r in entry_rows]
    await session.execute(
        delete(tables.dictionary_entry).where(tables.dictionary_entry.c.dict_id == dict_id)
    )
    for data in entry_data:
        await _capture(
            session, "dictionary_entry", "delete", "id", data.get("id"), data
        )
    await session.execute(delete(tables.dictionary).where(tables.dictionary.c.id == dict_id))
    await _capture(session, "dictionary", "delete", "id", dict_id, dict_data)
    await session.commit()
    return True


async def add_entry(
    session: AsyncSession, dict_id: int, code_name: str, term: str
) -> dict | str | None:
    """Add one term → code-name entry.

    Returns the entry row on success, ``None`` when the dictionary does not
    exist, or ``"duplicate"`` when the term already exists in the dictionary.
    """
    existing = (
        await session.execute(
            select(tables.dictionary.c.id).where(tables.dictionary.c.id == dict_id)
        )
    ).first()
    if existing is None:
        return None
    code_name = code_name.strip()
    term = term.strip()
    if not code_name or not term:
        raise ValueError("code name and term must not be empty")
    try:
        result = await session.execute(
            insert(tables.dictionary_entry).values(
                dict_id=dict_id, code_name=code_name, term=term
            )
        )
    except IntegrityError:
        await session.rollback()
        return "duplicate"
    await session.commit()
    new_id = _inserted_pk(result)
    await _capture_dict(session, "dictionary_entry", "insert", "id", new_id)
    await session.commit()
    row = (
        await session.execute(
            select(tables.dictionary_entry).where(
                tables.dictionary_entry.c.id == new_id
            )
        )
    ).first()
    assert row is not None
    return _rowdict(row)


async def remove_entry(session: AsyncSession, entry_id: int) -> bool:
    from qualcoder_api.persistence.repositories import _capture, _rowdict

    existing = (
        await session.execute(
            select(tables.dictionary_entry).where(tables.dictionary_entry.c.id == entry_id)
        )
    ).first()
    if existing is None:
        return False
    data = _rowdict(existing)
    await session.execute(delete(tables.dictionary_entry).where(tables.dictionary_entry.c.id == entry_id))
    await _capture(session, "dictionary_entry", "delete", "id", entry_id, data)
    await session.commit()
    return True


# ---------------------------------------------------------------------------
# Import (text/CSV: "code,term1,term2,..." per line)
# ---------------------------------------------------------------------------


def parse_dictionary_text(content: str) -> dict[str, list[str]]:
    """Parse dictionary text into {code_name: [terms]}.

    One ``code,term1,term2,...`` line per entry; a bare single term on its
    own line is assigned to the previous line's code. Empty lines and lines
    starting with ``#`` are ignored.
    """
    result: dict[str, list[str]] = {}
    last_code: str | None = None
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 1:
            if last_code is not None and parts[0]:
                result.setdefault(last_code, []).append(parts[0])
            continue
        code = parts[0]
        if not code:
            continue
        terms = [p for p in parts[1:] if p]
        result.setdefault(code, []).extend(terms)
        last_code = code
    return result


async def import_dictionary(
    session: AsyncSession, name: str, content: str, owner: str
) -> dict:
    """Create (or extend) a dictionary from parsed text; returns a summary.

    ``name`` selects an existing dictionary to extend (when the caller passes
    an id via ``dict_id``-style flow) — here: create-or-extend by name.
    """
    parsed = parse_dictionary_text(content)
    existing = (
        await session.execute(
            select(tables.dictionary).where(func.lower(tables.dictionary.c.name) == name.lower())
        )
    ).first()
    if existing is not None:
        dictionary = await get_dictionary(session, existing.id)
        assert dictionary is not None
        created_dict = False
    else:
        dictionary = await create_dictionary(session, name, owner)
        assert dictionary is not None
        created_dict = True
    dict_id = dictionary["id"]
    added = 0
    skipped = 0
    for code_name, terms in parsed.items():
        for term in terms:
            outcome = await add_entry(session, dict_id, code_name, term)
            if outcome == "duplicate" or outcome is None:
                skipped += 1
            else:
                added += 1
    return {
        "dictionary": dictionary,
        "created": created_dict,
        "added": added,
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# Dictionary autocode — reuses coding_service.autocode per entry
# ---------------------------------------------------------------------------


def whole_word_pattern(term: str) -> str:
    """Case-insensitive whole-word literal regex for one dictionary term."""
    return f"(?i)(?<!\\w){re.escape(term)}(?!\\w)"


async def dictionary_autocode(
    session: AsyncSession,
    *,
    dictionary_id: int,
    owner: str,
    source_ids: list[int] | None = None,
) -> dict | None:
    """Autocode every dictionary entry against the project (or ``source_ids``).

    Returns None when the dictionary does not exist. Each entry runs through
    the regular autocode engine with the term as a case-insensitive whole-word
    literal; the created codings carry the entry's code. Terms whose code no
    longer exists are skipped and reported. Result::

        {
          "dictionary_id": 1,
          "per_code": [{"code_name": ..., "count": n}, ...],
          "total": n,
          "unmatched_codes": ["...", ...],
          "skipped_terms": [term, ...],
          "created_rows": [<full code_text row>, ...],
        }
    """
    from qualcoder_api.services.coding_service import autocode

    dictionary = await get_dictionary(session, dictionary_id)
    if dictionary is None:
        return None

    entries = dictionary["entries"]
    # Resolve code names to code ids (exact name match, like the AI fallback).
    code_rows = (
        await session.execute(select(tables.code_name.c.cid, tables.code_name.c.name))
    ).all()
    cid_by_name: dict[str, int] = {}
    for cid, name in code_rows:
        cid_by_name.setdefault(str(name), cid)

    per_code: Counter[str] = Counter()
    skipped_terms: list[str] = []
    created_rows: list[dict] = []
    for entry in entries:
        cid = cid_by_name.get(entry["code_name"])
        if cid is None:
            skipped_terms.append(entry["term"])
            continue
        pattern = whole_word_pattern(entry["term"])
        if source_ids:
            for fid in source_ids:
                result = await autocode(
                    session,
                    fid=fid,
                    cids=[cid],
                    find_texts=[pattern],
                    mode="all",
                    use_regex=True,
                    owner=owner,
                )
                per_code[entry["code_name"]] += len(result["created"])
                created_rows.extend(result["created"])
        else:
            result = await autocode(
                session,
                fid=None,
                cids=[cid],
                find_texts=[pattern],
                mode="all",
                use_regex=True,
                owner=owner,
            )
            per_code[entry["code_name"]] += len(result["created"])
            created_rows.extend(result["created"])

    unmatched = sorted(
        {entry["code_name"] for entry in entries if entry["code_name"] not in cid_by_name}
    )
    per_code_rows = [
        {"code_name": code, "count": count}
        for code, count in sorted(per_code.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "dictionary_id": dictionary_id,
        "per_code": per_code_rows,
        "total": sum(per_code.values()),
        "unmatched_codes": unmatched,
        "skipped_terms": skipped_terms,
        "created_rows": created_rows,
    }


# ---------------------------------------------------------------------------
# Frequency matrix — same tokenizer as the word-frequency report
# ---------------------------------------------------------------------------


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _term_tokens(term: str) -> list[str]:
    return _TOKEN_RE.findall(term.lower())


def _count_term(tokens: list[str], term_tokens: list[str]) -> int:
    """Count non-overlapping occurrences of the term's token sequence."""
    n = len(term_tokens)
    if n == 0 or len(tokens) < n:
        return 0
    count = 0
    i = 0
    while i <= len(tokens) - n:
        if tokens[i : i + n] == term_tokens:
            count += 1
            i += n
        else:
            i += 1
    return count


async def dictionary_frequencies(
    session: AsyncSession,
    dictionary_id: int,
    *,
    normalize: bool = False,
    use_stopwords: bool = True,
) -> dict | None:
    """Per-document x per-term occurrence matrix for a dictionary.

    Terms are matched with the same tokenization as the word-frequency
    report (lowercased words, one embedded apostrophe/hyphen allowed).
    ``use_stopwords`` (default True, like the word-frequency report) drops
    English stopword terms from the matrix. With ``normalize`` each cell is
    the term's share of its file's term occurrences (percent, one decimal).
    Returns None when the dictionary does not exist.
    """
    dictionary = await get_dictionary(session, dictionary_id)
    if dictionary is None:
        return None
    from qualcoder_api.services.report_service import _STOPWORDS

    terms = [entry["term"] for entry in dictionary["entries"]]
    terms = [t for t in terms if t.strip()]
    if use_stopwords:
        terms = [t for t in terms if t.lower() not in _STOPWORDS]

    file_rows = (
        await session.execute(
            select(tables.source.c.id, tables.source.c.name, tables.source.c.fulltext).where(
                tables.source.c.fulltext.is_not(None),
                tables.source.c.mediapath.is_(None)
                | tables.source.c.mediapath.like("/docs/%")
                | tables.source.c.mediapath.like("docs:%"),
            )
        )
    ).all()

    term_token_lists = [_term_tokens(t) for t in terms]
    counts: list[list[int]] = []
    files: list[dict] = []
    for fid, name, fulltext in file_rows:
        tokens = _tokens(fulltext)
        row_counts = [_count_term(tokens, tt) for tt in term_token_lists]
        files.append({"fid": fid, "name": name})
        counts.append(row_counts)

    grand_total = sum(sum(row) for row in counts)
    column_totals = [sum(row[i] for row in counts) for i in range(len(terms))]

    rows: list[dict] = []
    for file_item, row_counts in zip(files, counts, strict=True):
        row_total = sum(row_counts)
        cells: list[int] | list[float] = row_counts
        if normalize and row_total > 0:
            cells = [round(c / row_total * 100, 1) for c in row_counts]
        rows.append(
            {
                "fid": file_item["fid"],
                "file": file_item["name"],
                "counts": cells,
                "total": 100.0 if (normalize and row_total > 0) else row_total,
            }
        )
    col_totals_out: list[int] | list[float]
    if normalize and grand_total > 0:
        col_totals_out = [round(c / grand_total * 100, 1) for c in column_totals]
        totals_out = 100.0
    else:
        col_totals_out = column_totals
        totals_out = grand_total
    return {
        "dictionary_id": dictionary_id,
        "dictionary_name": dictionary["name"],
        "terms": terms,
        "files": files,
        "rows": rows,
        "column_totals": col_totals_out,
        "total": totals_out,
        "normalize": normalize,
    }
