"""Interchange import API — RQDA, Taguette, Transana, NVivo, RIS, Survey CSV, XLSX, SPSS uploads."""

from __future__ import annotations

import asyncio
import csv
import io
import os
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from qualcoder_api.api.v1.deps import DbDep, ServiceDep
from qualcoder_api.interchange import importers

router = APIRouter(prefix="/interchange/import", tags=["interchange"])

#: Kinds the auto endpoint accepts as an explicit ``force_kind`` override
#: (file-based importers only — Zotero reads a local API, not an upload).
FORCEABLE_KINDS = frozenset(
    {"refi", "rqda", "taguette", "transana", "nvivo", "ris", "survey", "xlsx", "sav", "codebook", "merge"}
)


def _detect_kind(tmp: str) -> str:
    """Sniff an interchange upload the same way ``import_auto`` routes it.

    NVivo bundles are zips whose XML carries the NVivo marker; they must be
    recognized before the generic zip/xlsx/merge sniffing. Everything else
    delegates to ``importers.detect_import_kind`` (raises ``ValueError`` for
    unsupported files).
    """
    with open(tmp, "rb") as fh:
        head = fh.read(4)
    if head.startswith(b"PK\x03\x04"):
        import zipfile

        from qualcoder_api.interchange.nvivo_import import archive_has_nvivo_marker

        try:
            with zipfile.ZipFile(tmp) as archive:
                if archive_has_nvivo_marker(archive):
                    return "nvivo"
        except zipfile.BadZipFile:
            pass
    return importers.detect_import_kind(tmp)


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
    force_kind: str | None = Form(None),
) -> dict:
    """Import an interchange file with automatic format detection.

    Detects REFI-QDA (.qdp/.qdc XML), RQDA, Taguette and Transana
    databases, NVivo (.nvpx) projects, RIS bibliographies, survey CSVs,
    Excel .xlsx workbooks, SPSS .sav data files, plain-text codebooks and
    zipped .qda projects from the file content. ``qualitative_headers``
    only applies to survey-style imports (CSV/XLSX/SAV). ``force_kind``
    skips the content sniffing and routes the file to the named importer
    (used by the import preview manager's format override).
    """
    if svc.project_path == "" or svc.session_factory is None:
        raise HTTPException(status_code=409, detail="no project is open")
    tmp = await _save_upload(file, svc, "import")
    try:
        try:
            if force_kind:
                kind = force_kind.strip().lower()
                if kind not in FORCEABLE_KINDS:
                    raise HTTPException(
                        status_code=422, detail=f"unsupported format override: {force_kind}"
                    )
            else:
                kind = _detect_kind(tmp)
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
            if kind in ("survey", "xlsx", "sav"):
                headers = [
                    h.strip()
                    for h in (qualitative_headers or "").split(",")
                    if h.strip()
                ]
                importer_fn = {
                    "survey": importers.import_survey,
                    "xlsx": importers.import_xlsx,
                    "sav": importers.import_sav,
                }[kind]

                async def _importer(session_factory, path: str, codername: str) -> dict:
                    return await importer_fn(
                        session_factory, path, codername, qualitative_headers=headers
                    )

            elif kind == "codebook":
                _importer = codebook.import_codebook
            elif kind == "nvivo":
                from qualcoder_api.interchange.nvivo_import import import_nvivo

                _importer = import_nvivo
            else:
                _importer = {
                    "rqda": importers.import_rqda,
                    "taguette": importers.import_taguette,
                    "transana": importers.import_transana,
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


@router.post("/preview")
async def preview_interchange(
    file: Annotated[UploadFile, File()],
    force_kind: str | None = Form(None),
) -> dict:
    """Sniff an interchange upload and return a lightweight content preview.

    Returns the detected format plus, where cheap to extract, a sample of
    the parsed content: ``columns`` + ``rows_sample`` (first ~15 rows) and
    the detected qualitative (free-text) columns for survey CSVs / Excel
    workbooks / SPSS files, or ``lines`` for plain-text codebooks. Other
    formats (REFI-QDA, RQDA, NVivo, archives…) return the format only —
    the UI falls back to the per-format help text. ``force_kind`` lets the
    caller re-interpret the file as another format (the manager's override
    select). Read-only: no project is required and nothing is imported.
    """
    fd, tmp = tempfile.mkstemp(
        prefix="qc_preview_", suffix=os.path.splitext(file.filename or "")[1]
    )
    os.close(fd)
    try:
        with open(tmp, "wb") as out:  # noqa: ASYNC230 - small local temp write
            while chunk := await file.read(1 << 20):
                out.write(chunk)
        try:
            if force_kind:
                kind = force_kind.strip().lower()
                if kind not in FORCEABLE_KINDS:
                    raise HTTPException(
                        status_code=422, detail=f"unsupported format override: {force_kind}"
                    )
            else:
                kind = _detect_kind(tmp)
            preview = await _preview_for_kind(tmp, kind)
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err)) from err
        return {"format": kind, **preview}
    finally:
        os.remove(tmp)


def _looks_numeric(value: str) -> bool:
    """A cell counts as numeric when it parses as a float (empty = neutral)."""
    stripped = value.strip()
    if not stripped:
        return True
    try:
        float(stripped)
        return True
    except ValueError:
        return False


