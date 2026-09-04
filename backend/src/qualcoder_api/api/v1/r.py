"""R integration API — Rscript status, R job submission/polling, artifacts.

``POST /r/run`` starts a background R job (see ``r_service``); the job is
polled via ``GET /r/jobs/{id}``, cancelled via ``DELETE /r/jobs/{id}``, and
any ``.png``/``.csv`` the run produced in ``r_exchange/out/`` is listed and
served under ``/r/artifacts``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from qualcoder_api.api.v1.deps import DbDep, OpenProjectDep
from qualcoder_api.services import r_service

router = APIRouter(prefix="/r", tags=["r"])

R_NOT_FOUND = "R not found — install R (r-project.org)"


@router.get("/status")
async def status() -> dict:
    import asyncio

    return await asyncio.to_thread(r_service.get_status)


class RunRRequest(BaseModel):
    script: str = Field(max_length=200_000)


@router.post("/run", status_code=202, response_model=None)
async def run_r(req: RunRRequest, svc: OpenProjectDep, db: DbDep, request: Request) -> dict | JSONResponse:
    """Start an R job; returns its id for polling."""
    from qualcoder_api.core.server_config import is_server_mode
    from qualcoder_api.services import audit
    from qualcoder_api.services.user_settings import get_codername

    if not req.script.strip():
        raise HTTPException(status_code=422, detail="script is empty")
    if len(req.script) > 200_000:
        raise HTTPException(status_code=422, detail="script too large (max 200KB)")
    if is_server_mode():
        # Arbitrary R code is remote code execution: only admins may run it
        # on a shared server. Viewers are already blocked by the project
        # gate; editors are blocked here.
        from qualcoder_api.api.v1.auth_deps import get_current_user as _get_user

        # Resolve the bearer token from the request headers when available.
        auth = ""
        try:
            # ``request`` is injected by FastAPI when present; fall back to
            # empty (401) when the signature injection failed.
            auth = request.headers.get("authorization", "") if request is not None else ""
        except Exception:
            auth = ""
        user = await _get_user(auth)
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="admin role required for R execution")
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
