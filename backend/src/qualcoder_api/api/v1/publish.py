"""Publish API — Smart Publisher: render report datasets into Office files.

``POST /publish/from-report`` re-runs the ``report_service`` query behind the
requested report and renders it as .docx / .pptx / .xlsx bytes with a
``Content-Disposition`` attachment header. The report names mirror the
``/reports`` endpoints; PowerPoint is only supported where a per-code slide
layout makes sense (code-segments, code-frequencies).
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import text

from qualcoder_api.api.v1.deps import DbDep
from qualcoder_api.services import publish_service, report_service

router = APIRouter(prefix="/publish", tags=["publish"])

REPORT_TITLES = {
    "code-frequencies": "Code frequencies",
    "code-segments": "Codes by segments",
    "coder-comparison": "Coder comparison",
    "codebook": "Codebook",
    "summary-table": "Summary table",
}

FORMAT_MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

PPTX_REPORTS = frozenset({"code-segments", "code-frequencies"})


class PublishRequest(BaseModel):
    report: str
    format: str
    options: dict[str, Any] | None = None


def _project_name() -> str:
    from qualcoder_api.main import service

    return service.project_name or ""


def _clip(text: str, limit: int = 300) -> str:
    """Flatten whitespace and cap a segment quote for slide bullets."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else f"{flat[:limit]}…"


def _intro(report: str, extra: str = "") -> str:
    parts = [f"Generated {date.today().isoformat()} — {_project_name() or REPORT_TITLES[report]}."]
    if extra:
        parts.append(extra)
    return " ".join(parts)


async def _collect(
    report: str, db: DbDep, options: dict[str, Any]
) -> dict[str, Any]:
    """Fetch the report data and map it to docx sections / xlsx sheets /
    pptx slides (all three shapes, so the caller picks by format)."""
    intro = _intro(report)

    if report == "code-frequencies":
        rows = await report_service.code_frequencies(db)
        headers = ["Code", "Category", "Segments"]
        table = [[r["name"], r["category"], r["count"]] for r in rows]
        top_n = options.get("top_n", 20)
        try:
            top_n = int(top_n) if top_n is not None else 20
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422, detail="options.top_n must be an integer"
            ) from None
        top_n = max(1, min(top_n, 200))
        slides = [
            {
                "title": r["name"],
                "bullets": [f"Category: {r['category'] or '—'}", f"Segments: {r['count']}"],
            }
            for r in rows[:top_n]
        ]
        return {
            "title": REPORT_TITLES[report],
            "sections": [
                {"paragraph": f"{intro} {len(rows)} codes."},
                {"heading": "Coding counts", "table": [headers, *table]},
            ],
            "sheets": [{"name": "Code frequencies", "headers": headers, "rows": table}],
            "slides": slides,
        }

    if report == "code-segments":
        rows = await report_service.codes_by_segments(db)
        by_code: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_code.setdefault(row["code_name"], []).append(row)
        sections: list[dict[str, Any]] = [{"paragraph": f"{intro} {len(rows)} segments."}]
        for name, items in by_code.items():
            sections.append({"heading": name})
            sections.extend(
                {"quote": f"[{item['file_name']}] {item['seltext']}"} for item in items
            )
        headers = ["Code", "Category", "File", "Segment", "Owner", "Date"]
        table = [
            [
                r["code_name"], r["category"], r["file_name"], r["seltext"],
                r["owner"], r["date"],
            ]
            for r in rows
        ]
        code_memo_rows = (
            await db.execute(
                text("SELECT COALESCE(name, ''), COALESCE(memo, '') FROM code_name")
            )
        ).all()
        code_memos: dict[str, str] = {row[0]: row[1] for row in code_memo_rows}
        slides = [
            {
                "title": name,
                "bullets": [f"{item['file_name']} — {_clip(item['seltext'])}" for item in items],
                "memo": code_memos.get(name, ""),
            }
            for name, items in by_code.items()
        ]
        return {
            "title": REPORT_TITLES[report],
            "sections": sections,
            "sheets": [{"name": "Code segments", "headers": headers, "rows": table}],
            "slides": slides,
        }

    if report == "coder-comparison":
        rows = await report_service.coder_comparison(db)
        headers = ["Coder", "Codings", "Files"]
        table = [[r["owner"], r["codings_count"], r["files_count"]] for r in rows]
        return {
            "title": REPORT_TITLES[report],
            "sections": [
                {"paragraph": f"{intro} {len(rows)} coders."},
                {"heading": "Coding volume per coder", "table": [headers, *table]},
            ],
            "sheets": [{"name": "Coder comparison", "headers": headers, "rows": table}],
            "slides": [],
        }

    if report == "codebook":
        book_text = await report_service.codebook_plain(db, include_memos=True)
        lines = book_text.splitlines()
        sections = [{"paragraph": f"{intro} {len(lines)} entries."}]
        sections.append({"heading": "Codebook"})
        sections.extend({"paragraph": line} for line in lines)
        sheets = [
            {
                "name": "Codebook",
                "headers": ["Code path", "Memo"],
                "rows": [line.partition("\t")[::2] for line in lines],
            }
        ]
        return {
            "title": REPORT_TITLES[report],
            "sections": sections,
            "sheets": sheets,
            "slides": [],
        }

    # summary-table
    scope = options.get("scope") or "file"
    if scope not in ("file", "case"):
        raise HTTPException(status_code=422, detail="options.scope must be 'file' or 'case'")
    data = await report_service.summary_table(db, scope)
    headers = ["Document" if scope == "file" else "Case", *(c["name"] for c in data["codes"])]
    table = [[r["name"], *(cell["memo"] for cell in r["cells"])] for r in data["rows"]]
    return {
        "title": REPORT_TITLES[report],
        "sections": [
            {"paragraph": f"{intro} {len(data['rows'])} units."},
            {"heading": "Summary table", "table": [headers, *table]},
        ],
        "sheets": [{"name": "Summary table", "headers": headers, "rows": table}],
        "slides": [],
    }


@router.post("/from-report")
async def publish_from_report(db: DbDep, req: PublishRequest) -> Response:
    report = req.report
    fmt = req.format
    if report not in REPORT_TITLES:
        raise HTTPException(status_code=422, detail=f"unknown report: {report}")
    if fmt not in FORMAT_MEDIA:
        raise HTTPException(status_code=422, detail=f"unknown format: {fmt}")
    if fmt == "pptx" and report not in PPTX_REPORTS:
        raise HTTPException(
            status_code=422,
            detail=f"PowerPoint is only supported for code-segments and code-frequencies, not '{report}'",
        )
    data = await _collect(report, db, req.options or {})
    if fmt == "docx":
        payload = await asyncio.to_thread(publish_service.build_docx, data["title"], data["sections"])
    elif fmt == "pptx":
        payload = await asyncio.to_thread(publish_service.build_pptx, data["title"], data["slides"])
    else:
        payload = await asyncio.to_thread(publish_service.build_xlsx, data["sheets"])
    return Response(
        content=payload,
        media_type=FORMAT_MEDIA[fmt],
        headers={"Content-Disposition": f'attachment; filename="{report}.{fmt}"'},
    )
