"""Screening eligibility — the single inclusion rule (contract §2/§10).

``evaluate_criteria`` is used by screening, downloads, extraction and (later)
PRISMA, so inclusion is never computed twice with different semantics.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.models import MetaCriterion, MetaHit


def _applies(entry: Any) -> Any:
    """The comparable verdict value from a verdict entry."""
    if isinstance(entry, dict):
        return entry.get("applies")
    return entry


def _norm(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else str(value)
    return str(value or "").strip().lower()


def _passes(value: Any, pass_values: list) -> bool:
    wanted = {_norm(v) for v in (pass_values or ["yes"])}
    return _norm(value) in wanted


def criterion_passes(criterion: MetaCriterion, entry: Any) -> bool:
    """Whether one criterion's verdict entry passes."""
    value = _applies(entry)
    if value is None:
        return False
    return _passes(value, list(criterion.pass_values or ["yes"]))


def evaluate_criteria(
    criteria: list[MetaCriterion], verdicts: dict | None
) -> dict[str, Any]:
    """Evaluate a screening verdict set against the configured criteria.

    Returns ``{"eligible": bool, "failing": [keys], "reasons": [labels]}``.

    * ``gating=0`` criteria are informational and never block inclusion.
    * ``verdict`` criteria pass when the verdict is in ``pass_values``
      (default ``["yes"]``); ``classify``/``number`` criteria compare the
      selected/number value against ``pass_values``.
    * With no configured criteria the legacy rule applies (every recorded
      verdict must be an affirmative ``yes``), so v1 projects keep working.
    """
    verdicts = verdicts or {}
    if not verdicts:
        return {"eligible": False, "failing": [], "reasons": []}

    if not criteria:
        ok = all(_passes(_applies(v), ["yes"]) for v in verdicts.values())
        return {"eligible": ok, "failing": [], "reasons": []}

    failing: list[str] = []
    reasons: list[str] = []
    for criterion in criteria:
        if not getattr(criterion, "gating", 1):
            continue
        if criterion_passes(criterion, verdicts.get(criterion.key)):
            continue
        failing.append(criterion.key)
        reasons.append(criterion.exclude_reason or criterion.label or criterion.key)
    return {"eligible": not failing, "failing": failing, "reasons": reasons}


async def eligible_hit_ids(session: AsyncSession, hits: list[MetaHit]) -> set[int]:
    """Latest screening row per hit (any coder) that passes all criteria.

    "Latest" = highest ``meta_screening.id`` (rows are append-only upserts,
    so id order matches write order).
    """
    if not hits:
        return set()
    from qualcoder_api.persistence.repo.meta_repo import MetaRepository

    criteria = await MetaRepository(session).list_criteria()
    rows = (
        await session.execute(
            text(
                "SELECT hit_id, verdicts FROM meta_screening "
                "WHERE id IN (SELECT MAX(id) FROM meta_screening GROUP BY hit_id)"
            )
        )
    ).all()
    latest = {int(r[0]): r[1] for r in rows}
    eligible = set()
    for hit in hits:
        raw = latest.get(hit.hit_id)
        if not raw:
            continue
        try:
            verdicts = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if evaluate_criteria(criteria, verdicts)["eligible"]:
            eligible.add(hit.hit_id)
    return eligible
