"""Plain-text codebook import (upstream ``ImportPlainTextCodes`` port).

Format: one entry per line, ``category>>subcategory>>code``; a tab-separated
second column becomes the code memo. Categories are created on demand
(hierarchically by ``>>``), codes are deduplicated by name, and a random
palette color is assigned to new codes.
"""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.core.palette import random_code_color
from qualcoder_api.core.timeutil import now as _now

logger = logging.getLogger(__name__)


def _parse_rows(path: str) -> list[list[str]]:
    raw = Path(path).read_bytes()
    text_data = raw.decode("utf-8-sig", errors="surrogateescape")
    rows: list[list[str]] = []
    if path.lower().endswith(".csv"):
        reader = csv.reader(io.StringIO(text_data), delimiter=",")
        rows = [row for row in reader if row]
    else:
        reader = csv.reader(io.StringIO(text_data), delimiter="\t")
        rows = [row for row in reader if row]
    return rows


async def import_codebook(
    session_factory: async_sessionmaker, path: str, codername: str
) -> dict:
    """Import a plain-text codebook into the open project."""
    # The file read is blocking; run it off the event loop.
    import asyncio

    rows = await asyncio.to_thread(_parse_rows, path)
    if not rows:
        raise ValueError("codebook file is empty")

    imported_categories = 0
    imported_codes = 0
    duplicates = 0
    async with session_factory() as session:
        # --- categories (in path order so parents exist first) ----------
        category_paths: list[str] = []
        for row in rows:
            if not row or not row[0]:
                continue
            parts = [p.strip() for p in row[0].split(">>")]
            if len(parts) < 2 or parts[0] == "":
                continue
            path_so_far: list[str] = []
            for part in parts[:-1]:  # the last part is the code name
                path_so_far.append(part)
                if part == "":
                    continue
                full = ">>".join(path_so_far)
                if full in category_paths:
                    continue
                parent_name = path_so_far[-2] if len(path_so_far) > 1 else None
                parent_id = None
                if parent_name:
                    row_p = (
                        await session.execute(
                            text("SELECT catid FROM code_cat WHERE name = :n"),
                            {"n": parent_name},
                        )
                    ).first()
                    if row_p is not None:
                        parent_id = row_p[0]
                exists = (
                    await session.execute(
                        text("SELECT catid FROM code_cat WHERE name = :n"), {"n": part}
                    )
                ).first()
                if exists is not None:
                    category_paths.append(full)
                    continue
                await session.execute(
                    text(
                        "INSERT INTO code_cat (name, memo, owner, date, supercatid) "
                        "VALUES (:name, '', :owner, :date, :supercatid)"
                    ),
                    {
                        "name": part,
                        "owner": codername,
                        "date": _now(),
                        "supercatid": parent_id,
                    },
                )
                category_paths.append(full)
                imported_categories += 1
        await session.commit()

        # --- codes -------------------------------------------------------
        rows_cat = await session.execute(text("SELECT name, catid FROM code_cat"))
        name_to_catid = {name: catid for name, catid in rows_cat}  # noqa: C416 - cursor rows

        for row in rows:
            if not row or not row[0]:
                continue
            memo = row[1].strip() if len(row) > 1 else ""
            parts = [p.strip() for p in row[0].split(">>")]
            code_name = parts[-1].strip()
            category_name = parts[-2].strip() if len(parts) > 1 else ""
            if code_name == "":
                continue
            exists = (
                await session.execute(
                    text("SELECT cid FROM code_name WHERE name = :n"), {"n": code_name}
                )
            ).first()
            if exists is not None:
                duplicates += 1
                continue
            catid = name_to_catid.get(category_name)
            await session.execute(
                text(
                    "INSERT INTO code_name (name, memo, owner, date, catid, color) "
                    "VALUES (:name, :memo, :owner, :date, :catid, :color)"
                ),
                {
                    "name": code_name,
                    "memo": memo,
                    "owner": codername,
                    "date": _now(),
                    "catid": catid,
                    "color": random_code_color(),
                },
            )
            imported_codes += 1
        await session.commit()

    message = (
        f"Codebook import complete: {imported_categories} categories, "
        f"{imported_codes} codes, {duplicates} duplicates skipped"
    )
    return {
        "ok": True,
        "message": message,
        "categories": imported_categories,
        "codes": imported_codes,
        "duplicates": duplicates,
    }
