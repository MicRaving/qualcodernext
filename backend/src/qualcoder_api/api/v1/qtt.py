"""QTT workspace API — MAXQDA-style Questions-Themes-Theories worksheets.

A ``qtt_sheet`` row is a worksheet: a name, a kind (``qual`` or ``mixed``)
and the ordered list of its sections (JSON). Mixed worksheets seed the
canonical Creswell 14-step mixed-methods design as section names. Items
(``qtt_item`` rows) collect insights per section — segments (a quote with a
source span), notes (free text), charts (a report reference) and links (a
URL). Mutations are audit-recorded and journaled to ``sync_log`` exactly
like the creative-coding endpoints.
"""

from __future__ import annotations

import datetime
import json
from typing import Any, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, insert, select
from sqlalchemy import update as sa_update
from sqlalchemy.engine import CursorResult, Result

from qualcoder_api.api.v1.deps import DbDep
from qualcoder_api.persistence import tables
from qualcoder_api.services import audit, sync
from qualcoder_api.services.user_settings import get_codername, resolve_owner

router = APIRouter(prefix="/qtt", tags=["qtt"])

# The canonical Creswell mixed-methods design steps (Creswell & Plano Clark,
# "Designing and Conducting Mixed Methods Research") used as the section
# list of kind=mixed worksheets.
CRESWELL_MIXED_SECTIONS = [
    "Research Questions",
    "Qualitative Data Collection",
    "Quantitative Data Collection",
    "Qualitative Data Analysis",
    "Quantitative Data Analysis",
    "Joint Display Planning",
    "Data Integration",
    "Meta-Inferences",
    "Validity & Reliability",
    "Limitations",
    "Reporting",
    "Ethical Considerations",
    "Reflexivity",
    "Conclusions & Implications",
]

# Default single section for plain qualitative worksheets.
QUAL_DEFAULT_SECTIONS = ["Insights"]

ITEM_KINDS = {"segment", "note", "chart", "link"}


def _now() -> str:
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _inserted_pk(result: Result) -> int:
    """First inserted primary key from an INSERT statement result."""
    pk = cast(CursorResult[Any], result).inserted_primary_key
    if pk is None:  # pragma: no cover - inserts always return a pk here
        raise RuntimeError("insert returned no primary key")
    return int(pk[0])


def _sections(sheet: dict) -> list[str]:
    try:
        parsed = json.loads(sheet.get("sections_json") or "[]")
    except (TypeError, json.JSONDecodeError):  # pragma: no cover - written by us
        parsed = []
    return [str(s) for s in parsed if isinstance(s, str) and s]


def _sheet_response(sheet: dict, counts: dict[tuple[int, str], int]) -> dict:
    sections = _sections(sheet)
    return {
        "id": sheet["id"],
        "name": sheet["name"],
        "kind": sheet["kind"],
        "sections": sections,
        "counts": {s: counts.get((sheet["id"], s), 0) for s in sections},
        "research_question": sheet.get("research_question") or "",
        "purpose": sheet.get("purpose") or "",
        "framework": sheet.get("framework") or "",
        "owner": sheet.get("owner") or "",
        "date": sheet.get("date") or "",
    }


async def _resolve_item(db, item: dict) -> dict:
    """Attach the parsed payload and (for segments) the source excerpt."""
    out = dict(item)
    out["payload"] = {}
    try:
        out["payload"] = json.loads(item.get("payload_json") or "{}")
    except (TypeError, json.JSONDecodeError):  # pragma: no cover - written by us
        out["payload"] = {}
    out.pop("payload_json", None)
    out["source_name"] = ""
    out["source_text"] = ""
    if item.get("kind") != "segment":
        return out
    fid = out["payload"].get("fid")
    if fid is None:
        return out
    row = (
        await db.execute(
            select(tables.source.c.name, tables.source.c.fulltext).where(
                tables.source.c.id == fid
            )
        )
    ).first()
    if row is None:
        return out
    out["source_name"] = row[0]
    start = out["payload"].get("pos0")
    end = out["payload"].get("pos1")
    fulltext = row[1] or ""
    out["source_text"] = (
        fulltext[start:end] if start is not None and end is not None and 0 <= start < end <= len(fulltext) else ""
    )
    return out


