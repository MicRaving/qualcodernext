"""Shared helpers for the repository package.

``_capture`` and ``_rowdict`` bridge to ``audit_capture`` lazily (inside the
functions) to keep the import graph acyclic — do not move them to the module
top level.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy.engine import CursorResult, Result

# ``_now`` is re-exported via the ``repo`` barrel (``repositories.py`` shim),
# so keep the alias import even though base.py itself never calls it.
from qualcoder_api.core.timeutil import now as _now  # noqa: F401


def _coding_row(mapping) -> dict:
    """Normalize a raw coding row for model validation.

    Legacy data may carry ``important = NULL``; the models require an int,
    so NULL is coerced to 0 (the column default).
    """
    data = dict(mapping)
    if data.get("important") is None:
        data["important"] = 0
    return data


def _inserted_pk(result: Result[Any]) -> int:
    """First inserted primary key from an INSERT statement result.

    ``AsyncSession.execute`` is statically typed as returning ``Result``,
    but for INSERT/DML statements the runtime type is ``CursorResult``
    which carries ``inserted_primary_key``.
    """
    pk = cast(CursorResult[Any], result).inserted_primary_key
    if pk is None:  # pragma: no cover - inserts always return a pk here
        raise RuntimeError("insert returned no primary key")
    return int(pk[0])


def _rowdict(row) -> dict:
    """Raw table-column dict from a row mapping (sync-safe snapshot)."""
    from qualcoder_api.persistence import audit_capture

    return audit_capture.table_row(row._mapping)


async def _capture(
    session, entity: str, action: str, pk_name: str, pk_value: int | str | None, row: dict | None
) -> None:
    from qualcoder_api.persistence import audit_capture

    await audit_capture.capture(
        session, entity=entity, action=action, pk_name=pk_name, pk_value=pk_value, row=row
    )
