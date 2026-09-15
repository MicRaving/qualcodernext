"""Meta hits import — EBSCO XML, Excel/CSV search exports and RIS files.

Adapted from the reference ``Inoculation_Meta/meta/core/screening.py``
parsers: same column-alias detection and EBSCO XML field mapping, but written
for QCnext's stack (openpyxl instead of pandas, rispy instead of manual RIS
parsing) and targeting the ``meta_hit`` table instead of xlsx round-trips.
"""

from __future__ import annotations

import csv
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

import openpyxl  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "titel", "article title", "document title", "ti", "t1"),
    "abstract": ("abstract", "zusammenfassung", "ab"),
    "authors": ("author", "authors", "autoren", "verfasser", "au", "a1"),
    "doi": ("doi", "digital object identifier", "identifier"),
    "year": ("year", "jahr", "publication year", "published", "date", "py"),
    "source": ("source", "quelle", "journal", "container", "publication", "jo"),
    "language": ("language", "sprache", "la"),
}

#: Fields a search-results file must provide (abstract is optional).
REQUIRED_FIELDS = ("title", "authors", "doi")

#: Reference EBSCO layout (0-based): D=title, E=abstract, G=authors, AC=doi.
#: Used only when NO recognizable header row exists.
FALLBACK_COLUMNS: dict[str, int] = {"title": 3, "abstract": 4, "authors": 6, "doi": 28}

#: How many leading rows to scan for a header (Excel exports often put a
#: title/blank line above the real header).
_HEADER_SCAN_ROWS = 15

#: Every field the import labeler can map a column to.
FIELD_KEYS = ("title", "abstract", "authors", "doi", "year", "source", "language")


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_hit(fields: dict) -> dict:
    """Trim + optional-field defaults for a hit row."""
    out = {
        "title": _clean(fields.get("title") or ""),
        "abstract": _clean(fields.get("abstract") or "") or None,
        "authors": _clean(fields.get("authors") or "") or None,
        "doi": _clean(fields.get("doi") or "") or None,
        "year": _clean(fields.get("year") or "") or None,
        "source": _clean(fields.get("source") or "") or None,
        "language": _clean(fields.get("language") or "") or None,
    }
    if out["doi"]:
        out["doi"] = out["doi"].replace("https://doi.org/", "").replace("http://doi.org/", "").strip()
    return out


def parse_ebsco_xml(path: str) -> list[dict]:
    """Parse an EBSCOhost XML export into hit dicts."""
    tree = ET.parse(path)
    records = tree.getroot().findall("record")
    if not records:
        raise ValueError(f"No <record> elements found in '{path}'.")

    hits = []
    for rec in records:
        def text(tag: str, _rec=rec) -> str:
            el = _rec.find(tag)
            return (el.text or "").strip() if el is not None else ""

        pub_date = text("publicationDate")
        hits.append(
            _normalize_hit(
                {
                    "title": text("title"),
                    "abstract": text("abstract"),
                    "authors": text("contributors").replace(" ; ", ", "),
                    "doi": text("doi"),
                    "year": pub_date[:4] if pub_date else "",
                    "source": text("source"),
                    "language": text("language"),
                }
            )
        )
    return hits


def _detect_columns(header: list[str], *, fallback: bool = True) -> dict[str, int]:
    """Map canonical field names to column indices using a header row.

    Exact header matches win over substring matches (so "Publication Year"
    maps to ``year``, not ``source``); each column feeds at most one field.
    With ``fallback`` the reference EBSCO positions fill any still-missing
    required field.
    """
    cells = [str(cell or "").lower().strip() for cell in header]
    mapping: dict[str, int] = {}
    used: set[int] = set()

    for exact in (True, False):
        for canonical, aliases in COLUMN_ALIASES.items():
            if canonical in mapping:
                continue
            for idx, cell in enumerate(cells):
                if idx in used or not cell:
                    continue
                matched = cell == canonical or cell in aliases
                if not matched and not exact:
                    matched = any(alias in cell for alias in aliases)
                if matched:
                    mapping[canonical] = idx
                    used.add(idx)
                    break

    if fallback:
        for canonical in REQUIRED_FIELDS:
            if canonical not in mapping and canonical in FALLBACK_COLUMNS:
                mapping[canonical] = FALLBACK_COLUMNS[canonical]
    return mapping


