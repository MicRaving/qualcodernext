"""Codes & categories API — tree, CRUD, merge, memo, color."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text, union

from qualcoder_api.api.v1.deps import DbDep
from qualcoder_api.core.models import Category, Code
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import CodeRepository
from qualcoder_api.services import audit
from qualcoder_api.services.user_settings import get_codername, resolve_owner

router = APIRouter(prefix="/codes", tags=["codes"])


class CodeCreate(BaseModel):
    name: str
    owner: str | None = None
    catid: int | None = None
    color: str | None = None
    memo: str = ""
    supercid: int | None = None


class CodeUpdate(BaseModel):
    name: str | None = None
    memo: str | None = None
    color: str | None = None
    catid: int | None = None
    supercid: int | None = None


class CategoryCreate(BaseModel):
    name: str
    owner: str | None = None
    supercatid: int | None = None
    memo: str = ""


class MergeRequest(BaseModel):
    target_cid: int


class MergeCategoryRequest(BaseModel):
    target_catid: int


class CodeTreeItem(BaseModel):
    """One node of the codebook tree: category or code."""

    kind: str  # "category" | "code"
    id: int
    name: str
    color: str | None = None
    parent_id: int | None = None
    memo: str = ""
    subcode: bool = False


class RecentExample(BaseModel):
    """One recent ``code_text`` row, joined with the source file name."""

    ctid: int
    fid: int
    file_name: str
    seltext: str
    pos0: int
    pos1: int


class CodeDetails(BaseModel):
    """Aggregated details for a single code."""

    code: Code
    category_path: list[str]
    coding_count: int
    file_count: int
    recent_examples: list[RecentExample]


@router.get("", response_model=list[CodeTreeItem])
async def code_tree(db: DbDep) -> list[CodeTreeItem]:
    """Return the full hierarchical codebook (categories and codes).

    Sub-codes (upstream v16) are encoded as ``parent_id`` pointing at the
    parent code's id; the tree builder must distinguish ``kind=="code"``
    parents from categories.
    """
    repo = CodeRepository(db)
    categories = await repo.list_categories()
    codes = await repo.list_codes()
    items = [
        CodeTreeItem(
            kind="category", id=cat.catid, name=cat.name,
            parent_id=cat.supercatid, memo=cat.memo,
        )
        for cat in categories
    ]
    items.extend(
        CodeTreeItem(
            kind="code", id=code.cid, name=code.name,
            color=code.color, parent_id=code.supercid or code.catid, memo=code.memo,
            subcode=code.supercid is not None,
        )
        for code in codes
    )
    # Guard against parent cycles (self-references or loops from legacy /
    # imported projects): detach any item whose parent chain circles back
    # on itself so the tree always stays renderable. Categories and codes
    # use separate id sequences (upstream legacy), so parent references
    # resolve kind-aware: codes point at a category unless they are
    # sub-codes, which point at the parent code.
    cats_by_id = {item.id: item for item in items if item.kind == "category"}
    codes_by_id = {item.id: item for item in items if item.kind == "code"}

    def resolve_parent(item: CodeTreeItem) -> CodeTreeItem | None:
        if item.parent_id is None:
            return None
        if item.kind == "category":
            return cats_by_id.get(item.parent_id)
        if item.subcode:
            return codes_by_id.get(item.parent_id)
        return cats_by_id.get(item.parent_id)

    for item in items:
        if item.parent_id is None:
            continue
        seen = {(item.kind, item.id)}
        parent = resolve_parent(item)
        while parent is not None:
            key = (parent.kind, parent.id)
            if key in seen:
                item.parent_id = None
                break
            seen.add(key)
            parent = resolve_parent(parent)
    return items


@router.post("", response_model=Code, status_code=201)
async def create_code(req: CodeCreate, db: DbDep) -> Code:
    code = await CodeRepository(db).add_code(
        name=req.name, owner=resolve_owner(req.owner), catid=req.catid,
        color=req.color, memo=req.memo, supercid=req.supercid,
    )
    if code is None:
        raise HTTPException(status_code=409, detail="duplicate code name")
    await audit.record(
        db, user=resolve_owner(req.owner), action="code.create", entity="code",
        entity_id=code.cid, detail=code.model_dump(),
    )
    return code


@router.patch("/{cid}", response_model=Code)
async def update_code(cid: int, req: CodeUpdate, db: DbDep) -> Code:
    repo = CodeRepository(db)
    old_code = await repo.get_code(cid)
    if req.name is not None:
        code = await repo.rename_code(cid, req.name)
        if code is None:
            raise HTTPException(status_code=404, detail="code not found")
    if req.supercid is not None or (old_code is not None and old_code.supercid is not None and "supercid" in req.model_dump()):
        try:
            code = await repo.set_supercid(cid, req.supercid)
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err)) from err
        if code is None:
            raise HTTPException(status_code=404, detail="code not found")
    if req.memo is not None or req.color is not None or req.catid is not None:
        values = req.model_dump(exclude_none=True, exclude={"name", "supercid"})
        if values:
            from sqlalchemy import update as sa_update

            from qualcoder_api.persistence import tables

            await db.execute(
                sa_update(tables.code_name)
                .where(tables.code_name.c.cid == cid)
                .values(**values)
            )
            await db.commit()
    code = await repo.get_code(cid)
    if code is None:
        raise HTTPException(status_code=404, detail="code not found")
    await audit.record(
        db, user=get_codername(), action="code.rename", entity="code",
        entity_id=cid,
        detail={
            "cid": cid,
            "old_name": old_code.name if old_code else None,
            "new_name": code.name,
        },
    )
    return code


@router.delete("/{cid}", status_code=204)
async def delete_code(cid: int, db: DbDep) -> None:
    from sqlalchemy import select

    from qualcoder_api.persistence import tables

    row = (
        await db.execute(select(tables.code_name).where(tables.code_name.c.cid == cid))
    ).first()
    detail = dict(row._mapping) if row is not None else {}
    await CodeRepository(db).delete_code(cid)
    await audit.record(
        db, user=get_codername(), action="code.delete", entity="code",
        entity_id=cid, detail=detail,
    )


@router.get("/{cid}/details", response_model=CodeDetails)
async def code_details(cid: int, db: DbDep) -> CodeDetails:
    """Aggregate details for one code: ancestry, usage counts, examples."""
    code = await CodeRepository(db).get_code(cid)
    if code is None:
        raise HTTPException(status_code=404, detail="code not found")

    category_path: list[str] = []
    seen: set[int] = set()
    current = code.catid
    while current is not None and current not in seen:
        seen.add(current)
        row = (
            await db.execute(
                select(tables.code_cat.c.name, tables.code_cat.c.supercatid).where(
                    tables.code_cat.c.catid == current
                )
            )
        ).first()
        if row is None:
            break
        category_path.append(row[0] or "")
        current = row[1]
    category_path.reverse()

    coding_count = 0
    for tbl in ("code_text_visible", "code_av_visible", "code_image_visible"):
        count = (
            await db.execute(
                text(f"SELECT COUNT(*) FROM {tbl} WHERE cid = :cid"), {"cid": cid}
            )
        ).scalar_one()
        coding_count += count

    file_rows = await db.execute(
        union(
            select(tables.code_text.c.fid).where(tables.code_text.c.cid == cid),
            select(tables.code_av.c.id).where(tables.code_av.c.cid == cid),
            select(tables.code_image.c.id).where(tables.code_image.c.cid == cid),
        )
    )
    file_count = len({r[0] for r in file_rows})

    example_rows = await db.execute(
        text(
            "SELECT ct.ctid, ct.fid, s.name, ct.seltext, ct.pos0, ct.pos1 "
            "FROM code_text_visible ct JOIN source s ON s.id = ct.fid "
            "WHERE ct.cid = :cid ORDER BY ct.ctid DESC LIMIT 5"
        ),
        {"cid": cid},
    )
    recent_examples = [
        RecentExample(
            ctid=r[0], fid=r[1], file_name=r[2] or "", seltext=r[3] or "", pos0=r[4], pos1=r[5]
        )
        for r in example_rows
    ]

    return CodeDetails(
        code=code,
        category_path=category_path,
        coding_count=coding_count,
        file_count=file_count,
        recent_examples=recent_examples,
    )


@router.post("/{cid}/merge", response_model=Code)
async def merge_code(cid: int, req: MergeRequest, db: DbDep) -> Code:
    """Merge code ``cid`` into ``req.target_cid``."""
    repo = CodeRepository(db)
    if cid == req.target_cid:
        raise HTTPException(status_code=422, detail="cannot merge a code into itself")
    await repo.merge_codes(cid, req.target_cid)
    code = await repo.get_code(req.target_cid)
    if code is None:
        raise HTTPException(status_code=404, detail="target code not found")
    await audit.record(
        db, user=get_codername(), action="code.merge", entity="code",
        entity_id=req.target_cid, detail={"from_cid": cid},
    )
    return code


@router.post("/categories", response_model=Category, status_code=201)
async def create_category(req: CategoryCreate, db: DbDep) -> Category:
    category = await CodeRepository(db).add_category(
        name=req.name, owner=resolve_owner(req.owner), supercatid=req.supercatid, memo=req.memo
    )
    if category is None:
        raise HTTPException(status_code=409, detail="duplicate category name")
    await audit.record(
        db, user=resolve_owner(req.owner), action="category.create", entity="code_cat",
        entity_id=category.catid, detail={"name": req.name},
    )
    return category


@router.delete("/categories/{catid}", status_code=204)
async def delete_category(catid: int, db: DbDep) -> None:
    await CodeRepository(db).delete_category(catid)
    await audit.record(
        db, user=get_codername(), action="category.delete", entity="code_cat", entity_id=catid
    )


class CategoryRename(BaseModel):
    name: str


@router.patch("/categories/{catid}", response_model=Category)
async def rename_category(catid: int, req: CategoryRename, db: DbDep) -> Category:
    """Rename a category (the code PATCH endpoint only covers codes)."""
    from sqlalchemy import update as sa_update

    from qualcoder_api.persistence import tables

    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="category name must not be empty")
    old = (
        await db.execute(
            select(tables.code_cat.c.name).where(tables.code_cat.c.catid == catid)
        )
    ).first()
    if old is None:
        raise HTTPException(status_code=404, detail="category not found")
    try:
        await db.execute(
            sa_update(tables.code_cat).where(tables.code_cat.c.catid == catid).values(name=name)
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=409, detail="duplicate category name") from None
    row = (
        await db.execute(select(tables.code_cat).where(tables.code_cat.c.catid == catid))
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="category not found")
    await audit.record(
        db, user=get_codername(), action="category.rename", entity="code_cat",
        entity_id=catid, detail={"old_name": old[0], "new_name": name},
    )
    return Category.model_validate(row._mapping)


@router.post("/categories/{catid}/merge", status_code=204)
async def merge_category(catid: int, req: MergeCategoryRequest, db: DbDep) -> None:
    if catid == req.target_catid:
        raise HTTPException(status_code=422, detail="cannot merge a category into itself")
    await CodeRepository(db).merge_category(catid, req.target_catid)
    await audit.record(
        db, user=get_codername(), action="category.merge", entity="code_cat",
        entity_id=req.target_catid, detail={"from_catid": catid},
    )
