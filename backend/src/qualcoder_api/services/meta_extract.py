"""Meta-analysis extraction — scheme-driven prescreen + full extraction.

Adapted from the reference ``Inoculation_Meta/meta/core/extraction.py``: a
cheap LLM prescreen gates full-text extraction; the full coding prompt is
scheme-defined; DV metrics are normalized and validated through the field
**roles** (``meta_roles``) against the scheme's enabled ``effect_families``;
results flatten to one row per DV metric for export. Written for QCnext's
stack (``source.fulltext``, ``MetaRepository``, ``AiService``).
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from qualcoder_api.core.models import MetaHit, MetaScheme
from qualcoder_api.persistence.repo.meta_repo import MetaRepository
from qualcoder_api.services import ai_service
from qualcoder_api.services.meta_effects import metric_status
from qualcoder_api.services.meta_prompt import (
    build_extraction_messages,
    build_prescreen_messages,
    extract_json,
    scheme_prompt_hash,
    truncate_for_context,
)
from qualcoder_api.services.meta_roles import (
    STUDY_ROLES,
    metric_by_role,
    role_map,
    value_by_role,
    write_role_value,
)
from qualcoder_api.services.meta_scheme import (
    all_fields,
    code_field_names,
    enabled_families,
    metrics_group,
    normalise_codebook,
    study_fields,
)
from qualcoder_api.services.user_settings import get_ai_settings

logger = logging.getLogger(__name__)

#: Default per-request input ceiling for full-text extraction (~30k tokens).
#: Callers can override per run; the value only prevents an oversized paper
#: from hard-failing the whole request on a smaller-context model.
DEFAULT_MAX_INPUT_CHARS = 120_000
#: The prescreen only needs the front matter; capping it keeps the cheap gate
#: cheap even when the caller allows a large extraction window.
PRESCREEN_MAX_CHARS = 60_000


# ── role-driven metric normalization (ported from the reference pipeline) ─

def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _int(value: Any) -> int | None:
    num = _num(value)
    if num is None or num <= 0 or not num.is_integer():
        return None
    return int(num)


def _infer_balanced_group_sizes(by_role: dict[str, Any]) -> None:
    """Infer missing group sizes from ``n_total`` (role-level)."""
    n_total = _int(by_role.get("n_total"))
    n1 = _int(by_role.get("n1"))
    n2 = _int(by_role.get("n2"))
    if n1 is None and n2 is None and n_total is not None and n_total > 1:
        by_role["n1"] = n_total // 2
        by_role["n2"] = n_total - by_role["n1"]
        return
    if n1 is None and n_total is not None and n2 is not None:
        by_role["n1"] = max(n_total - n2, 0)
        return
    if n2 is None and n_total is not None and n1 is not None:
        by_role["n2"] = max(n_total - n1, 0)


def _infer_effect_size_aliases(by_role: dict[str, Any]) -> None:
    """``d``/``g`` → ``yi`` and derive ``vi``/``sei`` (role-level)."""
    if by_role.get("yi") is None:
        if by_role.get("d") is not None:
            by_role["yi"] = by_role.get("d")
        elif by_role.get("g") is not None:
            by_role["yi"] = by_role.get("g")
    yi = _num(by_role.get("yi"))
    if yi is None:
        return
    n1 = _int(by_role.get("n1"))
    n2 = _int(by_role.get("n2"))
    if by_role.get("vi") is None and n1 and n2:
        total_n = n1 + n2
        by_role["vi"] = (total_n / (n1 * n2)) + ((yi * yi) / (2 * total_n))
    vi = _num(by_role.get("vi"))
    if by_role.get("sei") is None and vi is not None and vi >= 0:
        by_role["sei"] = math.sqrt(vi)


_ROLES_WRITTEN_BACK = ("n1", "n2", "m1", "m2", "sd1", "sd2", "yi", "vi", "sei")


def normalize_metric(
    metric: Any, roles: dict[str, str] | None = None, families: list[str] | None = None
) -> Any:
    """Normalise a metric through its roles (aliases, balanced groups, d/g→yi)."""
    if not isinstance(metric, dict):
        return metric
    by_role = metric_by_role(metric, roles)
    _infer_balanced_group_sizes(by_role)
    _infer_effect_size_aliases(by_role)
    for role in _ROLES_WRITTEN_BACK:
        if by_role.get(role) is not None:
            write_role_value(metric, roles, role, by_role[role])
    return metric


def metric_has_full_descriptives(metric: dict, roles: dict[str, str] | None = None) -> bool:
    """v1-compatibility helper: kept because the legacy unit tests import it."""
    by_role = metric_by_role(metric, roles)
    return all(
        _num(by_role.get(role)) is not None
        for role in ("n1", "m1", "sd1", "n2", "m2", "sd2")
    )


def metric_has_metafor_fallback(
    metric: dict, roles: dict[str, str] | None = None, families: list[str] | None = None
) -> bool:
    """v1-compatibility helper: kept because the legacy unit tests import it."""
    status, _ = metric_status(metric_by_role(metric, roles), families)
    return status == "fallback"


def normalize_and_validate(
    response_json: Any,
    roles: dict[str, str] | None = None,
    families: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Normalize DV metrics; returns (records, missing_entries).

    v1-compatibility helper (contract ``DV_Metrics`` response shape): retained
    only because the legacy unit tests import it. New extraction writes go
    through :func:`records_from_response` which returns the contract §4 shape.
    """
    records = response_json if isinstance(response_json, list) else [response_json]
    records = [r for r in records if isinstance(r, dict)]
    missing: list[dict] = []
    for record in records:
        metrics = record.get("DV_Metrics")
        if not isinstance(metrics, list):
            continue
        for i, metric in enumerate(metrics):
            metric = normalize_metric(metric, roles, families)
            metrics[i] = metric
            if not isinstance(metric, dict):
                continue
            status, default_reason = metric_status(metric_by_role(metric, roles), families)
            if status == "incomplete":
                reason = _role_value(metric, roles, "missing_reason")
                if not reason:
                    reason = default_reason
                    _set_missing_reason(metric, roles, reason)
                missing.append(
                    {
                        "study_id": _role_value(record, roles, "study_id"),
                        "dv_name": _role_value(metric, roles, "dv_name"),
                        "comparison_label": _role_value(metric, roles, "comparison_label"),
                        "reason": reason,
                    }
                )
    return records, missing


