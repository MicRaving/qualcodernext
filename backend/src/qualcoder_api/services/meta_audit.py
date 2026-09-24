"""Extraction-variable coverage and role-integrity audit.

The QCnext analogue of the reference Harmonizer's variable audit: it walks the
scheme's study/metric fields over every extracted record and reports how often
each field actually carries a value, together with the structural problems that
would silently drop an effect from the synthesis — metric fields that merely
look coded, missing outcome identifiers, half-entered descriptive sets, a
reported ``yi`` without a variance, and incomplete metrics that never recorded
why. Field names come from the codebook; semantics come from ``meta_roles`` and
``meta_effects`` only.
"""

from __future__ import annotations

from typing import Any

from qualcoder_api.services.meta_effects import metric_status
from qualcoder_api.services.meta_roles import metric_by_role, role_map
from qualcoder_api.services.meta_scheme import (
    all_fields,
    enabled_families,
    metric_fields,
    normalise_codebook,
    study_fields,
)

#: Roles whose absence makes an effect unpoolable; their emptiness is a warning
#: rather than background information.
_CRITICAL_METRIC_ROLES = frozenset(
    {
        "dv_name",
        "dv_domain",
        "eligible_primary",
        "n1",
        "n2",
        "m1",
        "m2",
        "sd1",
        "sd2",
        "yi",
        "vi",
        "sei",
    }
)
_CRITICAL_STUDY_ROLES = frozenset({"study_id"})
#: Roles reported by their own dedicated checks below (not the generic coverage
#: sweep) so the audit does not duplicate the same finding.
_EXPLICIT_ROLES = frozenset({"dv_name", "dv_domain", "eligible_primary"})
_DESCRIPTIVE_GROUP1 = ("n1", "m1", "sd1")
_DESCRIPTIVE_GROUP2 = ("n2", "m2", "sd2")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _is_empty(value: Any) -> bool:
    """True when a coded value carries no information (``None``/blank/empty)."""
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def _field_entry(field: dict[str, Any], kind: str, present: int, total: int) -> dict[str, Any]:
    return {
        "name": field["name"],
        "label": field.get("label") or field["name"],
        "group": field.get("group") or "",
        "kind": kind,
        "role": field.get("role"),
        "editor": field.get("editor") or "text",
        "set": present,
        "total": total,
        "coverage": (present / total) if total else 0.0,
    }


