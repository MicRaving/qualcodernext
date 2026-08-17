"""Attribute repository (``attribute_type``/``attribute`` tables)."""

from __future__ import annotations

import json

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.models import Attribute, AttributeType
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repo.base import _capture, _inserted_pk, _now, _rowdict


class AttributeRepository:
    """CRUD for attribute types and values."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_types(self) -> list[AttributeType]:
        rows = await self.session.execute(
            select(tables.attribute_type).order_by(func.lower(tables.attribute_type.c.name))
        )
        return [AttributeType.model_validate(r._mapping) for r in rows]

    async def add_type(self, *, name: str, owner: str, case_or_file: str = "case",
                       value_type: str = "text", memo: str = "",
                       value_labels: dict[str, str] | None = None) -> AttributeType:
        labels = value_labels or {}
        await self.session.execute(
            insert(tables.attribute_type).values(
                name=name,
                date=_now(),
                owner=owner,
                memo=memo,
                caseOrFile=case_or_file,
                valuetype=value_type,
                value_labels=json.dumps(labels),
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.attribute_type).where(tables.attribute_type.c.name == name)
            )
        ).first()
        if row is not None:
            await _capture(
                self.session, "attribute_type", "insert", "name", name, _rowdict(row)
            )
            await self.session.commit()
        return AttributeType(
            name=name, date=_now(), owner=owner, memo=memo,
            case_or_file=case_or_file, value_type=value_type, value_labels=labels,
        )

    async def delete_type(self, name: str) -> None:
        """Delete an attribute type and all its values.

        ``attribute.name`` holds the attribute type name; ``attribute.attr_type``
        holds the scope ("case"/"file").
        """
        rows = (
            await self.session.execute(select(tables.attribute).where(tables.attribute.c.name == name))
        ).all()
        await self.session.execute(
            delete(tables.attribute).where(tables.attribute.c.name == name)
        )
        for row in rows:
            data = _rowdict(row)
            await _capture(
                self.session, "attribute", "delete", "attrid", data.get("attrid"), data
            )
        type_row = (
            await self.session.execute(
                select(tables.attribute_type).where(tables.attribute_type.c.name == name)
            )
        ).first()
        await self.session.execute(
            delete(tables.attribute_type).where(tables.attribute_type.c.name == name)
        )
        if type_row is not None:
            await _capture(
                self.session, "attribute_type", "delete", "name", name, _rowdict(type_row)
            )
        await self.session.commit()

    async def list_values(self, *, entity_id: int | None = None,
                          attr_type: str | None = None) -> list[Attribute]:
        stmt = select(tables.attribute)
        if entity_id is not None:
            stmt = stmt.where(tables.attribute.c.id == entity_id)
        if attr_type is not None:
            stmt = stmt.where(tables.attribute.c.attr_type == attr_type)
        rows = await self.session.execute(stmt.order_by(tables.attribute.c.name))
        return [Attribute.model_validate(r._mapping) for r in rows]

    async def set_value(self, *, name: str, attr_type: str, value: str,
                        entity_id: int, owner: str) -> Attribute:
        """Insert or replace an attribute value for an entity."""
        existing = (
            await self.session.execute(
                select(tables.attribute).where(
                    tables.attribute.c.name == name,
                    tables.attribute.c.attr_type == attr_type,
                    tables.attribute.c.id == entity_id,
                )
            )
        ).first()
        action = "update" if existing is not None else "insert"
        await self.session.execute(
            delete(tables.attribute).where(
                tables.attribute.c.name == name,
                tables.attribute.c.attr_type == attr_type,
                tables.attribute.c.id == entity_id,
            )
        )
        result = await self.session.execute(
            insert(tables.attribute).values(
                name=name,
                attr_type=attr_type,
                value=value,
                id=entity_id,
                date=_now(),
                owner=owner,
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.attribute).where(
                    tables.attribute.c.attrid == _inserted_pk(result)
                )
            )
        ).first()
        assert row is not None
        await _capture(
            self.session, "attribute", action, "attrid", row.attrid, _rowdict(row)
        )
        await self.session.commit()
        return Attribute.model_validate(row._mapping)