def _role_value(record: dict, roles: dict[str, str] | None, role: str) -> Any:
    if roles:
        found = value_by_role(record, roles, role)
        if found is not None:
            return found
    return metric_by_role(record).get(role)


def _set_missing_reason(metric: dict, roles: dict[str, str] | None, reason: str) -> None:
    if not write_role_value(metric, roles, "missing_reason", reason):
        metric["missing_metrics_reason"] = reason


# ── extraction record model (contract §4) ────────────────────────────────

def _split_response_record(raw: dict, group: str) -> tuple[dict, list]:
    # Canonical manual-save shape: {"study": {...}, "metrics": [...]}.
    study_in = raw.get("study")
    if isinstance(study_in, dict):
        metrics = raw.get("metrics")
        return dict(study_in), metrics if isinstance(metrics, list) else []
    metrics = raw.get(group)
    if not isinstance(metrics, list):
        metrics = raw.get("DV_Metrics")
    if not isinstance(metrics, list):
        metrics = raw.get("metrics")
    metrics = metrics if isinstance(metrics, list) else []
    study = {k: v for k, v in raw.items() if k not in (group, "DV_Metrics", "metrics")}
    return study, metrics


def records_from_response(
    response_json: Any, codebook: dict | None
) -> tuple[list[dict], list[dict]]:
    """Normalise an LLM response to ``[{"study": {...}, "metrics": [...]}]``.

    Returns ``(records, missing)`` where ``missing`` lists metric comparisons
    that lack a complete statistic set (with the default reason applied).
    """
    book = normalise_codebook(codebook)
    roles = role_map(all_fields(book))
    families = enabled_families(book)
    group = metrics_group(book)

    raw_records = response_json if isinstance(response_json, list) else [response_json]
    raw_records = [r for r in raw_records if isinstance(r, dict)]
    records: list[dict] = []
    missing: list[dict] = []
    for raw in raw_records:
        study, raw_metrics = _split_response_record(raw, group)
        metrics: list[dict] = []
        for metric in raw_metrics:
            if not isinstance(metric, dict):
                continue
            metric = normalize_metric(dict(metric), roles, families)
            metrics.append(metric)
            status, default_reason = metric_status(metric_by_role(metric, roles), families)
            if status == "incomplete":
                reason = _role_value(metric, roles, "missing_reason")
                if not reason:
                    reason = default_reason
                    _set_missing_reason(metric, roles, reason)
                missing.append(
                    {
                        "study_id": _role_value(study, roles, "study_id"),
                        "dv_name": _role_value(metric, roles, "dv_name"),
                        "comparison_label": _role_value(metric, roles, "comparison_label"),
                        "reason": reason,
                    }
                )
        records.append({"study": study, "metrics": metrics})
    return records, missing


