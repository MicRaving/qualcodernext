"""Interchange import API — RQDA, Taguette, Transana, NVivo, RIS, Survey CSV, XLSX, SPSS uploads."""

from __future__ import annotations

import asyncio
import csv
import io
import os
import sqlite3
import tempfile
import xml.etree.ElementTree as etree
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
    workbooks / SPSS files, or ``lines`` for plain-text codebooks. Every
    format also gets a ``destination`` summary — what the import would
    create (``{"kind", "counts", "note"}`` with ``counts`` keyed by
    codes/categories/sources/codings/cases/attributes/references/files)
    computed from a real parse; ``null`` for formats that cannot be counted
    cheaply (a zipped ``.qda`` merge). Other formats (REFI-QDA, RQDA,
    NVivo, archives…) return the format only — the UI falls back to the
    per-format help text. ``force_kind`` lets the caller re-interpret the
    file as another format (the manager's override select). Read-only: no
    project is required and nothing is imported.
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
    column) the import manager prefills into the qualitative-columns input,
    plus a ``destination`` summary of what the import would create (one
    case per data row, one attribute type per non-qualitative column, one
    text file per row per qualitative column, one coding per such file).
    """
    columns: list[str] = []
    sample: list[list[str]] = []
    qual: list[str] = []
    cases = 0
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
        cases = sum(1 for row in rows[1:] if row and row[0].strip())
    elif kind == "xlsx":
        try:
            sheets = await asyncio.to_thread(importers._read_xlsx_sheets, path)
        except Exception as err:  # openpyxl raises on malformed workbooks
            raise ValueError(f"Invalid XLSX file: {err}") from err
        survey_sheets = [
            rows for rows in sheets.values() if importers._sheet_looks_like_survey(rows)
        ]
        if not survey_sheets:
            counts = _empty_destination_counts()
            counts["sources"] = len(sheets)
            note = (
                "no multi-column sheet — every sheet becomes one text source"
                if sheets else None
            )
            return {
                "columns": None, "rows_sample": None, "qual_columns": None,
                "lines": None, "destination": _destination(kind, counts, note),
            }
        sheet_rows = survey_sheets[0]
        columns = sheet_rows[0]
        sample = sheet_rows[1:16]
        cases = sum(
            1 for rows in survey_sheets for row in rows[1:] if row and row[0].strip()
        )
    else:  # sav
        try:
            import pyreadstat

            def _read_sav():
                sample_df, sample_meta = pyreadstat.read_sav(path, row_limit=16)
                total = getattr(
                    pyreadstat.read_sav(path, metadataonly=True)[1], "number_rows", None
                )
                return sample_df, sample_meta, int(total) if total else len(sample_df)

            df, meta, total_rows = await asyncio.to_thread(_read_sav)
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
            cases = total_rows
        counts = _empty_destination_counts()
        counts["cases"] = cases
        counts["attributes"] = max(0, len(columns) - 1 - len(qual))
        counts["files"] = len(qual)
        counts["codings"] = cases * len(qual)
        return {
            "columns": columns, "rows_sample": sample, "qual_columns": qual,
            "lines": None, "destination": _destination(kind, counts),
        }

    for idx, col in enumerate(columns):
        if idx == 0:  # first column is the case name — not a qualitative field
            continue
        values = [row[idx] for row in sample if idx < len(row)]
        if any(not _looks_numeric(v) for v in values):
            qual.append(col)
    counts = _empty_destination_counts()
    counts["cases"] = cases
    counts["attributes"] = max(0, len(columns) - 1 - len(qual))
    counts["files"] = len(qual)
    counts["codings"] = cases * len(qual)
    return {
        "columns": columns, "rows_sample": sample, "qual_columns": qual,
        "lines": None, "destination": _destination(kind, counts),
    }


#: Keys of the ``destination.counts`` summary — always present, 0 when n/a.
DESTINATION_KEYS = (
    "codes", "categories", "sources", "codings", "cases",
    "attributes", "references", "files",
)


def _empty_destination_counts() -> dict[str, int]:
    """A destination counts dict with every key zeroed."""
    return dict.fromkeys(DESTINATION_KEYS, 0)


def _destination(kind: str, counts: dict[str, int], note: str | None = None) -> dict:
    """Structured "will create" summary for the preview response.

    ``counts`` holds the entity counts the import would create (best-effort
    for the interchange formats), ``note`` a short caveat when part of the
    file cannot be counted exactly.
    """
    return {"kind": kind, "counts": counts, "note": note}


def _table_row_count(conn: sqlite3.Connection, table: str) -> int:
    """Row count of ``table`` (0 when the table is absent or unreadable)."""
    try:
        row = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def _distinct_column_values(
    conn: sqlite3.Connection, table: str, *candidates: str
) -> set[str]:
    """Distinct non-null values of the first present column among ``candidates``."""
    for column in candidates:
        try:
            return {
                str(row[0])
                for row in conn.execute(f"SELECT DISTINCT {column} FROM {table}")
                if row[0]
            }
        except sqlite3.Error:
            continue
    return set()


def _count_sqlite_destination(path: str, kind: str) -> tuple[dict[str, int], str | None]:
    """Best-effort entity counts for RQDA / Taguette / Transana SQLite databases.

    Reads the source database read-only and counts the rows of the tables
    the importers map to project entities. Anything the importer would skip
    (missing media files, unresolvable references) is not subtracted — the
    counts are an upper bound, noted where it matters.
    """
    counts = _empty_destination_counts()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return counts, "database could not be read"
    try:
        tables = {
            row[0].lower()
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if kind == "rqda":
            if "source" in tables:
                counts["sources"] += _table_row_count(conn, "source")
            elif "file" in tables:
                counts["sources"] += _table_row_count(conn, "file")
            if "codecat" in tables:
                counts["categories"] += _table_row_count(conn, "codecat")
            if "freecode" in tables:
                counts["codes"] += _table_row_count(conn, "freecode")
            for table in ("coding", "coding2"):
                if table in tables:
                    counts["codings"] += _table_row_count(conn, table)
            for table in ("casename", "cases"):
                if table in tables:
                    counts["cases"] += _table_row_count(conn, table)
            names = _distinct_column_values(conn, "attributes", "name", "variable")
            names |= _distinct_column_values(conn, "caseattr", "variable", "name")
            names |= _distinct_column_values(conn, "fileattr", "variable", "name")
            counts["attributes"] = len(names)
        elif kind == "taguette":
            if "documents" in tables:
                counts["sources"] += _table_row_count(conn, "documents")
            if "tags" in tables:
                counts["codes"] += _table_row_count(conn, "tags")
            if "highlights" in tables:
                counts["codings"] += _table_row_count(conn, "highlights")
        elif kind == "transana":
            for table in ("transcripts", "episodetranscripts"):
                if table in tables:
                    counts["sources"] += _table_row_count(conn, table)
            media = sum(
                _table_row_count(conn, table)
                for table in ("mediafiles", "media")
                if table in tables
            )
            if "keywordtypes" in tables:
                counts["categories"] += _table_row_count(conn, "keywordtypes")
            if "keywords" in tables:
                counts["codes"] += _table_row_count(conn, "keywords")
            for table in (
                "transcriptkeywordassignments",
                "keywordassignments",
                "episodekeywordassignments",
            ):
                if table in tables:
                    counts["codings"] += _table_row_count(conn, table)
            if media:
                return counts, (
                    f"{media} media/episode files are imported only when the media "
                    "files exist next to the database (not counted)"
                )
    finally:
        conn.close()
    return counts, None


def _count_refi_destination(path: str) -> tuple[dict[str, int], str | None]:
    """Count the code/category/source/coding/case elements of a REFI-QDA XML."""
    from qualcoder_api.interchange.refi import local_name

    counts = _empty_destination_counts()
    try:
        root = etree.parse(path).getroot()
    except etree.ParseError as err:
        return counts, f"XML could not be parsed ({err})"
    source_tags = {"TextSource", "AudioSource", "VideoSource", "PDFSource"}
    for elem in root.iter():
        name = local_name(elem.tag)
        if name == "Code":
            counts["codes"] += 1
        elif name == "Category":
            counts["categories"] += 1
        elif name in source_tags:
            counts["sources"] += 1
        elif name == "CodedText":
            counts["codings"] += 1
        elif name == "Case":
            counts["cases"] += 1
    return counts, None


def _count_nvivo_destination(path: str) -> tuple[dict[str, int], str | None]:
    """Count documents/nodes/codings of an NVivo .nvpx ZIP (best-effort)."""
    from qualcoder_api.interchange.nvivo_import import (
        _NON_TEXT_DOC_TYPES,
        _attr,
        _build_node_tree,
        _collect_xml,
        _name_of,
        _parse_positions,
    )

    counts = _empty_destination_counts()
    import zipfile

    try:
        with zipfile.ZipFile(path) as archive:
            documents, node_elems, coding_elems = _collect_xml(archive)
    except zipfile.BadZipFile:
        return counts, "archive could not be read"
    for elem in documents:
        if not _name_of(elem) or (_attr(elem, "type") or "").lower() in _NON_TEXT_DOC_TYPES:
            continue
        counts["sources"] += 1
    coded_guids = {
        guid
        for elem in coding_elems
        if (guid := _attr(elem, "node", "nodeID", "nodeGuid"))
    }
    for rec in _build_node_tree(node_elems):
        if not rec.name:
            continue
        if rec.children:
            counts["categories"] += 1  # node folders become categories
            if rec.guid is not None and rec.guid in coded_guids:
                counts["codes"] += 1  # a coded folder is imported as both
        else:
            counts["codes"] += 1
    skipped = 0
    for elem in coding_elems:
        if not (
            _attr(elem, "source", "sourceID", "sourceGuid")
            and _attr(elem, "node", "nodeID", "nodeGuid")
        ):
            skipped += 1
            continue
        positions = _parse_positions(elem)
        counts["codings"] += len(positions)
        if not positions:
            skipped += 1
    note = f"{skipped} codings without parseable positions are skipped" if skipped else None
    return counts, note


def _count_ris_destination(path: str) -> tuple[dict[str, int], str | None]:
    """Count the records of a RIS bibliography with rispy."""
    import rispy

    counts = _empty_destination_counts()
    try:
        with open(path, encoding="utf-8", errors="surrogateescape") as fh:
            counts["references"] = len(rispy.load(fh))
    except (OSError, ValueError) as err:
        return counts, f"reference file could not be parsed ({err})"
    return counts, None


def _count_codebook_destination(path: str) -> tuple[dict[str, int], str | None]:
    """Count codes and distinct category paths of a plain-text codebook.

    Mirrors the codebook importer: ``category>>subcategory>>code`` lines,
    one category per distinct path prefix, one code per non-empty last part
    (a tab/comma-separated second column is the memo, not counted).
    """
    raw = Path(path).read_bytes()
    text_data = raw.decode("utf-8-sig", errors="surrogateescape")
    delimiter = "," if path.lower().endswith(".csv") else "\t"
    rows = [
        row for row in csv.reader(io.StringIO(text_data), delimiter=delimiter) if row
    ]
    counts = _empty_destination_counts()
    category_paths: set[str] = set()
    for row in rows:
        if not row or not row[0].strip():
            continue
        parts = [part.strip() for part in row[0].split(">>")]
        if len(parts) >= 2 and parts[0]:
            for i in range(1, len(parts)):
                prefix = ">>".join(parts[:i])
                if parts[i - 1] == "" or prefix in category_paths:
                    continue
                category_paths.add(prefix)
        if parts[-1]:
            counts["codes"] += 1
    counts["categories"] = len(category_paths)
    return counts, None


def _destination_counts_sync(path: str, kind: str) -> tuple[dict[str, int], str | None]:
    """Best-effort entity counts for one non-tabular interchange upload."""
    if kind == "refi":
        return _count_refi_destination(path)
    if kind == "nvivo":
        return _count_nvivo_destination(path)
    if kind in ("rqda", "taguette", "transana"):
        return _count_sqlite_destination(path, kind)
    if kind == "ris":
        return _count_ris_destination(path)
    if kind == "codebook":
        return _count_codebook_destination(path)
    return _empty_destination_counts(), None


async def _destination_for_kind(path: str, kind: str) -> dict | None:
    """``destination`` summary for a previewed kind (``None`` = uncountable).

    Merge archives (zipped ``.qda`` projects) cannot be counted without
    extracting them — the UI falls back to the per-format note instead.
    """
    if kind == "merge":
        return None
    counts, note = await asyncio.to_thread(_destination_counts_sync, path, kind)
    return _destination(kind, counts, note)


async def _preview_for_kind(path: str, kind: str) -> dict:
    """Build the preview payload for a detected kind (no preview = format only)."""
    if kind in ("survey", "xlsx", "sav"):
        return await _preview_tabular(path, kind)
    if kind == "codebook":
        text = Path(path).read_bytes().decode("utf-8", errors="replace")
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        return {
            "columns": None, "rows_sample": None, "qual_columns": None,
            "lines": lines[:15],
            "destination": await _destination_for_kind(path, kind),
        }
    return {
        "columns": None, "rows_sample": None, "qual_columns": None, "lines": None,
        "destination": await _destination_for_kind(path, kind),
    }


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
