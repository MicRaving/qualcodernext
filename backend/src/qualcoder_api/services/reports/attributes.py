"""Attribute reports: attribute listing and code x attribute crosstabs."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.services.reports._shared import (
    _attr_definition,
    _crosstab_stats,
    _sorted_values,
    _unit_coding_sets,
    _units_with_values,
)


async def attributes_report(session: AsyncSession) -> list[dict]:
    """All attribute values with the owning entity's name."""
    rows = await session.execute(
        text(
            "SELECT a.name, COALESCE(a.value, ''), a.attr_type, "
            "COALESCE(s.name, c.name) AS entity_name "
            "FROM attribute a "
            "LEFT JOIN source s ON a.attr_type = 'file' AND s.id = a.id "
            "LEFT JOIN cases c ON a.attr_type = 'case' AND c.caseid = a.id "
            "WHERE (a.attr_type = 'file' AND s.id IS NOT NULL) "
            "OR (a.attr_type = 'case' AND c.caseid IS NOT NULL) "
            "ORDER BY a.name, entity_name"
        )
    )
    return [
        {
            "name": name,
            "value": value,
            "attr_type": attr_type,
            "entity_kind": attr_type,
            "entity_name": entity_name,
        }
        for name, value, attr_type, entity_name in rows
    ]


async def crosstab(
    session: AsyncSession,
    attr_name: str,
    codes: list[int] | None,
    scope: str,
) -> dict:
    """Contingency of code presence (rows) x attribute values (columns).

    Rows are the selected codes (default: every code present in the scope);
    columns are the distinct attribute values. Each cell counts the units
    (cases or files) that carry the value AND have the code present. Returns
    the matrix plus chi-square / Cramér's V.
    """
    definition = await _attr_definition(session, attr_name)
    if definition is not None and definition["scope"] != scope:
        raise ValueError(
            f"attribute '{attr_name}' is a {definition['scope']}-scope attribute"
        )
    units, values = await _units_with_values(session, scope, attr_name)
    presence = await _unit_coding_sets(session, scope)

    code_rows = await session.execute(
        text("SELECT cid, name, COALESCE(color, '') FROM code_name ORDER BY name")
    )
    all_codes = [
        {"cid": cid, "name": name, "color": color}
        for cid, name, color in code_rows
    ]
    selected = [c for c in all_codes if codes is None or c["cid"] in codes]
    if codes is None:
        present_cids = {cid for cids in presence.values() for cid in cids}
        selected = [c for c in selected if c["cid"] in present_cids]

    columns = _sorted_values(set(values.values()))
    code_ids = [c["cid"] for c in selected]
    matrix = [
        [
            sum(
                1
                for unit in units
                if values.get(unit["id"]) == column
                and code_ids[ri] in presence.get(unit["id"], set())
            )
            for column in columns
        ]
        for ri in range(len(selected))
    ]
    stats = _crosstab_stats(matrix, columns)
    return {
        "attr_name": attr_name,
        "scope": scope,
        "units_total": len(units),
        "units_with_value": len(values),
        "codes": selected,
        "values": columns,
        "counts": matrix,
        "row_totals": [sum(row) for row in matrix],
        "col_totals": [sum(row[c] for row in matrix) for c in range(len(columns))],
        "stats": stats,
    }