def refresh_dv_metrics(extraction: Any, codebook: dict | None) -> Any:
    """Copy of ``extraction`` with ``dv_metrics`` re-derived from its records.

    The persisted ``dv_metrics`` column is a cache: after a scheme role edit it
    can disagree with what the live codebook would derive. Analysis and export
    call this so they always read the current derivation; pass ``None`` to
    leave the cached value untouched (e.g. a legacy extraction with no scheme).
    """
    if codebook is None:
        return extraction
    study_vars = (
        extraction.get("study_vars")
        if isinstance(extraction, dict)
        else getattr(extraction, "study_vars", None)
    )
    records = study_vars.get("records") if isinstance(study_vars, dict) else None
    if not isinstance(records, list):
        return extraction
    book = normalise_codebook(codebook)
    dv_metrics = derive_dv_metrics(records, role_map(study_fields(book)))
    if isinstance(extraction, dict):
        return {**extraction, "dv_metrics": dv_metrics}
    return extraction.model_copy(update={"dv_metrics": dv_metrics})


def derive_dv_metrics(
    records: list[dict], study_role_map: dict[str, str] | None = None
) -> list[dict]:
    """Flatten records to one row per metric (study role values merged in).

    Each row carries a ``_record`` index so agreement/analysis can key back to
    the experiment it came from.
    """
    role_map_values = set((study_role_map or {}).values())
    has_study_roles = any(role in STUDY_ROLES for role in role_map_values)
    out: list[dict] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        study = record.get("study")
        study = study if isinstance(study, dict) else {}
        merged_study: dict[str, Any] = {}
        for name, value in study.items():
            if isinstance(value, (dict, list)):
                continue
            if has_study_roles and (study_role_map or {}).get(name) not in STUDY_ROLES:
                continue
            merged_study[name] = value
        metrics = record.get("metrics")
        for metric in metrics if isinstance(metrics, list) else []:
            if not isinstance(metric, dict):
                continue
            out.append({**merged_study, **metric, "_record": index})
    return out


# ── prescreen / extraction logic ─────────────────────────────────────────

def _prescreen_include(result: dict) -> bool:
    """All boolean keys (excluding ``rationale``) must be true."""
    flags = [v for k, v in result.items() if k != "rationale" and isinstance(v, bool)]
    return bool(flags) and all(flags)


def _rationale_from_flags(result: dict) -> str:
    false_flags = [k for k, v in result.items() if k != "rationale" and v is False]
    if not false_flags:
        return "The paper appears to meet the screening criteria."
    if len(false_flags) == 1:
        return f"Excluded because {false_flags[0]}."
    return "Excluded because " + ", ".join(false_flags) + "."


async def _ai(ai: dict, messages: list[dict], model: str | None) -> str:
    effective = dict(ai)
    if model:
        effective["model"] = model
    service = ai_service.AiService(None)
    return await service.chat_messages(effective, messages)


async def prescreen_hit(
    ai: dict,
    scheme: MetaScheme,
    hit: MetaHit,
    source_text: str,
    model: str | None = None,
    max_chars: int = PRESCREEN_MAX_CHARS,
) -> tuple[bool, dict]:
    """Run the scheme's prescreen prompt against the paper text."""
    messages = build_prescreen_messages(
        scheme.prescreen_prompt or "",
        truncate_for_context(source_text, max_chars),
        title=hit.title,
    )
    raw = await _ai(ai, messages, model)
    result = extract_json(raw) or {}
    if not isinstance(result, dict):
        result = {}
    if not result.get("rationale"):
        result["rationale"] = _rationale_from_flags(result)
    include = _prescreen_include(result)
    return include, result


