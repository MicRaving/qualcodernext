"""Bibliography references — the ``ris`` table + Zotero 7 local API import.

The ``ris`` table stores one row per tag occurrence (risid, tag, longtag,
value). This module groups rows into reference entries and imports new
entries from Zotero 7+'s read-only local HTTP API (``localhost:23119``),
mirroring the upstream ``manage_references_import_zotero`` behaviour
(metadata only; PDF attachments are skipped).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qualcoder_api.persistence import tables

logger = logging.getLogger(__name__)

ZOTERO_API = "http://localhost:23119"
# Zotero item types treated as references (everything but notes/attachments).
REFERENCE_TYPES = {
    "artwork", "audioRecording", "bill", "blogPost", "book", "bookSection",
    "case", "computerProgram", "conferencePaper", "dictionaryEntry",
    "document", "email", "encyclopediaArticle", "film", "forumPost",
    "hearing", "instantMessage", "interview", "journalArticle",
    "letter", "magazineArticle", "manuscript", "map", "newspaperArticle",
    "patent", "podcast", "presentation", "radioBroadcast", "report",
    "statute", "thesis", "tvBroadcast", "videoRecording", "webpage",
}


async def list_references(session: AsyncSession) -> list[dict]:
    """All references grouped by ``risid``, newest first, with source links."""
    rows = (
        await session.execute(
            text("SELECT risid, tag, longtag, value FROM ris ORDER BY risid, rowid")
        )
    ).all()
    by_id: dict[int, dict] = {}
    for risid, tag, longtag, value in rows:
        entry = by_id.setdefault(risid, {"risid": risid, "fields": {}})
        values = entry["fields"].setdefault(longtag or tag or "", [])
        if value is not None and value not in values:
            values.append(value)
    if not by_id:
        return []

    source_rows = (
        await session.execute(
            text("SELECT id, name, risid FROM source WHERE risid IS NOT NULL")
        )
    ).all()
    links: dict[int, list[dict]] = {}
    for sid, name, risid in source_rows:
        links.setdefault(risid, []).append({"id": sid, "name": name})

    def title_of(entry: dict) -> str:
        for key in ("title", "Title", "TI", "shortTitle"):
            values = entry["fields"].get(key)
            if values and values[0]:
                return values[0]
        return f"Reference {entry['risid']}"

    def authors_of(entry: dict) -> list[str]:
        out: list[str] = []
        for key in ("authors", "creator", "AU", "A1"):
            for value in entry["fields"].get(key, []):
                cleaned = str(value).strip().strip(";")
                if cleaned:
                    out.append(cleaned)
        return out

    result = []
    for risid, entry in by_id.items():
        result.append(
            {
                "risid": risid,
                "title": title_of(entry),
                "authors": authors_of(entry),
                "year": entry["fields"].get("year", entry["fields"].get("PY", [""]))[0] or "",
                "type": entry["fields"].get("type", entry["fields"].get("TY", [""]))[0] or "",
                "fields": entry["fields"],
                "sources": links.get(risid, []),
            }
        )
    result.sort(key=lambda r: (r["title"] or "").lower())
    return result


async def _capture_sources_by_ids(
    session: AsyncSession, sids: list[int]
) -> None:
    """Journal ``source`` rows touched by a risid relink (the ``ris`` table
    itself is not synced; the ``source.risid`` column is)."""
    from qualcoder_api.persistence.repositories import _capture

    if not sids:
        return
    rows = (
        await session.execute(
            select(tables.source).where(tables.source.c.id.in_(sids))
        )
    ).all()
    for row in rows:
        data = {k: v for k, v in dict(row._mapping).items() if not k.startswith("_")}
        await _capture(
            session, "source", "update", "id", data.get("id"), data
        )


async def delete_reference(session: AsyncSession, risid: int) -> None:
    """Delete one reference and unlink its sources."""
    await session.execute(delete(tables.ris).where(tables.ris.c.risid == risid))
    sids = [
        r[0]
        for r in (
            await session.execute(
                select(tables.source.c.id).where(tables.source.c.risid == risid)
            )
        ).all()
    ]
    await session.execute(
        text("UPDATE source SET risid = NULL WHERE risid = :risid"),
        {"risid": risid},
    )
    await _capture_sources_by_ids(session, [int(i) for i in sids])
    await session.commit()


async def attach_file(
    session_factory: async_sessionmaker,
    project_path: str,
    risid: int,
    source_path: str,
    filename: str,
    owner: str,
) -> dict:
    """Attach a PDF/EPUB (or any document) to a reference.

    The file is imported as a regular source (text extracted for PDFs) and
    linked to the reference via ``source.risid``, mirroring the upstream
    reference manager's attachment behaviour. Raises ``ValueError`` when the
    reference does not exist.
    """

    async with session_factory() as session:
        row = (
            await session.execute(
                text("SELECT 1 FROM ris WHERE risid = :risid LIMIT 1"), {"risid": risid}
            )
        ).first()
        if row is None:
            raise ValueError("reference not found")

    from qualcoder_api.services.import_service import ImportService

    importer = ImportService(project_path, session_factory)
    source = await importer.import_file(
        source_path, owner=owner, link=False, filename=filename
    )
    if source is None:
        raise ValueError("duplicate filename or import failed")
    async with session_factory() as session:
        await session.execute(
            text("UPDATE source SET risid = :risid WHERE id = :sid"),
            {"risid": risid, "sid": source.id},
        )
        await _capture_sources_by_ids(session, [int(source.id)])
        await session.commit()
    return {"ok": True, "source_id": source.id, "name": source.name, "risid": risid}


async def detach_file(session: AsyncSession, risid: int, source_id: int) -> None:
    """Remove the attachment link (the source itself stays in the project)."""
    await session.execute(
        text("UPDATE source SET risid = NULL WHERE id = :sid AND risid = :risid"),
        {"sid": source_id, "risid": risid},
    )
    await _capture_sources_by_ids(session, [int(source_id)])
    await session.commit()


async def import_zotero(
    session_factory: async_sessionmaker, api_base: str = ZOTERO_API, limit: int = 500
) -> dict:
    """Import references from Zotero's local HTTP API (metadata only).

    Queries ``/api/users/0/items?format=json``, keeps reference-type items,
    and writes them into the ``ris`` table with upstream-compatible tags.
    Raises ``ValueError`` when the Zotero API is unreachable.
    """
    url = f"{api_base.rstrip('/')}/api/users/0/items?format=json&limit={limit}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
    except httpx.RequestError as err:
        raise ValueError(
            "Zotero local API is not running — start Zotero 7+ and try again."
        ) from err
    if response.status_code != 200:
        raise ValueError(f"Zotero API error {response.status_code}")

    items: list[dict] = []
    try:
        items = response.json()
    except Exception as err:  # pragma: no cover - defensive
        raise ValueError("unexpected Zotero API response") from err

    entries = [
        item
        for item in items
        if isinstance(item, dict)
        and (item.get("data") or {}).get("itemType") in REFERENCE_TYPES
    ][:limit]

    async with session_factory() as session:
        row = (
            await session.execute(select(tables.ris.c.risid).order_by(tables.ris.c.risid.desc()))
        ).first()
        next_risid = (row[0] if row is not None and row[0] is not None else 0) + 1
        imported = 0
        for item in entries:
            data: dict[str, Any] = item.get("data") or {}
            item_type = data.get("itemType") or ""
            creators = data.get("creators") or []
            author_names: list[str] = []
            for creator in creators:
                if not isinstance(creator, dict):
                    continue
                last = (creator.get("lastName") or "").strip()
                first = (creator.get("firstName") or "").strip()
                if last or first:
                    author_names.append(f"{last}, {first}" if last else first)
            year = ""
            date = (data.get("date") or "").strip()
            match = __import__("re").search(r"\d{4}", date)
            if match:
                year = match.group(0)
            pairs = [
                ("TY", item_type),
                ("TI", data.get("title") or ""),
                ("T1", data.get("title") or ""),
                ("PY", year),
                ("Y1", date),
                ("UR", data.get("url") or ""),
                ("AB", data.get("abstractNote") or ""),
                ("PB", data.get("publisher") or ""),
                ("CY", data.get("place") or ""),
                ("VL", data.get("volume") or ""),
                ("IS", data.get("issue") or ""),
                ("SP", data.get("pages") or ""),
                ("DO", data.get("DOI") or ""),
                ("LA", data.get("language") or ""),
                ("KW", "; ".join(data.get("tags") or [])),
            ]
            pairs.extend(("AU", name) for name in author_names)
            for tag, value in pairs:
                if not value:
                    continue
                await session.execute(
                    tables.ris.insert().values(
                        risid=next_risid, tag=tag, longtag=tag, value=str(value)
                    )
                )
            next_risid += 1
            imported += 1
        await session.commit()
    return {
        "ok": True,
        "message": f"Imported {imported} references from Zotero",
        "references": imported,
    }
