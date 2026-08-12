"""Interchange import API — RQDA, Taguette, RIS and Survey CSV uploads."""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from qualcoder_api.api.v1.deps import DbDep, ServiceDep
from qualcoder_api.interchange import importers

router = APIRouter(prefix="/interchange/import", tags=["interchange"])


async def _run_import(svc, file: UploadFile, codername: str | None, importer, kind: str) -> dict:
    """Save the upload next to the project, run ``importer``, delete the temp file."""
    if svc.project_path == "":
        raise HTTPException(status_code=409, detail="no project is open")
    tmp = svc.project_path + "/_import_" + (file.filename or "import")
    with open(tmp, "wb") as out:  # noqa: ASYNC230 - small local temp write
        while chunk := await file.read(1 << 20):
            out.write(chunk)
    try:
        from qualcoder_api.services import audit
        from qualcoder_api.services.user_settings import get_codername, resolve_owner

        result = await importer(svc.session_factory, tmp, resolve_owner(codername))
        async with svc.session_factory() as session:
            await audit.record(
                session, user=get_codername(), action="interchange.import",
                entity=kind, detail=result if isinstance(result, dict) else {},
            )
        return result
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    finally:
        os.remove(tmp)


async def _merge_archive(svc, archive_path: str, codername: str | None) -> dict:
    """Merge a zipped ``.qda`` project (``data.qda`` + media folders)."""
    import asyncio
    import zipfile

    if svc.project_path == "" or svc.session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    extracted = archive_path + "_dir"
    try:
        try:
            # Zip extraction is CPU/IO heavy — keep it off the event loop.
            await asyncio.to_thread(
                lambda: zipfile.ZipFile(archive_path).extractall(extracted)
            )
        except zipfile.BadZipFile as err:
            raise HTTPException(status_code=422, detail="not a zip archive") from err
        candidates = [extracted]
        for entry in os.listdir(extracted):
            full = os.path.join(extracted, entry)
            if os.path.isdir(full) and os.path.exists(os.path.join(full, "data.qda")):
                candidates.append(full)
        source_dir = None
        for candidate in candidates:
            if os.path.exists(os.path.join(candidate, "data.qda")):
                source_dir = candidate
                break
        if source_dir is None:
            raise HTTPException(status_code=422, detail="no data.qda found in the archive")
        from qualcoder_api.services import audit, merge_projects
        from qualcoder_api.services.user_settings import get_codername, resolve_owner

        result = await merge_projects.merge_projects(
            svc.session_factory, svc.project_path, source_dir, resolve_owner(codername)
        )
        async with svc.session_factory() as session:
            await audit.record(
                session, user=get_codername(), action="interchange.import",
                entity="merge", detail={"result": str(result.get("message", ""))[:400]},
            )
        return result
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    finally:
        import asyncio
        import shutil

        await asyncio.to_thread(shutil.rmtree, extracted, True)


async def _save_upload(file: UploadFile, svc, prefix: str) -> str:
    """Write the upload next to the project; return the temp path."""
    if svc.project_path == "":
        raise HTTPException(status_code=409, detail="no project is open")
    tmp = svc.project_path + "/_" + prefix + "_" + (file.filename or "import")
    with open(tmp, "wb") as out:  # noqa: ASYNC230 - small local temp write
        while chunk := await file.read(1 << 20):
            out.write(chunk)
    return tmp


