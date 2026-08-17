"""Survey CSV importer — import a survey-style tabular CSV."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.interchange.importers.base import (
    _existing_names,
)
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repositories import (
    AttributeRepository,
    CaseRepository,
    CodeRepository,
    CodingRepository,
    SourceRepository,
)


async def _import_survey_rows(
    session_factory: async_sessionmaker,
    headers: list[str],
    data: list[list[str]],
    codername: str,
    qualitative_headers: list[str] | None,
    pseudonyms_dir: str,
    value_types: dict[str, str] | None = None,
) -> dict:
    """Shared core of the survey-family importers.

    Consumes an already-parsed table: ``headers`` names the columns (the
    first one holds the case name) and ``data`` holds the string-formatted
    rows. Columns listed in ``qualitative_headers`` become one text source
    per row (``<case name>_<column>``) linked to the case and coded with a
    code named after the column; every other column becomes a case
    attribute. ``value_types`` optionally maps column names to the
    ``attribute_type.valuetype`` of newly created types (default "text").
    """
    if not data:
        return {
            "ok": True, "message": "No data rows", "cases": 0, "attributes": 0,
            "qualitative_files": 0, "qualitative_codings": 0,
        }
    qualitative = {h for h in (qualitative_headers or []) if h in headers}

    from qualcoder_api.services import pseudonyms

    cases = 0
    attributes = 0
    qualitative_files = 0
    qualitative_codings = 0
    async with session_factory() as session:
        case_repo = CaseRepository(session)
        attr_repo = AttributeRepository(session)
        source_repo = SourceRepository(session)
        code_repo = CodeRepository(session)
        coding_repo = CodingRepository(session)

        existing_types = await _existing_names(session, tables.attribute_type, "name")
        for header in headers[1:]:
            if header and header not in qualitative and header not in existing_types:
                await attr_repo.add_type(
                    name=header, owner=codername, case_or_file="case",
                    value_type=(value_types or {}).get(header, "text"),
                )
                existing_types.add(header)

        # Qualitative column codes (one code per column, gray, no category).
        existing_codes = await _existing_names(session, tables.code_name, "name")
        qual_cid: dict[str, int] = {}
        for header in qualitative:
            if header not in existing_codes:
                code = await code_repo.add_code(
                    name=header, owner=codername, color="#B8B8B8"
                )
                if code is not None:
                    qual_cid[header] = code.cid
                    existing_codes.add(header)
            else:
                row = (
                    await session.execute(
                        select(tables.code_name.c.cid).where(tables.code_name.c.name == header)
                    )
                ).first()
                if row is not None:
                    qual_cid[header] = row[0]

        for row in data:
            name = row[0].strip() if row else ""
            if not name:
                continue
            existing = (
                await session.execute(
                    select(tables.cases.c.caseid).where(tables.cases.c.name == name)
                )
            ).first()
            if existing is not None:
                caseid = existing[0]
            else:
                case = await case_repo.add_case(name=name, owner=codername)
                if case is None:
                    continue
                caseid = case.caseid
                cases += 1
            for col, header in enumerate(headers[1:], start=1):
                if not header:
                    continue
                value = row[col].strip() if col < len(row) else ""
                if header in qualitative:
                    if not value:
                        continue
                    qual_name = f"{name}_{header}"
                    existing_file = (
                        await session.execute(
                            select(tables.source.c.id).where(tables.source.c.name == qual_name)
                        )
                    ).first()
                    fulltext = pseudonyms.apply_pseudonyms(value, pseudonyms_dir)
                    if existing_file is not None:
                        fid = existing_file[0]
                    else:
                        source = await source_repo.add_source(
                            name=qual_name,
                            mediapath=None,
                            fulltext=fulltext,
                            memo="",
                            owner=codername,
                        )
                        fid = source.id
                        qualitative_files += 1
                        await case_repo.link_file(caseid=caseid, fid=fid, owner=codername)
                    cid = qual_cid.get(header)
                    if cid is not None:
                        try:
                            await coding_repo.add_text_coding(
                                cid=cid, fid=fid, seltext=fulltext,
                                pos0=0, pos1=max(0, len(fulltext) - 1),
                                owner=codername,
                            )
                            qualitative_codings += 1
                        except IntegrityError:
                            await session.rollback()
                else:
                    await attr_repo.set_value(
                        name=header, attr_type="case", value=value,
                        entity_id=caseid, owner=codername,
                    )
                    attributes += 1

    return {
        "ok": True,
        "cases": cases,
        "attributes": attributes,
        "qualitative_files": qualitative_files,
        "qualitative_codings": qualitative_codings,
    }


async def import_survey(
    session_factory: async_sessionmaker,
    csv_path: str,
    codername: str,
    qualitative_headers: list[str] | None = None,
) -> dict:
    """Import a survey CSV: one row = one case, columns = case attributes.

    ``qualitative_headers`` names the columns whose free text becomes one
    text file per row (``<case name>_<field>``), linked to the case and
    coded with a code named after the field (upstream survey importer).
    The CSV is read as UTF-8 (BOM tolerated) and a ``;`` delimiter is
    accepted when ``,`` yields single-column rows.
    """
    raw = Path(csv_path).read_bytes()
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
        return {"ok": True, "message": "Survey CSV is empty", "cases": 0, "attributes": 0,
                "qualitative_files": 0, "qualitative_codings": 0}
    headers = [h.strip() for h in rows[0]]
    result = await _import_survey_rows(
        session_factory, headers, rows[1:], codername, qualitative_headers,
        str(Path(csv_path).parent),
    )
    message = (
        f"Survey import complete: {result['cases']} cases, {result['attributes']} "
        f"attribute values, {result['qualitative_files']} qualitative files, "
        f"{result['qualitative_codings']} qualitative codings"
    )
    return {**result, "message": message}
