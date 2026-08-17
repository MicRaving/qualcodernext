"""Excel XLSX importer — import an Excel .xlsx workbook."""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.interchange.importers.base import (
    _existing_names,
)
from qualcoder_api.interchange.importers.survey import _import_survey_rows
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import (
    SourceRepository,
)


def _read_xlsx_sheets(xlsx_path: str) -> dict[str, list[list[str]]]:
    """Parse an XLSX workbook into ``{sheet title: rows}`` (string cells).

    Runs inside ``asyncio.to_thread`` — openpyxl is CPU/IO bound. Rows that
    are entirely empty are dropped; every cell is stripped to text.
    """
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    try:
        sheets: dict[str, list[list[str]]] = {}
        for ws in wb.worksheets:
            rows = []
            for row in ws.iter_rows(values_only=True):
                cells = ["" if value is None else str(value).strip() for value in row]
                if any(cells):
                    rows.append(cells)
            sheets[ws.title] = rows
        return sheets
    finally:
        wb.close()


def _sheet_looks_like_survey(rows: list[list[str]]) -> bool:
    """A sheet holds survey data when it has a header row plus data rows
    and the header spans at least two columns (single-column sheets are
    treated as free text)."""
    return len(rows) >= 2 and sum(1 for cell in rows[0] if cell) >= 2


async def import_xlsx(
    session_factory: async_sessionmaker,
    xlsx_path: str,
    codername: str,
    qualitative_headers: list[str] | None = None,
) -> dict:
    """Import an Excel ``.xlsx`` workbook.

    Every sheet whose first row reads as a multi-column header is imported
    with the shared survey logic (first column = case name, the rest case
    attributes, ``qualitative_headers`` columns become one text file per
    row). Any other sheet becomes a single text source per sheet
    (``<workbook>-<sheet>.txt``) with its rows rendered tab-separated.
    """
    try:
        sheets = await asyncio.to_thread(_read_xlsx_sheets, xlsx_path)
    except Exception as err:  # openpyxl raises InvalidFileException/BadZipFile/... on bad files
        raise ValueError(f"Invalid XLSX file: {err}") from err

    if not sheets:
        return {
            "ok": True, "message": "XLSX workbook is empty",
            "cases": 0, "attributes": 0, "qualitative_files": 0,
            "qualitative_codings": 0, "sources": 0,
        }

    counts: dict[str, int] = {
        "cases": 0, "attributes": 0, "qualitative_files": 0,
        "qualitative_codings": 0, "sources": 0,
    }
    # The API layer uploads under a ``_import_``/``_merge_`` temp name —
    # strip that prefix so the source name reflects the original file.
    stem = Path(xlsx_path).stem
    for prefix in ("_import_", "_merge_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    async with session_factory() as session:
        source_repo = SourceRepository(session)
        existing = await _existing_names(session, tables.source, "name")
        for sheet_name, rows in sheets.items():
            if _sheet_looks_like_survey(rows):
                partial = await _import_survey_rows(
                    session_factory, rows[0], rows[1:], codername,
                    qualitative_headers, str(Path(xlsx_path).parent),
                )
                for key in counts:
                    counts[key] += partial.get(key, 0)
            else:
                name = f"{stem}-{sheet_name}.txt"
                if name in existing:
                    continue
                fulltext = "\n".join("\t".join(row) for row in rows)
                await source_repo.add_source(
                    name=name, mediapath=None, fulltext=fulltext,
                    memo="", owner=codername,
                )
                existing.add(name)
                counts["sources"] += 1

    message = (
        f"XLSX import complete: {counts['cases']} cases, {counts['attributes']} "
        f"attribute values, {counts['qualitative_files']} qualitative files, "
        f"{counts['qualitative_codings']} qualitative codings, {counts['sources']} text sources"
    )
    return {"ok": True, "message": message, **counts}
