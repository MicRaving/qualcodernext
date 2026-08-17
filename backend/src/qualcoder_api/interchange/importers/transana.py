"""Transana importer — import a Transana ``.tprd`` SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import aiosqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.core.enums import MediaType
from qualcoder_api.interchange.importers.base import (
    TRANSANA_TABLES,
    _columns,
    _existing_names,
    _fetch,
    _first,
    _pick,
    _table_names,
)
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import (
    CodeRepository,
    CodingRepository,
    SourceRepository,
)
from qualcoder_api.services.import_service import detect_media_type


def _resolve_media_path(base_dir: Path, stored: str | None, name: str | None) -> Path | None:
    """The first existing file among the candidates for a stored media path.

    Candidates: the stored path (when absolute), the stored path or plain
    file name relative to the database's directory. Returns ``None`` when
    none exists.
    """
    candidates: list[Path] = []
    if stored:
        if Path(stored).is_absolute():
            candidates.append(Path(stored))
        candidates.append(base_dir / stored)
    if name:
        candidates.append(base_dir / name)
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _clamp_offsets(pos0: int, pos1: int, length: int) -> tuple[int, int]:
    """Clamp an offset pair into ``[0, length]`` with a non-empty span."""
    pos0 = max(0, min(pos0, length))
    pos1 = max(0, min(pos1, length))
    if pos1 <= pos0:
        pos1 = min(length, pos0 + 1)
    return pos0, pos1


async def import_transana(
    session_factory: async_sessionmaker, transana_path: str, codername: str
) -> dict:
    """Import a Transana ``.tprd`` SQLite database into the open project.

    The Transana schema varies between versions, so the importer probes the
    database and maps whatever exists: transcripts
    (``Transcripts``/``EpisodeTranscripts``) become text sources, media and
    episode files (``MediaFiles``/``Media``, ``Episodes``/``EpisodeFiles``)
    become audio/video sources when their file is found next to the
    database (external ``audio:``/``video:`` links, media type derived from
    the file extension like the file import pipeline); ``Keywords`` become
    codes, grouped into categories when a ``KeywordTypes`` table exists;
    keyword assignments (``TranscriptKeywordAssignments``,
    ``KeywordAssignments``, ``EpisodeKeywordAssignments``) become text or
    AV codings. Transana stores assignment positions as media timecodes
    (milliseconds); when a schema has no character offsets, the time range
    is projected proportionally onto the transcript text and clamped to its
    length — positions are best-effort, not exact, and the coded segment
    text is whatever that slice contains. Rows whose name already exists in
    the project are skipped. Raises ``ValueError`` when the file is not a
    readable Transana SQLite database.
    """
    try:
        uri = Path(transana_path).as_uri() + "?mode=ro"
        async with aiosqlite.connect(uri, uri=True) as src:
            return await _import_transana(src, session_factory, codername, transana_path)
    except sqlite3.Error as err:
        raise ValueError(f"Invalid Transana file: {err}") from err


async def _import_transana(
    src: aiosqlite.Connection, session_factory, codername: str, transana_path: str
) -> dict:
    counts: dict[str, int] = {
        "sources": 0,
        "categories": 0,
        "codes": 0,
        "codings": 0,
        "skipped": 0,
    }
    tables_present = {name.lower() for name in await _table_names(src)}
    if not tables_present & TRANSANA_TABLES:
        raise ValueError("Not a Transana database")

    base_dir = Path(transana_path).parent

    async def cols_of(table: str) -> set[str]:
        """Lowercased column names — Transana uses CamelCase (``StartTime``),
        probed with lowercase candidates. SQLite identifiers are
        case-insensitive, so the lowercased names select fine."""
        return {c.lower() for c in await _columns(src, table)}

    async with session_factory() as session:
        source_repo = SourceRepository(session)
        code_repo = CodeRepository(session)
        coding_repo = CodingRepository(session)

        # -- transcripts -> text sources ---------------------------------
        transcript_id_map: dict[int, int] = {}
        transcript_text: dict[int, str] = {}
        existing = await _existing_names(session, tables.source, "name")
        for table in ("transcripts", "episodetranscripts"):
            if table not in tables_present:
                continue
            cols = await cols_of(table)
            id_col = _first(cols, "transcriptid", "id", "transcriptkey")
            name_col = _first(cols, "transcriptname", "transcripttitle", "name")
            text_col = _first(cols, "transcripttext", "transcriptcontents", "text", "fulltext")
            memo_col = _first(cols, "transcriptnotes", "notes", "memo", "description")
            if not (id_col and name_col and text_col):
                continue
            pick = _pick(cols, id_col, name_col, text_col, memo_col)
            for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM {table}"):
                values = dict(zip(pick, row, strict=True))
                name = values[name_col]
                if not name or name in existing:
                    continue
                text = values[text_col] or ""
                source = await source_repo.add_source(
                    name=name,
                    mediapath=None,
                    fulltext=text,
                    memo=values.get(memo_col or "") or "" if memo_col else "",
                    owner=codername,
                )
                transcript_id_map[values[id_col]] = source.id
                transcript_text[values[id_col]] = text
                existing.add(name)
                counts["sources"] += 1

        # -- media files -> audio/video sources ----------------------------
        # Registered only when the file is actually found next to the
        # database (external ``audio:``/``video:`` links, media type derived
        # from the extension — same classification as the file import).
        media_id_map: dict[int, int] = {}
        media_by_path: dict[Path, int] = {}
        for table, id_cands, name_cands, path_cands in (
            ("mediafiles", ("mediaid", "id", "mediakey"), ("mediafilename", "name"),
             ("mediafilepath", "filepath", "path")),
            ("media", ("mediaid", "id", "mediakey"), ("mediafilename", "name"),
             ("mediafilepath", "filepath", "path")),
        ):
            if table not in tables_present:
                continue
            cols = await cols_of(table)
            id_col = _first(cols, *id_cands)
            name_col = _first(cols, *name_cands)
            path_col = _first(cols, *path_cands)
            if not id_col or not (name_col or path_col):
                continue
            pick = _pick(cols, id_col, name_col, path_col)
            for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM {table}"):
                values = dict(zip(pick, row, strict=True))
                resolved = _resolve_media_path(
                    base_dir, values[path_col] if path_col else None,
                    values[name_col] if name_col else None,
                )
                if resolved is None:
                    counts["skipped"] += 1
                    continue
                filename = resolved.name
                if filename in existing:
                    counts["skipped"] += 1
                    continue
                mtype = detect_media_type(filename)
                media_prefix = {
                    MediaType.TEXT: "docs:",
                    MediaType.PDF: "docs:",
                    MediaType.IMAGE: "images:",
                    MediaType.AUDIO: "audio:",
                    MediaType.VIDEO: "video:",
                }[mtype]
                source = await source_repo.add_source(
                    name=filename,
                    mediapath=f"{media_prefix}{resolved.as_posix()}",
                    fulltext=None,
                    memo="",
                    owner=codername,
                )
                media_id_map[values[id_col]] = source.id
                media_by_path[resolved] = source.id
                existing.add(filename)
                counts["sources"] += 1

        # -- episodes -> existing media source or their own source ---------
        # An episode usually wraps a media file; when that file is already
        # registered, the episode maps to it (its assignments code the media
        # source). A distinct episode file gets its own source.
        episode_id_map: dict[int, int] = {}
        for table, id_cands, name_cands, path_cands in (
            ("episodes", ("episodeid", "id", "episodekey"), ("episodename", "name"),
             ("episodefilepath", "filepath", "path")),
            ("episodefiles", ("episodeid", "id", "episodekey"), ("episodename", "name"),
             ("episodefilepath", "filepath", "path")),
        ):
            if table not in tables_present:
                continue
            cols = await cols_of(table)
            id_col = _first(cols, *id_cands)
            name_col = _first(cols, *name_cands)
            path_col = _first(cols, *path_cands)
            if not id_col or not (name_col or path_col):
                continue
            pick = _pick(cols, id_col, name_col, path_col)
            for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM {table}"):
                values = dict(zip(pick, row, strict=True))
                resolved = _resolve_media_path(
                    base_dir, values[path_col] if path_col else None,
                    values[name_col] if name_col else None,
                )
                if resolved is None:
                    counts["skipped"] += 1
                    continue
                existing_fid = media_by_path.get(resolved)
                if existing_fid is not None:
                    episode_id_map[values[id_col]] = existing_fid
                    continue
                filename = resolved.name
                if filename in existing:
                    counts["skipped"] += 1
                    continue
                mtype = detect_media_type(filename)
                media_prefix = {
                    MediaType.TEXT: "docs:",
                    MediaType.PDF: "docs:",
                    MediaType.IMAGE: "images:",
                    MediaType.AUDIO: "audio:",
                    MediaType.VIDEO: "video:",
                }[mtype]
                source = await source_repo.add_source(
                    name=filename,
                    mediapath=f"{media_prefix}{resolved.as_posix()}",
                    fulltext=None,
                    memo="",
                    owner=codername,
                )
                episode_id_map[values[id_col]] = source.id
                media_by_path[resolved] = source.id
                existing.add(filename)
                counts["sources"] += 1

        # -- keyword types -> categories ----------------------------------
        type_map: dict[int, int] = {}
        if "keywordtypes" in tables_present:
            cols = await cols_of("keywordtypes")
            id_col = _first(cols, "keywordtypeid", "id", "typeid")
            name_col = _first(cols, "keywordtypename", "typename", "name")
            if id_col and name_col:
                existing = await _existing_names(session, tables.code_cat, "name")
                for type_id, name in await _fetch(
                    src, f"SELECT {id_col}, {name_col} FROM keywordtypes"
                ):
                    if not name or name in existing:
                        continue
                    category = await code_repo.add_category(name=name, owner=codername)
                    if category is not None:
                        type_map[type_id] = category.catid
                        existing.add(name)
                        counts["categories"] += 1

        # -- keywords -> codes ---------------------------------------------
        code_map: dict[int, int] = {}
        if "keywords" in tables_present:
            cols = await cols_of("keywords")
            id_col = _first(cols, "keywordid", "id", "keywordkey")
            name_col = _first(cols, "keywordname", "keyword", "name")
            type_col = _first(cols, "keywordtypeid", "typeid", "keywordcategoryid", "categoryid")
            memo_col = _first(cols, "keywordnotes", "notes", "memo", "description")
            if id_col and name_col:
                pick = _pick(cols, id_col, name_col, type_col, memo_col)
                existing = await _existing_names(session, tables.code_name, "name")
                for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM keywords"):
                    values = dict(zip(pick, row, strict=True))
                    name = values[name_col]
                    if not name or name in existing:
                        continue
                    catid = type_map.get(values[type_col]) if type_col else None
                    code = await code_repo.add_code(
                        name=name,
                        owner=codername,
                        catid=catid,
                        memo=values.get(memo_col or "") or "" if memo_col else "",
                    )
                    if code is not None:
                        code_map[values[id_col]] = code.cid
                        existing.add(name)
                        counts["codes"] += 1

        # -- keyword assignments -> codings --------------------------------
        # Transana positions are media timecodes (ms). Some schemas store
        # character offsets instead — those are used directly. With only
        # timecodes, the range is projected proportionally onto the
        # transcript text using the transcript's latest assignment end time
        # as the duration, then clamped to the text length (best-effort).
        max_end: dict[int, int] = {}
        for table in ("transcriptkeywordassignments", "keywordassignments"):
            if table not in tables_present:
                continue
            cols = await cols_of(table)
            t_col = _first(cols, "transcriptid", "transcriptkey")
            end_col = _first(cols, "endtime", "endtimecode", "end")
            if t_col and end_col:
                for t_id, end in await _fetch(
                    src, f"SELECT {t_col}, {end_col} FROM {table}"
                ):
                    if end is not None and end > max_end.get(t_id, 0):
                        max_end[t_id] = end

        for table in ("transcriptkeywordassignments", "keywordassignments",
                      "episodekeywordassignments"):
            if table not in tables_present:
                continue
            cols = await cols_of(table)
            keyword_col = _first(cols, "keywordid", "keywordkey", "keyword")
            transcript_col = _first(cols, "transcriptid", "transcriptkey")
            episode_col = _first(cols, "episodeid", "episodekey")
            char0_col = _first(cols, "startchar", "startpos", "pos0", "startoffset")
            char1_col = _first(cols, "endchar", "endpos", "pos1", "endoffset")
            time0_col = _first(cols, "starttime", "starttimecode", "start")
            time1_col = _first(cols, "endtime", "endtimecode", "end")
            snippet_col = _first(cols, "snippet", "selectedtext", "seltext")
            if not keyword_col:
                continue
            if transcript_col and not (char0_col or time0_col):
                continue
            if episode_col and not time0_col:
                continue
            pick = _pick(
                cols, transcript_col, episode_col, keyword_col,
                char0_col, char1_col, time0_col, time1_col, snippet_col,
            )
            for row in await _fetch(src, f"SELECT {', '.join(pick)} FROM {table}"):
                values = dict(zip(pick, row, strict=True))
                new_cid = code_map.get(values[keyword_col])
                if new_cid is None:
                    counts["skipped"] += 1
                    continue
                if transcript_col:
                    t_id = values[transcript_col]
                    new_fid = transcript_id_map.get(t_id)
                    if new_fid is None:
                        counts["skipped"] += 1
                        continue
                    text = transcript_text.get(t_id, "")
                    if not text:
                        counts["skipped"] += 1
                        continue
                    if char0_col and char1_col and values[char0_col] is not None:
                        pos0, pos1 = _clamp_offsets(
                            int(values[char0_col] or 0), int(values[char1_col] or 0), len(text)
                        )
                    else:
                        total = max_end.get(t_id, 0) or 0
                        if total <= 0:
                            counts["skipped"] += 1
                            continue
                        assert time0_col is not None
                        assert time1_col is not None
                        pos0 = round((values[time0_col] or 0) * len(text) / total)
                        pos1 = round((values[time1_col] or 0) * len(text) / total)
                        pos0, pos1 = _clamp_offsets(pos0, pos1, len(text))
                    seltext = values.get(snippet_col or "") or "" if snippet_col else ""
                    if not seltext:
                        seltext = text[pos0:pos1]
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
                        counts["skipped"] += 1
                        await session.rollback()
                elif episode_col:
                    new_fid = episode_id_map.get(values[episode_col])
                    if new_fid is None:
                        counts["skipped"] += 1
                        continue
                    assert time0_col is not None
                    assert time1_col is not None
                    try:
                        await coding_repo.add_av_coding(
                            id=new_fid,
                            pos0=int(values[time0_col] or 0),
                            pos1=int(values[time1_col] or 0),
                            cid=new_cid,
                            owner=codername,
                        )
                        counts["codings"] += 1
                    except IntegrityError:
                        counts["skipped"] += 1
                        await session.rollback()

    message = (
        f"Transana import complete: {counts['sources']} sources, "
        f"{counts['categories']} categories, {counts['codes']} codes, "
        f"{counts['codings']} codings, {counts['skipped']} skipped"
    )
    return {"ok": True, "message": message, **counts}