async def extract_hit(
    ai: dict,
    scheme: MetaScheme,
    hit: MetaHit,
    source_text: str,
    model: str | None = None,
    max_chars: int = DEFAULT_MAX_INPUT_CHARS,
    codebook: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """Run the scheme's full coding prompt; returns (records, missing)."""
    messages = build_extraction_messages(
        scheme.coding_prompt or "",
        truncate_for_context(source_text, max_chars),
        title=hit.title,
    )
    raw = await _ai(ai, messages, model)
    response_json = extract_json(raw)
    if response_json is None:
        raise ValueError("No valid JSON found in model response.")
    records, missing = records_from_response(response_json, codebook)
    if not records:
        raise ValueError("Model returned no study records.")
    return records, missing


async def _source_fulltext(session, source_id: int) -> str:
    from sqlalchemy import select

    from qualcoder_api.persistence import tables

    row = (
        await session.execute(
            select(tables.source.c.fulltext).where(tables.source.c.id == source_id)
        )
    ).first()
    if row is None or not row[0]:
        return ""
    return str(row[0])


async def run_extraction(
    session_factory: async_sessionmaker,
    *,
    hit_ids: list[int] | None,
    owner: str,
    scheme_name: str,
    model: str | None = None,
    stop_after: int = 0,
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
    fulltext_only: bool = True,
    progress_cb=None,
    should_stop=None,
) -> dict:
    """Prescreen + extract eligible hits; returns a summary dict."""
    progress_cb = progress_cb or (lambda done, total, msg="": None)
    should_stop = should_stop or (lambda: False)
    ai = get_ai_settings()
    if not ai.get("enabled"):
        raise ValueError("AI is not enabled — enable it in Settings first.")

    from qualcoder_api.services.meta_eligibility import eligible_hit_ids

    async with session_factory() as session:
        repo = MetaRepository(session)
        scheme = await repo.get_scheme(name=scheme_name)
        if scheme is None:
            raise ValueError(f"Unknown scheme '{scheme_name}' — create it first.")
        codebook: dict = {}
        if scheme.codebook:
            try:
                codebook = normalise_codebook(json.loads(scheme.codebook))
            except (TypeError, ValueError):
                codebook = normalise_codebook({})
        study_role_map = role_map(study_fields(codebook))
        if hit_ids:
            # Explicit selection: honour the user's choice regardless of the
            # current screening/link state (they may be re-extracting).
            hits = [h for h in [await repo.get_hit(hid) for hid in hit_ids] if h is not None]
            skipped_no_pdf = 0
        else:
            # Whole-queue: every hit that passes ALL inclusion criteria
            # (latest verdict per hit, any coder) AND has a downloaded source.
            # Hits are not required to carry a particular status — LLM and
            # manual screening both drive eligibility through verdict rows.
            all_hits = await repo.list_hits()
            eligible = await eligible_hit_ids(session, all_hits)
            eligible_hits = [h for h in all_hits if h.hit_id in eligible]
            if fulltext_only:
                docs = {d.hit_id: d for d in await repo.list_documents()}
                hits = [
                    h
                    for h in eligible_hits
                    if (doc := docs.get(h.hit_id)) is not None and doc.source_id is not None
                ]
            else:
                hits = eligible_hits
            skipped_no_pdf = len(eligible_hits) - len(hits)

        total = len(hits)
        processed = 0
        included = 0
        excluded = 0
        extracted = 0
        stopped = False
        errors: list[str] = []

        for hit in hits:
            if should_stop():
                stopped = True
                break
            if stop_after and processed >= stop_after:
                break
            processed += 1
            doc = await repo.get_document_for_hit(hit.hit_id)
            source_id = doc.source_id if doc is not None else None
            source_text = await _source_fulltext(session, source_id) if source_id else ""

            prompt_hash = scheme_prompt_hash(
                scheme.name, scheme.coding_prompt or "", scheme.prescreen_prompt or ""
            )
            try:
                if not source_text:
                    raise ValueError("No source text — download the paper first.")
                include, prescreen = await prescreen_hit(
                    ai, scheme, hit, source_text, model=model
                )
                if not include:
                    await repo.upsert_extraction(
                        hit_id=hit.hit_id,
                        owner=owner,
                        scheme=scheme.name,
                        source_id=source_id,
                        prescreen=prescreen,
                        model=ai.get("model") or model,
                        prompt_hash=prompt_hash,
                        status="excluded",
                    )
                    await repo.set_hit_status(hit.hit_id, "excluded")
                    excluded += 1
                    progress_cb(processed, total, f"excluded: {hit.title}")
                    continue
                included += 1
                records, missing = await extract_hit(
                    ai, scheme, hit, source_text, model=model,
                    max_chars=max_input_chars, codebook=codebook,
                )
                dv_metrics = derive_dv_metrics(records, study_role_map)
                missing_reason = (
                    f"{len(missing)} DV comparisons lack full statistics" if missing else None
                )
                await repo.upsert_extraction(
                    hit_id=hit.hit_id,
                    owner=owner,
                    scheme=scheme.name,
                    source_id=source_id,
                    study_vars={"records": records},
                    dv_metrics=dv_metrics,
                    prescreen=prescreen,
                    model=ai.get("model") or model,
                    prompt_hash=prompt_hash,
                    status="extracted",
                    missing_reason=missing_reason,
                )
                await repo.set_hit_status(hit.hit_id, "extracted")
                extracted += 1
                progress_cb(processed, total, f"extracted: {hit.title}")
            except Exception as err:
                logger.warning("Extraction failed for %s: %s", hit.title, err)
                errors.append(f"{hit.title}: {err}")
                progress_cb(processed, total, f"error: {hit.title}")

    return {
        "total": total,
        "processed": processed,
        "included": included,
        "excluded": excluded,
        "extracted": extracted,
        "skipped_no_pdf": skipped_no_pdf,
        "errors": errors,
        "stopped": stopped,
    }


# ── export ───────────────────────────────────────────────────────────────

def _study_of(record: Any) -> dict:
    """Study dict from either a v2 ``{study, metrics}`` record or a v1 study."""
    if isinstance(record, dict):
        study = record.get("study")
        if isinstance(study, dict):
            return study
        return record
    return {}


def _is_v2_records(ext) -> bool:
    records = (ext.study_vars or {}).get("records") if isinstance(ext.study_vars, dict) else None
    return isinstance(records, list) and any(
        isinstance(r, dict) and "metrics" in r and "study" in r for r in records
    )


def flatten_to_rows(extractions: list) -> list[dict]:
    """One dict per DV metric (study vars merged in, minus nested lists)."""
    rows: list[dict] = []
    for ext in extractions:
        base = {"hit_id": ext.hit_id, "scheme": ext.scheme, "owner": ext.owner}
        metrics = ext.dv_metrics or []
        if _is_v2_records(ext):
            for metric in metrics:
                if not isinstance(metric, dict):
                    continue
                rows.append({**base, **_scalars(metric)})
            continue
        # v1 shape: study rows + metric-only dv_metrics (merge by Study_ID).
        study_rows = (ext.study_vars or {}).get("records", []) if isinstance(ext.study_vars, dict) else []
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            study = {}
            if isinstance(study_rows, list):
                for s in study_rows:
                    if isinstance(s, dict) and s.get("Study_ID") == metric.get("Study_ID"):
                        study = s
                        break
            elif isinstance(study_rows, dict):
                study = study_rows
            row = dict(base)
            for k, v in (study or {}).items():
                if k == "DV_Metrics" or isinstance(v, (dict, list)):
                    continue
                row[k] = _scalar(v)
            for k, v in metric.items():
                if k == "cell_descriptives" or isinstance(v, (dict, list)):
                    continue
                row[f"DV_{k}"] = _scalar(v)
            rows.append(row)
        if not metrics and study_rows:
            for study in study_rows:
                if not isinstance(study, dict):
                    continue
                rows.append({**base, **_scalars(study)})
    return rows


def _scalars(record: dict) -> dict:
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key == "cell_descriptives" or isinstance(value, (dict, list)):
            continue
        out[key] = _scalar(value)
    return out


def _scalar(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def export_csv(rows: list[dict]) -> tuple[str, bytes]:
    import csv
    import io

    if not rows:
        return "meta_extraction.csv", b""
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: "" if v is None else v for k, v in row.items()})
    return "meta_extraction.csv", buf.getvalue().encode("utf-8-sig")


