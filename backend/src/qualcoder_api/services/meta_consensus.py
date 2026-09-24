"""Consensus extraction rows for analysis (no coder picker in Analyze).

When no ``owner`` filter is given, analysis must combine *all* codings minus
unresolved conflicts instead of picking one extraction per hit. This module
merges the extracted rows of one ``(hit_id, scheme)`` group into a single
consensus row:

* Single-owner groups pass through unchanged (today's behaviour).
* Multi-owner groups align records across owners by the ``study_id`` role
  value (record index as fallback) and metrics within a record by the
  ``dv_name`` role value (metric index as fallback) — the same alignment the
  agreement machinery uses (``meta_agreement``), so reordered records/metrics
  never fabricate a conflict.
* Per unit-field the values across owners are compared canonically.
  Unanimous fields are kept. On disagreement the settled master value wins
  (see below); without one the field is EXCLUDED. Records/metrics present in
  only one coder are kept (they are not conflicts).
* A metric that loses its last derivable effect to exclusion is dropped
  (and counted); metrics that were underivable anyway stay in the row and
  are skipped downstream exactly as today.

Settled master values: the agreement machinery
(``meta_agreement.conflicts``) marks a disagreeing cell ``settled`` exactly
when the non-master raters disagree and the ``master`` owner holds a value
for it. Resolution writes that value into a ``master``-owned extraction row,
so consulting the master row for disagreeing cells is equivalent to reading
``settled`` + ``master_value`` out of the conflicts envelope — with the
advantage that alignment by coded ids (rather than record positions) survives
reordered records. The adjudicator is the owner named ``master`` (the same
convention ``_analysis_rows``/``_rank_extraction`` already use), overridable
via the ``master`` parameter. Owners resolving under their own coder name
stay regular codings: their agreement still counts, and genuine multi-way
disagreements drop visibly (counted in the report) instead of silently
picking a side.
"""

from __future__ import annotations

from typing import Any

from qualcoder_api.services.meta_effects import derive_effect
from qualcoder_api.services.meta_extract import derive_dv_metrics
from qualcoder_api.services.meta_roles import metric_by_role, role_map, value_by_role
from qualcoder_api.services.meta_scheme import (
    all_fields,
    normalise_codebook,
    study_fields,
)

