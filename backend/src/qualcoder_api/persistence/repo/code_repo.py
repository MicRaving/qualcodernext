"""Code and category tree repository (``code_name``/``code_cat`` tables)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.models import Category, Code
from qualcoder_api.core.palette import random_code_color
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repo.base import _inserted_pk, _now, _rowdict


class CodeRepository:
    """CRUD for codes, categories, and the codebook tree."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_categories(self) -> list[Category]:
        rows = await self.session.execute(
            select(tables.code_cat).order_by(
                tables.code_cat.c.position, tables.code_cat.c.catid
            )
        )
        return [Category.model_validate(r._mapping) for r in rows]

    async def list_codes(self) -> list[Code]:
        rows = await self.session.execute(
            select(tables.code_name).order_by(
                tables.code_name.c.position, tables.code_name.c.cid
            )
        )
        return [Code.model_validate(r._mapping) for r in rows]

    async def _code_group_position(
        self, *, catid: int | None, supercid: int | None
    ) -> int:
        """Append position for a new member of a code sibling group.

        Sub-codes are grouped by their parent code; plain codes by their
        category (NULL = root).
        """
        if supercid is not None:
            stmt = (
                select(func.coalesce(func.max(tables.code_name.c.position), -1) + 1)
                .where(tables.code_name.c.supercid == supercid)
            )
        else:
            stmt = (
                select(func.coalesce(func.max(tables.code_name.c.position), -1) + 1)
                .where(
                    tables.code_name.c.supercid.is_(None),
                    tables.code_name.c.catid.is_(catid)
                    if catid is None
                    else tables.code_name.c.catid == catid,
                )
            )
        return int((await self.session.execute(stmt)).scalar_one())

    async def _category_group_position(self, supercatid: int | None) -> int:
        stmt = (
            select(func.coalesce(func.max(tables.code_cat.c.position), -1) + 1)
            .where(
                tables.code_cat.c.supercatid.is_(supercatid)
                if supercatid is None
                else tables.code_cat.c.supercatid == supercatid
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def _code_siblings(
        self, *, catid: int | None, supercid: int | None
    ) -> list[int]:
        """cids of one code sibling group in tree order (position, cid)."""
        if supercid is not None:
            stmt = (
                select(tables.code_name.c.cid)
                .where(tables.code_name.c.supercid == supercid)
                .order_by(tables.code_name.c.position, tables.code_name.c.cid)
            )
        else:
            stmt = (
                select(tables.code_name.c.cid)
                .where(
                    tables.code_name.c.supercid.is_(None),
                    tables.code_name.c.catid.is_(catid)
                    if catid is None
                    else tables.code_name.c.catid == catid,
                )
                .order_by(tables.code_name.c.position, tables.code_name.c.cid)
            )
        rows = await self.session.execute(stmt)
        return [int(r[0]) for r in rows]

    async def _category_siblings(self, supercatid: int | None) -> list[int]:
        stmt = (
            select(tables.code_cat.c.catid)
            .where(
                tables.code_cat.c.supercatid.is_(supercatid)
                if supercatid is None
                else tables.code_cat.c.supercatid == supercatid
            )
            .order_by(tables.code_cat.c.position, tables.code_cat.c.catid)
        )
        rows = await self.session.execute(stmt)
        return [int(r[0]) for r in rows]

    async def _set_code_positions(self, cids: list[int]) -> None:
        """Renumber a sibling group: positions 0..n-1 in list order."""
        for index, cid in enumerate(cids):
            await self.session.execute(
                update(tables.code_name)
                .where(tables.code_name.c.cid == cid)
                .values(position=index)
            )

    async def _set_category_positions(self, catids: list[int]) -> None:
        for index, catid in enumerate(catids):
            await self.session.execute(
                update(tables.code_cat)
                .where(tables.code_cat.c.catid == catid)
                .values(position=index)
            )

    async def _merged_root(self) -> list[tuple[str, int]]:
        """The root sibling group merged across both tables, in tree order.

        Root-level codes and categories share ONE child list; ordering is
        (position, id) with the two tables interleaved (the same sort the
        tree endpoint applies). Positions are renumbered jointly so the two
        tables never collide.
        """
        code_rows = await self.session.execute(
            select(tables.code_name.c.cid, tables.code_name.c.position).where(
                tables.code_name.c.catid.is_(None),
                tables.code_name.c.supercid.is_(None),
            )
        )
        cat_rows = await self.session.execute(
            select(tables.code_cat.c.catid, tables.code_cat.c.position).where(
                tables.code_cat.c.supercatid.is_(None)
            )
        )
        merged = [("code", int(r[0]), int(r[1])) for r in code_rows]
        merged += [("cat", int(r[0]), int(r[1])) for r in cat_rows]
        merged.sort(key=lambda entry: (entry[2], entry[1]))
        return [(entry[0], entry[1]) for entry in merged]

    async def _renumber_merged_root(self, merged: list[tuple[str, int]]) -> None:
        for index, (kind, id_) in enumerate(merged):
            if kind == "code":
                await self.session.execute(
                    update(tables.code_name)
                    .where(tables.code_name.c.cid == id_)
                    .values(position=index)
                )
            else:
                await self.session.execute(
                    update(tables.code_cat)
                    .where(tables.code_cat.c.catid == id_)
                    .values(position=index)
                )

    async def root_rank_of(self, kind: str, id_: int) -> int | None:
        """Visual rank of a root-level item in the merged root list (None
        when the item is not at the root) — used by promote to conserve
        positions across the code/category boundary."""
        merged = await self._merged_root()
        for index, (entry_kind, entry_id) in enumerate(merged):
            if entry_kind == kind and entry_id == id_:
                return index
        return None

    async def add_code(
        self,
        *,
        name: str,
        owner: str,
        catid: int | None = None,
        color: str | None = None,
        memo: str = "",
        supercid: int | None = None,
    ) -> Code | None:
        if color is None:
            color = random_code_color()
        position = await self._code_group_position(catid=catid, supercid=supercid)
        result = await self.session.execute(
            insert(tables.code_name).values(
                name=name, memo=memo, owner=owner, date=_now(), catid=catid, color=color,
                supercid=supercid, position=position,
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.code_name).where(
                    tables.code_name.c.cid == _inserted_pk(result)
                )
            )
        ).first()
        code = Code.model_validate(row._mapping) if row else None
        from qualcoder_api.persistence import audit_capture

        if row is not None:
            await audit_capture.capture_insert(
                self.session, entity="code_name", pk_name="cid", pk_value=row.cid,
                row=audit_capture.table_row(row._mapping),
            )
        await self.session.commit()
        return code

    async def add_category(
        self,
        *,
        name: str,
        owner: str,
        supercatid: int | None = None,
        memo: str = "",
    ) -> Category | None:
        position = await self._category_group_position(supercatid)
        result = await self.session.execute(
            insert(tables.code_cat).values(
                name=name, memo=memo, owner=owner, date=_now(), supercatid=supercatid,
                position=position,
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.code_cat).where(
                    tables.code_cat.c.catid == _inserted_pk(result)
                )
            )
        ).first()
        category = Category.model_validate(row._mapping) if row else None
        from qualcoder_api.persistence import audit_capture

        if row is not None:
            await audit_capture.capture_insert(
                self.session, entity="code_cat", pk_name="catid", pk_value=row.catid,
                row=audit_capture.table_row(row._mapping),
            )
        await self.session.commit()
        return category

    async def rename_code(self, cid: int, name: str) -> Code | None:
        await self.session.execute(
            update(tables.code_name).where(tables.code_name.c.cid == cid).values(name=name)
        )
        await self.session.commit()
        code = await self.get_code(cid)
        from qualcoder_api.persistence import audit_capture

        if code is not None:
            row = (
                await self.session.execute(
                    select(tables.code_name).where(tables.code_name.c.cid == cid)
                )
            ).first()
            await audit_capture.capture_update(
                self.session, entity="code_name", pk_name="cid", pk_value=cid,
                row=audit_capture.table_row(row._mapping) if row else None,
            )
            await self.session.commit()
        return code

    async def set_supercid(self, cid: int, supercid: int | None) -> Code | None:
        """Nest ``cid`` under code ``supercid`` (sub-codes, upstream v16).

        Raises ``ValueError`` when nesting would create a cycle (a code
        cannot be its own ancestor).
        """
        if supercid is not None:
            if supercid == cid:
                raise ValueError("a code cannot be its own parent")
            # Walk up the parent chain from supercid; if we reach cid, cycle.
            seen: set[int] = set()
            current: int | None = supercid
            while current is not None and current not in seen:
                if current == cid:
                    raise ValueError("cannot nest a code under its own sub-code")
                seen.add(current)
                parent_row = (
                    await self.session.execute(
                        select(tables.code_name.c.supercid).where(
                            tables.code_name.c.cid == current
                        )
                    )
                ).first()
                current = int(parent_row[0]) if parent_row is not None and parent_row[0] is not None else None
        await self.session.execute(
            update(tables.code_name).where(tables.code_name.c.cid == cid).values(supercid=supercid)
        )
        await self.session.commit()
        code = await self.get_code(cid)
        from qualcoder_api.persistence import audit_capture

        if code is not None:
            row = (
                await self.session.execute(
                    select(tables.code_name).where(tables.code_name.c.cid == cid)
                )
            ).first()
            await audit_capture.capture_update(
                self.session, entity="code_name", pk_name="cid", pk_value=cid,
                row=audit_capture.table_row(row._mapping) if row else None,
            )
            await self.session.commit()
        return code

    async def get_code(self, cid: int) -> Code | None:
        row = (
            await self.session.execute(
                select(tables.code_name).where(tables.code_name.c.cid == cid)
            )
        ).first()
        return Code.model_validate(row._mapping) if row else None

    async def get_category(self, catid: int) -> Category | None:
        row = (
            await self.session.execute(
                select(tables.code_cat).where(tables.code_cat.c.catid == catid)
            )
        ).first()
        return Category.model_validate(row._mapping) if row else None

    async def set_code_catid(self, cid: int, catid: int | None) -> Code | None:
        """Move a code between categories (or to the root with ``None``)."""
        await self.session.execute(
            update(tables.code_name).where(tables.code_name.c.cid == cid).values(catid=catid)
        )
        await self.session.commit()
        code = await self.get_code(cid)
        from qualcoder_api.persistence import audit_capture

        if code is not None:
            row = (
                await self.session.execute(
                    select(tables.code_name).where(tables.code_name.c.cid == cid)
                )
            ).first()
            await audit_capture.capture_update(
                self.session, entity="code_name", pk_name="cid", pk_value=cid,
                row=audit_capture.table_row(row._mapping) if row else None,
            )
            await self.session.commit()
        return code

    async def move_code(
        self,
        cid: int,
        *,
        catid: int | None,
        supercid: int | None,
        after_cid: int | None = None,
        before_cid: int | None = None,
        position: int | None = None,
    ) -> Code | None:
        """Reposition/reparent a code inside the tree (drag & drop).

        The destination group is ``supercid`` when not None (the code
        becomes a sub-code of that code; its category is left untouched —
        legacy demote semantics) or the ``catid`` category group otherwise
        (``None`` = root; ``supercid`` is cleared). The landing slot is
        pinned by ``after_cid``/``before_cid`` (members of the destination
        group), or an explicit ``position`` index; without any pin the code
        is appended at the end of the group. The moved code's old group and
        the destination group are both renumbered; the root group spans both
        tables (codes + categories) so cross-kind ordering stays exact.

        Raises ``ValueError`` when the move would create a cycle (a code
        cannot be nested under its own descendant).
        """
        code = await self.get_code(cid)
        if code is None:
            return None
        if supercid is not None:
            if supercid == cid:
                raise ValueError("a code cannot be its own parent")
            # Walk up the parent chain from supercid; if we reach cid, cycle.
            seen: set[int] = set()
            current: int | None = supercid
            while current is not None and current not in seen:
                if current == cid:
                    raise ValueError("cannot nest a code under its own sub-code")
                seen.add(current)
                parent_row = (
                    await self.session.execute(
                        select(tables.code_name.c.supercid).where(
                            tables.code_name.c.cid == current
                        )
                    )
                ).first()
                current = (
                    int(parent_row[0])
                    if parent_row is not None and parent_row[0] is not None
                    else None
                )
        if after_cid is not None and before_cid is not None:
            raise ValueError("after_cid and before_cid are mutually exclusive")
        anchor = after_cid if after_cid is not None else before_cid
        if anchor is not None and anchor == cid:
            raise ValueError("cannot move a code relative to itself")

        root_destination = supercid is None and catid is None
        if root_destination:
            # The root child list spans both tables — renumber them jointly.
            full: list[tuple[str, int]] = await self._merged_root()
        else:
            full = [
                ("code", cid_)
                for cid_ in await self._code_siblings(catid=catid, supercid=supercid)
            ]
        if anchor is not None and anchor not in [v for _, v in full]:
            raise ValueError("target sibling is not in the destination group")
        old_index = full.index(("code", cid)) if ("code", cid) in full else None
        rest = [entry for entry in full if entry != ("code", cid)]
        if after_cid is not None:
            after_idx = [v for _, v in full].index(after_cid)
            if old_index is not None and old_index < after_idx:
                after_idx -= 1
            insert_at = after_idx + 1
        elif before_cid is not None:
            before_idx = [v for _, v in full].index(before_cid)
            if old_index is not None and old_index < before_idx:
                before_idx -= 1
            insert_at = before_idx
        elif position is not None:
            insert_at = max(0, min(position, len(rest)))
        else:
            insert_at = len(rest)
        rest.insert(insert_at, ("code", cid))

        if root_destination:
            await self.session.execute(
                update(tables.code_name)
                .where(tables.code_name.c.cid == cid)
                .values(catid=None, supercid=None)
            )
            await self._renumber_merged_root(rest)
        else:
            values: dict[str, Any] = {"position": insert_at}
            if supercid is not None:
                values["supercid"] = supercid
            else:
                values["supercid"] = None
                values["catid"] = catid
            await self.session.execute(
                update(tables.code_name)
                .where(tables.code_name.c.cid == cid)
                .values(**values)
            )
            await self._set_code_positions([id_ for _, id_ in rest])
        await self.session.commit()
        moved = await self.get_code(cid)
        from qualcoder_api.persistence import audit_capture

        if moved is not None:
            row = (
                await self.session.execute(
                    select(tables.code_name).where(tables.code_name.c.cid == cid)
                )
            ).first()
            await audit_capture.capture_update(
                self.session, entity="code_name", pk_name="cid", pk_value=cid,
                row=audit_capture.table_row(row._mapping) if row else None,
            )
            await self.session.commit()
        return moved

    async def move_category(
        self,
        catid: int,
        supercatid: int | None,
        *,
        after_catid: int | None = None,
        before_catid: int | None = None,
        position: int | None = None,
    ) -> Category | None:
        """Reparent/reposition a category in the tree (promote/demote/DnD).

        ``after_catid``/``before_catid`` pin the landing slot among the
        destination group's members; ``position`` is an explicit index;
        without any pin the category is appended at the end. The old and
        new sibling groups are renumbered.

        Raises ``ValueError`` when the move would create a cycle (a
        category cannot be its own ancestor).
        """
        category = await self.get_category(catid)
        if category is None:
            return None
        if supercatid is not None:
            if supercatid == catid:
                raise ValueError("a category cannot be its own parent")
            # Walk up the parent chain from supercatid; if we reach catid, cycle.
            seen: set[int] = set()
            current: int | None = supercatid
            while current is not None and current not in seen:
                if current == catid:
                    raise ValueError("cannot nest a category under its own sub-category")
                seen.add(current)
                parent_row = (
                    await self.session.execute(
                        select(tables.code_cat.c.supercatid).where(
                            tables.code_cat.c.catid == current
                        )
                    )
                ).first()
                current = (
                    int(parent_row[0])
                    if parent_row is not None and parent_row[0] is not None
                    else None
                )
        if after_catid is not None and before_catid is not None:
            raise ValueError("after_catid and before_catid are mutually exclusive")
        anchor = after_catid if after_catid is not None else before_catid
        if anchor is not None and anchor == catid:
            raise ValueError("cannot move a category relative to itself")

        root_destination = supercatid is None
        if root_destination:
            # The root child list spans both tables — renumber them jointly.
            full: list[tuple[str, int]] = await self._merged_root()
        else:
            full = [
                ("cat", catid_)
                for catid_ in await self._category_siblings(supercatid)
            ]
        if anchor is not None and anchor not in [v for _, v in full]:
            raise ValueError("target sibling is not in the destination group")
        old_index = full.index(("cat", catid)) if ("cat", catid) in full else None
        rest = [entry for entry in full if entry != ("cat", catid)]
        if after_catid is not None:
            after_idx = [v for _, v in full].index(after_catid)
            if old_index is not None and old_index < after_idx:
                after_idx -= 1
            insert_at = after_idx + 1
        elif before_catid is not None:
            before_idx = [v for _, v in full].index(before_catid)
            if old_index is not None and old_index < before_idx:
                before_idx -= 1
            insert_at = before_idx
        elif position is not None:
            insert_at = max(0, min(position, len(rest)))
        else:
            insert_at = len(rest)
        rest.insert(insert_at, ("cat", catid))

        if root_destination:
            await self.session.execute(
                update(tables.code_cat)
                .where(tables.code_cat.c.catid == catid)
                .values(supercatid=None)
            )
            await self._renumber_merged_root(rest)
        else:
            await self.session.execute(
                update(tables.code_cat)
                .where(tables.code_cat.c.catid == catid)
                .values(supercatid=supercatid, position=insert_at)
            )
            await self._set_category_positions([id_ for _, id_ in rest])
        await self.session.commit()
        moved = await self.get_category(catid)
        from qualcoder_api.persistence import audit_capture

        if moved is not None:
            row = (
                await self.session.execute(
                    select(tables.code_cat).where(tables.code_cat.c.catid == catid)
                )
            ).first()
            await audit_capture.capture_update(
                self.session, entity="code_cat", pk_name="catid", pk_value=catid,
                row=audit_capture.table_row(row._mapping) if row else None,
            )
            await self.session.commit()
        return moved

    async def previous_sibling_code(
        self, cid: int, *, catid: int | None, supercid: int | None
    ) -> int | None:
        """The code immediately before ``cid`` at the same level (demote target).

        Siblings share the same category and the same parent code (either
        can be NULL — matched NULL-safely); the previous sibling is the
        member directly before ``cid`` in (position, cid) order.
        """
        members = await self._code_siblings(catid=catid, supercid=supercid)
        index = members.index(cid) if cid in members else -1
        if index <= 0:
            return None
        return members[index - 1]

    async def previous_sibling_category(self, catid: int, *, supercatid: int | None) -> int | None:
        """The category immediately before ``catid`` at the same level."""
        members = await self._category_siblings(supercatid)
        index = members.index(catid) if catid in members else -1
        if index <= 0:
            return None
        return members[index - 1]

    async def code_sibling_index(
        self, cid: int, *, catid: int | None, supercid: int | None
    ) -> int | None:
        """0-based index of ``cid`` within its sibling group (None when
        absent) — used by promote to conserve positions."""
        members = await self._code_siblings(catid=catid, supercid=supercid)
        return members.index(cid) if cid in members else None

    async def category_sibling_index(self, catid: int, *, supercatid: int | None) -> int | None:
        members = await self._category_siblings(supercatid)
        return members.index(catid) if catid in members else None

    async def delete_code(self, cid: int) -> None:
        """Delete a code and all its codings (legacy order)."""
        from qualcoder_api.persistence import audit_capture

        for tbl, col, pk in (
            (tables.code_name, tables.code_name.c.cid, "cid"),
            (tables.code_text, tables.code_text.c.cid, "ctid"),
            (tables.code_av, tables.code_av.c.cid, "avid"),
            (tables.code_image, tables.code_image.c.cid, "imid"),
        ):
            rows = (await self.session.execute(select(tbl).where(col == cid))).all()
            await self.session.execute(delete(tbl).where(col == cid))
            for row in rows:
                await audit_capture.capture_delete(
                    self.session, entity=tbl.name, pk_name=pk,
                    pk_value=_rowdict(row).get(pk), row=_rowdict(row),
                )
        # Sub-codes of the deleted code are orphaned (reparented to null).
        sub_rows = (
            await self.session.execute(
                select(tables.code_name).where(tables.code_name.c.supercid == cid)
            )
        ).all()
        await self.session.execute(
            update(tables.code_name)
            .where(tables.code_name.c.supercid == cid)
            .values(supercid=None)
        )
        for row in sub_rows:
            data = _rowdict(row)
            data["supercid"] = None
            await audit_capture.capture_update(
                self.session, entity="code_name", pk_name="cid",
                pk_value=data.get("cid"), row=data,
            )
        await self.session.commit()

    async def delete_category(self, catid: int) -> None:
        """Delete a category; reassign orphaned codes and children to null."""
        from qualcoder_api.persistence import audit_capture

        code_rows = (
            await self.session.execute(
                select(tables.code_name).where(tables.code_name.c.catid == catid)
            )
        ).all()
        await self.session.execute(
            update(tables.code_name).where(tables.code_name.c.catid == catid).values(catid=None)
        )
        for row in code_rows:
            data = _rowdict(row)
            data["catid"] = None
            await audit_capture.capture_update(
                self.session, entity="code_name", pk_name="cid",
                pk_value=data.get("cid"), row=data,
            )
        cat_rows = (
            await self.session.execute(
                select(tables.code_cat).where(tables.code_cat.c.supercatid == catid)
            )
        ).all()
        await self.session.execute(
            update(tables.code_cat).where(tables.code_cat.c.supercatid == catid).values(supercatid=None)
        )
        for row in cat_rows:
            data = _rowdict(row)
            data["supercatid"] = None
            await audit_capture.capture_update(
                self.session, entity="code_cat", pk_name="catid",
                pk_value=data.get("catid"), row=data,
            )
        cat_row = (
            await self.session.execute(
                select(tables.code_cat).where(tables.code_cat.c.catid == catid)
            )
        ).first()
        await self.session.execute(
            delete(tables.code_cat).where(tables.code_cat.c.catid == catid)
        )
        if cat_row is not None:
            await audit_capture.capture_delete(
                self.session, entity="code_cat", pk_name="catid", pk_value=catid,
                row=_rowdict(cat_row),
            )
        await self.session.execute(
            text(
                "UPDATE code_cat SET supercatid = NULL "
                "WHERE supercatid IS NOT NULL AND supercatid NOT IN (SELECT catid FROM code_cat)"
            )
        )
        await self.session.commit()

    async def merge_codes(self, old_cid: int, new_cid: int) -> None:
        """Merge code ``old_cid`` into ``new_cid`` (legacy semantics).

        ``code_text`` has a unique(cid,fid,pos0,pos1,owner) constraint: if the
        merged segment would collide with an existing one under ``new_cid``,
        the source row is DELETED (matching legacy ``merge_codes``). The
        ``code_av``/``code_image`` tables have no unique constraint, so their
        rows are reassigned unconditionally.
        """
        rows = (
            await self.session.execute(
                select(tables.code_text).where(tables.code_text.c.cid == old_cid)
            )
        ).all()
        from qualcoder_api.persistence import audit_capture

        for row in rows:
            dup = (
                await self.session.execute(
                    select(tables.code_text.c.ctid).where(
                        tables.code_text.c.cid == new_cid,
                        tables.code_text.c.fid == row.fid,
                        tables.code_text.c.pos0 == row.pos0,
                        tables.code_text.c.pos1 == row.pos1,
                        tables.code_text.c.owner == row.owner,
                    )
                )
            ).first()
            if dup is not None:
                data = audit_capture.table_row(row._mapping)
                await audit_capture.capture_delete(
                    self.session, entity="code_text", pk_name="ctid",
                    pk_value=data.get("ctid"), row=data,
                )
                await self.session.execute(
                    delete(tables.code_text).where(tables.code_text.c.ctid == row.ctid)
                )
            else:
                await self.session.execute(
                    update(tables.code_text)
                    .where(tables.code_text.c.ctid == row.ctid)
                    .values(cid=new_cid)
                )
                data = audit_capture.table_row(row._mapping)
                data["cid"] = new_cid
                await audit_capture.capture_update(
                    self.session, entity="code_text", pk_name="ctid",
                    pk_value=data.get("ctid"), row=data,
                )
        for tbl, col in (
            (tables.code_av, tables.code_av.c.cid),
            (tables.code_image, tables.code_image.c.cid),
        ):
            rows = (await self.session.execute(select(tbl).where(col == old_cid))).all()
            await self.session.execute(
                update(tbl).where(col == old_cid).values(**{col.name: new_cid})
            )
            for row in rows:
                data = audit_capture.table_row(row._mapping)
                data[col.name] = new_cid
                pk = "avid" if tbl is tables.code_av else "imid"
                await audit_capture.capture_update(
                    self.session, entity=tbl.name, pk_name=pk,
                    pk_value=int(data[pk]), row=data,
                )
        # Sub-codes of the merged-away code move under the target code.
        sub_rows = (
            await self.session.execute(
                select(tables.code_name).where(tables.code_name.c.supercid == old_cid)
            )
        ).all()
        await self.session.execute(
            update(tables.code_name)
            .where(tables.code_name.c.supercid == old_cid)
            .values(supercid=new_cid)
        )
        for row in sub_rows:
            data = audit_capture.table_row(row._mapping)
            data["supercid"] = new_cid
            await audit_capture.capture_update(
                self.session, entity="code_name", pk_name="cid",
                pk_value=data.get("cid"), row=data,
            )
        old_row = (
            await self.session.execute(
                select(tables.code_name).where(tables.code_name.c.cid == old_cid)
            )
        ).first()
        await self.session.execute(
            delete(tables.code_name).where(tables.code_name.c.cid == old_cid)
        )
        if old_row is not None:
            await audit_capture.capture_delete(
                self.session, entity="code_name", pk_name="cid", pk_value=old_cid,
                row=audit_capture.table_row(old_row._mapping),
            )
        await self.session.commit()

    async def merge_category(self, catid: int, target_catid: int) -> None:
        """Merge category ``catid`` into ``target_catid``."""
        from qualcoder_api.persistence import audit_capture

        code_rows = (
            await self.session.execute(
                select(tables.code_name).where(tables.code_name.c.catid == catid)
            )
        ).all()
        await self.session.execute(
            update(tables.code_name)
            .where(tables.code_name.c.catid == catid)
            .values(catid=target_catid)
        )
        for row in code_rows:
            data = audit_capture.table_row(row._mapping)
            data["catid"] = target_catid
            await audit_capture.capture_update(
                self.session, entity="code_name", pk_name="cid",
                pk_value=data.get("cid"), row=data,
            )
        cat_row = (
            await self.session.execute(
                select(tables.code_cat).where(tables.code_cat.c.catid == catid)
            )
        ).first()
        await self.session.execute(
            delete(tables.code_cat).where(tables.code_cat.c.catid == catid)
        )
        if cat_row is not None:
            await audit_capture.capture_delete(
                self.session, entity="code_cat", pk_name="catid", pk_value=catid,
                row=audit_capture.table_row(cat_row._mapping),
            )
        sub_rows = (
            await self.session.execute(
                select(tables.code_cat).where(tables.code_cat.c.supercatid == catid)
            )
        ).all()
        await self.session.execute(
            update(tables.code_cat)
            .where(tables.code_cat.c.supercatid == catid)
            .values(supercatid=target_catid)
        )
        for row in sub_rows:
            data = audit_capture.table_row(row._mapping)
            data["supercatid"] = target_catid
            await audit_capture.capture_update(
                self.session, entity="code_cat", pk_name="catid",
                pk_value=data.get("catid"), row=data,
            )
        await self.session.execute(
            text(
                "UPDATE code_cat SET supercatid = NULL "
                "WHERE supercatid IS NOT NULL AND supercatid NOT IN (SELECT catid FROM code_cat)"
            )
        )
        await self.session.commit()