async def _validate_span(db, fid: int | None, pos0: int | None, pos1: int | None) -> None:
    """Span positions must fall inside the source's text (422 otherwise)."""
    if not isinstance(fid, int):
        raise HTTPException(status_code=422, detail="fid must be an integer")
    if not isinstance(pos0, int) or not isinstance(pos1, int):
        raise HTTPException(status_code=422, detail="pos0 and pos1 must be integers")
    if pos1 <= pos0:
        raise HTTPException(status_code=422, detail="pos1 must be greater than pos0")
    if pos0 < 0:
        raise HTTPException(status_code=422, detail="pos0 out of range")
    row = (
        await db.execute(
            select(tables.source.c.fulltext).where(tables.source.c.id == fid)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=422, detail=f"source {fid} not found")
    length = len(row[0] or "")
    if pos1 > length:
        raise HTTPException(status_code=422, detail=f"pos1 exceeds the source text length ({length})")


async def _segment_text(db, fid: int, pos0: int, pos1: int) -> str:
    await _validate_span(db, fid, pos0, pos1)
    row = (
        await db.execute(
            select(tables.source.c.fulltext).where(tables.source.c.id == fid)
        )
    ).first()
    assert row is not None
    return (row[0] or "")[pos0:pos1]


async def _validate_payload(db, kind: str, payload: dict) -> dict:
    """Validate and normalize an item payload per kind (422 on bad shape)."""
    if kind not in ITEM_KINDS:
        raise HTTPException(status_code=422, detail=f"unknown item kind: {kind}")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="payload must be an object")
    if kind == "note":
        text = str(payload.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="note text must not be empty")
        return {"text": text}
    if kind == "segment":
        fid = payload.get("fid")
        pos0 = payload.get("pos0")
        pos1 = payload.get("pos1")
        if not isinstance(fid, int) or not isinstance(pos0, int) or not isinstance(pos1, int):
            raise HTTPException(status_code=422, detail="segment payload requires fid, pos0, pos1")
        text = await _segment_text(db, fid, pos0, pos1)
        return {"fid": fid, "pos0": pos0, "pos1": pos1, "text": text}
    if kind == "chart":
        report = str(payload.get("report") or "").strip()
        if not report:
            raise HTTPException(status_code=422, detail="chart payload requires a report name")
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            raise HTTPException(status_code=422, detail="chart params must be an object")
        return {"report": report, "params": params}
    if kind == "link":
        url = str(payload.get("url") or "").strip()
        if not url:
            raise HTTPException(status_code=422, detail="link payload requires a url")
        return {"url": url}
    raise HTTPException(status_code=422, detail=f"unknown item kind: {kind}")  # pragma: no cover


