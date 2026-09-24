"""Categorical summary of the extracted data (contract §8).

Counts the levels of every scheme field with a closed option list (and every
boolean) plus the categorical values of the scheme's role vocabulary, together
with the number of distinct studies behind each level. Field names are user
data; semantics come from the options and the ``meta_roles`` vocabulary only.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from qualcoder_api.services.meta_roles import (
    metric_by_role,
    role_map,
    value_by_role,
)
from qualcoder_api.services.meta_scheme import (
    all_fields,
    metric_fields,
    normalise_codebook,
    study_fields,
)

_MAX_LEVELS = 50


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _canon(value: Any, options: list[str] | None = None) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = str(value).strip()
    if not text:
        return ""
    if options:
        low = text.lower()
        for option in options:
            if option.lower() == low:
                return option
    return text


def _values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(value)] if value not in (None, "") else []


def _study_id(study: dict[str, Any], roles: dict[str, str], hit_id: Any) -> str:
    value = value_by_role(study, roles, "study_id")
    if value in (None, ""):
        value = metric_by_role(study).get("study_id")
    return str(value) if value not in (None, "") else str(hit_id)


class _Levels:
    def __init__(self) -> None:
        self.counts: Counter = Counter()
        self.studies: dict[str, set[str]] = {}

    def add(self, value: str, study_id: str) -> None:
        self.counts[value] += 1
        self.studies.setdefault(value, set()).add(study_id)

    def rows(self) -> list[dict[str, Any]]:
        return [
            {"value": value, "n": count, "n_studies": len(self.studies.get(value, set()))}
            for value, count in sorted(self.counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]


def build_summary(extractions: list[Any], codebook: Any = None) -> dict[str, Any]:
    """Categorical level counts + contributing study counts."""
    book = normalise_codebook(codebook) if codebook is not None else None
    roles = role_map(all_fields(book)) if book else {}
    study_roles = role_map(study_fields(book)) if book else {}

    study_fields_list = study_fields(book) if book else []
    metric_fields_list = metric_fields(book) if book else []

    def categorical(field: dict[str, Any]) -> tuple[bool, list[str]]:
        options = [str(o) for o in (field.get("options") or [])]
        editor = str(field.get("editor") or "")
        ftype = str(field.get("type") or "")
        if options:
            return True, options
        if ftype == "boolean" or editor == "boolean":
            return True, ["true", "false"]
        return False, []

    study_defs = [
        (field, *categorical(field)) for field in study_fields_list if field.get("name")
    ]
    metric_defs = [
        (field, *categorical(field)) for field in metric_fields_list if field.get("name")
    ]

    study_levels: dict[str, _Levels] = {}
    metric_levels: dict[str, _Levels] = {}
    role_levels: dict[str, _Levels] = {}
    role_samples: dict[str, list[Any]] = {}

    n_extractions = 0
    n_records = 0
    studies: set[str] = set()
    study_records: Counter = Counter()

    extracted = [
        ext
        for ext in (extractions if isinstance(extractions, list) else [])
        if str(_get(ext, "status", "extracted")) == "extracted"
    ]
    n_extractions = len(extracted)
    for ext in extracted:
        hit_id = _get(ext, "hit_id")
        study_vars = _get(ext, "study_vars", {}) or {}
        records = study_vars.get("records") if isinstance(study_vars, dict) else None
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            n_records += 1
            study_obj = record.get("study")
            study: dict[str, Any] = study_obj if isinstance(study_obj, dict) else {}
            sid = _study_id(study, study_roles, hit_id)
            studies.add(sid)
            study_records[sid] += 1
            for field, ok, options in study_defs:
                if not ok:
                    continue
                for value in _values(study.get(field["name"])):
                    study_levels.setdefault(field["name"], _Levels()).add(
                        _canon(value, options), sid
                    )
            metrics_obj = record.get("metrics")
            metrics: list[Any] = metrics_obj if isinstance(metrics_obj, list) else []
            for metric in metrics:
                if not isinstance(metric, dict):
                    continue
                for field, ok, options in metric_defs:
                    if not ok:
                        continue
                    for value in _values(metric.get(field["name"])):
                        metric_levels.setdefault(field["name"], _Levels()).add(
                            _canon(value, options), sid
                        )
                by_role = metric_by_role(metric, roles) if roles else metric_by_role(metric)
                for role, value in by_role.items():
                    if isinstance(value, (dict, list)) or value in (None, ""):
                        continue
                    text = _canon(value)
                    if not text:
                        continue
                    role_samples.setdefault(role, []).append(value)
                    role_levels.setdefault(role, _Levels()).add(text, sid)

    fields_out: list[dict[str, Any]] = []
    covered_roles = {
        field.get("role")
        for field, ok, _options in [*study_defs, *metric_defs]
        if ok and field.get("role")
    }
    for field, ok, _options in study_defs:
        if not ok:
            continue
        fields_out.append(
            {
                "name": field["name"],
                "label": field.get("label") or field["name"],
                "group": field.get("group") or "",
                "kind": "study",
                "role": field.get("role"),
                "levels": study_levels.get(field["name"], _Levels()).rows(),
            }
        )
    for field, ok, _options in metric_defs:
        if not ok:
            continue
        fields_out.append(
            {
                "name": field["name"],
                "label": field.get("label") or field["name"],
                "group": field.get("group") or "",
                "kind": "metric",
                "role": field.get("role"),
                "levels": metric_levels.get(field["name"], _Levels()).rows(),
            }
        )
    for role, levels in role_levels.items():
        if role in covered_roles:
            continue
        values = role_samples.get(role, [])
        categorical_values = all(
            isinstance(v, (bool, str)) or (isinstance(v, float) and v.is_integer())
            for v in values
        )
        if not categorical_values or len(levels.counts) > _MAX_LEVELS:
            continue
        fields_out.append(
            {
                "name": role,
                "label": role.replace("_", " ").capitalize(),
                "group": "Roles",
                "kind": "role",
                "role": role,
                "levels": levels.rows(),
            }
        )
    fields_out.sort(key=lambda f: (f["kind"], str(f["label"]).lower()))

    contributing = [
        {"study_id": sid, "n_records": study_records[sid]}
        for sid in sorted(studies)
    ]
    return {
        "n_extractions": n_extractions,
        "n_records": n_records,
        "n_studies": len(studies),
        "fields": fields_out,
        "contributing": contributing,
    }
