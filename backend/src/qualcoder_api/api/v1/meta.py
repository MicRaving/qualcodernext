"""Meta-analysis pipeline API — hits, criteria, screening, downloads,
extraction, schemes and background jobs.

Local-only in v1: writes go through ``MetaRepository`` (no ``sync_log``
capture), so meta changes are intentionally not collaboration-synced nor
undoable. Audit rows are still recorded so the activity shows in History.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from qualcoder_api.api.v1.deps import DbDep, OpenProjectDep
from qualcoder_api.core.models import MetaHit
from qualcoder_api.persistence.repo.meta_repo import MetaRepository
from qualcoder_api.services import meta_jobs
from qualcoder_api.services import meta_screen as screen_service
from qualcoder_api.services.meta_download import run_downloads
from qualcoder_api.services.meta_eligibility import verdict_all_yes
from qualcoder_api.services.meta_extract import (
    export_csv,
    export_xlsx,
    flatten_to_rows,
    publish_to_cases,
    publish_to_codes,
    run_extraction,
)
from qualcoder_api.services.project_service import ProjectService
from qualcoder_api.services.user_settings import get_ai_settings, get_codername

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meta", tags=["meta"])


# ── request/response models ──────────────────────────────────────────────

class CriterionItem(BaseModel):
    position: int = 0
    key: str
    label: str
    prompt_text: str


class ScreeningSave(BaseModel):
    hit_id: int
    run_id: str = ""
    verdicts: dict = {}
    intervention_type: str | None = None
    rationale: str | None = None
    owner: str | None = None


class LlmScreenRequest(BaseModel):
    run_id: str = ""
    hit_ids: list[int] | None = None
    cluster_size: int = Field(default=8, ge=1, le=64)
    model: str | None = None


class DownloadRunRequest(BaseModel):
    hit_ids: list[int] | None = None
    email: str = ""


class ExtractRunRequest(BaseModel):
    scheme: str
    hit_ids: list[int] | None = None
    model: str | None = None
    stop_after: int = Field(default=0, ge=0)
    #: Per-request full-text ceiling (chars, head+tail truncated). Keeps an
    #: oversized paper from hard-failing a smaller-context model.
    max_input_chars: int = Field(default=120_000, ge=2_000, le=2_000_000)
    #: When True (default) whole-queue runs only process papers that have an
    #: acquired fulltext; switch off to attempt every included paper (e.g.
    #: to record why a fulltext-less paper cannot be coded).
    fulltext_only: bool = True


class SchemeCreate(BaseModel):
    name: str
    label: str | None = None
    description: str | None = None
    prescreen_prompt: str | None = None
    coding_prompt: str | None = None
    codebook: dict | None = None


class PublishRequest(BaseModel):
    hit_id: int
    to_cases: bool = True
    to_codes: bool = True


def _hit_payload(hit: MetaHit, eligible: bool, screened: bool) -> dict:
    data = hit.model_dump()
    data["eligible"] = eligible
    data["screened"] = screened
    return data


# ── hits ─────────────────────────────────────────────────────────────────

@router.get("/hits", response_model=dict)
async def list_hits(
    db: DbDep,
    search_run: str | None = None,
    filter: str | None = None,
    scope: str = "all",
    limit: int = 200,
    offset: int = 0,
) -> dict:
    """One page of hits (paginated: an 11k-study import must not be loaded
    whole), with the latest-verdict eligibility for just this page."""
    repo = MetaRepository(db)
    limit = max(1, min(limit, 1000))
    hits = await repo.list_hits(
        search_run=search_run, filter_text=filter, limit=limit, offset=offset, scope=scope
    )
    verdicts = await repo.latest_verdicts_for([h.hit_id for h in hits])
    total = await repo.count_hits(search_run=search_run, filter_text=filter, scope=scope)
    return {
        "hits": [
            _hit_payload(
                h, verdict_all_yes(verdicts.get(h.hit_id) or {}), h.hit_id in verdicts
            )
            for h in hits
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/hits/search-runs", response_model=list[str])
async def hit_search_runs(db: DbDep) -> list[str]:
    return await MetaRepository(db).search_runs()


async def _save_upload(svc, file: UploadFile, prefix: str) -> str:
    """Write an upload next to the project; returns the temp path."""
    from qualcoder_api.core.security import sanitize_filename

    safe_name = sanitize_filename(file.filename or prefix, prefix)
    tmp = os.path.join(svc.project_path, f"_{safe_name}")
    with open(tmp, "wb") as out:  # noqa: ASYNC230 - small local temp write
        while chunk := await file.read(1 << 20):
            out.write(chunk)
    return tmp


@router.post("/hits/preview", response_model=dict)
async def preview_hits(
    svc: OpenProjectDep,
    file: Annotated[UploadFile, File()],
    sheet: Annotated[str | None, Form()] = None,
) -> dict:
    """Describe an upload for the import labeler (sheets, header row, columns,
    sample rows, auto-mapping). Read-only — no hits are created."""
    from qualcoder_api.services.meta_import import preview_hits_file

    tmp = await _save_upload(svc, file, "meta")
    try:
        try:
            return await asyncio.to_thread(preview_hits_file, tmp, sheet=sheet)
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err)) from err
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)


@router.post("/hits/import", response_model=dict)
async def import_hits(
    svc: OpenProjectDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    search_run: Annotated[str | None, Form()] = None,
    sheet: Annotated[str | None, Form()] = None,
    header_row: Annotated[int | None, Form()] = None,
    mapping: Annotated[str | None, Form()] = None,
) -> dict:
    """Import a search-results file (EBSCO XML, Excel, RIS, CSV).

    ``sheet`` / ``header_row`` / ``mapping`` (JSON) come from the import
    dialog and override the automatic column detection.
    """
    from qualcoder_api.services.meta_import import parse_hits_file

    parsed_mapping: dict | None = None
    if mapping:
        try:
            loaded = json.loads(mapping)
            parsed_mapping = loaded if isinstance(loaded, dict) else None
        except ValueError:
            parsed_mapping = None

    tmp = await _save_upload(svc, file, "meta")
    try:
        try:
            parsed = await asyncio.to_thread(
                parse_hits_file,
                tmp,
                sheet=sheet or None,
                header_row=header_row,
                mapping=parsed_mapping,
            )
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err)) from err
        for hit in parsed:
            if search_run:
                hit["search_run"] = search_run.strip()
        repo = MetaRepository(db)
        imported = await repo.add_hits(parsed)
        return {
            "ok": True,
            "imported": imported,
            "parsed": len(parsed),
            "duplicates_skipped": len(parsed) - imported,
        }
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)


@router.patch("/hits/{hit_id}", response_model=MetaHit)
async def update_hit(hit_id: int, db: DbDep, body: dict) -> MetaHit:
    allowed = {"title", "abstract", "authors", "doi", "year", "source", "language", "status"}
    fields = {k: v for k, v in body.items() if k in allowed and v is not None}
    hit = await MetaRepository(db).update_hit(hit_id, **fields)
    if hit is None:
        raise HTTPException(status_code=404, detail="hit not found")
    return hit


@router.delete("/hits/{hit_id}", status_code=204)
async def delete_hit(hit_id: int, db: DbDep) -> None:
    if not await MetaRepository(db).delete_hit(hit_id):
        raise HTTPException(status_code=404, detail="hit not found")


@router.get("/status", response_model=dict)
async def meta_status(db: DbDep) -> dict:
    """Counts only — never loads the hit/row sets (11k-study safe)."""
    repo = MetaRepository(db)
    tabs = await repo.tab_counts()
    return {
        "hits": tabs["screening"],
        "criteria": len(await repo.list_criteria()),
        "schemes": len(await repo.list_schemes()),
        "screening_rows": await repo.count_screening(),
        "eligible": tabs["downloads"],
        "documents_done": tabs["extraction"],
        "extracted": await repo.count_extractions("extracted"),
        "tabs": tabs,
        "by_status": await repo.status_counts(),
    }


# ── criteria ─────────────────────────────────────────────────────────────

@router.get("/criteria", response_model=list)
async def list_criteria(db: DbDep) -> list:
    return await MetaRepository(db).list_criteria()


@router.put("/criteria", response_model=list)
async def replace_criteria(db: DbDep, body: list[CriterionItem]) -> list:
    """Atomic replace of the configured inclusion criteria."""
    return await MetaRepository(db).replace_criteria([c.model_dump() for c in body])


@router.delete("/criteria/{criterion_id}", status_code=204)
async def delete_criterion(criterion_id: int, db: DbDep) -> None:
    if not await MetaRepository(db).delete_criterion(criterion_id):
        raise HTTPException(status_code=404, detail="criterion not found")


# ── schemes ──────────────────────────────────────────────────────────────

@router.get("/schemes", response_model=list)
async def list_schemes(db: DbDep) -> list:
    return await MetaRepository(db).list_schemes()


@router.post("/schemes", response_model=dict, status_code=201)
async def create_scheme(db: DbDep, body: SchemeCreate) -> dict:
    repo = MetaRepository(db)
    if await repo.get_scheme(name=body.name) is not None:
        raise HTTPException(status_code=409, detail=f"scheme '{body.name}' already exists")
    scheme = await repo.add_scheme(
        name=body.name,
        label=body.label,
        description=body.description,
        prescreen_prompt=body.prescreen_prompt,
        coding_prompt=body.coding_prompt,
        codebook=json.dumps(body.codebook) if body.codebook is not None else None,
    )
    return {"ok": True, "id": scheme.id, "name": scheme.name}


@router.put("/schemes/{scheme_id}", response_model=dict)
async def update_scheme(scheme_id: int, db: DbDep, body: SchemeCreate) -> dict:
    repo = MetaRepository(db)
    fields = {
        "name": body.name,
        "label": body.label,
        "description": body.description,
        "prescreen_prompt": body.prescreen_prompt,
        "coding_prompt": body.coding_prompt,
        "codebook": json.dumps(body.codebook) if body.codebook is not None else None,
    }
    fields = {k: v for k, v in fields.items() if v is not None}
    scheme = await repo.update_scheme(scheme_id, **fields)
    if scheme is None:
        raise HTTPException(status_code=404, detail="scheme not found")
    return {"ok": True, "id": scheme.id}


@router.delete("/schemes/{scheme_id}", status_code=204)
async def delete_scheme(scheme_id: int, db: DbDep) -> None:
    if not await MetaRepository(db).delete_scheme(scheme_id):
        raise HTTPException(status_code=404, detail="scheme not found")


# ── screening ────────────────────────────────────────────────────────────

@router.get("/screening", response_model=list)
async def list_screening(
    db: DbDep, hit_id: int | None = None, owner: str | None = None, run_id: str | None = None
) -> list:
    return await MetaRepository(db).list_screening(hit_id=hit_id, owner=owner, run_id=run_id)


@router.put("/screening", response_model=dict)
async def save_screening(db: DbDep, body: ScreeningSave) -> dict:
    """Save a (manual or edited) verdict row for the current coder."""
    repo = MetaRepository(db)
    if await repo.get_hit(body.hit_id) is None:
        raise HTTPException(status_code=404, detail="hit not found")
    owner = body.owner or get_codername()
    row = await repo.upsert_screening(
        hit_id=body.hit_id,
        owner=owner,
        run_id=body.run_id,
        verdicts=body.verdicts,
        intervention_type=body.intervention_type,
        rationale=body.rationale,
        origin="manual",
    )
    # Reflect the pipeline's latest-row eligibility onto the hit status.
    latest = await repo.latest_screening_by_hit()
    verdicts = latest[body.hit_id].verdicts if body.hit_id in latest else {}
    status = "included" if verdict_all_yes(verdicts) else "excluded"
    if verdicts:
        await repo.set_hit_status(body.hit_id, status)
    return {"ok": True, "id": row.id, "hit_id": body.hit_id, "status": status}


@router.post("/screening/llm", response_model=dict)
async def llm_screen(svc: OpenProjectDep, db: DbDep, body: LlmScreenRequest) -> dict:
    """Start an LLM screening job over the given (or all unscreened) hits."""
    repo = MetaRepository(db)
    criteria = await repo.list_criteria()
    if not criteria:
        raise HTTPException(status_code=422, detail="Configure inclusion criteria first.")
    ai = get_ai_settings()
    if not ai.get("enabled"):
        raise HTTPException(status_code=422, detail="AI is not enabled — enable it in Settings.")
    owner = get_codername()
    session_factory = svc.session_factory
    run_id = body.run_id

    async def run(progress_cb, should_stop):
        return await screen_service.llm_screen_hits(
            session_factory,
            criteria=criteria,
            hit_ids=body.hit_ids,
            owner=owner,
            run_id=run_id,
            model=body.model,
            cluster_size=body.cluster_size,
            progress_cb=lambda done, total: progress_cb(done, total, "screening"),
            should_stop=should_stop,
        )

    job_id = meta_jobs.start_job(kind="screen", label=f"LLM screening ({owner})", run=run)
    return {"ok": True, "job_id": job_id}


# ── downloads ────────────────────────────────────────────────────────────

@router.get("/documents", response_model=list)
async def list_documents(db: DbDep) -> list[dict]:
    repo = MetaRepository(db)
    docs = await repo.list_documents()
    hits = {h.hit_id: h for h in await repo.list_hits()}
    return [
        {
            **d.model_dump(),
            "title": hits[d.hit_id].title if d.hit_id in hits else "",
            "doi": hits[d.hit_id].doi if d.hit_id in hits else "",
        }
        for d in docs
    ]


@router.post("/downloads/run", response_model=dict)
async def start_downloads(svc: OpenProjectDep, db: DbDep, body: DownloadRunRequest) -> dict:
    if svc.session_factory is None or not svc.project_path:
        raise HTTPException(status_code=409, detail="no project is open")
    session_factory = svc.session_factory
    project_path = svc.project_path
    owner = get_codername()

    async def run(progress_cb, should_stop):
        return await run_downloads(
            session_factory,
            project_path=project_path,
            hit_ids=body.hit_ids,
            owner=owner,
            email=body.email,
            progress_cb=lambda d, t, msg: progress_cb(d, t, msg or "downloading"),
            should_stop=should_stop,
        )

    job_id = meta_jobs.start_job(kind="download", label="Paper downloads", run=run)
    return {"ok": True, "job_id": job_id}


def _normalize_key(text: str) -> str:
    """Fold a filename/DOI/title to lowercase alphanumerics for matching."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _match_hit_for_filename(filename: str, hits: list[MetaHit]) -> MetaHit | None:
    """Best-effort match of an imported PDF name to a hit (DOI, then title)."""
    key = _normalize_key(os.path.splitext(filename)[0])
    if not key:
        return None
    for hit in hits:
        if not hit.doi:
            continue
        doi = _normalize_key(hit.doi.replace("https://doi.org/", "").replace("http://doi.org/", ""))
        if len(doi) >= 8 and doi in key:
            return hit
    for hit in hits:
        title = _normalize_key(hit.title or "")
        if len(title) < 24:
            continue
        if title in key or title[:48] in key:
            return hit
    return None


