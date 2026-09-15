"""Eligibility helper — which hits pass screening (all criteria = Yes).

Local-only in v1: the pipeline reads verdict rows directly from
``meta_screening`` (never through the collaboration-synced views).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.models import MetaHit


def verdict_all_yes(verdicts: dict) -> bool:
    """True when every criterion verdict applies == "Yes"."""
    if not verdicts:
        return False
    return all(
        str(v.get("applies") or "").strip().lower() == "yes"
        for v in verdicts.values()
    )


async def eligible_hit_ids(session: AsyncSession, hits: list[MetaHit]) -> set[int]:
    """Latest screening row per hit (any coder) that passes all criteria.

    "Latest" = highest ``meta_screening.id`` (rows are append-only upserts,
    so id order matches write order).
    """
    if not hits:
        return set()
    rows = (
        await session.execute(
            text(
                "SELECT hit_id, verdicts FROM meta_screening "
                "WHERE id IN (SELECT MAX(id) FROM meta_screening GROUP BY hit_id)"
            )
        )
    ).all()
    latest = {int(r[0]): r[1] for r in rows}
    import json

    eligible = set()
    for hit in hits:
        raw = latest.get(hit.hit_id)
        if not raw:
            continue
        try:
            verdicts = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if verdict_all_yes(verdicts):
            eligible.add(hit.hit_id)
    return eligible
