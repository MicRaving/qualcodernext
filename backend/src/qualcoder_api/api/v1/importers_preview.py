"""Preview + destination-count helpers for the interchange import API.

These pure helpers sample an interchange upload (columns/rows for the
tabular formats, lines for plain-text codebooks) and compute a
best-effort ``destination`` summary of what the import would create
(codes/categories/sources/codings/cases/attributes/references/files).
The import router (``api/v1/importers.py``) calls them from its
``/preview`` endpoint; they never touch the open project.
"""

from __future__ import annotations

import asyncio
import csv
import io
import sqlite3
import xml.etree.ElementTree as etree
from pathlib import Path

from qualcoder_api.interchange import importers


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
                sample_data, sample_meta = pyreadstat.read_sav(
                    path, row_limit=16, output_format="dict"
                )
                total = getattr(
                    pyreadstat.read_sav(path, metadataonly=True, output_format="dict")[1],
                    "number_rows",
                    None,
                )
                if total:
                    n_rows = int(total)
                elif sample_meta.column_names:
                    n_rows = len(sample_data.get(sample_meta.column_names[0], []))
                else:
                    n_rows = 0
                return sample_data, sample_meta, n_rows

            data, meta, total_rows = await asyncio.to_thread(_read_sav)
        except Exception as err:  # pyreadstat raises ReadstatError on unreadable files
            raise ValueError(f"Invalid SPSS .sav file: {err}") from err
        columns = list(meta.column_names)
        if columns:
            var_types = getattr(meta, "readstat_variable_types", {}) or {}
            qual = [
                col for col in columns[1:] if var_types.get(col) not in ("double", "integer")
            ]
            sample = [
                [importers._sav_cell(data.get(col, [])[i]) for col in columns]
                for i in range(len(data.get(columns[0], [])))
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


def _quote_ident(name: str) -> str:
    """Quote a SQLite identifier (table/column) safely."""
    return '"' + name.replace('"', '""') + '"'


def _table_row_count(conn: sqlite3.Connection, table: str) -> int:
    """Row count of ``table`` (0 when the table is absent or unreadable)."""
    if not table.replace("_", "").replace("2", "").isalnum():
        return 0
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {_quote_ident(table)}").fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def _distinct_column_values(
    conn: sqlite3.Connection, table: str, *candidates: str
) -> set[str]:
    """Distinct non-null values of the first present column among ``candidates``."""
    if not table.replace("_", "").isalnum():
        return set()
    for column in candidates:
        if not column.replace("_", "").isalnum():
            continue
        try:
            return {
                str(row[0])
                for row in conn.execute(
                    f"SELECT DISTINCT {_quote_ident(column)} FROM {_quote_ident(table)}"
                )
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