def variable_audit(extractions: Any, codebook: Any = None) -> dict[str, Any]:
    """Audit extraction-variable coverage and role integrity.

    Returns the per-field coverage (with the fields' own issue messages) plus a
    flat list of ``warn``/``info`` findings. ``coverage`` is ``set / total``
    where ``total`` is the number of records (study fields) or metrics (metric
    fields) examined.
    """
    book = normalise_codebook(codebook) if codebook is not None else normalise_codebook({})
    roles = role_map(all_fields(book))
    families = enabled_families(book)
    study_defs = [f for f in study_fields(book) if f.get("name")]
    metric_defs = [f for f in metric_fields(book) if f.get("name")]
    field_by_name = {field["name"]: field for field in [*study_defs, *metric_defs]}

    extracted = [
        ext
        for ext in (extractions if isinstance(extractions, list) else [])
        if str(_get(ext, "status", "extracted")) == "extracted"
    ]
    n_extractions = len(extracted)
    study_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    for ext in extracted:
        study_vars = _get(ext, "study_vars", {}) or {}
        records = study_vars.get("records") if isinstance(study_vars, dict) else None
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            study_obj = record.get("study")
            study: dict[str, Any] = study_obj if isinstance(study_obj, dict) else record
            study_rows.append(study)
            metrics = record.get("metrics")
            metric_rows.extend(
                metric
                for metric in (metrics if isinstance(metrics, list) else [])
                if isinstance(metric, dict)
            )
    n_records = len(study_rows)
    n_metrics = len(metric_rows)

    issues: list[dict[str, Any]] = []
    field_issues: dict[str, list[str]] = {}

    def add(severity: str, field: str, message: str, count: int) -> None:
        issues.append(
            {
                "severity": severity,
                "field": field,
                "message": message,
                "count": int(count),
            }
        )
        if field in field_by_name:
            field_issues.setdefault(field, []).append(message)

    def role_field(role: str) -> str:
        for field in [*study_defs, *metric_defs]:
            if field.get("role") == role:
                return str(field["name"])
        return role

    entries: list[dict[str, Any]] = []
    for field in study_defs:
        present = sum(1 for row in study_rows if not _is_empty(row.get(field["name"])))
        entries.append(_field_entry(field, "study", present, n_records))
    for field in metric_defs:
        present = sum(1 for row in metric_rows if not _is_empty(row.get(field["name"])))
        entries.append(_field_entry(field, "metric", present, n_metrics))

    # Metric fields that carry a role but were never (or only partly) filled.
    for entry in entries:
        role = entry["role"]
        if not role or role in _EXPLICIT_ROLES or entry["total"] == 0:
            continue
        missing = entry["total"] - entry["set"]
        if missing <= 0:
            continue
        critical = (
            entry["kind"] == "metric" and role in _CRITICAL_METRIC_ROLES
        ) or (entry["kind"] == "study" and role in _CRITICAL_STUDY_ROLES)
        severity = "warn" if critical else "info"
        add(
            severity,
            entry["name"],
            f"{missing} of {entry['total']} {entry['kind']} records leave "
            f"'{entry['label']}' (role {role}) empty.",
            missing,
        )

    metric_roles = [
        metric_by_role(metric, roles) if roles else metric_by_role(metric)
        for metric in metric_rows
    ]

    # Required outcome-identifier roles.
    for role in ("dv_name", "dv_domain", "eligible_primary"):
        missing = sum(1 for by_role in metric_roles if _is_empty(by_role.get(role)))
        if missing:
            field_name = role_field(role)
            label = field_by_name.get(field_name, {}).get("label") or field_name
            add(
                "warn",
                field_name,
                f"{missing} of {n_metrics} metrics have no '{label}' (role {role}).",
                missing,
            )

    # Half-entered effect sets.
    missing_group2 = missing_group1 = yi_no_variance = 0
    for by_role in metric_roles:
        group1 = [not _is_empty(by_role.get(role)) for role in _DESCRIPTIVE_GROUP1]
        group2 = [not _is_empty(by_role.get(role)) for role in _DESCRIPTIVE_GROUP2]
        if any(group1) and not all(group2):
            missing_group2 += 1
        if any(group2) and not all(group1):
            missing_group1 += 1
        if (
            not _is_empty(by_role.get("yi"))
            and _is_empty(by_role.get("vi"))
            and _is_empty(by_role.get("sei"))
        ):
            yi_no_variance += 1
    if missing_group2:
        add(
            "warn",
            role_field("m2"),
            f"{missing_group2} metrics report some of n1/m1/sd1 but lack the "
            "matching n2/m2/sd2.",
            missing_group2,
        )
    if missing_group1:
        add(
            "warn",
            role_field("m1"),
            f"{missing_group1} metrics report some of n2/m2/sd2 but lack the "
            "matching n1/m1/sd1.",
            missing_group1,
        )
    if yi_no_variance:
        add(
            "warn",
            role_field("vi"),
            f"{yi_no_variance} metrics report yi without a vi/sei variance.",
            yi_no_variance,
        )

    # Incomplete metrics that never recorded a reason.
    incomplete_no_reason = 0
    for by_role in metric_roles:
        status, _reason = metric_status(by_role, families)
        if status == "incomplete" and _is_empty(by_role.get("missing_reason")):
            incomplete_no_reason += 1
    if incomplete_no_reason:
        add(
            "warn",
            role_field("missing_reason"),
            f"{incomplete_no_reason} incomplete metrics do not record a "
            "missing_reason.",
            incomplete_no_reason,
        )

    fields_out = [
        {**entry, "issues": field_issues.get(entry["name"], [])} for entry in entries
    ]
    issues.sort(key=lambda item: (0 if item["severity"] == "warn" else 1, item["field"]))
    return {
        "n_extractions": n_extractions,
        "n_records": n_records,
        "n_metrics": n_metrics,
        "fields": fields_out,
        "issues": issues,
    }
