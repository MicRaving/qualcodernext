"""Meta-analysis screening — LLM-driven abstract screening.

Adapted from the reference ``Inoculation_Meta/meta/core/screening.py``:
clusters of abstracts per request, per-criterion applies/certainty verdicts,
resumable passes, and a deterministic ``prompt_hash``. Writes verdict rows
through ``MetaRepository`` (local-only in v1).
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qualcoder_api.core.models import MetaCriterion, MetaHit
from qualcoder_api.persistence.repo.meta_repo import MetaRepository
from qualcoder_api.services import ai_service
from qualcoder_api.services.meta_eligibility import verdict_all_yes
from qualcoder_api.services.meta_prompt import (
    build_cluster_messages,
    criteria_prompt_hash,
    extract_json,
)
from qualcoder_api.services.user_settings import get_ai_settings

logger = logging.getLogger(__name__)

CRITERION_KEYS = ("applies", "certainty")

# Free-text answers are normalized so a stray "YES"/"maybe"/"moderate" from the
# model never leaks into the UI or breaks the all-Yes eligibility rule.
_APPLIES_MAP = {
    "yes": "Yes",
    "no": "No",
    "unsure": "Unsure",
    "maybe": "Unsure",
    "unclear": "Unsure",
    "unknown": "Unsure",
    "possibly": "Unsure",
    "partial": "Unsure",
}
_CERTAINTY_MAP = {
    "high": "High",
    "medium": "Medium",
    "moderate": "Medium",
    "low": "Low",
}


def _normalize(raw: object, mapping: dict[str, str], default: str) -> str:
    return mapping.get(str(raw or "").strip().lower(), default)


def parse_verdicts(entry: dict, criteria: list[MetaCriterion]) -> dict:
    """Extract a clean verdicts dict from one LLM response entry.

    Accepts the documented ``criterionN_applies`` / ``criterionN_certainty``
    keys, and also tolerates the model answering under the criterion's own key
    (a bool or ``{"applies": ...}``), which schema-agnostic models often do.
    """
    verdicts: dict = {}
    for i, criterion in enumerate(criteria, start=1):
        raw_applies = entry.get(f"criterion{i}_applies")
        if raw_applies is None:
            alt = entry.get(criterion.key)
            if isinstance(alt, bool):
                raw_applies = "Yes" if alt else "No"
            elif isinstance(alt, dict):
                raw_applies = alt.get("applies")
            elif isinstance(alt, str):
                raw_applies = alt
        if raw_applies is None:
            continue
        verdicts[criterion.key] = {
            "applies": _normalize(raw_applies, _APPLIES_MAP, "Unsure"),
            "certainty": _normalize(entry.get(f"criterion{i}_certainty"), _CERTAINTY_MAP, "Medium"),
        }
    return verdicts


def _index_to_position(raw: object, count: int, fallback: int) -> int | None:
    """Map a model-reported index to a 0-based cluster position.

    Accepts both 0-based and 1-based numbering; anything out of range falls
    back to the array position so a result is never written to the wrong hit.
    """
    try:
        idx = int(str(raw).strip().lower().replace("study", "").strip())
    except (TypeError, ValueError):
        return fallback if 0 <= fallback < count else None
    if 1 <= idx <= count:
        return idx - 1
    if 0 <= idx < count:
        return idx
    return fallback if 0 <= fallback < count else None


def assign_entries(parsed: object, count: int) -> dict[int, dict]:
    """Map an LLM response to 0-based cluster positions.

    Array order is the primary contract (the prompt demands the same order);
    the reported ``index`` is only trusted when the array length disagrees.
    """
    if isinstance(parsed, dict):
        return {0: parsed} if count == 1 else {}
    if not isinstance(parsed, list):
        return {}
    result: dict[int, dict] = {}
    if len(parsed) == count:
        return {pos: entry for pos, entry in enumerate(parsed) if isinstance(entry, dict)}
    for arr_pos, entry in enumerate(parsed):
        if not isinstance(entry, dict):
            continue
        pos = _index_to_position(entry.get("index"), count, arr_pos)
        if pos is not None and pos not in result:
            result[pos] = entry
    return result


async def _screen_cluster(
    session: AsyncSession,
    ai: dict,
    criteria: list[MetaCriterion],
    items: list[tuple[int, MetaHit]],
    owner: str,
    run_id: str,
    prompt_hash: str,
) -> int:
    """Screen one cluster with a single LLM request; returns rows written."""
    # Studies are labelled 1..N in the prompt (position, not hit_id) and the
    # response is mapped back by position — a model that renumbers or omits the
    # index can then never write a verdict to the wrong hit.
    messages = build_cluster_messages(
        [(pos + 1, hit.model_dump()) for pos, (_hid, hit) in enumerate(items)],
        criteria,
        max_context_chars=24000,
        max_response_chars=8000,
    )
    service = ai_service.AiService(None)
    raw = await service.chat_messages(ai, messages)
    parsed = extract_json(raw)
    assigned = assign_entries(parsed, len(items))

    repo = MetaRepository(session)
    written = 0
    for pos, entry in assigned.items():
        if pos < 0 or pos >= len(items):
            continue
        hit_id = items[pos][0]
        verdicts = parse_verdicts(entry, criteria)
        if not verdicts:
            continue
        await repo.upsert_screening(
            hit_id=hit_id,
            owner=owner,
            run_id=run_id,
            verdicts=verdicts,
            intervention_type=entry.get("intervention_type"),
            rationale=entry.get("comments"),
            origin="llm",
            model=ai.get("model"),
            prompt_hash=prompt_hash,
        )
        # Keep the hit status in sync so the whole-queue download/extraction
        # passes (and the UI badge) reflect the AI verdict immediately.
        await repo.set_hit_status(hit_id, "included" if verdict_all_yes(verdicts) else "excluded")
        written += 1
    return written


async def llm_screen_hits(
    session_factory: async_sessionmaker,
    *,
    criteria: list[MetaCriterion],
    hit_ids: list[int] | None,
    owner: str,
    run_id: str,
    model: str | None = None,
    cluster_size: int = 8,
    progress_cb=None,
    should_stop=None,
) -> dict:
    """Screen (or resume screening) the given hits with the LLM.

    Returns a summary dict. Progress callback receives (done, total).
    """
    progress_cb = progress_cb or (lambda done, total: None)
    should_stop = should_stop or (lambda: False)
    ai = get_ai_settings()
    if not ai.get("enabled"):
        raise ValueError("AI is not enabled — enable it in Settings first.")
    if model:
        ai = {**ai, "model": model}
    prompt_hash = criteria_prompt_hash(criteria)

    async with session_factory() as session:
        repo = MetaRepository(session)
        if hit_ids:
            hits = [h for h in [await repo.get_hit(hid) for hid in hit_ids] if h is not None]
        else:
            hits = await repo.list_hits()
        # Resume: skip hits already screened for this (owner, run).
        existing = {
            s.hit_id for s in await repo.list_screening(owner=owner, run_id=run_id)
        }
        pending = [h for h in hits if h.hit_id not in existing]

        clusters = [pending[i : i + cluster_size] for i in range(0, len(pending), cluster_size)]
        total = len(pending)
        done = 0
        written = 0
        stopped = False
        for cluster in clusters:
            if should_stop():
                stopped = True
                break
            items = [(h.hit_id, h) for h in cluster]
            try:
                written += await _screen_cluster(
                    session, ai, criteria, items, owner, run_id, prompt_hash
                )
            except ai_service.AiUnavailable as err:
                logger.warning("LLM screening failed for a cluster: %s", err)
                break
            done += len(cluster)
            progress_cb(done, total)
            await session.commit()

    return {
        "total": total,
        "processed": done,
        "written": written,
        "stopped": stopped,
        "prompt_hash": prompt_hash,
        "model": ai.get("model"),
    }
