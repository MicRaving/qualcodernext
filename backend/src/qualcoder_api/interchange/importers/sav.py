"""SPSS .sav importer — import an SPSS .sav data file."""

from __future__ import annotations

import asyncio
import datetime
import math
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.interchange.importers.survey import _import_survey_rows


def _sav_cell(value) -> str:
    """Format one SPSS cell value for storage as a string attribute.

    Missing values (``nan``/``None``) become empty strings, whole floats
    drop the trailing ``.0`` and dates are rendered ISO-style.
    """
    if value is None:
        return ""
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

        df, meta = await asyncio.to_thread(pyreadstat.read_sav, sav_path)
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
    for index in range(len(df)):
        record = df.iloc[index]
        name = _sav_cell(record[columns[0]])
        if not name:
            name = f"Case {index + 1}"
        rows.append([name] + [_sav_cell(record[col]) for col in columns[1:]])

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
