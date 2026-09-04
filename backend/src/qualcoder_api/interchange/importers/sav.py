"""SPSS .sav importer — import an SPSS .sav data file."""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import math
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.interchange.importers.survey import _import_survey_rows


def _sav_cell(value) -> str:
    """Format one SPSS cell value for storage as a string attribute.

    Missing values (``nan``/``None``) become empty strings, whole floats
    drop the trailing ``.0`` and dates are rendered ISO-style.

    ``pyreadstat`` is used with ``output_format="dict"`` (no pandas), so
    values are plain Python scalars — but numpy scalars are unwrapped
    defensively via ``.item()`` in case a future pyreadstat version
    returns numpy arrays instead of lists.
    """
    if value is None:
        return ""
    item = getattr(value, "item", None)
    if callable(item):
        with contextlib.suppress(ValueError, AttributeError):
            value = item()
        if value is None:
            return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, datetime.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value)


async def import_sav(
    session_factory: async_sessionmaker,
    sav_path: str,
    codername: str,
    qualitative_headers: list[str] | None = None,
) -> dict:
    """Import an SPSS ``.sav`` data file.

    Every row becomes a case named after the first variable's value (or
    ``Case <n>`` when empty); the remaining variables become case attribute
    types (created on first use, numeric variables as ``number``). String
    variables listed in ``qualitative_headers`` are imported as one text
    file per row exactly like the survey CSV importer.
    """
    try:
        import pyreadstat

        def _read():
            # Dict output (plain Python scalars) — avoids the pandas
            # dependency entirely; metadata is identical either way.
            return pyreadstat.read_sav(sav_path, output_format="dict")

        data, meta = await asyncio.to_thread(_read)
    except Exception as err:  # pyreadstat raises ReadstatError on unreadable files
        raise ValueError(f"Invalid SPSS .sav file: {err}") from err

    columns = list(meta.column_names)
    if not columns:
        return {
            "ok": True, "message": "SPSS .sav file has no variables",
            "cases": 0, "attributes": 0, "qualitative_files": 0,
            "qualitative_codings": 0,
        }

    var_types = getattr(meta, "readstat_variable_types", {}) or {}
    value_types = {
        col: "number" if var_types.get(col) in ("double", "integer") else "text"
        for col in columns
    }
    rows: list[list[str]] = []
    cols = {col: list(data.get(col, [])) for col in columns}
    n_rows = len(cols[columns[0]]) if columns else 0
    for index in range(n_rows):
        name = _sav_cell(cols[columns[0]][index])
        if not name:
            name = f"Case {index + 1}"
        rows.append([name] + [_sav_cell(cols[col][index]) for col in columns[1:]])

    if not rows:
        return {
            "ok": True, "message": "SPSS .sav file has no rows",
            "cases": 0, "attributes": 0, "qualitative_files": 0,
            "qualitative_codings": 0,
        }

    result = await _import_survey_rows(
        session_factory, columns, rows, codername, qualitative_headers,
        str(Path(sav_path).parent), value_types=value_types,
    )
    message = (
        f"SPSS .sav import complete: {result['cases']} cases, {result['attributes']} "
        f"attribute values, {result['qualitative_files']} qualitative files, "
        f"{result['qualitative_codings']} qualitative codings"
    )
    return {**result, "message": message}