async def _store_pdf(
    svc: ProjectService,
    repo: MetaRepository,
    hit: MetaHit,
    *,
    content: bytes,
    filename: str,
) -> tuple[int, int]:
    """Import PDF bytes as a source and link them to ``hit`` (manual method)."""
    from qualcoder_api.core.security import sanitize_filename
    from qualcoder_api.services.import_service import ImportService

    project_path = svc.project_path
    if project_path is None or svc.session_factory is None:
        raise ValueError("no project is open")
    safe_name = sanitize_filename(filename or "paper.pdf", "meta_pdf")
    tmp = f"{project_path}/_meta_assign_{hit.hit_id}_{safe_name}"
    with open(tmp, "wb") as out:  # noqa: ASYNC230 - small local temp write
        out.write(content)
    try:
        importer = ImportService(project_path, svc.session_factory)
        source = await importer.import_file(
            tmp, owner=get_codername(), filename=f"meta_{hit.hit_id}_{safe_name}"
        )
        if source is None:
            raise ValueError("file import failed (duplicate name?)")
        doc = await repo.upsert_document(
            hit_id=hit.hit_id,
            source_id=source.id,
            retrieval_method="manual",
            url=hit.doi or "",
            status="done",
            message="assigned manually",
        )
        await repo.set_hit_status(hit.hit_id, "downloaded")
        return source.id, doc.id
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)


