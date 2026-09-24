"""PRISMA 2020 flow counts (contract §8).

Derived from the imported hits, the append-only screening rows, the
paper-retrieval documents and the extractions. Inclusion is decided only by
``meta_eligibility.evaluate_criteria`` (the single inclusion rule), never
re-implemented here.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from qualcoder_api.core.models import MetaCriterion
from qualcoder_api.persistence.repo.meta_repo import MetaRepository, count_duplicate_hits
from qualcoder_api.services.meta_eligibility import evaluate_criteria
from qualcoder_api.services.meta_roles import role_map, value_by_role
from qualcoder_api.services.meta_scheme import normalise_codebook, study_fields


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _latest_by_hit(rows: list[Any], stage: str) -> dict[Any, Any]:
    latest: dict[Any, Any] = {}
    for row in rows:
        if stage and str(_get(row, "stage", "abstract") or "abstract") != stage:
            continue
        hit_id = _get(row, "hit_id")
        row_id = int(_get(row, "id", 0) or 0)
        current = latest.get(hit_id)
        if current is None or row_id >= int(_get(current, "id", 0) or 0):
            latest[hit_id] = row
    return latest


def _eval_reasons(criteria: list[MetaCriterion], row: Any) -> list[str]:
    verdicts = _get(row, "verdicts", {}) or {}
    return list(evaluate_criteria(criteria, verdicts).get("reasons") or [])


def _row_reason(criteria: list[MetaCriterion], row: Any) -> str:
    explicit = str(_get(row, "reason", "") or "").strip()
    if explicit:
        return explicit
    reasons = _eval_reasons(criteria, row)
    return ", ".join(reasons) if reasons else "Unspecified"


def _reason_list(counter: Counter) -> list[dict[str, Any]]:
    return [
        {"reason": reason, "n": count}
        for reason, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _coerce_criteria(criteria: list[Any]) -> list[MetaCriterion]:
    out = []
    for criterion in criteria:
        if isinstance(criterion, MetaCriterion):
            out.append(criterion)
        elif isinstance(criterion, dict):
            out.append(MetaCriterion.model_validate(criterion))
    return out


def _study_identifier(study: dict[str, Any], codebook: dict[str, Any] | None, hit_id: Any) -> str:
    roles = role_map(study_fields(codebook)) if codebook is not None else {}
    if roles:
        value = value_by_role(study, roles, "study_id")
        if value not in (None, ""):
            return str(value)
    from qualcoder_api.services.meta_roles import metric_by_role

    value = metric_by_role(study).get("study_id")
    if value not in (None, ""):
        return str(value)
    return str(hit_id)


def prisma_counts(
    hits: list[Any],
    criteria: list[Any],
    screenings: list[Any],
    documents: list[Any],
    extractions: list[Any],
    *,
    study_ids: dict[tuple[Any, str], str] | None = None,
) -> dict[str, Any]:
    """JSON-serialisable PRISMA 2020 flow structure."""
    criteria = _coerce_criteria(criteria)
    study_ids = study_ids or {}

    latest_abstract = _latest_by_hit(screenings, "abstract")
    latest_fulltext = _latest_by_hit(screenings, "fulltext")

    screened_hits = set(latest_abstract)
    abstract_reasons: Counter = Counter()
    abstract_excluded = 0
    abstract_included = 0
    for row in latest_abstract.values():
        if evaluate_criteria(criteria, _get(row, "verdicts", {}) or {})["eligible"]:
            abstract_included += 1
        else:
            abstract_excluded += 1
            abstract_reasons[_row_reason(criteria, row)] += 1
    abstract_screened = len(screened_hits)

    docs_done = [doc for doc in documents if str(_get(doc, "status", "")) == "done"]
    retrieved_hits = {_get(doc, "hit_id") for doc in docs_done}
    assessed_hits = set(latest_fulltext) | retrieved_hits

    extracted = [ext for ext in extractions if str(_get(ext, "status", "")) == "extracted"]
    excluded_extractions = [
        ext for ext in extractions if str(_get(ext, "status", "")) == "excluded"
    ]
    included_hits = {_get(ext, "hit_id") for ext in extracted}

    fulltext_reasons: Counter = Counter()
    for row in latest_fulltext.values():
        if evaluate_criteria(criteria, _get(row, "verdicts", {}) or {})["eligible"]:
            continue
        fulltext_reasons[_row_reason(criteria, row)] += 1
    for ext in excluded_extractions:
        prescreen = _get(ext, "prescreen", {}) or {}
        reason = ""
        if isinstance(prescreen, dict):
            reason = str(prescreen.get("rationale") or "").strip()
        fulltext_reasons[reason or "Excluded at full-text screening"] += 1

    sought = abstract_included if screened_hits else len(
        [h for h in hits if _get(h, "hit_id") is not None]
    )
    not_retrieved = max(0, sought - len(retrieved_hits | included_hits))

    studies: set[str] = set()
    for ext in extracted:
        hit_id = _get(ext, "hit_id")
        owner = str(_get(ext, "owner", "") or "")
        override = study_ids.get((hit_id, owner))
        if override:
            studies.add(override)
            continue
        study_vars = _get(ext, "study_vars", {}) or {}
        records = study_vars.get("records") if isinstance(study_vars, dict) else None
        if isinstance(records, list):
            for record in records:
                study = record.get("study") if isinstance(record, dict) else None
                if isinstance(study, dict):
                    studies.add(_study_identifier(study, None, hit_id))
        else:
            studies.add(str(hit_id))

    fulltext_assessed = len(assessed_hits)
    fulltext_excluded = sum(fulltext_reasons.values())

    return {
        "identification": {
            "total": len(hits),
            "database": len(hits),
            "other": 0,
            # Records removed as duplicates (DOI, else normalized title+authors).
            "duplicates": count_duplicate_hits(list(hits)),
        },
        "screening": {
            "screened": abstract_screened,
            "excluded": abstract_excluded,
            "included": abstract_included,
            "reasons": _reason_list(abstract_reasons),
        },
        "fulltext": {
            "sought": sought,
            "retrieved": len(retrieved_hits),
            "not_retrieved": not_retrieved,
            "assessed": fulltext_assessed,
            "excluded": fulltext_excluded,
            "included": len(included_hits),
            "reasons": _reason_list(fulltext_reasons),
        },
        "inclusion": {
            "included": len(included_hits),
            "studies": len(studies),
            "reports": len(extracted),
        },
        "exclusion_reasons": _reason_list(abstract_reasons + fulltext_reasons),
    }


async def build_prisma(session: Any) -> dict[str, Any]:
    """Load the meta pipeline and compute PRISMA counts."""
    repo = MetaRepository(session)
    hits = await repo.list_hits()
    criteria = await repo.list_criteria()
    screenings = await repo.list_screening()
    documents = await repo.list_documents()
    extractions = await repo.list_extractions()

    schemes = {scheme.name: scheme for scheme in await repo.list_schemes()}
    codebooks: dict[str, dict[str, Any]] = {}
    for name, scheme in schemes.items():
        if not scheme.codebook:
            continue
        import json

        try:
            codebooks[name] = normalise_codebook(json.loads(scheme.codebook))
        except (TypeError, ValueError):
            codebooks[name] = normalise_codebook({})
    study_ids: dict[tuple[Any, str], str] = {}
    for ext in extractions:
        codebook = codebooks.get(str(_get(ext, "scheme", "") or ""))
        if codebook is None:
            continue
        study_vars = _get(ext, "study_vars", {}) or {}
        records = study_vars.get("records") if isinstance(study_vars, dict) else None
        if not isinstance(records, list) or not records:
            continue
        study = records[0].get("study") if isinstance(records[0], dict) else None
        if isinstance(study, dict):
            study_ids[(_get(ext, "hit_id"), str(_get(ext, "owner", "") or ""))] = (
                _study_identifier(study, codebook, _get(ext, "hit_id"))
            )
    return prisma_counts(
        hits, criteria, screenings, documents, extractions, study_ids=study_ids
    )