@router.post("/auto")
async def import_auto(
    svc: ServiceDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    codername: str | None = Form(None),
    qualitative_headers: str | None = Form(None),
) -> dict:
    """Import an interchange file with automatic format detection.

    Detects REFI-QDA (.qdp/.qdc XML), RQDA and Taguette databases,
    RIS bibliographies, survey CSVs, plain-text codebooks and zipped
    .qda projects from the file content. ``qualitative_headers`` only
    applies to survey CSVs.
    """
    if svc.project_path == "" or svc.session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    tmp = await _save_upload(file, svc, "import")
    try:
        try:
            kind = importers.detect_import_kind(tmp)
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err)) from err

        from qualcoder_api.services import audit, codebook
        from qualcoder_api.services.user_settings import get_codername, resolve_owner

        if kind == "merge":
            return await _merge_archive(svc, tmp, codername)

        if kind == "refi":
            from qualcoder_api.interchange.refi import import_refi_qdp

            with open(tmp, "rb") as fh:  # noqa: ASYNC230 - small local temp read
                data = fh.read()
            result = await import_refi_qdp(svc.session_factory, data, resolve_owner(codername))
        else:
            _importer: Any
            if kind == "survey":
                headers = [
                    h.strip()
                    for h in (qualitative_headers or "").split(",")
                    if h.strip()
                ]

                async def _importer(session_factory, path: str, codername: str) -> dict:
                    return await importers.import_survey(
                        session_factory, path, codername, qualitative_headers=headers
                    )

            elif kind == "codebook":
                _importer = codebook.import_codebook
            else:
                _importer = {
                    "rqda": importers.import_rqda,
                    "taguette": importers.import_taguette,
                    "ris": importers.import_ris,
                }[kind]
            result = await _importer(svc.session_factory, tmp, resolve_owner(codername))

        async with svc.session_factory() as session:
            await audit.record(
                session, user=get_codername(), action="interchange.import",
                entity=kind, detail=result if isinstance(result, dict) else {},
            )
        return result
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    finally:
        os.remove(tmp)


@router.post("/rqda")
async def import_rqda(
    svc: ServiceDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    codername: str | None = Form(None),
) -> dict:
    """Import an RQDA ``.rqda`` SQLite database."""
    return await _run_import(svc, file, codername, importers.import_rqda, "rqda")


@router.post("/taguette")
async def import_taguette(
    svc: ServiceDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    codername: str | None = Form(None),
) -> dict:
    """Import a Taguette ``.taguette.sqlite3`` database."""
    return await _run_import(svc, file, codername, importers.import_taguette, "taguette")


@router.post("/ris")
async def import_ris(
    svc: ServiceDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    codername: str | None = Form(None),
) -> dict:
    """Import a .ris bibliography file."""
    return await _run_import(svc, file, codername, importers.import_ris, "ris")


@router.post("/survey")
async def import_survey(
    svc: ServiceDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    codername: str | None = Form(None),
    qualitative_headers: str | None = Form(None),
) -> dict:
    """Import a survey CSV: one row = one case, columns = case attributes.

    ``qualitative_headers`` is a comma-separated list of column names whose
    free text is imported as one text file per row (linked to the case and
    coded with a code named after the column).
    """
    headers = [
        h.strip()
        for h in (qualitative_headers or "").split(",")
        if h.strip()
    ]

    async def _import(session_factory, path: str, codername: str) -> dict:
        return await importers.import_survey(
            session_factory, path, codername, qualitative_headers=headers
        )

    return await _run_import(svc, file, codername, _import, "survey")


@router.post("/codebook")
async def import_codebook(
    svc: ServiceDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    codername: str | None = Form(None),
) -> dict:
    """Import a plain-text codebook (``category>>subcategory>>code`` lines)."""
    from qualcoder_api.services import codebook

    return await _run_import(svc, file, codername, codebook.import_codebook, "codebook")


@router.post("/merge")
async def import_merge(
    svc: ServiceDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    codername: str | None = Form(None),
) -> dict:
    """Merge another ``.qda`` project archive into the open project.

    The upload must be a zip archive containing a ``data.qda`` database
    (and optionally the media folders) — i.e. a zipped ``.qda`` project.
    """
    if svc.project_path == "" or svc.session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    tmp = await _save_upload(file, svc, "merge")
    try:
        return await _merge_archive(svc, tmp, codername)
    finally:
        os.remove(tmp)


@router.post("/zotero")
async def import_zotero(
    svc: ServiceDep,
    db: DbDep,
    codername: str | None = Form(None),
) -> dict:
    """Import references from Zotero 7+'s local read-only API (localhost:23119)."""
    from qualcoder_api.services import references

    if svc.project_path == "" or svc.session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    try:
        result = await references.import_zotero(svc.session_factory)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    async with svc.session_factory() as session:
        from qualcoder_api.services import audit
        from qualcoder_api.services.user_settings import get_codername

        await audit.record(
            session, user=get_codername(), action="interchange.import",
            entity="zotero", detail={"references": result.get("references", 0)},
        )
    return result