def export_xlsx(rows: list[dict]) -> tuple[str, bytes]:
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Extraction"
    if rows:
        columns: list[str] = []
        for row in rows:
            for key in row:
                if key not in columns:
                    columns.append(key)
        ws.append(columns)
        for row in rows:
            ws.append(["" if row.get(c) is None else row.get(c) for c in columns])
    buf = io.BytesIO()
    wb.save(buf)
    return "meta_extraction.xlsx", buf.getvalue()


# ── publish to QCnext primitives (opt-in) ────────────────────────────────

async def publish_to_cases(
    session, *, hit_id: int, owner: str, codebook: dict
) -> dict:
    """Mirror the extracted study fields onto a case + case attributes.

    Flat study-level fields (per the codebook's study fields) become case
    attributes; a case is created per hit when it does not exist yet.
    Returns a summary of created entities.
    """
    from qualcoder_api.persistence.repo.attribute_repo import AttributeRepository
    from qualcoder_api.persistence.repo.case_repo import CaseRepository

    repo = MetaRepository(session)
    ext = await repo.get_extraction_for_hit(hit_id, owner)
    hit = await repo.get_hit(hit_id)
    if ext is None or hit is None:
        return {"caseid": None, "attributes": 0, "error": "no extraction for hit"}

    book = normalise_codebook(codebook)
    study_rows = (ext.study_vars or {}).get("records", []) if isinstance(ext.study_vars, dict) else []
    study = _study_of(study_rows[0]) if study_rows else {}
    study_id = _role_value(study, role_map(study_fields(book)), "study_id")
    case_name = str(study_id or hit.title or f"Hit {hit_id}")[:120]

    case_repo = CaseRepository(session)
    cases = await case_repo.list_cases()
    case = next((c for c in cases if c.name == case_name), None)
    if case is None:
        case = await case_repo.add_case(name=case_name, memo="", owner=owner)
    if case is None:  # pragma: no cover - raced duplicate
        return {"caseid": None, "attributes": 0, "error": "case create failed"}

    attr_repo = AttributeRepository(session)
    field_defs = {f["name"]: f for f in study_fields(book) if f.get("name")}
    created = 0
    for field, value in study.items():
        field_def = field_defs.get(field) if field_defs else None
        if field_def is not None and field_def.get("role") == "notes":
            continue
        if isinstance(value, (dict, list)):
            continue
        if field_defs and field not in field_defs:
            continue
        types = await attr_repo.list_types()
        valuetype = "number" if isinstance(value, (int, float)) else "text"
        if not any(t.name == field for t in types):
            await attr_repo.add_type(
                name=field, owner=owner, case_or_file="case", value_type=valuetype
            )
        await attr_repo.set_value(
            name=field,
            attr_type="case",
            value="" if value is None else str(value),
            entity_id=case.caseid,
            owner=owner,
        )
        created += 1
    return {"caseid": case.caseid, "attributes": created}


