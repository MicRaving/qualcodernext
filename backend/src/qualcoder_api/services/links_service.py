"""Segment links — a directed link from one source span to another.

Rows mirror the ``annotation`` entity model (a positional entity with a
memo, owner and date), extended with a second span: ``from_*`` is the
anchor segment, ``to_*`` the linked target. Mutations are recorded in the
``sync_log`` change journal exactly like annotations so collaboration sync
sees them.
"""

from __future__ import annotations

import datetime
from typing import Any, cast

from sqlalchemy import delete, insert, select
from sqlalchemy.engine import CursorResult, Result, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.persistence import tables


def _now() -> str:
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _rowdict(mapping) -> dict:
    from qualcoder_api.services import sync

    return sync.table_row(mapping)


def _inserted_pk(result: Result) -> int:
    """First inserted primary key from an INSERT statement result."""
    pk = cast(CursorResult[Any], result).inserted_primary_key
    if pk is None:  # pragma: no cover - inserts always return a pk here
        raise RuntimeError("insert returned no primary key")
    return int(pk[0])


class LinkError(ValueError):
    """Invalid link payload (positions out of range, missing sources)."""


class LinkService:
    """CRUD for segment links with source names/excerpts resolved."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def list_outgoing(self, fid: int) -> list[dict]:
        """Links anchored on ``fid`` (from_fid == fid)."""
        rows = await self.session.execute(
            select(tables.link)
            .where(tables.link.c.from_fid == fid)
            .order_by(tables.link.c.from_pos0)
        )
        return [await self._resolve(r._mapping) for r in rows]

    async def list_incoming(self, fid: int) -> list[dict]:
        """Links pointing at ``fid`` (to_fid == fid)."""
        rows = await self.session.execute(
            select(tables.link)
            .where(tables.link.c.to_fid == fid)
            .order_by(tables.link.c.to_pos0)
        )
        return [await self._resolve(r._mapping) for r in rows]

    async def list_all(self) -> list[dict]:
        rows = await self.session.execute(select(tables.link).order_by(tables.link.c.id))
        return [await self._resolve(r._mapping) for r in rows]

    async def _resolve(self, data: dict | RowMapping) -> dict:
        """Attach the source names and short text excerpts for both ends."""
        out = dict(data)
        for side, fid_key in (("from", "from_fid"), ("to", "to_fid")):
            row = (
                await self.session.execute(
                    select(tables.source.c.name, tables.source.c.fulltext).where(
                        tables.source.c.id == data[fid_key]
                    )
                )
            ).first()
            if row is None:
                out[f"{side}_name"] = ""
                out[f"{side}_text"] = ""
                continue
            name, fulltext = row[0], row[1] or ""
            out[f"{side}_name"] = name
            start = data[f"{side}_pos0"]
            end = data[f"{side}_pos1"]
            out[f"{side}_text"] = fulltext[start:end] if 0 <= start < end <= len(fulltext) else ""
        return out

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        from_fid: int,
        from_pos0: int,
        from_pos1: int,
        to_fid: int,
        to_pos0: int,
        to_pos1: int,
        memo: str = "",
        owner: str = "",
    ) -> dict:
        await self._validate_span(from_fid, from_pos0, from_pos1, "from")
        await self._validate_span(to_fid, to_pos0, to_pos1, "to")
        result = await self.session.execute(
            insert(tables.link).values(
                from_fid=from_fid,
                from_pos0=from_pos0,
                from_pos1=from_pos1,
                to_fid=to_fid,
                to_pos0=to_pos0,
                to_pos1=to_pos1,
                memo=memo,
                owner=owner,
                date=_now(),
            )
        )
        await self.session.commit()
        link_id = _inserted_pk(result)
        row = (
            await self.session.execute(
                select(tables.link).where(tables.link.c.id == link_id)
            )
        ).first()
        assert row is not None
        data = _rowdict(row._mapping)
        await self._sync("insert", link_id, data)
        await self.session.commit()
        return await self._resolve(data)

    async def delete(self, link_id: int) -> dict | None:
        row = (
            await self.session.execute(
                select(tables.link).where(tables.link.c.id == link_id)
            )
        ).first()
        await self.session.execute(
            delete(tables.link).where(tables.link.c.id == link_id)
        )
        if row is None:
            await self.session.commit()
            return None
        data = _rowdict(row._mapping)
        await self._sync("delete", link_id, data)
        await self.session.commit()
        return data

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _validate_span(self, fid: int, pos0: int, pos1: int, side: str) -> None:
        """Positions must fall inside the source's text (422 otherwise)."""
        if pos1 <= pos0:
            raise LinkError(f"{side} span: pos1 must be greater than pos0")
        if pos0 < 0:
            raise LinkError(f"{side} span: pos0 out of range")
        row = (
            await self.session.execute(
                select(tables.source.c.fulltext).where(tables.source.c.id == fid)
            )
        ).first()
        if row is None:
            raise LinkError(f"source {fid} not found")
        length = len(row[0] or "")
        if pos1 > length:
            raise LinkError(f"{side} span: pos1 exceeds the source text length ({length})")

    async def _sync(self, action: str, link_id: int, data: dict) -> None:
        from qualcoder_api.services import sync

        if action == "insert":
            await sync.capture_insert(
                self.session, entity="link", pk_name="id", pk_value=link_id, row=data
            )
        elif action == "update":
            await sync.capture_update(
                self.session, entity="link", pk_name="id", pk_value=link_id, row=data
            )
        else:
            await sync.capture_delete(
                self.session, entity="link", pk_name="id", pk_value=link_id, row=data
            )
