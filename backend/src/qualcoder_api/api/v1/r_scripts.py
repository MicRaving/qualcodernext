"""R-integration API — saved R scripts and report-data preparation.

Saved scripts live in the ``r_script`` table (name is unique, case-
insensitive duplicates rejected with 409). ``POST /r/prepare-report``
materializes one report's tabular data as UTF-8 CSVs into the open
project's ``r_exchange/in/`` directory and returns a short R stub that
reads them back. Mutations are audit-recorded like every other domain
(see ``creative.py`` for the pattern).
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, insert, select
from sqlalchemy import update as sa_update

from qualcoder_api.api.v1.deps import DbDep, ServiceDep
from qualcoder_api.core.timeutil import now as _now
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repo.base import _inserted_pk
from qualcoder_api.services import audit, report_service, sync
from qualcoder_api.services.user_settings import get_codername, resolve_owner

router = APIRouter(prefix="/r", tags=["r"])

REPORTS = (
    "code-frequencies",
    "codes-by-segments",
    "coder-comparison",
    "summary-table",
)


class RScriptCreate(BaseModel):
    name: str
    script: str = ""
    owner: str | None = None


class RScriptUpdate(BaseModel):
    name: str | None = None
    script: str | None = None


class PrepareReportRequest(BaseModel):
    report: str
    fids: list[int] | None = None
    cids: list[int] | None = None


async def _get_script(db: DbDep, script_id: int) -> dict:
    """The ``r_script`` row as a dict; 404 when it does not exist."""
    row = (
        await db.execute(
            select(tables.r_script).where(tables.r_script.c.id == script_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="R script not found")
    return dict(row._mapping)


async def _assert_name_free(db: DbDep, name: str, exclude_id: int | None = None) -> None:
    """409 when another script already uses ``name`` (case-insensitive, like
    the code-name pre-check in the creative promote path)."""
    rows = await db.execute(select(tables.r_script.c.id, tables.r_script.c.name))
    for script_id, existing in rows:
        if exclude_id is not None and script_id == exclude_id:
            continue
        if existing and str(existing).strip().lower() == name.lower():
            raise HTTPException(status_code=409, detail="duplicate R script name")


@router.get("/scripts", response_model=list[dict])
async def list_r_scripts(db: DbDep) -> list[dict]:
    """All saved R scripts (id, name, updated), newest first."""
    rows = await db.execute(
        select(
            tables.r_script.c.id,
            tables.r_script.c.name,
            tables.r_script.c.updated,
        ).order_by(tables.r_script.c.id.desc())
    )
    return [dict(r._mapping) for r in rows]


@router.post("/scripts", response_model=dict, status_code=201)
async def create_r_script(req: RScriptCreate, db: DbDep) -> dict:
    """Save a new R script; duplicate names are rejected with 409."""
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="script name must not be empty")
    await _assert_name_free(db, name)
    owner = resolve_owner(req.owner)
    timestamp = _now()
    result = await db.execute(
        insert(tables.r_script).values(
            name=name, script=req.script, owner=owner,
            created=timestamp, updated=timestamp,
        )
    )
    await db.commit()
    script_id = _inserted_pk(result)
    row = (
        await db.execute(
            select(tables.r_script).where(tables.r_script.c.id == script_id)
        )
    ).first()
    assert row is not None
    data = dict(row._mapping)
    await sync.capture_insert(
        db, entity="r_script", pk_name="id", pk_value=script_id, row=data
    )
    await db.commit()
    await audit.record(
        db, user=owner, action="r_script.create", entity="r_script",
        entity_id=script_id, detail={"name": name, "script": req.script[:200], "row": data},
    )
    return data


@router.get("/scripts/{script_id}", response_model=dict)
async def get_r_script(script_id: int, db: DbDep) -> dict:
    """One saved R script with its full content."""
    return await _get_script(db, script_id)


@router.patch("/scripts/{script_id}", response_model=dict)
async def update_r_script(script_id: int, req: RScriptUpdate, db: DbDep) -> dict:
    """Rename / edit a script; a rename colliding with another name yields
    409. Touches ``updated`` on every change."""
    old = await _get_script(db, script_id)
    values = req.model_dump(exclude_none=True)
    if "name" in values:
        name = (values["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="script name must not be empty")
        values["name"] = name
        await _assert_name_free(db, name, exclude_id=script_id)
    if values:
        await db.execute(
            sa_update(tables.r_script)
            .where(tables.r_script.c.id == script_id)
            .values(**values, updated=_now())
        )
        await db.commit()
        row = (
            await db.execute(
                select(tables.r_script).where(tables.r_script.c.id == script_id)
            )
        ).first()
        assert row is not None
        data = dict(row._mapping)
        await sync.capture_update(
            db, entity="r_script", pk_name="id", pk_value=script_id, row=data
        )
        await db.commit()
        await audit.record(
            db, user=get_codername(), action="r_script.update", entity="r_script",
            entity_id=script_id,
            detail={
                **values,
                "old_name": old.get("name"),
                "before": old,
                "after": data,
            },
        )
        return data
    return old


@router.delete("/scripts/{script_id}", status_code=204)
async def delete_r_script(script_id: int, db: DbDep) -> None:
    """Delete a saved R script."""
    row = (
        await db.execute(
            select(tables.r_script).where(tables.r_script.c.id == script_id)
        )
    ).first()
    if row is None:
        await db.commit()
        raise HTTPException(status_code=404, detail="R script not found")
    data = dict(row._mapping)
    await db.execute(delete(tables.r_script).where(tables.r_script.c.id == script_id))
    await sync.capture_delete(
        db, entity="r_script", pk_name="id", pk_value=script_id, row=data
    )
    await db.commit()
    await audit.record(
        db, user=get_codername(), action="r_script.delete", entity="r_script",
        entity_id=script_id, detail=data,
    )


async def _report_rows(db: DbDep, report: str, fids: list[int] | None, cids: list[int] | None) -> tuple[list[list[Any]], list[str]]:
    """Rows + column names for one report, in the same shape the report
    endpoints return. The summary table is flattened to one row per
    unit with one column per code (cell = joined coding memos)."""
    if report == "code-frequencies":
        rows = await report_service.code_frequencies(db)
        return (
            [list(r.values()) for r in rows],
            ["cid", "name", "color", "category", "count"],
        )
    if report == "codes-by-segments":
        rows = await report_service.codes_by_segments(db)
        return (
            [list(r.values()) for r in rows],
            ["ctid", "file_name", "code_name", "category", "seltext", "owner", "date"],
        )
    if report == "coder-comparison":
        rows = await report_service.coder_comparison(db)
        return (
            [list(r.values()) for r in rows],
            ["owner", "codings_count", "files_count"],
        )
    # summary-table
    data = await report_service.summary_table(db, "file", fids, cids)
    cols = ["id", "name", *[c["name"] for c in data["codes"]]]
    out: list[list[Any]] = []
    for row in data["rows"]:
        cells = [cell["memo"] for cell in row["cells"]]
        out.append([row["id"], row["name"], *cells])
    return out, cols


def _csv_text(rows: list[list[Any]], cols: list[str]) -> str:
    """UTF-8 CSV payload: header + data rows (quoted where needed)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(cols)
    for row in rows:
        writer.writerow(["" if value is None else str(value) for value in row])
    return buffer.getvalue()


