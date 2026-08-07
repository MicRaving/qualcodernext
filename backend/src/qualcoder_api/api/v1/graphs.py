"""Graphs API — code-map editor CRUD and the six analytical model generators."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from qualcoder_api.api.v1.deps import DbDep
from qualcoder_api.services import audit, graph_service
from qualcoder_api.services.user_settings import get_codername

router = APIRouter(prefix="/graphs", tags=["graphs"])


class GraphCreate(BaseModel):
    name: str
    description: str = ""
    scene_width: int = 1600
    scene_height: int = 1000


class GraphUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    scene_width: int | None = None
    scene_height: int | None = None


class CdctItemCreate(BaseModel):
    kind: str  # "category" | "code"
    ref_id: int
    x: int = 0
    y: int = 0
    displaytext: str | None = None


class CaseItemCreate(BaseModel):
    caseid: int
    x: int = 0
    y: int = 0
    color: str = "#5882FA"


class FileItemCreate(BaseModel):
    fid: int
    x: int = 0
    y: int = 0
    color: str = "#6B6BDA"


class FreeItemCreate(BaseModel):
    x: int = 0
    y: int = 0
    free_text: str
    color: str = "#1d1d23"


class MemoItemCreate(BaseModel):
    memo_source_type: str  # "code" | "file"
    memo_source_id: int
    x: int = 0
    y: int = 0
    color: str = "#E8E8E8"


class CdctLineCreate(BaseModel):
    from_node: int  # gtextid
    to_node: int  # gtextid
    color: str = "#888888"
    linewidth: float = 1.0
    linetype: str = "solid"
    label: str = ""
    arrow_mode: str = "solid_with_arrow"


class EntityLineCreate(BaseModel):
    from_kind: str  # free|case|file|code|category|imid|avid
    from_id: int
    to_kind: str
    to_id: int
    color: str = "#888888"
    linewidth: float = 1.0
    linetype: str = "solid"
    label: str = ""
    arrow_mode: str = "solid_with_arrow"


class LineUpdate(BaseModel):
    color: str | None = None
    linewidth: float | None = None
    linetype: str | None = None
    label: str | None = None
    arrow_mode: str | None = None
    isvisible: int | None = None


class ItemPosUpdate(BaseModel):
    x: int | None = None
    y: int | None = None
    displaytext: str | None = None
    free_text: str | None = None
    color: str | None = None
    font_size: int | None = None
    bold: int | None = None
    isvisible: int | None = None


class ModelCreate(BaseModel):
    model: str
    name: str
    file_ids: list[int] | None = None
    case_ids: list[int] | None = None



@router.get("")
async def list_graphs(db: DbDep) -> dict:
    return {"graphs": await graph_service.list_graphs(db)}


@router.post("", status_code=201)
async def create_graph(req: GraphCreate, db: DbDep) -> dict:
    if not req.name.strip():
        raise HTTPException(status_code=422, detail="graph name must not be empty")
    from sqlalchemy.exc import IntegrityError

    try:
        graph = await graph_service.create_graph(
            db, req.name.strip(), req.description, req.scene_width, req.scene_height,
            owner=get_codername(),
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="duplicate graph name") from None
    await audit.record(
        db, user=get_codername(), action="graph.create", entity="graph",
        entity_id=graph["grid"], detail={"name": graph["name"]},
    )
    return graph


@router.get("/{grid}")
async def get_graph(grid: int, db: DbDep) -> dict:
    data = await graph_service.get_graph(db, grid)
    if data is None:
        raise HTTPException(status_code=404, detail="graph not found")
    return data


@router.patch("/{grid}")
async def update_graph(grid: int, req: GraphUpdate, db: DbDep) -> dict:
    graph = await graph_service.update_graph(db, grid, **req.model_dump(exclude_none=True))
    if graph is None:
        raise HTTPException(status_code=404, detail="graph not found")
    await audit.record(
        db, user=get_codername(), action="graph.update", entity="graph", entity_id=grid,
        detail={"name": graph.get("name")},
    )
    return graph


@router.delete("/{grid}", status_code=204)
async def delete_graph(grid: int, db: DbDep) -> None:
    await graph_service.delete_graph(db, grid)
    await audit.record(
        db, user=get_codername(), action="graph.delete", entity="graph", entity_id=grid
    )


# ----------------------------------------------------------------------
# Items
# ----------------------------------------------------------------------

@router.post("/{grid}/items/cdct", status_code=201)
async def add_cdct_item(grid: int, req: CdctItemCreate, db: DbDep) -> dict:
    if req.kind not in ("category", "code"):
        raise HTTPException(status_code=422, detail="kind must be category or code")
    try:
        return await graph_service.add_cdct_item(
            db, grid, req.kind, req.ref_id, req.x, req.y, req.displaytext
        )
    except Exception:
        raise HTTPException(status_code=404, detail="graph or referenced entity not found") from None


@router.patch("/{grid}/items/cdct/{gtextid}")
async def update_cdct_item(grid: int, gtextid: int, req: ItemPosUpdate, db: DbDep) -> dict:
    item = await graph_service.update_cdct_item(db, gtextid, **req.model_dump(exclude_none=True))
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return item


@router.delete("/{grid}/items/cdct/{gtextid}", status_code=204)
async def delete_cdct_item(grid: int, gtextid: int, db: DbDep) -> None:
    await graph_service.delete_cdct_item(db, gtextid)


@router.post("/{grid}/items/case", status_code=201)
async def add_case_item(grid: int, req: CaseItemCreate, db: DbDep) -> dict:
    return await graph_service.add_case_item(db, grid, req.caseid, req.x, req.y, req.color)


@router.patch("/{grid}/items/case/{gcaseid}")
async def update_case_item(grid: int, gcaseid: int, req: ItemPosUpdate, db: DbDep) -> dict:
    item = await graph_service.update_case_item(db, gcaseid, **req.model_dump(exclude_none=True))
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return item


@router.delete("/{grid}/items/case/{gcaseid}", status_code=204)
async def delete_case_item(grid: int, gcaseid: int, db: DbDep) -> None:
    await graph_service.delete_case_item(db, gcaseid)


@router.post("/{grid}/items/file", status_code=201)
async def add_file_item(grid: int, req: FileItemCreate, db: DbDep) -> dict:
    return await graph_service.add_file_item(db, grid, req.fid, req.x, req.y, req.color)


@router.patch("/{grid}/items/file/{gfileid}")
async def update_file_item(grid: int, gfileid: int, req: ItemPosUpdate, db: DbDep) -> dict:
    item = await graph_service.update_file_item(db, gfileid, **req.model_dump(exclude_none=True))
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return item


@router.delete("/{grid}/items/file/{gfileid}", status_code=204)
async def delete_file_item(grid: int, gfileid: int, db: DbDep) -> None:
    await graph_service.delete_file_item(db, gfileid)


@router.post("/{grid}/items/free", status_code=201)
async def add_free_item(grid: int, req: FreeItemCreate, db: DbDep) -> dict:
    return await graph_service.add_free_item(db, grid, req.x, req.y, req.free_text, req.color)


@router.patch("/{grid}/items/free/{gfreeid}")
async def update_free_item(grid: int, gfreeid: int, req: ItemPosUpdate, db: DbDep) -> dict:
    item = await graph_service.update_free_item(db, gfreeid, **req.model_dump(exclude_none=True))
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return item


@router.delete("/{grid}/items/free/{gfreeid}", status_code=204)
async def delete_free_item(grid: int, gfreeid: int, db: DbDep) -> None:
    await graph_service.delete_free_item(db, gfreeid)


@router.post("/{grid}/items/memo", status_code=201)
async def add_memo_item(grid: int, req: MemoItemCreate, db: DbDep) -> dict:
    try:
        return await graph_service.add_memo_item(
            db, grid, req.memo_source_type, req.memo_source_id, req.x, req.y, req.color
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@router.patch("/{grid}/items/memo/{gmemoid}")
async def update_memo_item(grid: int, gmemoid: int, req: ItemPosUpdate, db: DbDep) -> dict:
    item = await graph_service.update_memo_item(db, gmemoid, **req.model_dump(exclude_none=True))
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return item


@router.delete("/{grid}/items/memo/{gmemoid}", status_code=204)
async def delete_memo_item(grid: int, gmemoid: int, db: DbDep) -> None:
    await graph_service.delete_memo_item(db, gmemoid)


# ----------------------------------------------------------------------
# Lines
# ----------------------------------------------------------------------

@router.post("/{grid}/lines/cdct", status_code=201)
async def add_cdct_line(grid: int, req: CdctLineCreate, db: DbDep) -> dict:
    try:
        return await graph_service.add_cdct_line(
            db, grid, req.from_node, req.to_node, req.color, req.linewidth,
            req.linetype, 1, req.label, req.arrow_mode,
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@router.patch("/{grid}/lines/cdct/{glineid}")
async def update_cdct_line(grid: int, glineid: int, req: LineUpdate, db: DbDep) -> dict:
    item = await graph_service.update_cdct_line(db, glineid, **req.model_dump(exclude_none=True))
    if item is None:
        raise HTTPException(status_code=404, detail="line not found")
    return item


@router.delete("/{grid}/lines/cdct/{glineid}", status_code=204)
async def delete_cdct_line(grid: int, glineid: int, db: DbDep) -> None:
    await graph_service.delete_cdct_line(db, glineid)


@router.post("/{grid}/lines/entity", status_code=201)
async def add_entity_line(grid: int, req: EntityLineCreate, db: DbDep) -> dict:
    try:
        return await graph_service.add_entity_line(
            db, grid, req.from_kind, req.from_id, req.to_kind, req.to_id,
            req.color, req.linewidth, req.linetype, req.label, req.arrow_mode,
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@router.patch("/{grid}/lines/entity/{gflineid}")
async def update_entity_line(grid: int, gflineid: int, req: LineUpdate, db: DbDep) -> dict:
    item = await graph_service.update_free_line(db, gflineid, **req.model_dump(exclude_none=True))
    if item is None:
        raise HTTPException(status_code=404, detail="line not found")
    return item


@router.delete("/{grid}/lines/entity/{gflineid}", status_code=204)
async def delete_entity_line(grid: int, gflineid: int, db: DbDep) -> None:
    await graph_service.delete_free_line(db, gflineid)


# ----------------------------------------------------------------------
# Model generator
# ----------------------------------------------------------------------

@router.post("/models", status_code=201)
async def generate_model(req: ModelCreate, db: DbDep) -> dict:
    if req.model not in graph_service.MODELS:
        raise HTTPException(
            status_code=422,
            detail=f"unknown model — expected one of {', '.join(graph_service.MODELS)}",
        )
    if not req.name.strip():
        raise HTTPException(status_code=422, detail="graph name must not be empty")
    try:
        result = await graph_service.generate_model(
            db, req.model, req.name.strip(), owner=get_codername(),
            file_ids=req.file_ids, case_ids=req.case_ids,
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    await audit.record(
        db, user=get_codername(), action="graph.create", entity="graph",
        entity_id=result["grid"], detail={"model": req.model, "name": req.name},
    )
    return result


