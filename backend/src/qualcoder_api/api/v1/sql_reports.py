"""Ad-hoc SQL reports and saved-query management.

``POST /sql/run`` executes a read-only SQL statement against the open
project database and returns JSON-safe rows. Saved queries live in the
legacy ``stored_sql`` table (unique title). All endpoints depend on
``DbDep``, which already returns 409 when no project is open.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from qualcoder_api.api.v1.deps import DbDep
from qualcoder_api.persistence import tables

router = APIRouter(prefix="/sql", tags=["sql"])

MAX_ROWS = 5000
READ_ONLY_KEYWORDS = {"SELECT", "WITH", "EXPLAIN", "VALUES"}


class RunSqlRequest(BaseModel):
    sql: str


class SavedQueryCreate(BaseModel):
    title: str
    description: str = ""
    grouper: str = ""
    ssql: str


def _validate_read_only(sql: str) -> str:
    """Reject anything that is not a single read-only statement; return stripped stmt."""
    from qualcoder_api.core.security import validate_read_only_sql

    try:
        return validate_read_only_sql(sql)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


def _json_safe(value):
    """Convert a SQL cell to a JSON-serializable Python value."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


@router.post("/run")
async def run_sql(req: RunSqlRequest, db: DbDep) -> dict:
    """Execute a read-only statement and return columns/rows as JSON."""
    from qualcoder_api.core.security import append_limit

    stmt = _validate_read_only(req.sql)
    # Cap the rows the database materializes, not just the response: the
    # client only ever shows MAX_ROWS, so fetching a million-row table is
    # pure waste (and blocks the request handler).
    limited_sql = append_limit(stmt, MAX_ROWS)
    try:
        result = await db.execute(text(limited_sql))
    except (OperationalError, sqlite3.OperationalError) as err:
        raise HTTPException(status_code=422, detail=str(err)) from None
    columns = list(result.keys())
    rows = [[_json_safe(value) for value in row] for row in result.all()]
    body: dict = {"columns": columns, "rows": rows}
    if len(rows) > MAX_ROWS:
        body["rows"] = rows[:MAX_ROWS]
        body["truncated"] = True
    return body


@router.get("/saved")
async def list_saved_queries(db: DbDep) -> dict:
    """List saved queries ordered by title ascending."""
    rows = await db.execute(
        select(
            tables.stored_sql.c.title,
            tables.stored_sql.c.description,
            tables.stored_sql.c.grouper,
            tables.stored_sql.c.ssql,
        ).order_by(func.lower(tables.stored_sql.c.title))
    )
    return {
        "rows": [
            {
                "title": r[0],
                "description": r[1] or "",
                "grouper": r[2] or "",
                "ssql": r[3] or "",
            }
            for r in rows
        ]
    }


@router.post("/saved", status_code=201)
async def create_saved_query(req: SavedQueryCreate, db: DbDep) -> dict:
    """Save a query; the unique title constraint makes duplicates 409."""
    from qualcoder_api.services import audit
    from qualcoder_api.services.user_settings import get_codername

    try:
        await db.execute(
            insert(tables.stored_sql).values(
                title=req.title,
                description=req.description,
                grouper=req.grouper,
                ssql=req.ssql,
            )
        )
        await db.commit()
    except (IntegrityError, sqlite3.IntegrityError):
        await db.rollback()
        raise HTTPException(status_code=409, detail="duplicate title") from None
    from qualcoder_api.persistence.repositories import _capture

    row_data = {
        "title": req.title,
        "description": req.description or "",
        "grouper": req.grouper or "",
        "ssql": req.ssql,
    }
    await _capture(
        db, "stored_sql", "insert", "title", req.title, row_data
    )
    await db.commit()
    await audit.record(
        db, user=get_codername(), action="sql.save", entity="stored_sql",
        detail={"title": req.title, "row": row_data},
    )
    return req.model_dump()


@router.delete("/saved/{title}", status_code=204)
async def delete_saved_query(title: str, db: DbDep) -> None:
    """Delete a saved query by title."""
    from qualcoder_api.services import audit
    from qualcoder_api.services.user_settings import get_codername

    row = (
        await db.execute(
            select(tables.stored_sql).where(tables.stored_sql.c.title == title)
        )
    ).first()
    await db.execute(delete(tables.stored_sql).where(tables.stored_sql.c.title == title))
    if row is not None:
        from qualcoder_api.persistence.repositories import _capture, _rowdict

        await _capture(db, "stored_sql", "delete", "title", title, _rowdict(row))
    await db.commit()
    await audit.record(
        db, user=get_codername(), action="sql.delete", entity="stored_sql",
        detail={"title": title, "row": dict(row._mapping) if row is not None else None},
    )
