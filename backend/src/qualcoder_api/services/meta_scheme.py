"""Codebook v2 normalisation and field helpers (contract §3).

A scheme's ``codebook`` JSON is written by the frontend. v1 stored
``groups`` as strings and a flat ``study_fields`` list; v2 adds a repeatable
``metrics`` section, per-field ``role`` and ``effect_families``. Every read
goes through :func:`normalise_codebook`, so downstream code only ever sees v2.

``study_fields`` is kept as an alias of ``fields`` on the normalised output so
the existing publish path (``codebook.get("study_fields")``) keeps working.
"""

from __future__ import annotations

from typing import Any

from qualcoder_api.services.meta_roles import normalise_role

#: The effect families the extraction/analysis pipeline understands (§3).
EFFECT_FAMILIES = (
    "descriptives",
    "t",
    "F",
    "r",
    "yi",
    "d_g",
    "odds_ratio",
    "risk_ratio",
    "beta",
    "eta2p",
    "chi2",
)

FIELD_TYPES = ("string", "integer", "number", "boolean", "list", "object")
EDITORS = ("text", "textarea", "number", "boolean", "select", "multiselect", "date", "json", "objectlist", "kv")

#: A record's metric array is conventionally emitted under this key; v2 schemes
#: may rename it via ``metrics.group``.
DEFAULT_METRICS_GROUP = "DV_Metrics"