async def _preview_tabular(path: str, kind: str) -> dict:
    """Sample columns + first rows of a survey CSV / Excel workbook / SPSS file.

    Returns ``{"columns", "rows_sample", "qual_columns", "lines"}`` where
    ``qual_columns`` are the string-ish columns (excluding the case-name
    column) the import manager prefills into the qualitative-columns input.
    """
    columns: list[str] = []
    sample: list[list[str]] = []
    qual: list[str] = []
    if kind == "survey":
        raw = Path(path).read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("utf-8")
        try:
            rows = [
                row for row in csv.reader(io.StringIO(text)) if any(cell.strip() for cell in row)
            ]
            if rows and all(len(row) == 1 for row in rows):
                rows = [
                    row
                    for row in csv.reader(io.StringIO(text), delimiter=";")
                    if any(cell.strip() for cell in row)
                ]
        except csv.Error as err:
            raise ValueError(f"Invalid survey CSV: {err}") from err
        if not rows:
            raise ValueError("Survey CSV is empty")
        columns = [h.strip() for h in rows[0]]
        sample = rows[1:16]
    elif kind == "xlsx":
        try:
            sheets = await asyncio.to_thread(importers._read_xlsx_sheets, path)
        except Exception as err:  # openpyxl raises on malformed workbooks
            raise ValueError(f"Invalid XLSX file: {err}") from err
        sheet_rows = next(
            (rows for rows in sheets.values() if importers._sheet_looks_like_survey(rows)),
            None,
        )
        if sheet_rows is None:
            return {"columns": None, "rows_sample": None, "qual_columns": None, "lines": None}
        columns = sheet_rows[0]
        sample = sheet_rows[1:16]
    else:  # sav
        try:
            import pyreadstat

            df, meta = await asyncio.to_thread(lambda: pyreadstat.read_sav(path, row_limit=16))
        except Exception as err:  # pyreadstat raises ReadstatError on unreadable files
            raise ValueError(f"Invalid SPSS .sav file: {err}") from err
        columns = list(meta.column_names)
        if columns:
            var_types = getattr(meta, "readstat_variable_types", {}) or {}
            qual = [
                col for col in columns[1:] if var_types.get(col) not in ("double", "integer")
            ]
            sample = [
                [importers._sav_cell(record[col]) for col in columns] for _, record in df.iterrows()
            ]
        return {"columns": columns, "rows_sample": sample, "qual_columns": qual, "lines": None}

    for idx, col in enumerate(columns):
        if idx == 0:  # first column is the case name — not a qualitative field
            continue
        values = [row[idx] for row in sample if idx < len(row)]
        if any(not _looks_numeric(v) for v in values):
            qual.append(col)
    return {"columns": columns, "rows_sample": sample, "qual_columns": qual, "lines": None}


async def _preview_for_kind(path: str, kind: str) -> dict:
    """Build the preview payload for a detected kind (no preview = format only)."""
    if kind in ("survey", "xlsx", "sav"):
        return await _preview_tabular(path, kind)
    if kind == "codebook":
        text = Path(path).read_bytes().decode("utf-8", errors="replace")
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        return {"columns": None, "rows_sample": None, "qual_columns": None, "lines": lines[:15]}
    return {"columns": None, "rows_sample": None, "qual_columns": None, "lines": None}


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


@router.post("/transana")
async def import_transana(
    svc: ServiceDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    codername: str | None = Form(None),
) -> dict:
    """Import a Transana ``.tprd`` SQLite database.

    Transcripts become text sources, media/episode files become audio/video
    sources (registered when the file exists next to the database),
    keywords become codes and keyword assignments become text/AV codings.
    """
    return await _run_import(svc, file, codername, importers.import_transana, "transana")


@router.post("/nvivo")
async def import_nvivo(
    svc: ServiceDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    codername: str | None = Form(None),
) -> dict:
    """Import an NVivo .nvpx project (a ZIP of project XML).

    Best-effort: documents with text content become text sources, nodes
    become codes (node folders become categories), and codings with
    parseable character positions become text codings — anything opaque is
    skipped and counted instead of failing the import.
    """
    from qualcoder_api.interchange.nvivo_import import import_nvivo

    return await _run_import(svc, file, codername, import_nvivo, "nvivo")


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


@router.post("/xlsx")
async def import_xlsx(
    svc: ServiceDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    codername: str | None = Form(None),
    qualitative_headers: str | None = Form(None),
) -> dict:
    """Import an Excel .xlsx workbook.

    Sheets with a multi-column header row are imported like survey CSVs
    (one row = one case, columns = case attributes); any other sheet
    becomes one text source per sheet (``<workbook>-<sheet>.txt``).
    ``qualitative_headers`` is a comma-separated list of column names whose
    free text is imported as one text file per row.
    """
    headers = [
        h.strip()
        for h in (qualitative_headers or "").split(",")
        if h.strip()
    ]

    async def _import(session_factory, path: str, codername: str) -> dict:
        return await importers.import_xlsx(
            session_factory, path, codername, qualitative_headers=headers
        )

    return await _run_import(svc, file, codername, _import, "xlsx")


@router.post("/sav")
async def import_sav(
    svc: ServiceDep,
    db: DbDep,
    file: Annotated[UploadFile, File()],
    codername: str | None = Form(None),
    qualitative_headers: str | None = Form(None),
) -> dict:
    """Import an SPSS .sav data file.

    Every row becomes a case named after the first variable (or
    ``Case <n>``); the remaining variables become case attribute types.
    ``qualitative_headers`` is a comma-separated list of string variable
    names whose free text is imported as one text file per row (linked to
    the case and coded with a code named after the variable).
    """
    headers = [
        h.strip()
        for h in (qualitative_headers or "").split(",")
        if h.strip()
    ]

    async def _import(session_factory, path: str, codername: str) -> dict:
        return await importers.import_sav(
            session_factory, path, codername, qualitative_headers=headers
        )

    return await _run_import(svc, file, codername, _import, "sav")


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