#: Owner name treated as the adjudicator unless ``master=`` says otherwise.
MASTER_OWNER = "master"


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _canon(value: Any) -> str:
    """Canonical comparison form (mirrors ``meta_agreement._canon``)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        parts = sorted(_canon(item) for item in value)
        return " + ".join(part for part in parts if part)
    return str(value).strip()


def _unanimous(values: list[Any]) -> bool:
    """Canonical equality, ignoring letter case (``RCT`` vs ``rct`` is one
    coding, not a conflict)."""
    canons = {_canon(value) for value in values if _canon(value)}
    if len(canons) <= 1:
        return True
    lowered = {canon.lower() for canon in canons}
    return len(lowered) <= 1


def _record_key(study: dict[str, Any], roles: dict[str, str], index: int) -> str:
    """Stable record key: the coded ``study_id`` when present, else the index.

    Mirrors ``meta_agreement._coded_record_key`` (including its v1-alias
    fallback) so consensus alignment and conflict detection agree.
    """
    value = value_by_role(study, roles, "study_id") if roles else None
    if value in (None, ""):
        value = metric_by_role(study).get("study_id")
    return str(value) if value not in (None, "") else f"#{index}"


def _metric_keys(metrics: list[Any], roles: dict[str, str]) -> list[str]:
    """Stable metric keys: the ``dv_name`` value, else the position.

    Mirrors ``meta_agreement._metric_keys`` (duplicate names gain a
    ``#occurrence`` suffix) so consensus alignment and conflict detection
    agree.
    """
    dv_field = next((name for name, role in roles.items() if role == "dv_name"), None)
    keys: list[str] = []
    seen: dict[str, int] = {}
    for index, metric in enumerate(metrics):
        metric = metric if isinstance(metric, dict) else {}
        dv = metric.get(dv_field) if dv_field else None
        if dv in (None, ""):
            keys.append(f"#{index}")
            continue
        name = str(dv)
        occurrence = seen.get(name, 0)
        seen[name] = occurrence + 1
        keys.append(name if occurrence == 0 else f"{name}#{occurrence}")
    return keys


def _records_of(ext: Any) -> list[dict[str, Any]]:
    study_vars = _get(ext, "study_vars", {}) or {}
    records = study_vars.get("records") if isinstance(study_vars, dict) else None
    return list(records) if isinstance(records, list) else []


def _study_of(record: Any) -> dict[str, Any]:
    study = record.get("study") if isinstance(record, dict) else None
    return study if isinstance(study, dict) else {}


def _metrics_of(record: Any) -> list[Any]:
    metrics = record.get("metrics") if isinstance(record, dict) else None
    return metrics if isinstance(metrics, list) else []


def _empty_report() -> dict[str, Any]:
    return {
        "n_hits": 0,
        "n_groups": 0,
        "n_single_owner": 0,
        "n_consensus_units": 0,
        "n_fields_unanimous": 0,
        "n_master_resolved": 0,
        "n_dropped_conflicts": 0,
        "n_dropped_metrics": 0,
    }


def build_consensus_rows(
    extractions: Any,
    codebook: Any = None,
    *,
    master: str | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Merge ``extractions`` of one scheme into consensus rows.

    ``extractions`` are ``MetaExtraction`` models or plain dicts (only
    ``status == "extracted"`` rows contribute). Returns ``(rows, report)``:
    ``rows`` are the original single-owner objects plus one synthesised
    ``owner="consensus"`` dict per multi-owner ``(hit_id, scheme)`` group;
    ``report`` carries the transparency counts (``n_hits``,
    ``n_consensus_units``, ``n_dropped_conflicts``, ...).

    ``master`` names the adjudicating owner (default: the literal
    ``"master"`` owner when present, else no adjudicator and every
    disagreement is excluded + counted).
    """
    book = normalise_codebook(codebook) if codebook is not None else None
    roles = role_map(all_fields(book)) if book else {}
    study_role_map = role_map(study_fields(book)) if book else None
    report = _empty_report()

    rows_in = list(extractions if isinstance(extractions, list) else [])
    rows_in = [ext for ext in rows_in if str(_get(ext, "status", "extracted")) == "extracted"]
    if not rows_in:
        return [], report

    groups: dict[tuple[Any, Any], list[Any]] = {}
    for ext in rows_in:
        groups.setdefault((_get(ext, "hit_id", 0), _get(ext, "scheme", "")), []).append(ext)
    report["n_hits"] = len({hit for hit, _scheme in groups})
    report["n_groups"] = len(groups)

    out: list[Any] = []
    for (hit_id, scheme), group in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        adjudicator = master if master is not None else MASTER_OWNER
        coder_rows = [ext for ext in group if str(_get(ext, "owner", "")) != adjudicator]
        master_rows = [ext for ext in group if str(_get(ext, "owner", "")) == adjudicator]
        # A group whose only non-adjudicator owner is single passes through
        # unchanged — with no second coding there is nothing to reconcile.
        # (A lone adjudicator row with no codings behind it is data, not a
        # merge, so it passes through as well.)
        if len(coder_rows) <= 1 and not (len(coder_rows) == 0 and len(master_rows) > 1):
            if len(coder_rows) == 1:
                out.append(coder_rows[0])
            else:
                out.extend(master_rows)
            report["n_single_owner"] += 1
            continue
        if len(coder_rows) == 0:
            # Several adjudicator-owned rows (re-resolved over time): merge
            # them as peers with no adjudicator above them.
            coder_rows, master_rows = master_rows, []
        merged = _merge_group(
            hit_id, scheme, coder_rows, master_rows, roles, study_role_map, report
        )
        report["n_consensus_units"] += 1
        out.append(merged)
    return out, report


def _merge_group(
    hit_id: Any,
    scheme: Any,
    coder_rows: list[Any],
    master_rows: list[Any],
    roles: dict[str, str],
    study_role_map: dict[str, str] | None,
    report: dict[str, Any],
) -> dict[str, Any]:
    """Field-wise consensus of one multi-owner ``(hit_id, scheme)`` group."""
    # Align every row's records/metrics once: record key → (row position,
    # record, study, metric keys, metrics).
    aligned: list[dict[str, Any]] = []
    for ext in coder_rows:
        records = _records_of(ext)
        by_key: dict[str, dict[str, Any]] = {}
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            study = _study_of(record)
            key = _record_key(study, roles, index)
            if key in by_key:
                key = f"{key}##{index}"
            metrics = _metrics_of(record)
            by_key[key] = {
                "index": index,
                "study": study,
                "metric_keys": _metric_keys(metrics, roles),
                "metrics": metrics,
            }
        aligned.append({"ext": ext, "records": by_key})

    master_aligned: list[dict[str, Any]] = []
    for ext in master_rows:
        records = _records_of(ext)
        by_key = {}
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            study = _study_of(record)
            key = _record_key(study, roles, index)
            if key in by_key:
                key = f"{key}##{index}"
            metrics = _metrics_of(record)
            by_key[key] = {
                "study": study,
                "metric_keys": _metric_keys(metrics, roles),
                "metrics": metrics,
            }
        master_aligned.append(by_key)

    consensus_records: list[dict[str, Any]] = []
    record_keys: list[str] = []
    for entry in aligned:
        for key in entry["records"]:
            if key not in record_keys:
                record_keys.append(key)

    for key in record_keys:
        entries = [(entry, entry["records"][key]) for entry in aligned if key in entry["records"]]
        consensus_study: dict[str, Any] = {}
        excluded_study: dict[str, list[Any]] = {}
        field_names: list[str] = []
        for _entry, rec in entries:
            for name in rec["study"]:
                if name not in field_names:
                    field_names.append(name)
        for name in field_names:
            present = [(rec["study"][name], rec) for _entry, rec in entries if name in rec["study"]]
            raw_values = [value for value, _rec in present if _canon(value)]
            if not raw_values:
                continue
            if _unanimous(raw_values):
                consensus_study[name] = raw_values[0]
                report["n_fields_unanimous"] += 1
                continue
            settled = _master_value(master_aligned, key, None, name)
            if settled is not None:
                consensus_study[name] = settled
                report["n_master_resolved"] += 1
            else:
                excluded_study[name] = raw_values
                report["n_dropped_conflicts"] += 1

        # Metrics aligned by dv_name within this record (union across coders).
        metric_keys: list[str] = []
        for _entry, rec in entries:
            for mkey in rec["metric_keys"]:
                if mkey not in metric_keys:
                    metric_keys.append(mkey)
        consensus_metrics: list[dict[str, Any]] = []
        for mkey in metric_keys:
            holders = []
            for _entry, rec in entries:
                try:
                    pos = rec["metric_keys"].index(mkey)
                except ValueError:
                    continue
                metric = rec["metrics"][pos] if pos < len(rec["metrics"]) else None
                if isinstance(metric, dict):
                    holders.append(metric)
            if not holders:
                continue
            if len(holders) == 1:
                # Coded by a single coder: kept, never a conflict.
                consensus_metrics.append(dict(holders[0]))
                continue
            merged_metric: dict[str, Any] = {}
            excluded_metric: dict[str, list[Any]] = {}
            metric_fields: list[str] = []
            for holder in holders:
                for name in holder:
                    if name not in metric_fields:
                        metric_fields.append(name)
            for name in metric_fields:
                raw_values = [holder[name] for holder in holders if name in holder]
                raw_values = [value for value in raw_values if _canon(value)]
                if not raw_values:
                    continue
                if _unanimous(raw_values):
                    merged_metric[name] = raw_values[0]
                    report["n_fields_unanimous"] += 1
                    continue
                settled = _master_value(master_aligned, key, mkey, name)
                if settled is not None:
                    merged_metric[name] = settled
                    report["n_master_resolved"] += 1
                else:
                    excluded_metric[name] = raw_values
                    report["n_dropped_conflicts"] += 1
            if _derivable(consensus_study, merged_metric, roles, study_role_map):
                consensus_metrics.append(merged_metric)
            elif excluded_metric or excluded_study:
                # Lost its effect to exclusion: drop the metric (counted),
                # unless it was underivable anyway (kept; skipped downstream
                # exactly as a single-coder row would be).
                restored = dict(merged_metric)
                for name, raw_values in excluded_metric.items():
                    restored[name] = raw_values[0]
                restored_study = dict(consensus_study)
                for name, raw_values in excluded_study.items():
                    restored_study[name] = raw_values[0]
                if _derivable(restored_study, restored, roles, study_role_map):
                    report["n_dropped_metrics"] += 1
                    continue
                consensus_metrics.append(merged_metric)
            else:
                consensus_metrics.append(merged_metric)
        consensus_records.append({"study": consensus_study, "metrics": consensus_metrics})

    component_ids = [int(_get(ext, "id", 0) or 0) for ext in (*coder_rows, *master_rows)]
    source_id = _get(coder_rows[0], "source_id", None)
    return {
        "id": max(component_ids) if component_ids else 0,
        "hit_id": hit_id,
        "owner": "consensus",
        "scheme": scheme,
        "source_id": source_id,
        "study_vars": {"records": consensus_records},
        "dv_metrics": derive_dv_metrics(consensus_records, study_role_map),
        "status": "extracted",
    }


def _master_value(
    master_aligned: list[dict[str, Any]],
    record_key: str,
    metric_key: str | None,
    field_name: str,
) -> Any | None:
    """The adjudicator's raw value for one aligned unit-field (``None`` when
    the adjudicator holds nothing there — i.e. the conflict is unresolved)."""
    for by_key in master_aligned:
        rec = by_key.get(record_key)
        if not rec:
            continue
        if metric_key is None:
            value = rec["study"].get(field_name)
            if _canon(value):
                return value
            continue
        try:
            pos = rec["metric_keys"].index(metric_key)
        except ValueError:
            continue
        metric = rec["metrics"][pos] if pos < len(rec["metrics"]) else None
        if isinstance(metric, dict) and _canon(metric.get(field_name)):
            return metric[field_name]
    return None


def _derivable(
    study: dict[str, Any],
    metric: dict[str, Any],
    roles: dict[str, str],
    study_role_map: dict[str, str] | None,
) -> bool:
    """Whether one consensus metric still yields an effect size."""
    flat = derive_dv_metrics([{"study": study, "metrics": [metric]}], study_role_map)
    if not flat:
        return False
    return derive_effect(metric_by_role(flat[0], roles or None)) is not None