def _as_str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _normalise_field(raw: object, fallback_group: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    name = _as_str(raw.get("name"))
    label = _as_str(raw.get("label")) or name
    field: dict[str, Any] = {
        "name": name,
        "label": label,
        "group": _as_str(raw.get("group")) or fallback_group,
        "type": _as_str(raw.get("type"), "string") or "string",
        "editor": _as_str(raw.get("editor"), "text") or "text",
        "required": bool(raw.get("required", False)),
        "description": _as_str(raw.get("description")),
        "instruction": _as_str(raw.get("instruction")),
        "options": raw.get("options") if isinstance(raw.get("options"), list) else [],
        "columns": raw.get("columns") if isinstance(raw.get("columns"), list) else [],
        "role": normalise_role(raw.get("role")),
        #: Module identity for module-routed fields (``None`` for common/DV
        #: fields). Collision fields keep their first occurrence's ``options``
        #: and expose the per-module option lists here so an editor can honour
        #: the record's module without renaming the field (which would break
        #: the importer's by-name merge).
        "module": raw.get("module") if isinstance(raw.get("module"), str) and raw.get("module") else None,
        "module_options": raw.get("module_options") if isinstance(raw.get("module_options"), dict) else {},
        #: Whether the field may be chosen as an analysis moderator. Default
        #: True so every coded variable is offered unless the user hid it.
        "moderator": bool(raw.get("moderator", True)),
    }
    return field


def _normalise_groups(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for group in raw:
        if isinstance(group, dict):
            name = _as_str(group.get("name"))
            if not name:
                continue
            out.append({"name": name, "label": _as_str(group.get("label")) or name})
        elif isinstance(group, str) and group.strip():
            out.append({"name": group.strip(), "label": group.strip()})
    return out


def _normalise_code_fields(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for entry in raw:
        if isinstance(entry, dict):
            name = _as_str(entry.get("name"))
            if not name:
                continue
            out.append(
                {
                    "name": name,
                    "label": _as_str(entry.get("label")) or name,
                    "instruction": _as_str(entry.get("instruction")),
                }
            )
        elif isinstance(entry, str) and entry.strip():
            name = entry.strip()
            out.append({"name": name, "label": name, "instruction": ""})
    return out


def normalise_codebook(raw: object) -> dict[str, Any]:
    """Upgrade a v1 or v2 codebook to the canonical v2 shape."""
    book: dict[str, Any] = raw if isinstance(raw, dict) else {}
    groups = _normalise_groups(book.get("groups"))
    first_group = groups[0]["name"] if groups else "Study"

    raw_fields = book.get("study_fields")
    if not isinstance(raw_fields, list):
        raw_fields = book.get("fields")
    fields = [_normalise_field(f, first_group) for f in raw_fields] if isinstance(raw_fields, list) else []

    metrics_obj = book.get("metrics")
    raw_metrics: dict[str, Any] = metrics_obj if isinstance(metrics_obj, dict) else {}
    raw_metric_fields = raw_metrics.get("fields")
    metric_fields = (
        [_normalise_field(f, _as_str(raw_metrics.get("group")) or DEFAULT_METRICS_GROUP)
         for f in raw_metric_fields]
        if isinstance(raw_metric_fields, list)
        else []
    )
    metrics = {
        "enabled": bool(raw_metrics.get("enabled", bool(metric_fields))),
        "group": _as_str(raw_metrics.get("group")) or DEFAULT_METRICS_GROUP,
        "label": _as_str(raw_metrics.get("label")) or "Effect sizes",
        "fields": metric_fields,
    }

    families_raw = book.get("effect_families")
    families = (
        [f for f in families_raw if isinstance(f, str) and f in EFFECT_FAMILIES]
        if isinstance(families_raw, list)
        else []
    )

    normalised: dict[str, Any] = {
        "version": 2,
        "category": _as_str(book.get("category")) or "Meta",
        "groups": groups,
        "fields": fields,
        # Alias kept for the publish path and older readers.
        "study_fields": fields,
        "metrics": metrics,
        "effect_families": families,
        "code_fields": _normalise_code_fields(book.get("code_fields")),
        #: Intervention type -> module keys, preserved so a reader can derive
        #: which module fields apply to a record from its ``Intervention_Type``.
        "intervention_type_modules": (
            {str(k): [str(m) for m in v] for k, v in book["intervention_type_modules"].items()
             if isinstance(v, list)}
            if isinstance(book.get("intervention_type_modules"), dict)
            else {}
        ),
    }
    return normalised


def study_fields(codebook: dict[str, Any]) -> list[dict[str, Any]]:
    """Study/experiment-level fields (alias of ``fields``)."""
    fields = codebook.get("fields")
    if not isinstance(fields, list):
        fields = codebook.get("study_fields")
    return fields if isinstance(fields, list) else []


def metric_fields(codebook: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = codebook.get("metrics")
    if not isinstance(metrics, dict):
        return []
    fields = metrics.get("fields")
    return fields if isinstance(fields, list) else []


def all_fields(codebook: dict[str, Any]) -> list[dict[str, Any]]:
    return [*study_fields(codebook), *metric_fields(codebook)]


def enabled_families(codebook: dict[str, Any]) -> list[str]:
    return [f for f in (codebook.get("effect_families") or []) if f in EFFECT_FAMILIES]


def metrics_group(codebook: dict[str, Any]) -> str:
    metrics = codebook.get("metrics")
    if isinstance(metrics, dict) and metrics.get("group"):
        return str(metrics["group"])
    return DEFAULT_METRICS_GROUP


def field_by_role(codebook: dict[str, Any], role: str) -> dict[str, Any] | None:
    for field in all_fields(codebook):
        if field.get("role") == role:
            return field
    return None


def fields_by_role(codebook: dict[str, Any], role: str) -> list[dict[str, Any]]:
    return [f for f in all_fields(codebook) if f.get("role") == role]


def field_listing(fields: list[dict[str, Any]], *, include_role: bool = False) -> str:
    """Human/LLM-readable listing of fields, grouped in list order."""
    lines: list[str] = []
    group: object = None
    for field in fields:
        if not isinstance(field, dict):
            continue
        if field.get("group") != group:
            group = field.get("group")
            lines.append(f"### {group or 'Fields'}")
        label = field.get("label") or field.get("name") or ""
        name = field.get("name") or ""
        parts = [f"* **{name}**"]
        if label and label != name:
            parts.append(f" — {label}")
        if field.get("required"):
            parts.append(" (required)")
        description = field.get("description") or field.get("instruction")
        if description:
            parts.append(f": {description}")
        options = field.get("options")
        if isinstance(options, list) and options:
            rendered = ", ".join(str(o) for o in options)
            parts.append(f" Options: {rendered}.")
        if include_role and field.get("role"):
            parts.append(f" [role: {field['role']}]")
        lines.append("".join(parts))
    return "\n".join(lines)


def code_field_names(codebook: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for entry in codebook.get("code_fields") or []:
        if isinstance(entry, dict) and entry.get("name"):
            names.append(str(entry["name"]))
        elif isinstance(entry, str) and entry:
            names.append(entry)
    return names
