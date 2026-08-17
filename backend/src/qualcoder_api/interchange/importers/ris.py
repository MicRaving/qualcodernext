"""RIS importer — import a .ris bibliography file."""

from __future__ import annotations

import rispy
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.persistence import tables


async def import_ris(session_factory: async_sessionmaker, ris_path: str, codername: str) -> dict:
    """Import a .ris bibliography file into the ``ris`` table.

    Each RIS record becomes one ``risid``; every tag occurrence becomes a
    ``ris`` row (risid, tag, longtag, value) using the ``rispy`` tag mapping.
    ``codername`` is accepted for signature symmetry only (RIS rows carry no
    owner column). The ``ris`` table has no unique constraint, so rows are
    inserted as-is: ``references`` counts the tag rows inserted and
    ``entries`` the RIS records.
    """
    longtag_to_tag = {v: k for k, v in rispy.TAG_KEY_MAPPING.items()}
    with open(ris_path, encoding="utf-8", errors="surrogateescape") as ris_file:  # noqa: ASYNC230 - small local text read
        entries = rispy.load(ris_file)

    inserted = 0
    async with session_factory() as session:
        row = (await session.execute(select(func.max(tables.ris.c.risid)))).first()
        max_risid = row[0] if row is not None and row[0] is not None else 0
        for entry in entries:
            entry.pop("id", None)
            max_risid += 1
            for longtag, value in entry.items():
                if isinstance(value, list):
                    data = "; ".join(str(v) for v in value if v is not None)
                elif value is None:
                    continue
                else:
                    data = str(value)
                await session.execute(
                    insert(tables.ris).values(
                        risid=max_risid,
                        tag=longtag_to_tag.get(longtag, longtag),
                        longtag=longtag,
                        value=data,
                    )
                )
                inserted += 1
        await session.commit()
    return {
        "ok": True,
        "message": f"Imported {len(entries)} references ({inserted} tag rows)",
        "references": inserted,
        "entries": len(entries),
    }
