"""Meta-analysis extraction — scheme-driven prescreen + full extraction.

Adapted from the reference ``Inoculation_Meta/meta/core/extraction.py``: a
cheap LLM prescreen gates full-text extraction; the full coding prompt is
scheme-defined; DV metrics are normalized and validated against the metafor
completeness rules; results flatten to one row per DV metric for export.
Written for QCnext's stack (``source.fulltext``, ``MetaRepository``,
``AiService``).
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
from qualcoder_api.services.meta_prompt import (
    build_extraction_messages,
    build_prescreen_messages,
    extract_json,
    scheme_prompt_hash,
    truncate_for_context,
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


# ── DV metric normalization (ported from the reference pipeline) ─────────

def _is_complete(values: list) -> bool:
    return all(v is not None for v in values)


def _copy_legacy_descriptive_aliases(metric: dict) -> None:
    pairs = [
        ("n1i", "n_t"), ("m1i", "m_t"), ("sd1i", "sd_t"),
        ("n2i", "n_c"), ("m2i", "m_c"), ("sd2i", "sd_c"),
    ]
    for new, old in pairs:
        if metric.get(new) is None and metric.get(old) is not None:
            metric[new] = metric.get(old)


def _infer_balanced_group_sizes(metric: dict) -> None:
    n_total = metric.get("n_total")
    n1i = metric.get("n1i")
    n2i = metric.get("n2i")
    if n1i is None and n2i is None and isinstance(n_total, int) and n_total > 1:
        metric["n1i"] = n_total // 2
        metric["n2i"] = n_total - metric["n1i"]
        return
    if n1i is None and isinstance(n_total, int) and isinstance(n2i, int):
        metric["n1i"] = max(n_total - n2i, 0)
        return
    if n2i is None and isinstance(n_total, int) and isinstance(n1i, int):
        metric["n2i"] = max(n_total - n1i, 0)


def _infer_effect_size_aliases(metric: dict) -> None:
    if metric.get("yi") is None:
        if metric.get("d_val") is not None:
            metric["yi"] = metric.get("d_val")
        elif metric.get("g_val") is not None:
            metric["yi"] = metric.get("g_val")
    yi = metric.get("yi")
    if yi is None:
        return
    n1i = metric.get("n1i")
    n2i = metric.get("n2i")
    if (
        metric.get("vi") is None
        and isinstance(n1i, int) and isinstance(n2i, int)
        and n1i > 0 and n2i > 0
    ):
        total_n = n1i + n2i
        metric["vi"] = (total_n / (n1i * n2i)) + ((yi * yi) / (2 * total_n))
    vi = metric.get("vi")
    sei = metric.get("sei")
    if sei is None and isinstance(vi, (int, float)) and vi >= 0:
        metric["sei"] = math.sqrt(vi)


def normalize_metric(metric: Any) -> Any:
    if not isinstance(metric, dict):
        return metric
    _copy_legacy_descriptive_aliases(metric)
    _infer_balanced_group_sizes(metric)
    _infer_effect_size_aliases(metric)
    return metric


def metric_has_full_descriptives(metric: dict) -> bool:
    return _is_complete(
        [
            metric.get("n1i"), metric.get("m1i"), metric.get("sd1i"),
            metric.get("n2i"), metric.get("m2i"), metric.get("sd2i"),
        ]
    )


def metric_has_metafor_fallback(metric: dict) -> bool:
    n1i = metric.get("n1i")
    n2i = metric.get("n2i")
    return any(
        [
            _is_complete([metric.get("t_val"), n1i, n2i]),
            _is_complete([metric.get("F_val"), metric.get("df_num"), metric.get("df_den"), n1i, n2i]),
            _is_complete([metric.get("r_val"), metric.get("n_total")]),
            _is_complete([metric.get("yi"), metric.get("vi")]),
            _is_complete([metric.get("yi"), metric.get("sei")]),
        ]
    )


def normalize_and_validate(response_json: Any) -> tuple[list[dict], list[dict]]:
    """Normalize DV metrics; returns (records, missing_entries)."""
    records = response_json if isinstance(response_json, list) else [response_json]
    records = [r for r in records if isinstance(r, dict)]
    missing: list[dict] = []
    for record in records:
        metrics = record.get("DV_Metrics")
        if not isinstance(metrics, list):
            continue
        for i, metric in enumerate(metrics):
            metric = normalize_metric(metric)
            metrics[i] = metric
            if not isinstance(metric, dict):
                continue
            if not (metric_has_full_descriptives(metric) or metric_has_metafor_fallback(metric)):
                if not metric.get("missing_metrics_reason"):
                    metric["missing_metrics_reason"] = "Missing descriptive or fallback statistics."
                missing.append(
                    {
                        "study_id": record.get("Study_ID"),
                        "dv_name": metric.get("dv_name"),
                        "comparison_label": metric.get("comparison_label"),
                        "reason": metric["missing_metrics_reason"],
                    }
                )
    return records, missing


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
    records, missing = normalize_and_validate(response_json)
    if not records:
        raise ValueError("Model returned no study records.")
    return records, missing


def _split_records(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split records into (study-level rows, flattened DV metrics)."""
    study_rows: list[dict] = []
    metrics: list[dict] = []
    for record in records:
        dv_metrics = record.get("DV_Metrics") if isinstance(record, dict) else None
        study = {k: v for k, v in record.items() if k != "DV_Metrics"} if isinstance(record, dict) else {}
        study_rows.append(study)
        if isinstance(dv_metrics, list):
            for metric in dv_metrics:
                if not isinstance(metric, dict):
                    continue
                flat = {"Study_ID": study.get("Study_ID"), **metric}
                metrics.append(flat)
    return study_rows, metrics


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
                    ai, scheme, hit, source_text, model=model, max_chars=max_input_chars
                )
                study_rows, metrics = _split_records(records)
                missing_reason = (
                    f"{len(missing)} DV comparisons lack full statistics"
                    if missing
                    else None
                )
                await repo.upsert_extraction(
                    hit_id=hit.hit_id,
                    owner=owner,
                    scheme=scheme.name,
                    source_id=source_id,
                    study_vars={"records": study_rows},
                    dv_metrics=metrics,
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

def flatten_to_rows(extractions: list) -> list[dict]:
    """One dict per DV metric (study vars merged in, minus nested lists)."""
    rows: list[dict] = []
    for ext in extractions:
        study_rows = (ext.study_vars or {}).get("records", []) if isinstance(ext.study_vars, dict) else []
        metrics = ext.dv_metrics or []
        base = {
            "hit_id": ext.hit_id,
            "scheme": ext.scheme,
            "owner": ext.owner,
        }
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
                if k in ("cell_descriptives",) or isinstance(v, (dict, list)):
                    continue
                row[f"DV_{k}"] = _scalar(v)
            rows.append(row)
        if not metrics and study_rows:
            for study in study_rows:
                if not isinstance(study, dict):
                    continue
                row = dict(base)
                for k, v in study.items():
                    if k == "DV_Metrics" or isinstance(v, (dict, list)):
                        continue
                    row[k] = _scalar(v)
                rows.append(row)
    return rows


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

    from openpyxl import Workbook  # type: ignore[import-untyped]

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

    Flat study-level fields (per ``codebook.study_fields``) become case
    attributes; a case is created per hit when it does not exist yet.
    Returns a summary of created entities.
    """
    from qualcoder_api.persistence.repo.attribute_repo import AttributeRepository
    from qualcoder_api.persistence.repo.case_repo import CaseRepository

    repo = MetaRepository(session)
    ext = await repo.get_extraction_for_hit(hit_id)
    hit = await repo.get_hit(hit_id)
    if ext is None or hit is None:
        return {"caseid": None, "attributes": 0, "error": "no extraction for hit"}

    study_rows = (ext.study_vars or {}).get("records", []) if isinstance(ext.study_vars, dict) else []
    study = study_rows[0] if study_rows and isinstance(study_rows[0], dict) else {}
    case_name = str(study.get("Study_ID") or hit.title or f"Hit {hit_id}")[:120]

    case_repo = CaseRepository(session)
    cases = await case_repo.list_cases()
    case = next((c for c in cases if c.name == case_name), None)
    if case is None:
        case = await case_repo.add_case(name=case_name, memo="", owner=owner)
    if case is None:  # pragma: no cover - raced duplicate
        return {"caseid": None, "attributes": 0, "error": "case create failed"}

    attr_repo = AttributeRepository(session)
    field_defs = {f["name"]: f for f in (codebook.get("study_fields") or [])}
    created = 0
    for field, value in study.items():
        if field in ("Rationale_Notes",) or isinstance(value, (dict, list)):
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
    ext = await repo.get_extraction_for_hit(hit_id)
    hit = await repo.get_hit(hit_id)
    if ext is None or hit is None:
        return {"codes": 0, "error": "no extraction for hit"}

    study_rows = (ext.study_vars or {}).get("records", []) if isinstance(ext.study_vars, dict) else []
    study = study_rows[0] if study_rows and isinstance(study_rows[0], dict) else {}
    rationale = str(study.get("Rationale_Notes") or "")
    category_name = codebook.get("category") or "Meta"
    code_fields = codebook.get("code_fields") or []

    code_repo = CodeRepository(session)
    cats = await code_repo.list_categories()
    cat = next((c for c in cats if c.name == category_name), None)
    if cat is None:
        cat = await code_repo.add_category(name=category_name, owner=owner)

    created = 0
    existing_names = {c.name for c in await code_repo.list_codes()}
    for field in code_fields:
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
