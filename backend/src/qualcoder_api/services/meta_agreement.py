"""Inter-rater agreement and conflict resolution (contract §7).

Gwet's AC1/AC2 over deterministic labels (closed option lists, booleans, fewer
than 50 levels), with raters that need not overlap. Screening units are
``(hit_id, criterion_key)``; extraction units are
``(hit_id, record_index, metric_key, field_name)`` where ``metric_key`` is the
metric's ``dv_name`` role value when present and its position only as a
fallback — so reordered metrics never create false conflicts (reference defect
§13.2). Resolution writes an adjudicated row with ``owner = <master>``.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from qualcoder_api.persistence.repo.meta_repo import MetaRepository
from qualcoder_api.services.meta_eligibility import evaluate_criteria
from qualcoder_api.services.meta_extract import derive_dv_metrics
from qualcoder_api.services.meta_roles import metric_by_role, role_map, value_by_role
from qualcoder_api.services.meta_scheme import (
    all_fields,
    metric_fields,
    normalise_codebook,
    study_fields,
)

LABEL_MAX_LEVELS = 50

_SCREEN_VERDICT_LEVELS = ("Yes", "No", "Unsure")


# ── Gwet's AC ────────────────────────────────────────────────────────────

def gwet_ac(
    case_ratings: list[list[Any]],
    categories: list[Any],
    weights: Any = None,
) -> dict[str, Any] | None:
    """Gwet's AC1 (``weights is None``) / AC2 (weight callable) with missing data.

    Ported from the reference (Gwet, 2008; irrCAC's ``gwet.ac1.dist``): ``pa``
    is the mean pairwise agreement over subjects with >=2 raters; ``pe`` uses
    ``pi_k`` = the mean over all rated subjects of the proportion of raters
    choosing category ``k``. ``weights`` receives category *indices*.
    """
    n = len(case_ratings)
    q = len(categories)
    if n == 0 or q < 1:
        return None
    idx = {_canon(cat): i for i, cat in enumerate(categories)}
    agree = [[0] * q for _ in range(n)]
    ri = [0] * n
    for i, vals in enumerate(case_ratings):
        for value in vals:
            j = idx.get(_canon(value))
            if j is not None:
                agree[i][j] += 1
        ri[i] = sum(agree[i])
    n2 = sum(1 for count in ri if count >= 2)
    if n2 == 0:
        return None

    def weight(a: int, b: int) -> float:
        if weights is None:
            return 1.0 if a == b else 0.0
        return float(weights(a, b))

    total = 0.0
    for i in range(n):
        if ri[i] < 2:
            continue
        s = 0.0
        for k in range(q):
            nk = agree[i][k]
            if not nk:
                continue
            for level in range(q):
                nl = agree[i][level]
                if nl:
                    s += weight(k, level) * nk * nl
        total += (s - ri[i]) / (ri[i] * (ri[i] - 1))
    pa = total / n2

    pi = [
        sum(agree[i][k] / ri[i] for i in range(n) if ri[i] >= 1) / n
        for k in range(q)
    ]
    sum_w = sum(weight(k, level) for k in range(q) for level in range(q))
    pe = (
        (sum_w * sum(pi[k] * (1 - pi[k]) for k in range(q))) / (q * (q - 1))
        if q >= 2
        else 0.0
    )
    coeff = (pa - pe) / (1 - pe) if pe < 1 else None
    return {"pa": pa, "pe": pe, "coeff": coeff, "n": n, "n2": n2, "q": q}


def linear_weights(q: int) -> Any:
    if q <= 1:
        return lambda a, b: 1.0
    return lambda a, b: 1.0 - abs(a - b) / (q - 1)


# ── helpers ──────────────────────────────────────────────────────────────

def _canon(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _norm(value: Any) -> str:
    return _canon(value).lower()


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _is_int(value: Any) -> bool:
    return bool(re.fullmatch(r"-?\d+", _canon(value)))


def _match_option(value: Any, options: list[Any]) -> str:
    text = _canon(value)
    low = text.lower()
    for option in options or []:
        if _canon(option).lower() == low:
            return _canon(option)
    return text


def _case_json(case: Any) -> Any:
    if isinstance(case, tuple):
        return list(case)
    return case


# ── generic reliability / conflicts ──────────────────────────────────────

def reliability(
    fields: list[dict[str, Any]],
    case_maps: dict[str, dict[Any, dict[str, Any]]],
    *,
    exclude: set[str] | None = None,
    reference: str = "",
) -> dict[str, Any]:
    """Gwet's AC1 (and AC2 for ordered numeric labels) per deterministic field."""
    exclude = exclude or set()
    rows: list[dict[str, Any]] = []
    acc1 = wsum1 = acc2 = wsum2 = 0.0
    raters_seen: set[str] = set()
    for field in fields:
        cmap = case_maps.get(field["name"], {})
        case_ratings: list[list[str]] = []
        observed: set[str] = set()
        field_raters: set[str] = set()
        for vals in cmap.values():
            kept = {
                rater: _canon(value)
                for rater, value in vals.items()
                if rater not in exclude and _canon(value)
            }
            observed.update(kept.values())
            field_raters.update(kept)
            case_ratings.append(list(kept.values()))
        raters_seen.update(field_raters)
        n_items = len(case_ratings)
        n_multi = sum(1 for ratings in case_ratings if len(ratings) >= 2)
        levels = [str(level) for level in (field.get("levels") or [])]
        if field.get("multi"):
            cats: list[str] = sorted(observed)
        else:
            cats = levels + [v for v in sorted(observed) if v not in levels]
        ac1 = ac2 = None
        if 2 <= len(cats) < LABEL_MAX_LEVELS and n_multi:
            res1 = gwet_ac(case_ratings, cats)
            if res1:
                ac1 = res1
                if res1["coeff"] is not None:
                    acc1 += res1["coeff"] * res1["n2"]
                    wsum1 += res1["n2"]
            if field.get("ordered") and all(_is_int(c) for c in cats):
                res2 = gwet_ac(case_ratings, cats, linear_weights(len(cats)))
                if res2:
                    ac2 = res2
                    if res2["coeff"] is not None:
                        acc2 += res2["coeff"] * res2["n2"]
                        wsum2 += res2["n2"]
        rows.append(
            {
                "name": field["name"],
                "label": field.get("label") or field["name"],
                "group": field.get("group") or "",
                "kind": field.get("kind") or "",
                "role": field.get("role"),
                "multi": bool(field.get("multi")),
                "ordered": bool(field.get("ordered")),
                "n_levels": len(cats),
                "n_items": n_items,
                "n_multi": n_multi,
                "n_raters": len(field_raters),
                "ac1": ac1["coeff"] if ac1 else None,
                "ac1_pa": ac1["pa"] if ac1 else None,
                "ac1_pe": ac1["pe"] if ac1 else None,
                "ac2": ac2["coeff"] if ac2 else None,
                "ac2_pa": ac2["pa"] if ac2 else None,
                "ac2_pe": ac2["pe"] if ac2 else None,
            }
        )
    return {
        "reference": reference,
        "raters": sorted(raters_seen),
        "fields": rows,
        "overall": {
            "ac1": (acc1 / wsum1) if wsum1 else None,
            "ac2": (acc2 / wsum2) if wsum2 else None,
            "n_fields": len([r for r in rows if r["ac1"] is not None]),
            "n_items_total": sum(r["n_multi"] for r in rows),
        },
    }


def _case_identity(
    case: Any, field_name: str, extra: dict[str, Any] | None
) -> dict[str, Any]:
    """Stable identity keys for one conflict cell.

    ``extra`` (from the *case_meta* maps) is authoritative when present; a
    bare ``case`` tuple still yields a usable identity for the generic
    ``conflicts`` callers (screening = 2-tuple, extraction = 3-tuple).
    """
    extra = extra or {}
    hit_id = extra.get("hit_id")
    record_index = extra.get("record_index")
    metric_key = extra.get("metric_key")
    metric_index = extra.get("metric_index")
    criterion_key = extra.get("criterion_key")
    if isinstance(case, tuple):
        if hit_id is None and len(case) >= 1:
            hit_id = case[0]
        if len(case) == 2 and criterion_key is None:
            criterion_key = case[1]
        if len(case) == 3:
            if record_index is None:
                record_index = case[1]
            if metric_key is None:
                metric_key = case[2]
    if extra.get("key"):
        key = str(extra["key"])
    elif criterion_key is not None:
        key = f"screening:{hit_id}:{criterion_key}"
    elif metric_key is not None:
        key = f"extraction:{hit_id}:{record_index}:{metric_key}:{field_name}"
    else:
        key = f"extraction:{hit_id}:{record_index}:{field_name}"
    return {
        "key": key,
        "hit_id": hit_id,
        "record_index": record_index,
        "metric_key": metric_key,
        "metric_index": metric_index,
        "criterion_key": criterion_key,
    }


def conflicts(
    fields: list[dict[str, Any]],
    case_maps: dict[str, dict[Any, dict[str, Any]]],
    *,
    case_meta: dict[str, dict[Any, dict[str, Any]]] | None = None,
    master: str = "",
    field_filter: str = "",
    status: str = "open",
    study_filter: Any = None,
    limit: int = 300,
    offset: int = 0,
) -> dict[str, Any]:
    """Units where raters disagree, optionally filtered by open/settled status.

    Each row carries the ids the agreement UI needs to resolve it: a stable
    ``key`` plus ``hit_id`` and, depending on the window, ``criterion_key``
    (screening) or ``record_index``/``metric_key``/``metric_index``
    (extraction). ``case_meta`` supplies those when the case tuple alone is
    not enough.
    """
    meta_map = case_meta or {}
    rows: list[dict[str, Any]] = []
    counts: list[dict[str, Any]] = []
    studies: dict[str, dict[str, Any]] = {}
    status = (status or "open").lower()
    for field in fields:
        if field_filter and field["name"] != field_filter:
            continue
        open_n = settled_n = 0
        for case, vals in case_maps.get(field["name"], {}).items():
            compare = {
                rater: _canon(value)
                for rater, value in vals.items()
                if rater != master and _canon(value)
            }
            if len(set(compare.values())) < 2:
                continue
            master_value = _canon(vals.get(master, "")) if master else ""
            settled = bool(master_value)
            if settled:
                settled_n += 1
            else:
                open_n += 1
            if status == "open" and settled:
                continue
            if status == "settled" and not settled:
                continue
            study = case[0] if isinstance(case, tuple) else case
            meta = studies.setdefault(
                str(study),
                {"key": study, "label": str(study), "n_open": 0, "n_settled": 0, "fields": set()},
            )
            if settled:
                meta["n_settled"] += 1
            else:
                meta["n_open"] += 1
            meta["fields"].add(field["name"])
            if study_filter is not None and str(study) != str(study_filter):
                continue
            identity = _case_identity(
                case, field["name"], meta_map.get(field["name"], {}).get(case)
            )
            row = {
                "case": _case_json(case),
                "field": field["name"],
                "field_name": field["name"],
                "field_label": field.get("label") or field["name"],
                "group": field.get("group") or "",
                "kind": field.get("kind") or "",
                "role": field.get("role"),
                "multi": bool(field.get("multi")),
                "levels": field.get("levels") or [],
                "values": compare,
                "master_value": master_value or None,
                "settled": settled,
                "key": identity["key"],
                "hit_id": identity["hit_id"],
            }
            if identity["criterion_key"] is not None:
                row["criterion_key"] = identity["criterion_key"]
            if identity["record_index"] is not None:
                row["record_index"] = identity["record_index"]
                row["metric_key"] = identity["metric_key"]
                row["metric_index"] = identity["metric_index"]
            rows.append(row)
        counts.append(
            {
                "name": field["name"],
                "label": field.get("label") or field["name"],
                "group": field.get("group") or "",
                "kind": field.get("kind") or "",
                "multi": bool(field.get("multi")),
                "open": open_n,
                "settled": settled_n,
            }
        )
    study_list = [
        {
            "key": meta["key"],
            "label": meta["label"],
            "n_open": meta["n_open"],
            "n_settled": meta["n_settled"],
            "n_fields": len(meta["fields"]),
        }
        for meta in studies.values()
    ]
    study_list.sort(key=lambda s: (-s["n_open"], str(s["label"]).lower()))
    return {
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "rows": rows[offset : offset + limit],
        "fields": counts,
        "studies": study_list,
        "master": master,
    }


# ── screening ────────────────────────────────────────────────────────────

def _criterion_fields(criteria: list[Any]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for criterion in criteria:
        kind = str(_get(criterion, "kind", "verdict") or "verdict").lower()
        options = [str(o) for o in (_get(criterion, "options", []) or [])]
        if kind == "classify" and options:
            levels = options
        elif kind == "number":
            levels = []
        else:
            levels = list(_SCREEN_VERDICT_LEVELS)
        fields.append(
            {
                "name": str(_get(criterion, "key", "")),
                "label": str(_get(criterion, "label", "") or _get(criterion, "key", "")),
                "group": "Screening",
                "kind": "screening",
                "role": None,
                "multi": False,
                "ordered": bool(levels) and all(_is_int(level) for level in levels),
                "levels": levels,
            }
        )
    return fields


def _latest_screening_rows(
    screenings: list[Any], stage: str
) -> dict[tuple[str, int], tuple[int, Any]]:
    """Latest screening row per (owner, hit), restricted to ``stage``."""
    latest: dict[tuple[str, int], tuple[int, Any]] = {}
    for row in screenings:
        if stage and str(_get(row, "stage", "abstract") or "abstract") != stage:
            continue
        owner = str(_get(row, "owner", "") or "")
        hit_id = int(_get(row, "hit_id", 0) or 0)
        row_id = int(_get(row, "id", 0) or 0)
        key = (owner, hit_id)
        if key not in latest or row_id >= latest[key][0]:
            latest[key] = (row_id, row)
    return latest


def screening_case_maps(
    screenings: list[Any], criteria: list[Any], *, stage: str = "abstract"
) -> dict[str, dict[Any, dict[str, Any]]]:
    """Latest verdict per (owner, hit) keyed ``{criterion: {(hit_id, criterion): {rater: value}}}``."""
    latest = _latest_screening_rows(screenings, stage)
    fields = _criterion_fields(criteria)
    case_maps: dict[str, dict[Any, dict[str, Any]]] = {field["name"]: {} for field in fields}
    for (owner, hit_id), (_row_id, row) in latest.items():
        verdicts = _get(row, "verdicts", {}) or {}
        if not isinstance(verdicts, dict):
            continue
        for field in fields:
            key = field["name"]
            entry = verdicts.get(key)
            value = entry.get("applies") if isinstance(entry, dict) else entry
            value = _canon(value)
            if not value:
                continue
            if field["levels"]:
                value = _match_option(value, field["levels"])
            case_maps.setdefault(key, {}).setdefault((hit_id, key), {})[owner] = value
    return case_maps


def screening_case_meta(
    screenings: list[Any], criteria: list[Any], *, stage: str = "abstract"
) -> dict[str, dict[Any, dict[str, Any]]]:
    """Identity metadata matching :func:`screening_case_maps` case keys."""
    fields = _criterion_fields(criteria)
    out: dict[str, dict[Any, dict[str, Any]]] = {field["name"]: {} for field in fields}
    hit_ids = {
        int(hit_id)
        for _owner, hit_id in _latest_screening_rows(screenings, stage)
    }
    for field in fields:
        for hit_id in hit_ids:
            case = (hit_id, field["name"])
            out[field["name"]][case] = {
                "key": f"screening:{hit_id}:{field['name']}",
                "hit_id": hit_id,
                "criterion_key": field["name"],
            }
    return out


def screening_llm_excluded(
    screenings: list[Any], criteria: list[Any], *, stage: str = "abstract"
) -> list[dict[str, Any]]:
    """Hits an LLM excluded although >=1 human rater would include them.

    The LLM verdict is advisory: when it disagrees with every human reversal
    the discrepancy is surfaced for review instead of being silently lost.
    """
    latest = _latest_screening_rows(screenings, stage)
    included_by_human: dict[int, list[str]] = {}
    excluded_by_llm: dict[int, list[tuple[str, str]]] = {}
    for (owner, hit_id), (_row_id, row) in latest.items():
        verdicts = _get(row, "verdicts", {}) or {}
        eligible = bool(evaluate_criteria(criteria, verdicts).get("eligible"))
        origin = str(_get(row, "origin", "manual") or "manual").lower()
        if origin == "llm":
            if not eligible:
                excluded_by_llm.setdefault(hit_id, []).append(
                    (owner, str(_get(row, "reason", "") or ""))
                )
        elif eligible:
            included_by_human.setdefault(hit_id, []).append(owner)
    out: list[dict[str, Any]] = []
    for hit_id, humans in sorted(included_by_human.items()):
        excluded = excluded_by_llm.get(hit_id)
        if not excluded:
            continue
        out.append(
            {
                "hit_id": hit_id,
                "stage": stage or "abstract",
                "included_by": sorted(humans),
                "excluded_by": sorted(owner for owner, _reason in excluded),
                "llm_reason": next(
                    (reason for _owner, reason in excluded if reason), ""
                ),
            }
        )
    return out


# ── extraction ───────────────────────────────────────────────────────────

def _extraction_field_defs(codebook: Any) -> list[dict[str, Any]]:
    book = normalise_codebook(codebook)
    defs: list[dict[str, Any]] = []
    for kind, group in (("study", study_fields(book)), ("metric", metric_fields(book))):
        for field in group:
            name = field.get("name")
            if not name:
                continue
            options = [str(o) for o in (field.get("options") or [])]
            editor = str(field.get("editor") or "")
            ftype = str(field.get("type") or "")
            multi = editor == "multiselect"
            if options and 0 < len(options) < LABEL_MAX_LEVELS:
                levels = options
            elif ftype == "boolean" or editor == "boolean":
                levels = ["true", "false"]
            else:
                continue
            defs.append(
                {
                    "name": str(name),
                    "label": str(field.get("label") or name),
                    "group": str(field.get("group") or ""),
                    "kind": kind,
                    "role": field.get("role"),
                    "multi": multi,
                    "ordered": all(_is_int(level) for level in levels),
                    "levels": levels,
                }
            )
    return defs


def _canon_multi(value: Any, field: dict[str, Any]) -> str:
    if field.get("multi"):
        values = value if isinstance(value, list) else (
            [p.strip() for p in str(value).split("+")] if isinstance(value, str) else [value]
        )
        levels = field.get("levels") or []
        clean = {_match_option(v, levels) or _canon(v) for v in values}
        clean.discard("")
        return " + ".join(sorted(clean))
    return _match_option(value, field.get("levels") or [])


def _metric_keys(record: dict[str, Any], roles: dict[str, str]) -> list[str]:
    """Stable metric keys: ``dv_name`` value, else position (unique within record)."""
    dv_field = next((name for name, role in roles.items() if role == "dv_name"), None)
    metrics = record.get("metrics")
    metrics = metrics if isinstance(metrics, list) else []
    keys: list[str] = []
    seen: dict[str, int] = {}
    for index, metric in enumerate(metrics):
        metric = metric if isinstance(metric, dict) else {}
        dv = metric.get(dv_field) if dv_field else None
        if dv in (None, ""):
            keys.append(str(index))
            continue
        name = str(dv)
        occurrence = seen.get(name, 0)
        seen[name] = occurrence + 1
        keys.append(name if occurrence == 0 else f"{name}#{occurrence}")
    return keys


def _coded_record_key(
    study: dict[str, Any], roles: dict[str, str], record_index: int
) -> Any:
    """Stable study/experiment key: the coded id when present, else the index."""
    value = value_by_role(study, roles, "study_id") if roles else None
    if value in (None, ""):
        value = metric_by_role(study).get("study_id")
    return str(value) if value not in (None, "") else record_index


def extraction_case_maps(
    extractions: list[Any], codebook: Any
) -> tuple[list[dict[str, Any]], dict[str, dict[tuple, dict[str, Any]]]]:
    """``(fields, case_maps)`` with ``metric_key`` stable across reorderings.

    Study fields are keyed by the coded study id when the extraction supplies
    one (so reordering experiments cannot fabricate a conflict), falling back
    to the record index.
    """
    fields = _extraction_field_defs(codebook)
    book = normalise_codebook(codebook)
    roles = role_map(all_fields(book))
    study_defs = [f for f in fields if f["kind"] == "study"]
    metric_defs = [f for f in fields if f["kind"] == "metric"]
    case_maps: dict[str, dict[tuple, dict[str, Any]]] = {f["name"]: {} for f in fields}
    for ext in extractions:
        if str(_get(ext, "status", "extracted")) != "extracted":
            continue
        hit_id = int(_get(ext, "hit_id", 0) or 0)
        owner = str(_get(ext, "owner", "") or "")
        study_vars = _get(ext, "study_vars", {}) or {}
        records = study_vars.get("records") if isinstance(study_vars, dict) else None
        if not isinstance(records, list):
            continue
        for record_index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            study_obj = record.get("study")
            study: dict[str, Any] = study_obj if isinstance(study_obj, dict) else {}
            metrics_obj = record.get("metrics")
            metrics: list[Any] = metrics_obj if isinstance(metrics_obj, list) else []
            keys = _metric_keys(record, roles)
            coded = _coded_record_key(study, roles, record_index)
            for field in study_defs:
                value = _canon_multi(study.get(field["name"]), field)
                if value:
                    case_maps[field["name"]].setdefault(
                        (hit_id, coded, ""), {}
                    )[owner] = value
            for metric_index, metric in enumerate(metrics):
                if not isinstance(metric, dict):
                    continue
                metric_key = keys[metric_index] if metric_index < len(keys) else str(metric_index)
                for field in metric_defs:
                    value = _canon_multi(metric.get(field["name"]), field)
                    if value:
                        case_maps[field["name"]].setdefault(
                            (hit_id, record_index, metric_key), {}
                        )[owner] = value
    return fields, case_maps


def extraction_case_meta(
    extractions: list[Any], codebook: Any
) -> dict[str, dict[tuple, dict[str, Any]]]:
    """Identity metadata matching :func:`extraction_case_maps` case keys."""
    fields = _extraction_field_defs(codebook)
    book = normalise_codebook(codebook)
    roles = role_map(all_fields(book))
    study_defs = [f for f in fields if f["kind"] == "study"]
    metric_defs = [f for f in fields if f["kind"] == "metric"]
    out: dict[str, dict[tuple, dict[str, Any]]] = {f["name"]: {} for f in fields}
    for ext in extractions:
        if str(_get(ext, "status", "extracted")) != "extracted":
            continue
        hit_id = int(_get(ext, "hit_id", 0) or 0)
        study_vars = _get(ext, "study_vars", {}) or {}
        records = study_vars.get("records") if isinstance(study_vars, dict) else None
        if not isinstance(records, list):
            continue
        for record_index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            study_obj = record.get("study")
            study: dict[str, Any] = study_obj if isinstance(study_obj, dict) else {}
            metrics_obj = record.get("metrics")
            metrics: list[Any] = metrics_obj if isinstance(metrics_obj, list) else []
            keys = _metric_keys(record, roles)
            coded = _coded_record_key(study, roles, record_index)
            for field in study_defs:
                case = (hit_id, coded, "")
                out[field["name"]][case] = {
                    "key": f"extraction:{hit_id}:{coded}:{field['name']}",
                    "hit_id": hit_id,
                    "record_index": record_index,
                    "metric_key": None,
                    "metric_index": None,
                }
            for metric_index, _metric in enumerate(metrics):
                metric_key = keys[metric_index] if metric_index < len(keys) else str(metric_index)
                for field in metric_defs:
                    case = (hit_id, record_index, metric_key)
                    out[field["name"]][case] = {
                        "key": (
                            f"extraction:{hit_id}:{record_index}:{metric_key}:"
                            f"{field['name']}"
                        ),
                        "hit_id": hit_id,
                        "record_index": record_index,
                        "metric_key": metric_key,
                        "metric_index": metric_index,
                    }
    return out


# ── async repository-backed wrappers ─────────────────────────────────────

async def screening_reliability(
    session: Any,
    criteria: list[Any],
    *,
    stage: str = "abstract",
    exclude: set[str] | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    repo = MetaRepository(session)
    rows = await repo.list_screening(stage=stage or None, owner=owner)
    fields = _criterion_fields(criteria)
    case_maps = screening_case_maps(rows, criteria, stage=stage)
    result = reliability(fields, case_maps, exclude=exclude, reference="screening")
    # Records the LLM excluded although a human rater would include them.
    result["llm_excluded"] = screening_llm_excluded(rows, criteria, stage=stage)
    return result


async def screening_conflicts(
    session: Any,
    criteria: list[Any],
    *,
    master: str = "",
    stage: str = "abstract",
    owner: str | None = None,
    run_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    repo = MetaRepository(session)
    rows = await repo.list_screening(stage=stage or None, owner=owner, run_id=run_id)
    fields = _criterion_fields(criteria)
    case_maps = screening_case_maps(rows, criteria, stage=stage)
    case_meta = screening_case_meta(rows, criteria, stage=stage)
    result = conflicts(fields, case_maps, case_meta=case_meta, master=master, **kwargs)
    result["raters"] = sorted({str(_get(r, "owner", "")) for r in rows if _get(r, "owner")})
    return result


async def resolve_screening(
    session: Any,
    *,
    hit_id: int,
    criterion_key: str,
    value: Any,
    master: str,
    run_id: str = "",
    stage: str = "abstract",
) -> dict[str, Any]:
    """Write the master's adjudicated verdict for one screening cell."""
    if not master:
        raise ValueError("master is required")
    repo = MetaRepository(session)
    if await repo.get_hit(hit_id) is None:
        raise ValueError("hit not found")
    existing = await repo.screening_for_hit(hit_id, master, run_id, stage or "abstract")
    verdicts = dict(existing.verdicts) if existing else {}
    entry = dict(verdicts.get(criterion_key) or {})
    cleaned = _canon(value)
    if cleaned:
        entry["applies"] = cleaned
    else:
        entry.pop("applies", None)
    verdicts[criterion_key] = entry
    row = await repo.upsert_screening(
        hit_id=hit_id,
        owner=master,
        run_id=run_id,
        verdicts=verdicts,
        origin="manual",
        stage=stage or "abstract",
    )
    return {"ok": True, "id": row.id, "hit_id": hit_id, "criterion": criterion_key, "value": cleaned}


async def extraction_reliability(
    session: Any,
    codebook: Any,
    *,
    exclude: set[str] | None = None,
    owner: str | None = None,
    scheme: str | None = None,
) -> dict[str, Any]:
    repo = MetaRepository(session)
    rows = await repo.list_extractions(owner=owner, scheme=scheme, include_dv_metrics=False)
    fields, case_maps = extraction_case_maps(rows, codebook)
    return reliability(fields, case_maps, exclude=exclude, reference="extraction")


async def extraction_conflicts(
    session: Any,
    codebook: Any,
    *,
    master: str = "",
    owner: str | None = None,
    scheme: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    repo = MetaRepository(session)
    rows = await repo.list_extractions(owner=owner, scheme=scheme, include_dv_metrics=False)
    fields, case_maps = extraction_case_maps(rows, codebook)
    case_meta = extraction_case_meta(rows, codebook)
    result = conflicts(fields, case_maps, case_meta=case_meta, master=master, **kwargs)
    result["raters"] = sorted({str(_get(r, "owner", "")) for r in rows if _get(r, "owner")})
    return result


async def resolve_extraction(
    session: Any,
    *,
    hit_id: int,
    field_name: str,
    value: Any,
    master: str,
    record_index: int = 0,
    metric_key: str | None = None,
    metric_index: int | None = None,
    scheme: str | None = None,
    codebook: Any = None,
) -> dict[str, Any]:
    """Write the master's adjudicated extraction cell (``owner = master``)."""
    if not master:
        raise ValueError("master is required")
    repo = MetaRepository(session)
    ext = await repo.get_extraction_for_hit(hit_id, master, scheme)
    source_id = ext.source_id if ext is not None else None
    if ext is not None:
        scheme_name = ext.scheme
        records = copy.deepcopy((ext.study_vars or {}).get("records") or [])
    else:
        candidates = await repo.list_extractions(hit_id=hit_id, scheme=scheme)
        if not candidates:
            raise ValueError("no extraction to adjudicate")
        source = candidates[0]
        scheme_name = source.scheme
        source_id = source.source_id
        records = copy.deepcopy((source.study_vars or {}).get("records") or [])
    if scheme is not None:
        scheme_name = scheme
    if codebook is None:
        scheme_row = await repo.get_scheme(name=scheme_name)
        if scheme_row is not None and scheme_row.codebook:
            import json

            try:
                codebook = json.loads(scheme_row.codebook)
            except ValueError:
                codebook = None

    if record_index < 0 or record_index >= len(records):
        raise ValueError("record index out of range")
    record = records[record_index]
    if not isinstance(record, dict):
        raise ValueError("record index out of range")

    field_defs = _extraction_field_defs(codebook) if codebook is not None else []
    field = next((f for f in field_defs if f["name"] == field_name), None)
    if value in (None, ""):
        new_value: Any = None
    elif field is not None:
        new_value = _canon_multi(value, field)
        if field.get("ordered") and _is_int(new_value):
            new_value = int(new_value)
    else:
        new_value = value

    if metric_key in (None, ""):
        study = record.get("study")
        if not isinstance(study, dict):
            study = {}
            record["study"] = study
        study[field_name] = new_value
    else:
        book = normalise_codebook(codebook) if codebook is not None else None
        roles = role_map(all_fields(book)) if book else {}
        keys = _metric_keys(record, roles)
        metrics = record.get("metrics")
        if not isinstance(metrics, list):
            metrics = []
            record["metrics"] = metrics
        target = next((i for i, key in enumerate(keys) if key == metric_key), None)
        if target is None and metric_index is not None and 0 <= metric_index < len(metrics):
            target = metric_index
        if target is None or target >= len(metrics):
            raise ValueError("metric not found")
        if not isinstance(metrics[target], dict):
            metrics[target] = {}
        metrics[target][field_name] = new_value

    study_roles = role_map(study_fields(normalise_codebook(codebook or {})))
    dv_metrics = derive_dv_metrics(records, study_roles)
    row = await repo.upsert_extraction(
        hit_id=hit_id,
        owner=master,
        scheme=scheme_name,
        source_id=source_id,
        study_vars={"records": records},
        dv_metrics=dv_metrics,
        status="extracted",
    )
    return {
        "ok": True,
        "id": row.id,
        "hit_id": hit_id,
        "record_index": record_index,
        "metric_key": metric_key,
        "field": field_name,
        "value": new_value,
    }