@router.post("/downloads/assign/{hit_id}", response_model=dict)
async def assign_pdf(
    svc: OpenProjectDep,
    db: DbDep,
    hit_id: int,
    file: Annotated[UploadFile, File()],
) -> dict:
    """Manually assign a PDF to a hit: import as a source and link it."""
    repo = MetaRepository(db)
    hit = await repo.get_hit(hit_id)
    if hit is None:
        raise HTTPException(status_code=404, detail="hit not found")
    try:
        source_id, document_id = await _store_pdf(
            svc, repo, hit, content=await file.read(), filename=file.filename or "paper.pdf"
        )
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    return {"ok": True, "source_id": source_id, "document_id": document_id}


@router.post("/downloads/assign-batch", response_model=dict)
async def assign_pdfs_batch(
    svc: OpenProjectDep,
    db: DbDep,
    files: Annotated[list[UploadFile], File()],
) -> dict:
    """Batch-assign PDFs, matching each filename to a hit by DOI or title."""
    if svc.session_factory is None or not svc.project_path:
        raise HTTPException(status_code=409, detail="no project is open")
    repo = MetaRepository(db)
    hits = await repo.list_hits()
    documents = {d.hit_id: d for d in await repo.list_documents()}
    assigned: list[dict] = []
    unmatched: list[str] = []
    failed: list[dict] = []
    for upload in files:
        filename = upload.filename or "paper.pdf"
        hit = _match_hit_for_filename(filename, hits)
        if hit is None:
            unmatched.append(filename)
            continue
        existing = documents.get(hit.hit_id)
        if existing is not None and existing.source_id is not None:
            failed.append({"filename": filename, "error": "already has a PDF"})
            continue
        try:
            source_id, document_id = await _store_pdf(
                svc, repo, hit, content=await upload.read(), filename=filename
            )
        except ValueError as err:
            failed.append({"filename": filename, "error": str(err)})
            continue
        assigned.append(
            {
                "filename": filename,
                "hit_id": hit.hit_id,
                "source_id": source_id,
                "document_id": document_id,
            }
        )
    return {
        "ok": True,
        "assigned": assigned,
        "unmatched": unmatched,
        "failed": failed,
    }


