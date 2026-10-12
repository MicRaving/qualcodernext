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
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import AliasChoices, BaseModel, Field

from qualcoder_api.api.v1.deps import DbDep, OpenProjectDep
from qualcoder_api.core.models import MetaHit
from qualcoder_api.persistence.repo.meta_repo import MetaRepository
from qualcoder_api.services import (
    meta_agreement,
    meta_analysis,
    meta_audit,
    meta_bayes,
    meta_consensus,
    meta_figures,
    meta_jobs,
    meta_multiverse,
    meta_prisma,
    meta_report,
    meta_summary,
)
from qualcoder_api.services import meta_screen as screen_service
from qualcoder_api.services.meta_download import run_downloads
from qualcoder_api.services.meta_eligibility import evaluate_criteria
from qualcoder_api.services.meta_extract import (
    derive_dv_metrics,
    export_csv,
    export_xlsx,
    flatten_to_rows,
    publish_to_cases,
    publish_to_codes,
    records_from_response,
    refresh_dv_metrics,
    run_extraction,
)
from qualcoder_api.services.meta_roles import role_map
from qualcoder_api.services.meta_scheme import (
    all_fields,
    metric_fields,
    normalise_codebook,
    study_fields,
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
    kind: str = "verdict"
    options: list = []
    pass_values: list = ["yes"]
    exclude_reason: str = ""
    gating: int = 1
    help: str = ""


class ScreeningSave(BaseModel):
    hit_id: int
    run_id: str = ""
    verdicts: dict = {}
    intervention_type: str | None = None
    rationale: str | None = None
    owner: str | None = None
    stage: str = "abstract"
    reason: str = ""


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


class ExtractionSave(BaseModel):
    """Manual save of a scheme-driven extraction (editor form)."""

    hit_id: int
    owner: str | None = None
    scheme: str | None = None
    study_vars: dict = {}
    status: str = "extracted"
    missing_reason: str | None = None


class ResolveScreeningRequest(BaseModel):
    hit_id: int
    criterion_key: str
    value: str | None = None
    master: str = ""
    run_id: str = ""
    stage: str = "abstract"


class ResolveExtractionRequest(BaseModel):
    hit_id: int
    #: Accept either the canonical ``field_name`` or the shorter ``field``.
    field_name: str = Field(validation_alias=AliasChoices("field_name", "field"))
    value: Any = None
    master: str = ""
    record_index: int = 0
    metric_key: str | None = None
    metric_index: int | None = None
    scheme: str | None = None


class AnalysisRequest(BaseModel):
    scheme: str | None = None
    owner: str | None = None
    primary: bool = True
    #: Pooling model: ``dl`` (default), ``two_level`` or ``fixed``.
    model: str = "dl"
    #: Restrict to one outcome domain (the ``dv_domain`` role value).
    domain: str | None = None
    #: Restrict to a set of enabled effect families.
    families: list[str] | None = None


class ModeratorRequest(AnalysisRequest):
    #: ``field`` selects a coded variable by its field name; ``role`` keeps the
    #: legacy role-id lookup. ``key = field or role``.
    field: str | None = None
    role: str = ""
    terms: list[str] = []
    #: ``[a, b]`` term pairs whose base columns enter as elementwise products.
    interactions: list[list[str]] = []


class SubgroupRequest(AnalysisRequest):
    #: ``key`` is the legacy position (role id or column); ``field`` selects a
    #: coded variable by name. ``key = field or key``.
    key: str = ""
    field: str | None = None


class LeaveOneOutRequest(AnalysisRequest):
    by: str = "effect"


class BayesRequest(AnalysisRequest):
    mu_sd: float = 1.0
    tau_prior: str = "half-normal"
    tau_scale: float = 0.5


class MultiverseRequest(AnalysisRequest):
    max_specs: int = Field(default=200, ge=1, le=2000)


class ReportRequest(BaseModel):
    format: str = "docx"
    scheme: str | None = None
    owner: str | None = None
    title: str | None = None
    primary: bool = True


class SchemeClone(BaseModel):
    name: str
    label: str | None = None


class SchemeImport(BaseModel):
    name: str
    label: str | None = None
    description: str | None = None
    prescreen_prompt: str | None = None
    coding_prompt: str | None = None
    codebook: dict | None = None
    overwrite: bool = False


class CodingStudioPreviewRequest(BaseModel):
    #: Absolute path of a reference CodingStudio project folder (read-only).
    folder: str


class CodingStudioImportRequest(BaseModel):
    folder: str
    owner: str = "codingstudio"
    run_id: str = "codingstudio"
    import_hits: bool = True
    import_screening: bool = True
    import_extractions: bool = True
    link_pdfs: bool = True
    scheme_name: str = "codingstudio"


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
    verdicts = await repo.latest_verdicts_for([h.hit_id for h in hits], stage="abstract")
    criteria = await repo.list_criteria()
    evaluated = {
        hit_id: evaluate_criteria(criteria, raw)["eligible"] for hit_id, raw in verdicts.items()
    }
    total = await repo.count_hits(search_run=search_run, filter_text=filter, scope=scope)
    return {
        "hits": [
            _hit_payload(h, evaluated.get(h.hit_id, False), h.hit_id in verdicts)
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
    criteria = await repo.list_criteria()
    tabs = await repo.tab_counts(lambda verdicts: evaluate_criteria(criteria, verdicts)["eligible"], stage="abstract")
    return {
        "hits": tabs["screening"],
        "criteria": len(criteria),
        "schemes": len(await repo.list_schemes()),
        "screening_rows": await repo.count_screening(),
        "screened_hits": await repo.count_screened_hits("abstract"),
        "eligible": tabs["downloads"],
        "documents_done": tabs["extraction"],
        "extracted": await repo.count_extractions("extracted"),
        "tabs": tabs,
        "by_status": await repo.status_counts(),
        "documents": await repo.document_status_counts(),
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


def _scheme_codebook(codebook_json: str | None) -> dict:
    if not codebook_json:
        return {}
    loaded: Any = None
    with contextlib.suppress(json.JSONDecodeError, TypeError):
        loaded = json.loads(codebook_json)
    return loaded if isinstance(loaded, dict) else {}


@router.get("/moderators", response_model=list)
async def list_moderators(db: DbDep, scheme: str | None = None) -> list[dict]:
    """Catalogue of coded variables that can act as analysis moderators.

    Aggregates the study/metric fields of every scheme (or just ``scheme``),
    skipping fields the user hid in the editor (``moderator is False``) and
    internal ``_``-prefixed names. Entries are deduplicated by field name and
    carry the schemes each variable appears in, sorted by group then label.
    """
    repo = MetaRepository(db)
    schemes = await repo.list_schemes()
    if scheme:
        schemes = [s for s in schemes if s.name == scheme]
    merged: dict[str, dict] = {}
    for row in schemes:
        book = normalise_codebook(_scheme_codebook(row.codebook))
        entries = [(field, "study") for field in study_fields(book)]
        entries += [(field, "metric") for field in metric_fields(book)]
        for field, kind in entries:
            name = str(field.get("name") or "")
            if not name or name.startswith("_") or field.get("moderator") is False:
                continue
            entry = merged.get(name)
            if entry is None:
                merged[name] = {
                    "name": name,
                    "label": field.get("label") or name,
                    "group": field.get("group") or "",
                    "kind": kind,
                    "role": field.get("role"),
                    "type": field.get("type") or "string",
                    "editor": field.get("editor") or "text",
                    "schemes": [row.name],
                }
                continue
            if row.name not in entry["schemes"]:
                entry["schemes"].append(row.name)
            label = field.get("label")
            if label and entry["label"] in ("", name):
                entry["label"] = label
            if not entry.get("role") and field.get("role"):
                entry["role"] = field["role"]
    return sorted(
        merged.values(),
        key=lambda item: (
            str(item.get("group") or "").lower(),
            str(item.get("label") or "").lower(),
        ),
    )


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
    """Delete a scheme; refused while extractions still reference it."""
    repo = MetaRepository(db)
    scheme = await repo.get_scheme(scheme_id=scheme_id)
    if scheme is None:
        raise HTTPException(status_code=404, detail="scheme not found")
    referenced = await repo.count_extractions_for_scheme(scheme.name)
    if referenced:
        raise HTTPException(
            status_code=409,
            detail=(
                f"scheme '{scheme.name}' is referenced by {referenced} extraction(s); "
                "delete or re-scheme those first"
            ),
        )
    await repo.delete_scheme(scheme_id)


# ── screening ────────────────────────────────────────────────────────────

@router.get("/screening", response_model=list)
async def list_screening(
    db: DbDep,
    hit_id: int | None = None,
    owner: str | None = None,
    run_id: str | None = None,
    stage: str | None = None,
) -> list:
    return await MetaRepository(db).list_screening(
        hit_id=hit_id, owner=owner, run_id=run_id, stage=stage
    )


@router.put("/screening", response_model=dict)
async def save_screening(db: DbDep, body: ScreeningSave) -> dict:
    """Save a (manual or edited) verdict row for the current coder."""
    repo = MetaRepository(db)
    if await repo.get_hit(body.hit_id) is None:
        raise HTTPException(status_code=404, detail="hit not found")
    owner = body.owner or get_codername()
    criteria = await repo.list_criteria()
    evaluation = evaluate_criteria(criteria, body.verdicts)
    # Derive the structured exclusion reason from the first failing criterion
    # when the caller did not supply one (contract §1/§5).
    reason = body.reason or ""
    if not reason and not evaluation["eligible"] and evaluation["reasons"]:
        reason = str(evaluation["reasons"][0])
    row = await repo.upsert_screening(
        hit_id=body.hit_id,
        owner=owner,
        run_id=body.run_id,
        verdicts=body.verdicts,
        intervention_type=body.intervention_type,
        rationale=body.rationale,
        origin="manual",
        stage=body.stage or "abstract",
        reason=reason,
    )
    # Reflect the pipeline's latest-row eligibility onto the hit status.
    status = "included" if evaluation["eligible"] else "excluded"
    if body.verdicts:
        await repo.set_hit_status(body.hit_id, status)
    return {
        "ok": True,
        "id": row.id,
        "hit_id": body.hit_id,
        "status": status,
        "eligible": evaluation["eligible"],
        "failing": evaluation["failing"],
        "reason": reason,
    }


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
    hits = {h.hit_id: h for h in await repo.list_hits_by_ids([d.hit_id for d in docs])}
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
async def list_extractions(
    db: DbDep,
    hit_id: int | None = None,
    owner: str | None = None,
    scheme: str | None = None,
) -> list[dict]:
    repo = MetaRepository(db)
    extras = await repo.list_extractions(hit_id=hit_id, owner=owner, scheme=scheme)
    hits = {h.hit_id: h for h in await repo.list_hits_by_ids([e.hit_id for e in extras])}
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


@router.put("/extractions", response_model=dict)
async def save_extraction(db: DbDep, body: ExtractionSave) -> dict:
    """Persist a manually edited extraction from the scheme-driven editor.

    Accepts the canonical ``{"records": [{"study": ..., "metrics": [...]}]}``
    shape, normalises metrics through the scheme's roles/effect families and
    derives the flat metric rows used by export/analysis/agreement.
    """
    repo = MetaRepository(db)
    hit = await repo.get_hit(body.hit_id)
    if hit is None:
        raise HTTPException(status_code=404, detail="hit not found")
    owner = body.owner or get_codername()
    existing = await repo.get_extraction_for_hit(body.hit_id, owner, body.scheme)
    scheme_name = body.scheme or (existing.scheme if existing else "")
    scheme = await repo.get_scheme(name=scheme_name) if scheme_name else None
    codebook: dict | None = None
    if scheme is not None and scheme.codebook:
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            codebook = json.loads(scheme.codebook)
    codebook = normalise_codebook(codebook)
    records_raw = (
        body.study_vars.get("records") if isinstance(body.study_vars, dict) else body.study_vars
    )
    records_raw = records_raw if isinstance(records_raw, list) else []
    records, missing = records_from_response(records_raw, codebook)
    flat = derive_dv_metrics(records, role_map(all_fields(codebook)))
    status = body.status or "extracted"
    await repo.upsert_extraction(
        hit_id=body.hit_id,
        owner=owner,
        scheme=scheme_name,
        source_id=existing.source_id if existing else None,
        study_vars={"records": records},
        dv_metrics=flat,
        status=status,
        missing_reason=body.missing_reason,
    )
    if status == "extracted":
        await repo.set_hit_status(body.hit_id, "extracted")
    saved = await repo.get_extraction_for_hit(body.hit_id, owner, scheme_name)
    if saved is None:
        raise HTTPException(status_code=409, detail="extraction could not be saved")
    return {
        "ok": True,
        "id": saved.id,
        "hit_id": saved.hit_id,
        "owner": saved.owner,
        "status": saved.status,
        "missing": missing,
        "extraction": saved.model_dump(),
    }


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
    owner = get_codername()
    ext = await repo.get_extraction_for_hit(body.hit_id, owner)
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
    extras = await repo.list_extractions(status="extracted")
    # Re-derive dv_metrics under each scheme's live codebook: the persisted
    # column is a cache and can lag behind a scheme role edit.
    schemes = {s.name: s for s in await repo.list_schemes()}
    codebooks: dict[str, Any] = {}
    refreshed = []
    for ext in extras:
        if ext.scheme not in codebooks:
            row = schemes.get(ext.scheme)
            codebook: Any = None
            if row is not None and row.codebook:
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    codebook = json.loads(row.codebook)
            codebooks[ext.scheme] = codebook
        refreshed.append(refresh_dv_metrics(ext, codebooks[ext.scheme]))
    rows = flatten_to_rows(refreshed)
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


# ── agreement ────────────────────────────────────────────────────────────

def _exclude_set(raw: str | None) -> set[str]:
    return {part.strip() for part in (raw or "").split(",") if part.strip()}


async def _codebook_for_scheme(repo: MetaRepository, name: str | None) -> dict:
    """Parsed codebook of one scheme (``{}`` when unknown/unreadable)."""
    if not name:
        return {}
    row = await repo.get_scheme(name=name)
    if row is None or not row.codebook:
        return {}
    try:
        loaded = json.loads(row.codebook)
    except ValueError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


async def _extraction_codebook(repo: MetaRepository, scheme: str | None) -> dict:
    name = scheme
    if not name:
        extras = await repo.list_extractions(include_dv_metrics=False)
        name = next((e.scheme for e in extras if e.scheme), None)
    return await _codebook_for_scheme(repo, name)


@router.get("/screening/agreement", response_model=dict)
async def screening_agreement(
    db: DbDep,
    stage: str = "abstract",
    exclude: str | None = None,
    owner: str | None = None,
) -> dict:
    criteria = await MetaRepository(db).list_criteria()
    return await meta_agreement.screening_reliability(
        db, criteria, stage=stage, exclude=_exclude_set(exclude), owner=owner
    )


@router.get("/screening/conflicts", response_model=dict)
async def screening_conflicts(
    db: DbDep,
    master: str = "",
    stage: str = "abstract",
    owner: str | None = None,
    run_id: str | None = None,
    field: str = "",
    status: str = "open",
    study: str | None = None,
    limit: int = 300,
    offset: int = 0,
) -> dict:
    criteria = await MetaRepository(db).list_criteria()
    return await meta_agreement.screening_conflicts(
        db,
        criteria,
        master=master,
        stage=stage,
        owner=owner,
        run_id=run_id,
        field_filter=field,
        status=status,
        study_filter=study,
        limit=max(1, min(limit, 2000)),
        offset=max(0, offset),
    )


@router.post("/screening/resolve", response_model=dict)
async def resolve_screening(db: DbDep, body: ResolveScreeningRequest) -> dict:
    try:
        return await meta_agreement.resolve_screening(
            db,
            hit_id=body.hit_id,
            criterion_key=body.criterion_key,
            value=body.value,
            master=body.master or get_codername(),
            run_id=body.run_id,
            stage=body.stage,
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@router.get("/extraction/agreement", response_model=dict)
async def extraction_agreement(
    db: DbDep,
    scheme: str | None = None,
    exclude: str | None = None,
    owner: str | None = None,
) -> dict:
    repo = MetaRepository(db)
    codebook = await _extraction_codebook(repo, scheme)
    return await meta_agreement.extraction_reliability(
        db, codebook, exclude=_exclude_set(exclude), owner=owner, scheme=scheme
    )


@router.get("/extraction/conflicts", response_model=dict)
async def extraction_conflicts(
    db: DbDep,
    master: str = "",
    scheme: str | None = None,
    owner: str | None = None,
    field: str = "",
    status: str = "open",
    study: str | None = None,
    limit: int = 300,
    offset: int = 0,
) -> dict:
    repo = MetaRepository(db)
    codebook = await _extraction_codebook(repo, scheme)
    return await meta_agreement.extraction_conflicts(
        db,
        codebook,
        master=master,
        owner=owner,
        scheme=scheme,
        field_filter=field,
        status=status,
        study_filter=study,
        limit=max(1, min(limit, 2000)),
        offset=max(0, offset),
    )


@router.post("/extraction/resolve", response_model=dict)
async def resolve_extraction(db: DbDep, body: ResolveExtractionRequest) -> dict:
    try:
        return await meta_agreement.resolve_extraction(
            db,
            hit_id=body.hit_id,
            field_name=body.field_name,
            value=body.value,
            master=body.master or get_codername(),
            record_index=body.record_index,
            metric_key=body.metric_key,
            metric_index=body.metric_index,
            scheme=body.scheme,
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


# ── analysis / reporting ─────────────────────────────────────────────────

def _fallback_filter_effects(
    rows: list[dict], domain: str | None, families: list[str] | None
) -> list[dict]:
    """Transitional filter used until ``meta_analysis.filter_effects`` exists.

    The canonical implementation lives in ``meta_analysis``; this mirrors its
    domain match (the ``dv_domain`` role) and a conservative effect-family
    match on the derived ``method`` so analysis still honours the request when
    both modules are not deployed together.
    """
    out = rows
    if domain:
        wanted = domain.casefold()
        out = [
            row
            for row in out
            if str(row.get("domain") or (row.get("roles") or {}).get("dv_domain") or "")
            .casefold()
            == wanted
        ]
    if families:
        wanted_families = {family.casefold() for family in families}
        out = [
            row
            for row in out
            if str(row.get("method") or "").casefold() in wanted_families
        ]
    return out


def _filter_effects(
    rows: list[dict], domain: str | None, families: list[str] | None
) -> list[dict]:
    if not domain and not families:
        return rows
    canonical = getattr(meta_analysis, "filter_effects", None)
    if canonical is not None:
        return canonical(rows, domain=domain, families=families)
    return _fallback_filter_effects(rows, domain, families)


def _pool_fixed(rows: list[dict]) -> dict:
    canonical = getattr(meta_analysis, "pool_fixed", None)
    if canonical is not None:
        return canonical(rows)
    # Transitional: no fixed-effect estimator available yet — fall back to the
    # random-effects model rather than failing the request.
    return meta_analysis.pool_dl(rows)


def _split_families(families: str | None) -> list[str] | None:
    parts = [part.strip() for part in (families or "").split(",") if part.strip()]
    return parts or None


def _rank_extraction(extraction: Any, preferred: str) -> tuple[int, int]:
    """Rank an extraction for the one-per-hit rule (higher wins)."""
    owner = extraction.owner
    rank = 2 if owner == preferred else (1 if owner == "master" else 0)
    return (rank, int(getattr(extraction, "id", 0) or 0))


def _extraction_id(extraction: Any) -> int:
    """Numeric id of an extraction model or consensus dict (recency order)."""
    if isinstance(extraction, dict):
        return int(extraction.get("id", 0) or 0)
    return int(getattr(extraction, "id", 0) or 0)


def _merge_consensus_report(into: dict[str, Any], part: dict[str, Any]) -> None:
    for key, value in part.items():
        if isinstance(value, (int, float)):
            into[key] = into.get(key, 0) + value


def _parse_codebook(row: Any) -> dict | None:
    """Parsed codebook JSON of a scheme row (``None`` when absent/unreadable)."""
    if row is None or not row.codebook:
        return None
    try:
        return json.loads(row.codebook)
    except (json.JSONDecodeError, TypeError):
        return None


def _derive_analysis_rows(
    extractions: list[Any],
    scheme: str | None,
    owner: str | None,
    primary: bool,
    domain: str | None,
    families: list[str] | None,
    codebooks: dict[str, dict | None],
) -> tuple[list[dict], int, dict[str, Any] | None]:
    """CPU-only half of :func:`_analysis_rows` (runs in a worker thread).

    ``extractions`` are already status/scheme filtered and ``codebooks`` maps
    every extraction's scheme name to its parsed codebook, so this never
    touches the database (no event-loop blocking, no per-row queries).
    """

    def codebook_for(name: str | None) -> dict | None:
        return codebooks.get(name) if name else None

    consensus: dict[str, Any] | None = None
    chosen: dict[Any, Any] = {}
    if owner:
        extractions = [e for e in extractions if e.owner == owner]
        preferred = owner
        for ext in extractions:
            key: Any = (ext.hit_id, ext.scheme) if scheme else ext.hit_id
            current = chosen.get(key)
            if current is None or _rank_extraction(ext, preferred) >= _rank_extraction(
                current, preferred
            ):
                chosen[key] = ext
        selected_rows: list[Any] = list(chosen.values())
    else:
        # Consensus path: merge each scheme's rows separately (each scheme has
        # its own codebook), then keep one row per key exactly as above so
        # scheme-free pooling never double-counts a hit.
        by_scheme: dict[str, list[Any]] = {}
        for ext in extractions:
            by_scheme.setdefault(ext.scheme, []).append(ext)
        consensus = {
            "n_hits": 0,
            "n_groups": 0,
            "n_single_owner": 0,
            "n_consensus_units": 0,
            "n_fields_unanimous": 0,
            "n_master_resolved": 0,
            "n_dropped_conflicts": 0,
            "n_dropped_metrics": 0,
        }
        merged: list[Any] = []
        for group_scheme in sorted(by_scheme):
            group_codebook = codebook_for(group_scheme)
            group_rows, group_report = meta_consensus.build_consensus_rows(
                by_scheme[group_scheme], group_codebook
            )
            _merge_consensus_report(consensus, group_report)
            merged.extend(group_rows)
        consensus["n_hits"] = len(
            {
                e.hit_id if not isinstance(e, dict) else e.get("hit_id")
                for e in extractions
            }
        )
        for ext in merged:
            hit_id = ext.get("hit_id") if isinstance(ext, dict) else ext.hit_id
            ext_scheme = ext.get("scheme") if isinstance(ext, dict) else ext.scheme
            key = (hit_id, ext_scheme) if scheme else hit_id
            current = chosen.get(key)
            if current is None or _extraction_id(ext) >= _extraction_id(current):
                chosen[key] = ext
        selected_rows = list(chosen.values())

    # Group by scheme so each codebook is normalised once, not once per row.
    effects_by_scheme: dict[str, list[dict]] = {}
    for ext in selected_rows:
        ext_scheme = ext.get("scheme") if isinstance(ext, dict) else ext.scheme
        codebook = codebook_for(ext_scheme)
        selected = refresh_dv_metrics(ext, codebook)
        effects_by_scheme.setdefault(ext_scheme or "", []).append(selected)

    rows: list[dict] = []
    for ext_scheme, selected in effects_by_scheme.items():
        rows.extend(
            meta_analysis.build_effects(selected, codebook_for(ext_scheme))
        )
    rows = _filter_effects(rows, domain, families)
    total = len(rows)
    if primary:
        rows = meta_analysis.primary_effects(rows)
    return rows, total, consensus


async def _analysis_rows(
    repo: MetaRepository,
    scheme: str | None,
    owner: str | None,
    primary: bool,
    domain: str | None = None,
    families: list[str] | None = None,
) -> tuple[list[dict], int, dict[str, Any] | None]:
    """Derive effect rows for the analysis endpoints.

    Selection rule (documented for the API contract): exactly ONE extraction
    contributes per hit. When a ``scheme`` is given the key is ``(hit, scheme)``
    (all rows share that scheme); when it is falsy the key is the hit id alone,
    so a hit coded under two schemes is not double-counted.

    With an explicit ``owner`` the requested coder's extraction wins, otherwise
    an ``owner == "master"`` adjudication, otherwise the most recent
    extraction. Without an ``owner`` filter every coder's rows are combined
    into consensus rows (``meta_consensus``: unanimous fields kept, disagreements
    settled by the ``master`` adjudication or excluded + counted), and the
    consensus report is returned as the third tuple item (``None`` when an
    owner filter scoped the rows to one coder).

    ``dv_metrics`` is re-derived from ``study_vars`` under each selected
    extraction's own scheme codebook (the persisted column is only a cache), so
    multi-scheme projects pool correctly. ``domain``/``families`` then filter
    the derived rows; ``primary`` keeps only flagged primary effects (falling
    back to all rows when none are flagged).

    Only ``status == "extracted"`` extractions are loaded (the excluded and
    pending rows contribute nothing), and the parse/derive work runs in a
    worker thread so an analysis over tens of thousands of effect rows never
    blocks the event loop.
    """
    extractions = await repo.list_extractions(
        status="extracted", include_dv_metrics=False
    )
    if scheme:
        extractions = [e for e in extractions if e.scheme == scheme]
    codebooks: dict[str, dict | None] = {
        name: _parse_codebook(await repo.get_scheme(name=name))
        for name in {e.scheme for e in extractions if e.scheme}
    }
    return await asyncio.to_thread(
        _derive_analysis_rows,
        extractions,
        scheme,
        owner,
        primary,
        domain,
        families,
        codebooks,
    )


@router.post("/analysis/pooled", response_model=dict)
async def analysis_pooled(db: DbDep, body: AnalysisRequest) -> dict:
    """Pooled effect estimate.

    ``model`` selects the estimator: ``dl`` (DerSimonian-Laird, default),
    ``two_level`` (effects nested in studies) or ``fixed``. Exactly one
    extraction per hit contributes (per ``(hit, scheme)`` when ``scheme`` is
    given): with an explicit ``owner`` the requested coder wins, else a
    ``master`` adjudication, else the most recent extraction; without an
    ``owner`` filter the coders' rows are combined into consensus rows (see
    ``meta_consensus``) and the ``consensus`` report is echoed so
    unresolved-conflict drops stay visible. ``domain``/``families`` restrict
    the rows before pooling.
    """
    rows, total, consensus = await _analysis_rows(
        MetaRepository(db),
        body.scheme,
        body.owner,
        body.primary,
        body.domain,
        body.families,
    )
    model = (body.model or "dl").strip().lower()
    if model == "two_level":
        result = await asyncio.to_thread(meta_analysis.pool_two_level, rows)
    elif model == "fixed":
        result = await asyncio.to_thread(_pool_fixed, rows)
    else:
        result = await asyncio.to_thread(meta_analysis.pool_dl, rows)
    result["k_total"] = total
    result["primary"] = body.primary
    result["model"] = model
    if consensus is not None:
        result["consensus"] = consensus
    return result


@router.post("/analysis/moderator", response_model=dict)
async def analysis_moderator(db: DbDep, body: ModeratorRequest) -> dict:
    rows, total, _consensus = await _analysis_rows(
        MetaRepository(db), body.scheme, body.owner, body.primary, body.domain, body.families
    )
    key = body.field or body.role
    result = await asyncio.to_thread(
        meta_analysis.moderator, rows, key, body.terms, body.interactions
    )
    # Echo the resolved key under both names so a field-name moderator and a
    # legacy role-id moderator are equally readable to the client.
    result["field"] = key
    result["role"] = key
    result["k_total"] = total
    return result


@router.post("/analysis/subgroup", response_model=dict)
async def analysis_subgroup(db: DbDep, body: SubgroupRequest) -> dict:
    rows, total, _consensus = await _analysis_rows(
        MetaRepository(db), body.scheme, body.owner, body.primary, body.domain, body.families
    )
    key = body.field or body.key
    result = await asyncio.to_thread(meta_analysis.subgroup, rows, key)
    result["field"] = key
    result["k_total"] = total
    return result


@router.post("/analysis/egger", response_model=dict)
async def analysis_egger(db: DbDep, body: AnalysisRequest) -> dict:
    rows, total, _consensus = await _analysis_rows(
        MetaRepository(db), body.scheme, body.owner, body.primary, body.domain, body.families
    )
    result = await asyncio.to_thread(meta_analysis.egger, rows)
    result["k_total"] = total
    return result


def _publication_bias_response(bias: dict, total: int) -> dict:
    """Exact publication-bias response shape the frontend expects."""
    egger = bias.get("egger") or {}
    pet_peese = bias.get("pet_peese") or {}
    trim = bias.get("trim_and_fill") or {}
    curve = bias.get("p_curve") or {}

    def terms(source: dict) -> dict:
        return {
            "intercept": source.get("intercept"),
            "se": source.get("se"),
            "t": source.get("t"),
            "p": source.get("p"),
        }

    return {
        "k": bias.get("k"),
        "k_total": total,
        "egger": {
            "intercept": egger.get("intercept"),
            "se": egger.get("se"),
            "t": egger.get("t"),
            "p": egger.get("p"),
            "slope": egger.get("slope"),
            "slope_se": egger.get("slope_se"),
            "slope_p": egger.get("slope_p"),
        },
        "pet_peese": {
            "pet": terms(pet_peese.get("pet") or {}),
            "peese": terms(pet_peese.get("peese") or {}),
            "recommended": pet_peese.get("recommended"),
        },
        "trim_and_fill": {
            "k0": trim.get("k0"),
            "side": trim.get("side"),
            "estimate": trim.get("estimate"),
            "se": trim.get("se"),
            "ci_low": trim.get("ci_low"),
            "ci_high": trim.get("ci_high"),
        },
        "p_curve": {
            "n_significant": curve.get("n_significant"),
            "n_p_lt_025": curve.get("n_p_lt_025"),
            "p_half": curve.get("p_half"),
            "evidential": curve.get("evidential"),
            "note": curve.get("note"),
        },
    }


@router.post("/analysis/publication-bias", response_model=dict)
async def analysis_publication_bias(db: DbDep, body: AnalysisRequest) -> dict:
    rows, total, _consensus = await _analysis_rows(
        MetaRepository(db), body.scheme, body.owner, body.primary, body.domain, body.families
    )
    bias = await asyncio.to_thread(meta_analysis.publication_bias, rows)
    return _publication_bias_response(bias, total)


@router.post("/analysis/bayes", response_model=dict)
async def analysis_bayes(db: DbDep, body: BayesRequest) -> dict:
    rows, total, _consensus = await _analysis_rows(
        MetaRepository(db), body.scheme, body.owner, body.primary, body.domain, body.families
    )
    result = await asyncio.to_thread(
        meta_bayes.bayes_pool,
        rows,
        mu_sd=body.mu_sd,
        tau_prior=body.tau_prior,
        tau_scale=body.tau_scale,
    )
    result["k_total"] = total
    result["sensitivity"] = await asyncio.to_thread(meta_bayes.bayes_sensitivity, rows)
    return result


@router.post("/analysis/leave-one-out", response_model=dict)
async def analysis_leave_one_out(db: DbDep, body: LeaveOneOutRequest) -> dict:
    rows, total, _consensus = await _analysis_rows(
        MetaRepository(db), body.scheme, body.owner, body.primary, body.domain, body.families
    )
    result = await asyncio.to_thread(meta_analysis.leave_one_out, rows, by=body.by)
    result["k_total"] = total
    return result


def _forest_png(rows: list[dict]) -> bytes:
    return meta_figures.forest_png(meta_analysis.forest(rows))


def _funnel_png(rows: list[dict]) -> bytes:
    return meta_figures.funnel_png(rows)


def _spec_curve_png(rows: list[dict]) -> bytes:
    return meta_figures.spec_curve_png(meta_multiverse.multiverse(rows))


def _bayes_png(rows: list[dict]) -> bytes:
    return meta_figures.bayes_png(meta_bayes.bayes_pool(rows))


@router.get("/analysis/forest", response_model=dict)
async def analysis_forest(
    db: DbDep,
    scheme: str | None = None,
    owner: str | None = None,
    primary: bool = True,
    domain: str | None = None,
    families: str | None = None,
) -> dict:
    rows, total, _consensus = await _analysis_rows(
        MetaRepository(db), scheme, owner, primary, domain, _split_families(families)
    )
    result = await asyncio.to_thread(meta_analysis.forest, rows)
    result["k_total"] = total
    return result


@router.get("/analysis/forest.png")
async def analysis_forest_png(
    db: DbDep,
    scheme: str | None = None,
    owner: str | None = None,
    primary: bool = True,
    domain: str | None = None,
    families: str | None = None,
) -> Response:
    rows, _, _consensus = await _analysis_rows(
        MetaRepository(db), scheme, owner, primary, domain, _split_families(families)
    )
    content = await asyncio.to_thread(_forest_png, rows)
    return Response(
        content=content,
        media_type="image/png",
        headers={"Content-Disposition": 'inline; filename="forest.png"'},
    )


@router.post("/analysis/multiverse", response_model=dict)
async def analysis_multiverse(db: DbDep, body: MultiverseRequest) -> dict:
    """Enumerate the specification grid over the derived effects.

    The request's ``primary`` flag is intentionally ignored: the grid itself
    crosses primary-only vs. all effects, so the base rows must stay unfiltered.
    """
    rows, _, _consensus = await _analysis_rows(
        MetaRepository(db), body.scheme, body.owner, False, body.domain, body.families
    )
    return await asyncio.to_thread(
        meta_multiverse.multiverse, rows, max_specs=body.max_specs
    )


@router.get("/analysis/funnel.png")
async def analysis_funnel_png(
    db: DbDep,
    scheme: str | None = None,
    owner: str | None = None,
    primary: bool = True,
    domain: str | None = None,
    families: str | None = None,
) -> Response:
    rows, _, _consensus = await _analysis_rows(
        MetaRepository(db), scheme, owner, primary, domain, _split_families(families)
    )
    content = await asyncio.to_thread(_funnel_png, rows)
    return Response(
        content=content,
        media_type="image/png",
        headers={"Content-Disposition": 'inline; filename="funnel.png"'},
    )


@router.get("/analysis/spec-curve.png")
async def analysis_spec_curve_png(
    db: DbDep,
    scheme: str | None = None,
    owner: str | None = None,
    primary: bool = True,
    domain: str | None = None,
    families: str | None = None,
) -> Response:
    # ``primary`` is accepted for API symmetry; the grid always carries both
    # primary and all-effect specifications.
    rows, _, _consensus = await _analysis_rows(
        MetaRepository(db), scheme, owner, False, domain, _split_families(families)
    )
    content = await asyncio.to_thread(_spec_curve_png, rows)
    return Response(
        content=content,
        media_type="image/png",
        headers={"Content-Disposition": 'inline; filename="spec-curve.png"'},
    )


@router.get("/analysis/bayes.png")
async def analysis_bayes_png(
    db: DbDep,
    scheme: str | None = None,
    owner: str | None = None,
    primary: bool = True,
    domain: str | None = None,
    families: str | None = None,
) -> Response:
    rows, _, _consensus = await _analysis_rows(
        MetaRepository(db), scheme, owner, primary, domain, _split_families(families)
    )
    content = await asyncio.to_thread(_bayes_png, rows)
    return Response(
        content=content,
        media_type="image/png",
        headers={"Content-Disposition": 'inline; filename="bayes.png"'},
    )


@router.get("/prisma", response_model=dict)
async def meta_prisma_counts(db: DbDep) -> dict:
    return await meta_prisma.build_prisma(db)


@router.get("/prisma.png")
async def meta_prisma_png(db: DbDep) -> Response:
    counts = await meta_prisma.build_prisma(db)
    content = await asyncio.to_thread(meta_figures.prisma_png, counts)
    return Response(
        content=content,
        media_type="image/png",
        headers={"Content-Disposition": 'inline; filename="prisma.png"'},
    )


@router.get("/summary", response_model=dict)
async def meta_categorical_summary(db: DbDep, scheme: str | None = None) -> dict:
    repo = MetaRepository(db)
    extractions = await repo.list_extractions(include_dv_metrics=False)
    scheme_name = scheme or next((e.scheme for e in extractions if e.scheme), None)
    codebook = await _codebook_for_scheme(repo, scheme_name)
    return await asyncio.to_thread(meta_summary.build_summary, extractions, codebook)


@router.get("/audit", response_model=dict)
async def meta_variable_audit(db: DbDep, scheme: str | None = None) -> dict:
    """Extraction-variable coverage and role-integrity audit (see ``meta_audit``)."""
    repo = MetaRepository(db)
    extractions = await repo.list_extractions(include_dv_metrics=False)
    scheme_name = scheme or next((e.scheme for e in extractions if e.scheme), None)
    codebook = await _codebook_for_scheme(repo, scheme_name)
    return await asyncio.to_thread(meta_audit.variable_audit, extractions, codebook)


@router.post("/report")
async def meta_report_file(db: DbDep, body: ReportRequest) -> Response:
    context = await meta_report.build_report(
        db,
        title=body.title,
        scheme=body.scheme,
        primary=body.primary,
        owner=body.owner,
    )
    fmt = (body.format or "docx").strip().lower()
    if fmt == "md":
        content = await asyncio.to_thread(meta_report.render_markdown, context)
        payload = content.encode("utf-8")
        media_type = "text/markdown; charset=utf-8"
        filename = "meta_report.md"
    elif fmt == "docx":
        payload = await asyncio.to_thread(meta_report.render_docx_bytes, context)
        media_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        filename = "meta_report.docx"
    elif fmt == "pptx":
        payload = await asyncio.to_thread(meta_report.render_pptx_bytes, context)
        media_type = (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
        filename = "meta_report.pptx"
    else:
        raise HTTPException(status_code=422, detail="format must be 'md', 'docx' or 'pptx'")
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── scheme clone / export / import ───────────────────────────────────────

@router.post("/schemes/{scheme_id}/clone", response_model=dict, status_code=201)
async def clone_scheme(scheme_id: int, db: DbDep, body: SchemeClone) -> dict:
    repo = MetaRepository(db)
    source = await repo.get_scheme(scheme_id=scheme_id)
    if source is None:
        raise HTTPException(status_code=404, detail="scheme not found")
    if await repo.get_scheme(name=body.name) is not None:
        raise HTTPException(status_code=409, detail=f"scheme '{body.name}' already exists")
    scheme = await repo.add_scheme(
        name=body.name,
        label=body.label or source.label,
        description=source.description,
        prescreen_prompt=source.prescreen_prompt,
        coding_prompt=source.coding_prompt,
        codebook=source.codebook,
    )
    return {"ok": True, "id": scheme.id, "name": scheme.name, "cloned_from": source.name}


@router.get("/schemes/{scheme_id}/export")
async def export_scheme(scheme_id: int, db: DbDep) -> Response:
    source = await MetaRepository(db).get_scheme(scheme_id=scheme_id)
    if source is None:
        raise HTTPException(status_code=404, detail="scheme not found")
    codebook: Any = None
    if source.codebook:
        try:
            codebook = json.loads(source.codebook)
        except ValueError:
            codebook = None
    payload = {
        "name": source.name,
        "label": source.label,
        "description": source.description,
        "prescreen_prompt": source.prescreen_prompt,
        "coding_prompt": source.coding_prompt,
        "codebook": codebook,
    }
    filename = f"{source.name}.meta-scheme.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/schemes/import", response_model=dict, status_code=201)
async def import_scheme(db: DbDep, body: SchemeImport) -> dict:
    repo = MetaRepository(db)
    codebook_json = json.dumps(body.codebook) if body.codebook is not None else None
    existing = await repo.get_scheme(name=body.name)
    if existing is not None:
        if not body.overwrite:
            raise HTTPException(
                status_code=409, detail=f"scheme '{body.name}' already exists"
            )
        updated = await repo.update_scheme(
            existing.id,
            label=body.label,
            description=body.description,
            prescreen_prompt=body.prescreen_prompt,
            coding_prompt=body.coding_prompt,
            codebook=codebook_json,
        )
        return {
            "ok": True,
            "id": updated.id if updated else existing.id,
            "name": body.name,
            "overwritten": True,
        }
    scheme = await repo.add_scheme(
        name=body.name,
        label=body.label,
        description=body.description,
        prescreen_prompt=body.prescreen_prompt,
        coding_prompt=body.coding_prompt,
        codebook=codebook_json,
    )
    return {"ok": True, "id": scheme.id, "name": scheme.name, "overwritten": False}


# ── CodingStudio folder import ───────────────────────────────────────────

@router.post("/codingstudio/preview", response_model=dict)
async def codingstudio_preview(svc: OpenProjectDep, body: CodingStudioPreviewRequest) -> dict:
    """Describe a CodingStudio project folder (read-only, nothing imported).

    Always answers 200: a missing folder is reported through ``exists`` /
    ``errors`` so the dialog can render it (the import then refuses 422).
    """
    from qualcoder_api.services.meta_codingstudio import preview_codingstudio

    return await asyncio.to_thread(preview_codingstudio, body.folder)


@router.post("/codingstudio/import", response_model=dict)
async def codingstudio_import(svc: OpenProjectDep, body: CodingStudioImportRequest) -> dict:
    """Import hits, screening, the scheme, extractions and PDFs from a folder.

    Idempotent: re-running the import never duplicates hits, screening rows,
    extractions or linked PDFs. 422 when the folder carries neither a
    ``master_dataset.xlsx`` nor ``Extraction/*.json``.
    """
    from qualcoder_api.services.meta_codingstudio import import_codingstudio

    if svc.session_factory is None or not svc.project_path:
        raise HTTPException(status_code=409, detail="no project is open")
    try:
        return await import_codingstudio(
            svc.session_factory,
            svc.project_path,
            body.folder,
            owner=body.owner,
            run_id=body.run_id,
            import_hits=body.import_hits,
            import_screening=body.import_screening,
            import_extractions=body.import_extractions,
            link_pdfs=body.link_pdfs,
            scheme_name=body.scheme_name,
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


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