async def _get_sheet(db, sheet_id: int) -> dict:
    row = (
        await db.execute(
            select(tables.qtt_sheet).where(tables.qtt_sheet.c.id == sheet_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="worksheet not found")
    return dict(row._mapping)


async def _section_counts(db) -> dict[tuple[int, str], int]:
    rows = await db.execute(
        select(
            tables.qtt_item.c.sheet_id,
            tables.qtt_item.c.section,
            func.count().label("n"),
        ).group_by(tables.qtt_item.c.sheet_id, tables.qtt_item.c.section)
    )
    return {(r[0], r[1]): int(r[2]) for r in rows}


class QttSheetCreate(BaseModel):
    name: str
    kind: str = "qual"
    owner: str | None = None


class QttSheetUpdate(BaseModel):
    name: str | None = None
    research_question: str | None = None
    purpose: str | None = None
    framework: str | None = None


class QttItemCreate(BaseModel):
    section: str
    kind: str
    payload: dict
    owner: str | None = None


class QttItemUpdate(BaseModel):
    section: str | None = None
    payload: dict | None = None


class QttSendSegment(BaseModel):
    fid: int
    pos0: int
    pos1: int
    section: str | None = None
    owner: str | None = None


@router.get("", response_model=list[dict])
async def list_qtt_sheets(db: DbDep) -> list[dict]:
    """All worksheets with their sections and per-section item counts."""
    rows = await db.execute(select(tables.qtt_sheet).order_by(tables.qtt_sheet.c.name))
    sheets = [dict(r._mapping) for r in rows]
    counts = await _section_counts(db)
    return [_sheet_response(s, counts) for s in sheets]


@router.post("", response_model=dict, status_code=201)
async def create_qtt_sheet(req: QttSheetCreate, db: DbDep) -> dict:
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name must not be empty")
    kind = (req.kind or "qual").strip().lower()
    if kind not in ("qual", "mixed"):
        raise HTTPException(status_code=422, detail="kind must be 'qual' or 'mixed'")
    sections = CRESWELL_MIXED_SECTIONS if kind == "mixed" else QUAL_DEFAULT_SECTIONS
    owner = resolve_owner(req.owner)
    result = await db.execute(
        insert(tables.qtt_sheet).values(
            name=name,
            kind=kind,
            sections_json=json.dumps(sections, ensure_ascii=False),
            research_question="",
            purpose="",
            framework="",
            owner=owner,
            date=_now(),
        )
    )
    await db.commit()
    sheet_id = _inserted_pk(result)
    row = (
        await db.execute(
            select(tables.qtt_sheet).where(tables.qtt_sheet.c.id == sheet_id)
        )
    ).first()
    assert row is not None
    data = dict(row._mapping)
    await sync.capture_insert(
        db, entity="qtt_sheet", pk_name="id", pk_value=sheet_id, row=data
    )
    await db.commit()
    await audit.record(
        db,
        user=owner,
        action="qtt.create",
        entity="qtt_sheet",
        entity_id=sheet_id,
        detail={"name": name, "kind": kind, "sections": sections, "row": data},
    )
    return _sheet_response(data, {})


@router.patch("/{sheet_id}", response_model=dict)
async def update_qtt_sheet(sheet_id: int, req: QttSheetUpdate, db: DbDep) -> dict:
    row = await _get_sheet(db, sheet_id)
    before = dict(row)
    values = req.model_dump(exclude_none=True)
    if "name" in values:
        name = (values["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="name must not be empty")
        values["name"] = name
    if values:
        await db.execute(
            sa_update(tables.qtt_sheet)
            .where(tables.qtt_sheet.c.id == sheet_id)
            .values(**values)
        )
        await db.commit()
        row = await _get_sheet(db, sheet_id)
        data = dict(row)
        await sync.capture_update(
            db, entity="qtt_sheet", pk_name="id", pk_value=sheet_id, row=data
        )
        await db.commit()
        await audit.record(
            db,
            user=get_codername(),
            action="qtt.update",
            entity="qtt_sheet",
            entity_id=sheet_id,
            detail={**values, "before": before, "after": data},
        )
    counts = await _section_counts(db)
    return _sheet_response(row, counts)


@router.delete("/{sheet_id}", status_code=204)
async def delete_qtt_sheet(sheet_id: int, db: DbDep) -> None:
    row = await _get_sheet(db, sheet_id)
    item_count = int(
        (
            await db.execute(
                select(func.count()).select_from(tables.qtt_item).where(
                    tables.qtt_item.c.sheet_id == sheet_id
                )
            )
        ).scalar()
        or 0
    )
    items = [
        dict(r._mapping)
        for r in (
            await db.execute(
                select(tables.qtt_item).where(tables.qtt_item.c.sheet_id == sheet_id)
            )
        ).all()
    ]
    await db.execute(
        delete(tables.qtt_item).where(tables.qtt_item.c.sheet_id == sheet_id)
    )
    await db.execute(
        delete(tables.qtt_sheet).where(tables.qtt_sheet.c.id == sheet_id)
    )
    await db.commit()
    await sync.capture_delete(
        db, entity="qtt_sheet", pk_name="id", pk_value=sheet_id, row=row
    )
    await db.commit()
    await audit.record(
        db,
        user=get_codername(),
        action="qtt.delete",
        entity="qtt_sheet",
        entity_id=sheet_id,
        detail={"name": row["name"], "kind": row["kind"], "item_count": item_count,
                "row": dict(row), "items": items},
    )


@router.get("/{sheet_id}", response_model=dict)
async def get_qtt_sheet(sheet_id: int, db: DbDep) -> dict:
    """One worksheet with its items grouped by section name."""
    sheet = await _get_sheet(db, sheet_id)
    rows = await db.execute(
        select(tables.qtt_item)
        .where(tables.qtt_item.c.sheet_id == sheet_id)
        .order_by(tables.qtt_item.c.date.desc(), tables.qtt_item.c.id.desc())
    )
    items: dict[str, list[dict]] = {s: [] for s in _sections(sheet)}
    for r in rows:
        item = await _resolve_item(db, dict(r._mapping))
        items.setdefault(item["section"], []).append(item)
    counts = await _section_counts(db)
    return {
        **_sheet_response(sheet, counts),
        "items": items,
    }


@router.post("/{sheet_id}/items", response_model=dict, status_code=201)
async def create_qtt_item(sheet_id: int, req: QttItemCreate, db: DbDep) -> dict:
    sheet = await _get_sheet(db, sheet_id)
    section = (req.section or "").strip()
    if section not in _sections(sheet):
        raise HTTPException(
            status_code=422,
            detail=f"section '{section}' is not in this worksheet",
        )
    payload = await _validate_payload(db, req.kind, req.payload)
    owner = resolve_owner(req.owner)
    result = await db.execute(
        insert(tables.qtt_item).values(
            sheet_id=sheet_id,
            section=section,
            kind=req.kind,
            payload_json=json.dumps(payload, ensure_ascii=False),
            owner=owner,
            date=_now(),
        )
    )
    await db.commit()
    item_id = _inserted_pk(result)
    row = (
        await db.execute(
            select(tables.qtt_item).where(tables.qtt_item.c.id == item_id)
        )
    ).first()
    assert row is not None
    data = dict(row._mapping)
    await sync.capture_insert(
        db, entity="qtt_item", pk_name="id", pk_value=item_id, row=data
    )
    await db.commit()
    await audit.record(
        db,
        user=owner,
        action="qtt.item.create",
        entity="qtt_item",
        entity_id=item_id,
        source_id=payload.get("fid") if req.kind == "segment" else None,
        detail={
            "sheet_id": sheet_id,
            "section": section,
            "kind": req.kind,
            "payload": payload,
            "row": data,
        },
    )
    return await _resolve_item(db, data)


@router.patch("/items/{item_id}", response_model=dict)
async def update_qtt_item(item_id: int, req: QttItemUpdate, db: DbDep) -> dict:
    row = (
        await db.execute(
            select(tables.qtt_item).where(tables.qtt_item.c.id == item_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="worksheet item not found")
    item = dict(row._mapping)
    item_before = dict(item)
    sheet = await _get_sheet(db, item["sheet_id"])
    values: dict[str, Any] = {}
    if req.section is not None:
        section = (req.section or "").strip()
        if section not in _sections(sheet):
            raise HTTPException(
                status_code=422,
                detail=f"section '{section}' is not in this worksheet",
            )
        values["section"] = section
    if req.payload is not None:
        current = {}
        try:
            current = json.loads(item.get("payload_json") or "{}")
        except (TypeError, json.JSONDecodeError):  # pragma: no cover - written by us
            current = {}
        merged = {**current, **(req.payload or {})}
        values["payload_json"] = json.dumps(
            await _validate_payload(db, item["kind"], merged), ensure_ascii=False
        )
    if values:
        await db.execute(
            sa_update(tables.qtt_item)
            .where(tables.qtt_item.c.id == item_id)
            .values(**values)
        )
        await db.commit()
        row = (
            await db.execute(
                select(tables.qtt_item).where(tables.qtt_item.c.id == item_id)
            )
        ).first()
        assert row is not None
        item = dict(row._mapping)
        await sync.capture_update(
            db, entity="qtt_item", pk_name="id", pk_value=item_id, row=item
        )
        await db.commit()
        payload = {}
        try:
            payload = json.loads(item.get("payload_json") or "{}")
        except (TypeError, json.JSONDecodeError):  # pragma: no cover - written by us
            payload = {}
        await audit.record(
            db,
            user=get_codername(),
            action="qtt.item.update",
            entity="qtt_item",
            entity_id=item_id,
            source_id=payload.get("fid") if item.get("kind") == "segment" else None,
            detail={**values, "before": item_before, "after": item},
        )
    return await _resolve_item(db, item)


@router.delete("/items/{item_id}", status_code=204)
async def delete_qtt_item(item_id: int, db: DbDep) -> None:
    row = (
        await db.execute(
            select(tables.qtt_item).where(tables.qtt_item.c.id == item_id)
        )
    ).first()
    await db.execute(delete(tables.qtt_item).where(tables.qtt_item.c.id == item_id))
    if row is None:
        await db.commit()
        raise HTTPException(status_code=404, detail="worksheet item not found")
    item = dict(row._mapping)
    await sync.capture_delete(
        db, entity="qtt_item", pk_name="id", pk_value=item_id, row=item
    )
    await db.commit()
    payload = {}
    try:
        payload = json.loads(item.get("payload_json") or "{}")
    except (TypeError, json.JSONDecodeError):  # pragma: no cover - written by us
        payload = {}
    await audit.record(
        db,
        user=get_codername(),
        action="qtt.item.delete",
        entity="qtt_item",
        entity_id=item_id,
        source_id=payload.get("fid") if item.get("kind") == "segment" else None,
        detail={
            "sheet_id": item["sheet_id"],
            "section": item["section"],
            "kind": item["kind"],
            "row": item,
        },
    )


@router.post("/{sheet_id}/send-segment", response_model=dict, status_code=201)
async def send_segment(sheet_id: int, req: QttSendSegment, db: DbDep) -> dict:
    """Convenience for the coder's "Send to QTT" menu: store the source span
    as a segment item. The segment text is resolved from the source fulltext
    (422 when the span is out of range)."""
    sheet = await _get_sheet(db, sheet_id)
    sections = _sections(sheet)
    section = (req.section or "").strip() or sections[0]
    if section not in sections:
        raise HTTPException(
            status_code=422,
            detail=f"section '{section}' is not in this worksheet",
        )
    text = await _segment_text(db, req.fid, req.pos0, req.pos1)
    payload = {"fid": req.fid, "pos0": req.pos0, "pos1": req.pos1, "text": text}
    owner = resolve_owner(req.owner)
    result = await db.execute(
        insert(tables.qtt_item).values(
            sheet_id=sheet_id,
            section=section,
            kind="segment",
            payload_json=json.dumps(payload, ensure_ascii=False),
            owner=owner,
            date=_now(),
        )
    )
    await db.commit()
    item_id = _inserted_pk(result)
    row = (
        await db.execute(
            select(tables.qtt_item).where(tables.qtt_item.c.id == item_id)
        )
    ).first()
    assert row is not None
    data = dict(row._mapping)
    await sync.capture_insert(
        db, entity="qtt_item", pk_name="id", pk_value=item_id, row=data
    )
    await db.commit()
    await audit.record(
        db,
        user=owner,
        action="qtt.send_segment",
        entity="qtt_item",
        entity_id=item_id,
        source_id=req.fid,
        detail={"sheet_id": sheet_id, "section": section, "pos0": req.pos0, "pos1": req.pos1,
                "row": data},
    )
    return await _resolve_item(db, data)