# ── extraction ───────────────────────────────────────────────────────────

@router.get("/extractions", response_model=list)
async def list_extractions(db: DbDep, hit_id: int | None = None) -> list[dict]:
    repo = MetaRepository(db)
    extras = await repo.list_extractions(hit_id=hit_id)
    hits = {h.hit_id: h for h in await repo.list_hits()}
    schemes = {s.name: s for s in await repo.list_schemes()}
    return [
        {
            **e.model_dump(),
            "title": hits[e.hit_id].title if e.hit_id in hits else "",
            "doi": hits[e.hit_id].doi if e.hit_id in hits else "",
            "scheme_label": (schemes[e.scheme].label if e.scheme in schemes else e.scheme),
        }
        for e in extras
    ]


@router.post("/extract/run", response_model=dict)
async def start_extraction(svc: OpenProjectDep, db: DbDep, body: ExtractRunRequest) -> dict:
    if svc.session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    repo = MetaRepository(db)
    if await repo.get_scheme(name=body.scheme) is None:
        raise HTTPException(status_code=422, detail=f"Unknown scheme '{body.scheme}'")
    session_factory = svc.session_factory
    owner = get_codername()

    async def run(progress_cb, should_stop):
        return await run_extraction(
            session_factory,
            hit_ids=body.hit_ids,
            owner=owner,
            scheme_name=body.scheme,
            model=body.model,
            stop_after=body.stop_after,
            max_input_chars=body.max_input_chars,
            fulltext_only=body.fulltext_only,
            progress_cb=lambda d, t, msg: progress_cb(d, t, msg or "extracting"),
            should_stop=should_stop,
        )

    job_id = meta_jobs.start_job(kind="extract", label=f"Extraction ({body.scheme})", run=run)
    return {"ok": True, "job_id": job_id}