def _best_header_row(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    """Find the most header-like row in the first rows; (-1, {}) when none."""
    best_idx, best_score = -1, 0
    for idx, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        mapping = _detect_columns(row, fallback=False)
        score = sum(1 for field in REQUIRED_FIELDS if field in mapping)
        if score > best_score:
            best_idx, best_score = idx, score
    if best_score == 0:
        return -1, {}
    return best_idx, _detect_columns(rows[best_idx], fallback=True)


def _rows_to_hits(
    rows: list[list[str]],
    source_name: str,
    *,
    header_row: int | None = None,
    mapping: dict[str, object] | None = None,
) -> list[dict]:
    """Turn a table into hit dicts.

    With ``mapping`` (field -> column index, from the import labeler) the
    caller's choice is used verbatim; otherwise the header row is auto-detected
    in the first rows and the reference EBSCO layout is assumed when none is
    found.
    """
    if not rows:
        raise ValueError(f"No rows found in '{source_name}'.")

    header_for_msg = 0
    if mapping:
        col_map: dict[str, int] = {}
        for field, idx in mapping.items():
            try:
                column = int(str(idx))
            except (TypeError, ValueError):
                continue
            if column >= 0:
                col_map[field] = column
        if "title" not in col_map:
            raise ValueError("Map the title column before importing.")
        data_start = (header_row + 1) if header_row is not None and header_row >= 0 else 0
        header_for_msg = header_row if header_row is not None and header_row >= 0 else 0
    else:
        header_idx, auto = _best_header_row(rows)
        if header_row is not None and 0 <= header_row < len(rows):
            header_idx = header_row
            auto = _detect_columns(rows[header_row], fallback=True)
        data_start = header_idx + 1 if header_idx >= 0 else 0
        col_map = auto or _detect_columns([], fallback=True)
        header_for_msg = header_idx if header_idx >= 0 else 0

    hits: list[dict] = []
    for row in rows[data_start:]:
        def cell(field: str, _row=row) -> str:
            idx = col_map.get(field)
            if idx is None or idx >= len(_row):
                return ""
            return _clean(_row[idx])

        if not cell("title") and not cell("doi") and not cell("abstract"):
            continue
        hits.append(
            _normalize_hit(
                {
                    "title": cell("title"),
                    "abstract": cell("abstract"),
                    "authors": cell("authors"),
                    "doi": cell("doi"),
                    "year": cell("year"),
                    "source": cell("source"),
                    "language": cell("language"),
                }
            )
        )

    if not hits:
        seen = ", ".join(c for c in rows[header_for_msg][:12] if c)
        raise ValueError(
            f"No usable data rows found in '{source_name}'. "
            f"Header: [{seen}]. Expected columns such as title, abstract, "
            "authors, doi — or map them in the import dialog."
        )
    return hits


def _load_sheets(path: str) -> list[tuple[str, list[list[str]]]]:
    """Non-empty sheets of an Excel workbook as ``[(title, rows)]``."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheets: list[tuple[str, list[list[str]]]] = []
        for ws in wb.worksheets:
            rows = [
                ["" if cell is None else str(cell) for cell in row]
                for row in ws.iter_rows(values_only=True)
            ]
            if any(any(cell for cell in row) for row in rows):
                sheets.append((ws.title, rows))
        return sheets
    finally:
        wb.close()


def parse_hits_xlsx(
    path: str,
    *,
    sheet: str | None = None,
    header_row: int | None = None,
    mapping: dict[str, object] | None = None,
) -> list[dict]:
    """Parse a search-results Excel workbook (.xlsx/.xlsm).

    Without ``sheet`` every sheet is tried (exports often carry a cover/notes
    sheet first) and the first that yields hits wins. ``header_row`` /
    ``mapping`` come from the import dialog and override auto-detection.
    """
    sheets = _load_sheets(path)
    name = Path(path).name
    if not sheets:
        raise ValueError(f"'{name}' contains no data.")

    if sheet:
        for title, rows in sheets:
            if title == sheet:
                return _rows_to_hits(
                    rows, f"{name} [{title}]", header_row=header_row, mapping=mapping
                )
        raise ValueError(f"Sheet '{sheet}' not found in '{name}'.")

    first_error: ValueError | None = None
    for title, rows in sheets:
        try:
            return _rows_to_hits(rows, f"{name} [{title}]")
        except ValueError as err:
            first_error = first_error or err
    raise first_error if first_error is not None else ValueError(f"No usable data rows in '{name}'.")


def parse_hits_csv(
    path: str,
    *,
    header_row: int | None = None,
    mapping: dict[str, object] | None = None,
) -> list[dict]:
    """Parse a comma-separated search-results export."""
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        rows = [list(r) for r in csv.reader(fh)]
    return _rows_to_hits(rows, Path(path).name, header_row=header_row, mapping=mapping)


def parse_hits_ris(path: str) -> list[dict]:
    """Parse an RIS export (via rispy)."""
    import rispy  # type: ignore[import-untyped]

    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        records = rispy.load(fh)
    hits = []
    for rec in records:
        authors = rec.get("authors") or []
        hits.append(
            _normalize_hit(
                {
                    "title": rec.get("title") or rec.get("primary_title") or "",
                    "abstract": rec.get("abstract") or rec.get("abstract_2") or "",
                    "authors": "; ".join(authors),
                    "doi": rec.get("doi") or "",
                    "year": str(rec.get("year") or ""),
                    "source": rec.get("journal") or rec.get("container_title") or "",
                    "language": rec.get("language") or "",
                }
            )
        )
    if not hits:
        raise ValueError(f"No records found in '{path}'.")
    return hits


def parse_hits_file(
    path: str,
    *,
    sheet: str | None = None,
    header_row: int | None = None,
    mapping: dict[str, object] | None = None,
) -> list[dict]:
    """Dispatch on file extension to the right parser."""
    suffix = Path(path).suffix.lower()
    if suffix == ".xml":
        return parse_ebsco_xml(path)
    if suffix in (".xlsx", ".xlsm"):
        return parse_hits_xlsx(path, sheet=sheet, header_row=header_row, mapping=mapping)
    if suffix == ".ris":
        return parse_hits_ris(path)
    if suffix == ".csv":
        return parse_hits_csv(path, header_row=header_row, mapping=mapping)
    if suffix == ".xls":
        raise ValueError(
            "Legacy Excel .xls is not supported — open the file in Excel and "
            "save it as .xlsx, then import again."
        )
    raise ValueError(
        f"Unsupported search-results file type: {suffix or '(none)'} "
        "(use .xml, .xlsx, .xlsm, .ris or .csv)"
    )


def _structured_preview(fmt: str, hits: list[dict]) -> dict:
    """Preview for formats that carry named fields (no mapping needed)."""
    return {
        "format": fmt,
        "structured": True,
        "sheets": [],
        "sheet": "",
        "header_row": -1,
        "columns": list(FIELD_KEYS),
        "head_rows": [],
        "rows_sample": [[str(h.get(f) or "") for f in FIELD_KEYS] for h in hits[:5]],
        "mapping": {f: i for i, f in enumerate(FIELD_KEYS)},
        "fields": list(FIELD_KEYS),
    }


def preview_hits_file(path: str, *, sheet: str | None = None) -> dict:
    """Describe a search-results file for the import labeler.

    Returns sheets (Excel), the chosen sheet's detected header row, its
    column headers, a few sample rows and the auto-detected field mapping.
    Structured formats (XML/RIS) report ``structured: true`` (import as-is).
    """
    suffix = Path(path).suffix.lower()
    name = Path(path).name

    if suffix == ".xml":
        return _structured_preview("xml", parse_ebsco_xml(path))
    if suffix == ".ris":
        return _structured_preview("ris", parse_hits_ris(path))
    if suffix == ".xls":
        raise ValueError(
            "Legacy Excel .xls is not supported — open the file in Excel and "
            "save it as .xlsx, then import again."
        )

    if suffix in (".xlsx", ".xlsm"):
        sheets = _load_sheets(path)
        if not sheets:
            raise ValueError(f"'{name}' contains no data.")
        chosen = sheet if sheet and any(t == sheet for t, _ in sheets) else sheets[0][0]
        rows = next(r for t, r in sheets if t == chosen)
        sheet_names = [t for t, _ in sheets]
    elif suffix == ".csv":
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
            rows = [list(r) for r in csv.reader(fh)]
        chosen, sheet_names = "", []
    else:
        raise ValueError(
            f"Unsupported search-results file type: {suffix or '(none)'} "
            "(use .xml, .xlsx, .xlsm, .ris or .csv)"
        )

    header_row, _ = _best_header_row(rows)
    detected = _detect_columns(rows[header_row] if header_row >= 0 else [], fallback=False)
    columns = rows[header_row] if header_row >= 0 else (rows[0] if rows else [])
    sample = rows[header_row + 1 : header_row + 6] if header_row >= 0 else rows[:5]
    return {
        "format": "xlsx" if suffix in (".xlsx", ".xlsm") else "csv",
        "structured": False,
        "sheets": sheet_names,
        "sheet": chosen,
        "header_row": header_row,
        "columns": [str(c or "") for c in columns],
        "head_rows": [[str(c or "") for c in row] for row in rows[:_HEADER_SCAN_ROWS]],
        "rows_sample": [[str(c or "") for c in row] for row in sample],
        "mapping": {k: detected.get(k) for k in FIELD_KEYS},
        "fields": list(FIELD_KEYS),
    }

