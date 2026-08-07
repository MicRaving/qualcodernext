"""Interchange API — REFI-QDA (.qdp XML) export and import."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from qualcoder_api.api.v1.deps import DbDep, ServiceDep
from qualcoder_api.interchange.refi import export_refi_qdp, import_refi_qdp

router = APIRouter(prefix="/interchange", tags=["interchange"])


@router.get("/export/refi")
async def export_refi(svc: ServiceDep, db: DbDep) -> Response:
    """Export the open project as a REFI-QDA .qdp XML document."""
    session_factory = svc.session_factory
    if session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    xml = await export_refi_qdp(session_factory, svc.project_name)
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{svc.project_name}.qdp"'},
    )


@router.post("/import/refi")
async def import_refi(
    svc: ServiceDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    codername: str | None = Form(None),
) -> dict:
    """Import a REFI-QDA .qdp XML document into the open project."""
    session_factory = svc.session_factory
    if session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    data = await file.read()
    try:
        from qualcoder_api.services import audit
        from qualcoder_api.services.user_settings import resolve_owner

        result = await import_refi_qdp(session_factory, data, resolve_owner(codername))
        await audit.record(
            db, user=resolve_owner(codername), action="interchange.import",
            entity="refi", detail=result if isinstance(result, dict) else {},
        )
        return result
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
