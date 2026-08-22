"""R integration API — Rscript status, R job submission/polling, artifacts.

``POST /r/run`` starts a background R job (see ``r_service``); the job is
polled via ``GET /r/jobs/{id}``, cancelled via ``DELETE /r/jobs/{id}``, and
any ``.png``/``.csv`` the run produced in ``r_exchange/out/`` is listed and
served under ``/r/artifacts``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from qualcoder_api.api.v1.deps import DbDep, OpenProjectDep
from qualcoder_api.services import r_service

router = APIRouter(prefix="/r", tags=["r"])

R_NOT_FOUND = "R not found — install R (r-project.org)"


@router.get("/status")
async def status() -> dict:
    return r_service.get_status()


class RunRRequest(BaseModel):
    script: str


@router.post("/run", status_code=202, response_model=None)
async def run_r(req: RunRRequest, svc: OpenProjectDep, db: DbDep) -> dict | JSONResponse:
    """Start an R job; returns its id for polling."""
    from qualcoder_api.services import audit
    from qualcoder_api.services.user_settings import get_codername

    if not req.script.strip():
        raise HTTPException(status_code=422, detail="script is empty")
    rscript = r_service.find_rscript()
    if rscript is None:
        return JSONResponse(status_code=503, content={"error": R_NOT_FOUND})
    job_id = r_service.start_r_job(project_path=svc.project_path, script=req.script, rscript=rscript)
    await audit.record(
        db,
        user=get_codername(),
        action="r.run",
        entity="r",
        detail={"job_id": job_id, "script_len": len(req.script)},
    )
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
async def job(job_id: str) -> dict:
    data = r_service.get_r_job(job_id)
    if data is None:
        raise HTTPException(status_code=404, detail="job not found")
    return data


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str) -> dict:
    if not r_service.control_r_job(job_id, "cancel"):
        raise HTTPException(status_code=404, detail="job not found or already finished")
    return {"ok": True}


@router.get("/artifacts")
async def artifacts(svc: OpenProjectDep) -> dict:
    return {"files": r_service.list_artifacts(svc.project_path)}


@router.get("/artifacts/{name}")
async def artifact(name: str, svc: OpenProjectDep) -> Response:
    result = r_service.read_artifact(svc.project_path, name)
    if result is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    content, media_type = result
    return Response(content=content, media_type=media_type)