def _r_stub(files: list[str]) -> str:
    """Short R script that reads the exported CSVs back into data frames."""
    lines: list[str] = []
    for i, name in enumerate(files):
        var = "df" if len(files) == 1 else f"df{i + 1}"
        lines.append(
            f'{var} <- read.csv(file.path(Sys.getenv("QC_EXCHANGE"), "in", "{name}"), '
            f'fileEncoding="UTF-8", check.names=FALSE)'
        )
        lines.append(f"str({var})")
    return "\n".join(lines)


@router.post("/prepare-report")
async def prepare_report(req: PrepareReportRequest, svc: ServiceDep, db: DbDep) -> dict:
    """Export one report's tabular data as CSVs into ``r_exchange/in/`` of
    the open project and return a stub R script that reads them."""
    if req.report not in REPORTS:
        raise HTTPException(
            status_code=422,
            detail=f"unknown report: {req.report} (expected one of {', '.join(REPORTS)})",
        )
    if svc.project_path == "":
        raise HTTPException(status_code=409, detail="no project is open")
    rows, cols = await _report_rows(db, req.report, req.fids, req.cids)

    in_dir = Path(svc.project_path) / "r_exchange" / "in"
    in_dir.mkdir(parents=True, exist_ok=True)
    payload = _csv_text(rows, cols)
    filename = f"{req.report}.csv"
    (in_dir / filename).write_text(payload, encoding="utf-8")

    files: list[dict[str, Any]] = [{"name": filename, "rows": len(rows), "cols": cols}]
    stub = _r_stub([f["name"] for f in files])
    await audit.record(
        db, user=get_codername(), action="r_script.prepare_report",
        entity="r_script",
        detail={
            "report": req.report,
            "fids": req.fids,
            "cids": req.cids,
            "files": files,
        },
    )
    return {"files": files, "stub": stub}
