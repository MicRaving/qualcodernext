"""Cases, attributes, journals and annotations API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from qualcoder_api.api.v1.deps import DbDep
from qualcoder_api.core.models import Annotation, Attribute, AttributeType, Case, CaseText, Journal
from qualcoder_api.persistence.repositories import (
    AnnotationRepository,
    AttributeRepository,
    CaseRepository,
    JournalRepository,
)
from qualcoder_api.services import audit
from qualcoder_api.services.user_settings import get_codername, resolve_owner

router = APIRouter(tags=["cases", "attributes", "journals", "annotations"])

# ----------------------------------------------------------------------
# Cases
# ----------------------------------------------------------------------

case_router = APIRouter(prefix="/cases")


class CaseCreate(BaseModel):
    name: str
    owner: str | None = None
    memo: str = ""


class CaseUpdate(BaseModel):
    name: str | None = None
    memo: str | None = None


class LinkFileRequest(BaseModel):
    fid: int
    owner: str | None = None
    memo: str = ""


class LinkSpanRequest(BaseModel):
    fid: int
    pos0: int
    pos1: int
    owner: str | None = None
    memo: str = ""


@case_router.get("", response_model=list[Case])
async def list_cases(db: DbDep) -> list[Case]:
    return await CaseRepository(db).list_cases()


@case_router.post("", response_model=Case, status_code=201)
async def create_case(req: CaseCreate, db: DbDep) -> Case:
    case = await CaseRepository(db).add_case(name=req.name, owner=resolve_owner(req.owner), memo=req.memo)
    if case is None:
        raise HTTPException(status_code=409, detail="duplicate case name")
    await audit.record(
        db, user=resolve_owner(req.owner), action="case.create", entity="case",
        entity_id=case.caseid, detail=case.model_dump(),
    )
    return case


@case_router.patch("/{caseid}", response_model=Case)
async def update_case(caseid: int, req: CaseUpdate, db: DbDep) -> Case:
    from sqlalchemy import select

    from qualcoder_api.persistence import tables

    old = (
        await db.execute(select(tables.cases).where(tables.cases.c.caseid == caseid))
    ).first()
    old_data = dict(old._mapping) if old is not None else {}
    case = await CaseRepository(db).update_case(caseid, **req.model_dump(exclude_none=True))
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    await audit.record(
        db, user=get_codername(), action="case.update", entity="case", entity_id=caseid,
        detail={
            "caseid": caseid,
            "old_name": old_data.get("name"),
            "new_name": case.name,
            "old_memo": old_data.get("memo"),
            "new_memo": case.memo,
        },
    )
    return case


@case_router.delete("/{caseid}", status_code=204)
async def delete_case(caseid: int, db: DbDep) -> None:
    await CaseRepository(db).delete_case(caseid)
    await audit.record(
        db, user=get_codername(), action="case.delete", entity="case", entity_id=caseid
    )


@case_router.get("/{caseid}/files", response_model=list[dict])
async def case_files(caseid: int, db: DbDep) -> list[dict]:
    return await CaseRepository(db).case_files(caseid)


@case_router.post("/{caseid}/files", response_model=CaseText, status_code=201)
async def link_file(caseid: int, req: LinkFileRequest, db: DbDep) -> CaseText:
    link = await CaseRepository(db).link_file(
        caseid=caseid, fid=req.fid, owner=resolve_owner(req.owner), memo=req.memo
    )
    await audit.record(
        db, user=resolve_owner(req.owner), action="case.link_file", entity="case_text",
        entity_id=link.id, source_id=req.fid,
    )
    return link


@case_router.post("/{caseid}/spans", response_model=CaseText, status_code=201)
async def link_span(caseid: int, req: LinkSpanRequest, db: DbDep) -> CaseText:
    if req.pos1 <= req.pos0:
        raise HTTPException(status_code=422, detail="pos1 must be greater than pos0")
    span = await CaseRepository(db).link_text_span(
        caseid=caseid, fid=req.fid, pos0=req.pos0, pos1=req.pos1,
        owner=resolve_owner(req.owner), memo=req.memo,
    )
    await audit.record(
        db, user=resolve_owner(req.owner), action="case.link_span", entity="case_text",
        entity_id=span.id, source_id=req.fid,
        detail={"caseid": caseid, "pos0": req.pos0, "pos1": req.pos1},
    )
    return span


@case_router.delete("/{caseid}/files/{fid}", status_code=204)
async def unlink_file(caseid: int, fid: int, db: DbDep) -> None:
    await CaseRepository(db).unlink_file(caseid=caseid, fid=fid)
    await audit.record(
        db, user=get_codername(), action="case.unlink_file", entity="case_text",
        source_id=fid, detail={"caseid": caseid, "fid": fid},
    )


# ----------------------------------------------------------------------
# Attributes
# ----------------------------------------------------------------------

attr_router = APIRouter(prefix="/attributes")


class AttrTypeCreate(BaseModel):
    name: str
    owner: str | None = None
    case_or_file: str = "case"
    value_type: str = "text"
    memo: str = ""


class AttrValueSet(BaseModel):
    value: str
    owner: str | None = None


@attr_router.get("/types", response_model=list[AttributeType])
async def list_attribute_types(db: DbDep) -> list[AttributeType]:
    return await AttributeRepository(db).list_types()


@attr_router.post("/types", response_model=AttributeType, status_code=201)
async def create_attribute_type(req: AttrTypeCreate, db: DbDep) -> AttributeType:
    attr = await AttributeRepository(db).add_type(
        name=req.name, owner=resolve_owner(req.owner), case_or_file=req.case_or_file,
        value_type=req.value_type, memo=req.memo,
    )
    await audit.record(
        db, user=resolve_owner(req.owner), action="attribute.create", entity="attribute_type",
        detail={"name": req.name},
    )
    return attr


@attr_router.delete("/types/{name}", status_code=204)
async def delete_attribute_type(name: str, db: DbDep) -> None:
    await AttributeRepository(db).delete_type(name)
    await audit.record(
        db, user=get_codername(), action="attribute.delete", entity="attribute_type",
        detail={"name": name},
    )


@attr_router.get("/values", response_model=list[Attribute])
async def list_attribute_values(
    db: DbDep, entity_id: int | None = None, attr_type: str | None = None
) -> list[Attribute]:
    return await AttributeRepository(db).list_values(entity_id=entity_id, attr_type=attr_type)


@attr_router.put("/values/{name}", response_model=Attribute)
async def set_attribute_value(
    name: str, attr_type: str, entity_id: int, req: AttrValueSet, db: DbDep
) -> Attribute:
    value = await AttributeRepository(db).set_value(
        name=name, attr_type=attr_type, value=req.value,
        entity_id=entity_id, owner=resolve_owner(req.owner),
    )
    await audit.record(
        db, user=resolve_owner(req.owner), action="attribute.set_value", entity="attribute",
        entity_id=entity_id, detail={"name": name, "value": req.value},
    )
    return value


# ----------------------------------------------------------------------
# Journals
# ----------------------------------------------------------------------

journal_router = APIRouter(prefix="/journals")


class JournalCreate(BaseModel):
    name: str
    jentry: str = ""
    owner: str | None = None


class JournalUpdate(BaseModel):
    name: str | None = None
    jentry: str | None = None


@journal_router.get("", response_model=list[Journal])
async def list_journals(db: DbDep) -> list[Journal]:
    return await JournalRepository(db).list_journals()


@journal_router.post("", response_model=Journal, status_code=201)
async def create_journal(req: JournalCreate, db: DbDep) -> Journal:
    journal = await JournalRepository(db).add_journal(
        name=req.name, jentry=req.jentry, owner=resolve_owner(req.owner)
    )
    await audit.record(
        db, user=resolve_owner(req.owner), action="journal.create", entity="journal",
        entity_id=journal.jid, detail=journal.model_dump(),
    )
    return journal


@journal_router.patch("/{jid}", response_model=Journal)
async def update_journal(jid: int, req: JournalUpdate, db: DbDep) -> Journal:
    from sqlalchemy import select

    from qualcoder_api.persistence import tables

    old = (
        await db.execute(select(tables.journal).where(tables.journal.c.jid == jid))
    ).first()
    old_data = dict(old._mapping) if old is not None else {}
    journal = await JournalRepository(db).update_journal(jid, **req.model_dump(exclude_none=True))
    if journal is None:
        raise HTTPException(status_code=404, detail="journal not found")
    await audit.record(
        db, user=get_codername(), action="journal.update", entity="journal", entity_id=jid,
        detail={
            "jid": jid,
            "old_name": old_data.get("name"),
            "new_name": journal.name,
            "old_jentry": old_data.get("jentry"),
            "new_jentry": journal.jentry,
        },
    )
    return journal


@journal_router.delete("/{jid}", status_code=204)
async def delete_journal(jid: int, db: DbDep) -> None:
    await JournalRepository(db).delete_journal(jid)
    await audit.record(
        db, user=get_codername(), action="journal.delete", entity="journal", entity_id=jid
    )


# ----------------------------------------------------------------------
# Annotations
# ----------------------------------------------------------------------

annotation_router = APIRouter(prefix="/annotations")


class AnnotationCreate(BaseModel):
    fid: int
    pos0: int
    pos1: int
    memo: str
    owner: str | None = None


class AnnotationUpdate(BaseModel):
    memo: str | None = None
    pos0: int | None = None
    pos1: int | None = None


@annotation_router.get("/{fid}", response_model=list[Annotation])
async def list_annotations(fid: int, db: DbDep) -> list[Annotation]:
    return await AnnotationRepository(db).list_for_file(fid)


@annotation_router.get("", response_model=list[dict])
async def list_all_annotations(db: DbDep) -> list[dict]:
    """Every annotation in the project with its file name (Notes workspace)."""
    from sqlalchemy import select

    from qualcoder_api.persistence import tables

    rows = await db.execute(
        select(tables.annotation, tables.source.c.name)
        .join(tables.source, tables.source.c.id == tables.annotation.c.fid)
        .order_by(tables.annotation.c.fid, tables.annotation.c.pos0)
    )
    out = []
    for row in rows:
        data = dict(row._mapping)
        data["file_name"] = data.pop("name", "")
        out.append(data)
    return out


@annotation_router.post("", response_model=Annotation, status_code=201)
async def create_annotation(req: AnnotationCreate, db: DbDep) -> Annotation:
    if req.pos1 <= req.pos0:
        raise HTTPException(status_code=422, detail="pos1 must be greater than pos0")
    ann = await AnnotationRepository(db).add_annotation(
        fid=req.fid, pos0=req.pos0, pos1=req.pos1, memo=req.memo, owner=resolve_owner(req.owner)
    )
    await audit.record(
        db, user=resolve_owner(req.owner), action="annotation.create", entity="annotation",
        entity_id=ann.anid, source_id=req.fid, detail=ann.model_dump(),
    )
    return ann


@annotation_router.patch("/{anid}", response_model=Annotation)
async def update_annotation(anid: int, req: AnnotationUpdate, db: DbDep) -> Annotation:
    from sqlalchemy import select

    from qualcoder_api.persistence import tables

    if req.pos0 is not None and req.pos1 is not None and req.pos1 <= req.pos0:
        raise HTTPException(status_code=422, detail="pos1 must be greater than pos0")
    # A single-row select for the old memo, not the file's whole list.
    old_memo = (
        await db.execute(
            select(tables.annotation.c.memo).where(tables.annotation.c.anid == anid)
        )
    ).scalar_one_or_none()
    annotation = await AnnotationRepository(db).update_annotation(
        anid, **req.model_dump(exclude_none=True)
    )
    if annotation is None:
        raise HTTPException(status_code=404, detail="annotation not found")
    await audit.record(
        db, user=get_codername(), action="annotation.update", entity="annotation",
        entity_id=anid, source_id=annotation.fid,
        detail={"anid": anid, "old_memo": old_memo, "new_memo": annotation.memo},
    )
    return annotation


@annotation_router.delete("/{anid}", status_code=204)
async def delete_annotation(anid: int, db: DbDep) -> None:
    from sqlalchemy import select

    from qualcoder_api.persistence import tables

    row = (
        await db.execute(select(tables.annotation).where(tables.annotation.c.anid == anid))
    ).first()
    detail = dict(row._mapping) if row is not None else {}
    await AnnotationRepository(db).delete_annotation(anid)
    await audit.record(
        db, user=get_codername(), action="annotation.delete", entity="annotation",
        entity_id=anid, source_id=detail.get("fid"), detail=detail,
    )