@router.post("/extract/publish", response_model=dict)
async def publish_extraction(db: DbDep, body: PublishRequest) -> dict:
    """Opt-in mirror of an extraction onto cases/attributes and codes/memos."""
    repo = MetaRepository(db)
    ext = await repo.get_extraction_for_hit(body.hit_id)
    if ext is None or ext.status != "extracted":
        raise HTTPException(status_code=422, detail="no extracted data for this hit")
    scheme = await repo.get_scheme(name=ext.scheme)
    codebook = {}
    if scheme and scheme.codebook:
        try:
            codebook = json.loads(scheme.codebook)
        except ValueError:
            codebook = {}
    result: dict = {}
    if body.to_cases:
        result["cases"] = await publish_to_cases(
            db, hit_id=body.hit_id, owner=get_codername(), codebook=codebook
        )
    if body.to_codes:
        result["codes"] = await publish_to_codes(
            db, hit_id=body.hit_id, owner=get_codername(), codebook=codebook
        )
    return {"ok": True, **result}


@router.get("/extract/export")
async def export_extractions(db: DbDep, fmt: str = "csv") -> Response:
    repo = MetaRepository(db)
    extras = await repo.list_extractions()
    extras = [e for e in extras if e.status == "extracted"]
    rows = flatten_to_rows(extras)
    if fmt == "xlsx":
        filename, content = export_xlsx(rows)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fmt == "csv":
        filename, content = export_csv(rows)
        media_type = "text/csv; charset=utf-8"
    else:
        raise HTTPException(status_code=422, detail="fmt must be 'csv' or 'xlsx'")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── jobs ─────────────────────────────────────────────────────────────────

@router.get("/jobs", response_model=list)
async def list_jobs(kind: str | None = None) -> list:
    return meta_jobs.list_jobs(kind=kind)


@router.get("/jobs/{job_id}", response_model=dict)
async def get_job(job_id: str) -> dict:
    job = meta_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.post("/jobs/{job_id}/control", response_model=dict)
async def control_job(job_id: str, action: str) -> dict:
    if not meta_jobs.control_job(job_id, action):
        raise HTTPException(status_code=409, detail="cannot control job in its current state")
    return {"ok": True}


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str) -> None:
    if not meta_jobs.delete_job(job_id):
        raise HTTPException(status_code=404, detail="job not found")