async def publish_to_codes(
    session, *, hit_id: int, owner: str, codebook: dict
) -> dict:
    """Derive labels as codes under ``Meta/<scheme>`` with rationale memos.

    Opt-in and conservative: each listed ``code_fields`` value becomes a code
    whose memo carries the extraction rationale. No codings are created (a
    meta extraction is not a text-span analysis); coders who want that do it
    in the coding workspace directly.
    """
    from qualcoder_api.persistence.repo.code_repo import CodeRepository

    repo = MetaRepository(session)
    ext = await repo.get_extraction_for_hit(hit_id, owner)
    hit = await repo.get_hit(hit_id)
    if ext is None or hit is None:
        return {"codes": 0, "error": "no extraction for hit"}

    book = normalise_codebook(codebook)
    study_rows = (ext.study_vars or {}).get("records", []) if isinstance(ext.study_vars, dict) else []
    study = _study_of(study_rows[0]) if study_rows else {}
    rationale = str(_role_value(study, role_map(study_fields(book)), "notes") or "")
    category_name = book.get("category") or "Meta"

    code_repo = CodeRepository(session)
    cats = await code_repo.list_categories()
    cat = next((c for c in cats if c.name == category_name), None)
    if cat is None:
        cat = await code_repo.add_category(name=category_name, owner=owner)

    created = 0
    existing_names = {c.name for c in await code_repo.list_codes()}
    for field in code_field_names(book):
        value = study.get(field)
        if value is None or value == "":
            continue
        values = value if isinstance(value, list) else [value]
        for v in values:
            code_name = f"{field}: {v}"
            if code_name in existing_names:
                continue
            memo = (
                f"Meta extraction for '{hit.title}'"
                + (f"\n\nRationale: {rationale}" if rationale else "")
            )
            await code_repo.add_code(
                name=code_name,
                catid=cat.catid if cat else None,
                owner=owner,
                memo=memo,
            )
            existing_names.add(code_name)
            created += 1
    return {"category": category_name, "codes": created}
