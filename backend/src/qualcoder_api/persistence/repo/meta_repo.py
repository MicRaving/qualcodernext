"""Meta-analysis repositories (``meta_*`` tables).

Local-only in v1: unlike the collaboration-synced repositories, these write
through plain SQL without ``audit_capture`` (no ``sync_log`` rows, no undo
handlers). The tables carry ``owner`` so a later milestone can add capture,
replay and undo additively without a schema change.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import bindparam, delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from qualcoder_api.core.models import (
    MetaCriterion,
    MetaDocument,
    MetaExtraction,
    MetaHit,
    MetaScheme,
    MetaScreening,
)
from qualcoder_api.core.timeutil import now as _now
from qualcoder_api.persistence import tables
from qualcoder_api.persistence.repo.base import _inserted_pk

# Local-only mode: no _capture. Commented out to make the deviation from the
# synced repositories explicit and greppable.
# from qualcoder_api.persistence.repo.base import _capture

#: Pipeline-stage scopes for the study lists (left bar / tab filters).
_SCOPE_STATUSES: dict[str, tuple[str, ...]] = {
    "included": ("included", "downloaded", "extracted"),
    "acquired": ("downloaded", "extracted"),
}


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _json_list(value: Any) -> str:
    """Encode a JSON list column, accepting an already-encoded string."""
    if isinstance(value, str):
        return value
    return _json(value) or "[]"


def _load_json(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _dedupe_fold(text: Any) -> str:
    """Fold text for dedupe: casefold and drop punctuation/whitespace."""
    return "".join(ch for ch in str(text or "").casefold() if ch.isalnum())


def hit_dedupe_key(*, doi: Any, title: Any, authors: Any) -> str | None:
    """Stable dedupe key for a hit, or ``None`` when it cannot be deduped.

    A DOI (normalised) is authoritative. Without one, the normalized
    ``title|authors`` pair is used — but only when BOTH are present, so blank
    or NULL bibliographic rows are never silently collapsed.
    """
    normalized_doi = _dedupe_fold(doi)
    if normalized_doi:
        return f"doi:{normalized_doi}"
    normalized_title = _dedupe_fold(title)
    normalized_authors = _dedupe_fold(authors)
    if normalized_title and normalized_authors:
        return f"ta:{normalized_title}|{normalized_authors}"
    return None


def _hit_field(hit: Any, name: str) -> Any:
    if isinstance(hit, dict):
        return hit.get(name)
    return getattr(hit, name, None)


def count_duplicate_hits(hits: list[Any]) -> int:
    """Number of stored hits that repeat an earlier hit's dedupe key."""
    seen: set[str] = set()
    duplicates = 0
    for hit in hits:
        key = hit_dedupe_key(
            doi=_hit_field(hit, "doi"),
            title=_hit_field(hit, "title"),
            authors=_hit_field(hit, "authors"),
        )
        if key is None:
            continue
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
    return duplicates


class MetaRepository:
    """CRUD for the meta-analysis pipeline (local-only, no sync capture)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── hits ────────────────────────────────────────────────────────────

    async def list_hits(
        self,
        search_run: str | None = None,
        *,
        filter_text: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        scope: str | None = None,
    ) -> list[MetaHit]:
        """Hits, newest-last, optionally filtered + paginated.

        ``scope`` restricts to a pipeline stage: ``all`` (default),
        ``included`` (abstract-included, i.e. screening passed) or
        ``acquired`` (a fulltext was downloaded). ``limit``/``offset`` keep
        the 11k-hit case from loading everything; ``filter_text`` does a
        case-insensitive substring match over the bibliographic columns.
        """
        stmt = select(tables.meta_hit)
        if search_run:
            stmt = stmt.where(tables.meta_hit.c.search_run == search_run)
        if scope in _SCOPE_STATUSES:
            stmt = stmt.where(tables.meta_hit.c.status.in_(_SCOPE_STATUSES[scope]))
        if filter_text:
            like = f"%{filter_text.lower()}%"
            stmt = stmt.where(
                text(
                    "lower(coalesce(title,'') || ' ' || coalesce(authors,'') || ' ' || "
                    "coalesce(doi,'') || ' ' || coalesce(year,'') || ' ' || "
                    "coalesce(abstract,'')) LIKE :q"
                )
            ).params(q=like)
        stmt = stmt.order_by(tables.meta_hit.c.hit_id)
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = await self.session.execute(stmt)
        return [MetaHit.model_validate(r._mapping) for r in rows]

    async def count_hits(
        self,
        search_run: str | None = None,
        *,
        filter_text: str | None = None,
        scope: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(tables.meta_hit)
        if search_run:
            stmt = stmt.where(tables.meta_hit.c.search_run == search_run)
        if scope in _SCOPE_STATUSES:
            stmt = stmt.where(tables.meta_hit.c.status.in_(_SCOPE_STATUSES[scope]))
        if filter_text:
            like = f"%{filter_text.lower()}%"
            stmt = stmt.where(
                text(
                    "lower(coalesce(title,'') || ' ' || coalesce(authors,'') || ' ' || "
                    "coalesce(doi,'') || ' ' || coalesce(year,'') || ' ' || "
                    "coalesce(abstract,'')) LIKE :q"
                )
            ).params(q=like)
        return int((await self.session.execute(stmt)).scalar() or 0)

    async def get_hit(self, hit_id: int) -> MetaHit | None:
        row = (
            await self.session.execute(
                select(tables.meta_hit).where(tables.meta_hit.c.hit_id == hit_id)
            )
        ).first()
        return MetaHit.model_validate(row._mapping) if row else None

    async def add_hit(self, **fields: Any) -> MetaHit:
        now = _now()
        result = await self.session.execute(
            insert(tables.meta_hit).values(created=now, updated=now, **fields)
        )
        await self.session.commit()
        row = await self._hit_row(_inserted_pk(result))
        assert row is not None
        return MetaHit.model_validate(row._mapping)

    async def add_hits(self, hits: list[dict]) -> int:
        """Batch-insert hits, skipping duplicates; returns inserted count.

        ``hits`` is a list of column dicts. A hit is a duplicate when its DOI
        (case-insensitively) matches an existing/batch hit, or — when it has no
        DOI — when its normalized ``title|authors`` pair matches one. Blank
        titles/authors are never deduped, so unstructured imports are not
        silently collapsed. Inserts run as a single executemany so an 11k-study
        import stays fast.
        """
        now = _now()
        existing_keys = {
            key
            for doi, title, authors in (
                await self.session.execute(
                    select(
                        tables.meta_hit.c.doi,
                        tables.meta_hit.c.title,
                        tables.meta_hit.c.authors,
                    )
                )
            ).all()
            if (key := hit_dedupe_key(doi=doi, title=title, authors=authors))
        }
        rows: list[dict] = []
        for fields in hits:
            key = hit_dedupe_key(
                doi=fields.get("doi"),
                title=fields.get("title"),
                authors=fields.get("authors"),
            )
            if key is not None:
                if key in existing_keys:
                    continue
                existing_keys.add(key)
            rows.append({**fields, "created": now, "updated": now})
        if rows:
            await self.session.execute(insert(tables.meta_hit), rows)
            await self.session.commit()
        return len(rows)

    async def _hit_row(self, hit_id: int):
        return (
            await self.session.execute(
                select(tables.meta_hit).where(tables.meta_hit.c.hit_id == hit_id)
            )
        ).first()

    async def update_hit(self, hit_id: int, **fields: Any) -> MetaHit | None:
        if fields:
            fields["updated"] = _now()
            await self.session.execute(
                update(tables.meta_hit)
                .where(tables.meta_hit.c.hit_id == hit_id)
                .values(**fields)
            )
            await self.session.commit()
        return await self.get_hit(hit_id)

    async def delete_hit(self, hit_id: int) -> bool:
        """Delete a hit and its meta rows, unlinking any acquired source.

        The imported source (if the paper was downloaded/assigned) is removed
        in the same transaction so deleting a hit does not leave an orphaned
        file sitting in the Sources list.
        """
        row = (
            await self.session.execute(
                select(tables.meta_hit.c.hit_id).where(tables.meta_hit.c.hit_id == hit_id)
            )
        ).first()
        if row is None:
            return False
        doc = (
            await self.session.execute(
                select(tables.meta_document.c.source_id).where(
                    tables.meta_document.c.hit_id == hit_id
                )
            )
        ).first()
        source_id = int(doc[0]) if doc is not None and doc[0] is not None else None
        for table in (tables.meta_screening, tables.meta_document, tables.meta_extraction):
            await self.session.execute(
                delete(table).where(table.c.hit_id == hit_id)
            )
        await self.session.execute(
            delete(tables.meta_hit).where(tables.meta_hit.c.hit_id == hit_id)
        )
        if source_id is not None:
            # ``_delete_source_row`` is the non-committing half of
            # ``SourceRepository.delete_source`` (it cascades codings,
            # annotations and case links and journals the sync deletes); we
            # commit once for the whole operation.
            from qualcoder_api.persistence.repo.source_repo import SourceRepository

            await SourceRepository(self.session)._delete_source_row(source_id)
        await self.session.commit()
        return True

    async def set_hit_status(self, hit_id: int, status: str) -> None:
        await self.session.execute(
            update(tables.meta_hit)
            .where(tables.meta_hit.c.hit_id == hit_id)
            .values(status=status, updated=_now())
        )
        await self.session.commit()

    async def search_runs(self) -> list[str]:
        rows = await self.session.execute(
            text("SELECT DISTINCT search_run FROM meta_hit WHERE search_run IS NOT NULL AND search_run != '' ORDER BY search_run")
        )
        return [str(r[0]) for r in rows]

    async def latest_screening_by_hit(self) -> dict[int, MetaScreening]:
        """Latest screening row per hit (any coder), keyed by hit_id."""
        rows = await self.session.execute(
            text(
                "SELECT * FROM meta_screening WHERE id IN "
                "(SELECT MAX(id) FROM meta_screening GROUP BY hit_id)"
            )
        )
        out: dict[int, MetaScreening] = {}
        for r in rows:
            mapping = r._mapping
            model = MetaScreening.model_validate(mapping).model_copy(
                update={"verdicts": _load_json(mapping.get("verdicts"), {}) or {}}
            )
            out[model.hit_id] = model
        return out

    async def latest_verdicts_for(
        self, hit_ids: list[int], stage: str | None = None
    ) -> dict[int, dict]:
        """Latest verdicts per hit for a page of hit ids (avoids loading all
        screening rows just to compute eligibility).

        ``stage`` restricts the "latest" window to one screening stage (e.g.
        ``"abstract"``), so full-text verdicts never leak into the abstract
        pipeline lists; ``None`` keeps the legacy any-stage window."""
        if not hit_ids:
            return {}
        if stage:
            stmt = text(
                "SELECT hit_id, verdicts FROM meta_screening "
                "WHERE id IN (SELECT MAX(id) FROM meta_screening "
                "WHERE stage = :stage GROUP BY hit_id) "
                "AND hit_id IN :ids"
            ).bindparams(bindparam("ids", expanding=True))
            rows = await self.session.execute(stmt, {"ids": hit_ids, "stage": stage})
        else:
            stmt = text(
                "SELECT hit_id, verdicts FROM meta_screening "
                "WHERE id IN (SELECT MAX(id) FROM meta_screening GROUP BY hit_id) "
                "AND hit_id IN :ids"
            ).bindparams(bindparam("ids", expanding=True))
            rows = await self.session.execute(stmt, {"ids": hit_ids})
        return {int(r[0]): (_load_json(r[1], {}) or {}) for r in rows}

    async def tab_counts(
        self, is_included: Any = None, stage: str | None = None
    ) -> dict[str, int]:
        """Study counts per pipeline tab: all / included / acquired.

        ``is_included`` is an optional ``verdicts -> bool`` predicate so the
        caller keeps the single ``evaluate_criteria`` inclusion rule (the repo
        stays free of matching semantics). ``stage`` restricts the verdict
        window to one screening stage (see :meth:`latest_verdicts_for`).
        """
        total = int(
            (await self.session.execute(select(func.count()).select_from(tables.meta_hit))).scalar()
            or 0
        )
        included = 0
        acquired = int(
            (
                await self.session.execute(
                    select(func.count())
                    .select_from(tables.meta_document)
                    .where(tables.meta_document.c.status == "done")
                )
            ).scalar()
            or 0
        )
        verdict_rows = await self.session.execute(
            text(
                "SELECT verdicts FROM meta_screening WHERE id IN "
                "(SELECT MAX(id) FROM meta_screening "
                + ("WHERE stage = :stage " if stage else "")
                + "GROUP BY hit_id)"
            ),
            {"stage": stage} if stage else {},
        )
        for (raw,) in verdict_rows:
            verdicts = _load_json(raw, {}) or {}
            if not verdicts:
                continue
            if is_included is not None:
                if is_included(verdicts):
                    included += 1
            elif all(
                str(v.get("applies") or "").strip().lower() == "yes" for v in verdicts.values()
            ):
                included += 1
        return {"screening": total, "downloads": included, "extraction": acquired}

    async def count_screening(self) -> int:
        return int(
            (await self.session.execute(select(func.count()).select_from(tables.meta_screening))).scalar()
            or 0
        )

    async def count_extractions(self, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(tables.meta_extraction)
        if status:
            stmt = stmt.where(tables.meta_extraction.c.status == status)
        return int((await self.session.execute(stmt)).scalar() or 0)

    async def status_counts(self) -> dict[str, int]:
        rows = await self.session.execute(
            text("SELECT status, COUNT(*) FROM meta_hit GROUP BY status")
        )
        return {str(s or "imported"): int(n) for s, n in rows}

    # ── criteria ────────────────────────────────────────────────────────

    async def list_criteria(self) -> list[MetaCriterion]:
        rows = await self.session.execute(
            text("SELECT * FROM meta_criterion ORDER BY position, id")
        )
        return [MetaCriterion.model_validate(r._mapping) for r in rows]

    async def get_criterion(self, criterion_id: int) -> MetaCriterion | None:
        row = (
            await self.session.execute(
                select(tables.meta_criterion).where(tables.meta_criterion.c.id == criterion_id)
            )
        ).first()
        return MetaCriterion.model_validate(row._mapping) if row else None

    async def add_criterion(
        self,
        *,
        position: int,
        key: str,
        label: str,
        prompt_text: str,
        kind: str = "verdict",
        options: Any = None,
        pass_values: Any = None,
        exclude_reason: str = "",
        gating: int = 1,
        help: str = "",
    ) -> MetaCriterion:
        result = await self.session.execute(
            insert(tables.meta_criterion).values(
                position=position,
                key=key,
                label=label,
                prompt_text=prompt_text,
                kind=kind,
                options=_json_list(options) if options is not None else "[]",
                pass_values=_json_list(pass_values)
                if pass_values is not None
                else _json(["yes"]),
                exclude_reason=exclude_reason,
                gating=int(gating),
                help=help,
                created=_now(),
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.meta_criterion).where(tables.meta_criterion.c.id == _inserted_pk(result))
            )
        ).first()
        assert row is not None
        return MetaCriterion.model_validate(row._mapping)

    async def update_criterion(self, criterion_id: int, **fields: Any) -> MetaCriterion | None:
        allowed = {
            "position",
            "key",
            "label",
            "prompt_text",
            "kind",
            "options",
            "pass_values",
            "exclude_reason",
            "gating",
            "help",
        }
        values = {k: v for k, v in fields.items() if k in allowed}
        for json_field in ("options", "pass_values"):
            if json_field in values and not isinstance(values[json_field], str):
                values[json_field] = _json(values[json_field])
        if values:
            await self.session.execute(
                update(tables.meta_criterion)
                .where(tables.meta_criterion.c.id == criterion_id)
                .values(**values)
            )
            await self.session.commit()
        return await self.get_criterion(criterion_id)

    async def replace_criteria(self, criteria: list[dict]) -> list[MetaCriterion]:
        """Atomic replace of the criterion list (used by import / seed).

        The delete and every insert share a single transaction: if any row is
        malformed the whole replace rolls back and the previous criteria
        survive, instead of the old delete-then-insert-per-row leaving the
        project with no criteria.
        """
        now = _now()
        rows = [
            {
                "position": int(c.get("position", i)),
                "key": str(c["key"]),
                "label": str(c["label"]),
                "prompt_text": str(c["prompt_text"]),
                "kind": str(c.get("kind") or "verdict"),
                "options": _json_list(c.get("options"))
                if c.get("options") is not None
                else "[]",
                "pass_values": _json_list(c.get("pass_values"))
                if c.get("pass_values") is not None
                else _json(["yes"]),
                "exclude_reason": str(c.get("exclude_reason") or ""),
                "gating": int(c.get("gating", 1)),
                "help": str(c.get("help") or ""),
                "created": now,
            }
            for i, c in enumerate(criteria)
        ]
        await self.session.execute(delete(tables.meta_criterion))
        if rows:
            await self.session.execute(insert(tables.meta_criterion), rows)
        await self.session.commit()
        return await self.list_criteria()

    async def delete_criterion(self, criterion_id: int) -> bool:
        row = (
            await self.session.execute(
                select(tables.meta_criterion.c.id).where(tables.meta_criterion.c.id == criterion_id)
            )
        ).first()
        if row is None:
            return False
        await self.session.execute(
            delete(tables.meta_criterion).where(tables.meta_criterion.c.id == criterion_id)
        )
        await self.session.commit()
        return True

    # ── screening ───────────────────────────────────────────────────────

    async def list_screening(
        self,
        hit_id: int | None = None,
        owner: str | None = None,
        run_id: str | None = None,
        stage: str | None = None,
    ) -> list[MetaScreening]:
        query = "SELECT * FROM meta_screening WHERE 1=1"
        params: dict[str, Any] = {}
        if hit_id is not None:
            query += " AND hit_id = :hit"
            params["hit"] = hit_id
        if owner:
            query += " AND owner = :owner"
            params["owner"] = owner
        if run_id is not None:
            query += " AND run_id = :run"
            params["run"] = run_id
        if stage:
            query += " AND stage = :stage"
            params["stage"] = stage
        query += " ORDER BY hit_id, owner, run_id"
        rows = await self.session.execute(text(query), params)
        out = []
        for r in rows:
            model = MetaScreening.model_validate(r._mapping)
            model = model.model_copy(
                update={"verdicts": _load_json(r._mapping.get("verdicts"), {}) or {}}
            )
            out.append(model)
        return out

    async def get_screening(self, screening_id: int) -> MetaScreening | None:
        row = (
            await self.session.execute(
                select(tables.meta_screening).where(tables.meta_screening.c.id == screening_id)
            )
        ).first()
        if row is None:
            return None
        model = MetaScreening.model_validate(row._mapping)
        return model.model_copy(
            update={"verdicts": _load_json(row._mapping.get("verdicts"), {}) or {}}
        )

    async def upsert_screening(
        self,
        *,
        hit_id: int,
        owner: str,
        run_id: str,
        verdicts: dict | None = None,
        intervention_type: str | None = None,
        rationale: str | None = None,
        origin: str = "manual",
        model: str | None = None,
        prompt_hash: str | None = None,
        stage: str = "abstract",
        reason: str = "",
    ) -> MetaScreening:
        """Insert or replace the (hit, owner, run, stage) verdict row.

        ``stage`` is part of the identity so a full-text verdict never
        overwrites the abstract verdict of the same hit/run.
        """
        existing = (
            await self.session.execute(
                select(tables.meta_screening).where(
                    tables.meta_screening.c.hit_id == hit_id,
                    tables.meta_screening.c.owner == owner,
                    tables.meta_screening.c.run_id == run_id,
                    tables.meta_screening.c.stage == stage,
                )
            )
        ).first()
        now = _now()
        if existing is None:
            result = await self.session.execute(
                insert(tables.meta_screening).values(
                    hit_id=hit_id,
                    owner=owner,
                    run_id=run_id,
                    verdicts=_json(verdicts),
                    intervention_type=intervention_type,
                    rationale=rationale,
                    origin=origin,
                    model=model,
                    prompt_hash=prompt_hash,
                    stage=stage,
                    reason=reason,
                    created=now,
                    updated=now,
                )
            )
            await self.session.commit()
            row = (
                await self.session.execute(
                    select(tables.meta_screening).where(tables.meta_screening.c.id == _inserted_pk(result))
                )
            ).first()
            assert row is not None
            return MetaScreening.model_validate(row._mapping).model_copy(
                update={"verdicts": _load_json(row._mapping.get("verdicts"), {}) or {}}
            )
        await self.session.execute(
            update(tables.meta_screening)
            .where(tables.meta_screening.c.id == existing.id)
            .values(
                verdicts=_json(verdicts) if verdicts is not None else existing.verdicts,
                intervention_type=intervention_type,
                rationale=rationale,
                origin=origin,
                model=model,
                prompt_hash=prompt_hash,
                stage=stage,
                reason=reason,
                updated=now,
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.meta_screening).where(tables.meta_screening.c.id == existing.id)
            )
        ).first()
        assert row is not None
        return MetaScreening.model_validate(row._mapping).model_copy(
            update={"verdicts": _load_json(row._mapping.get("verdicts"), {}) or {}}
        )

    async def screening_for_hit(
        self,
        hit_id: int,
        owner: str,
        run_id: str = "",
        stage: str | None = None,
    ) -> MetaScreening | None:
        stmt = select(tables.meta_screening).where(
            tables.meta_screening.c.hit_id == hit_id,
            tables.meta_screening.c.owner == owner,
            tables.meta_screening.c.run_id == run_id,
        )
        if stage:
            stmt = stmt.where(tables.meta_screening.c.stage == stage)
        row = (await self.session.execute(stmt.order_by(tables.meta_screening.c.id.desc()))).first()
        if row is None:
            return None
        model = MetaScreening.model_validate(row._mapping)
        return model.model_copy(
            update={"verdicts": _load_json(row._mapping.get("verdicts"), {}) or {}}
        )

    async def set_screening_origin(self, screening_id: int, origin: str) -> None:
        await self.session.execute(
            update(tables.meta_screening)
            .where(tables.meta_screening.c.id == screening_id)
            .values(origin=origin, updated=_now())
        )
        await self.session.commit()

    # ── documents ───────────────────────────────────────────────────────

    async def list_documents(self, hit_id: int | None = None) -> list[MetaDocument]:
        query = "SELECT * FROM meta_document"
        params: dict[str, Any] = {}
        if hit_id is not None:
            query += " WHERE hit_id = :hit"
            params["hit"] = hit_id
        query += " ORDER BY hit_id"
        rows = await self.session.execute(text(query), params)
        return [MetaDocument.model_validate(r._mapping) for r in rows]

    async def get_document_for_hit(self, hit_id: int) -> MetaDocument | None:
        row = (
            await self.session.execute(
                select(tables.meta_document).where(tables.meta_document.c.hit_id == hit_id)
            )
        ).first()
        return MetaDocument.model_validate(row._mapping) if row else None

    async def upsert_document(
        self,
        *,
        hit_id: int,
        source_id: int | None = None,
        retrieval_method: str | None = None,
        url: str | None = None,
        status: str = "pending",
        message: str | None = None,
    ) -> MetaDocument:
        now = _now()
        existing = (
            await self.session.execute(
                select(tables.meta_document).where(tables.meta_document.c.hit_id == hit_id)
            )
        ).first()
        if existing is None:
            await self.session.execute(
                insert(tables.meta_document).values(
                    hit_id=hit_id,
                    source_id=source_id,
                    retrieval_method=retrieval_method,
                    url=url,
                    status=status,
                    message=message,
                    created=now,
                    updated=now,
                )
            )
            await self.session.commit()
            return await self.get_document_for_hit(hit_id) or MetaDocument(hit_id=hit_id)
        await self.session.execute(
            update(tables.meta_document)
            .where(tables.meta_document.c.id == existing.id)
            .values(
                source_id=source_id if source_id is not None else existing.source_id,
                retrieval_method=retrieval_method
                if retrieval_method is not None
                else existing.retrieval_method,
                url=url if url is not None else existing.url,
                status=status,
                message=message if message is not None else existing.message,
                updated=now,
            )
        )
        await self.session.commit()
        return await self.get_document_for_hit(hit_id) or MetaDocument(hit_id=hit_id)

    async def patch_document_status(self, hit_id: int, status: str, message: str | None = None) -> None:
        values: dict[str, Any] = {"status": status, "updated": _now()}
        if message is not None:
            values["message"] = message
        await self.session.execute(
            update(tables.meta_document)
            .where(tables.meta_document.c.hit_id == hit_id)
            .values(**values)
        )
        await self.session.commit()

    # ── extractions ─────────────────────────────────────────────────────

    async def list_extractions(
        self,
        hit_id: int | None = None,
        owner: str | None = None,
        scheme: str | None = None,
    ) -> list[MetaExtraction]:
        query = "SELECT * FROM meta_extraction WHERE 1=1"
        params: dict[str, Any] = {}
        if hit_id is not None:
            query += " AND hit_id = :hit"
            params["hit"] = hit_id
        if owner:
            query += " AND owner = :owner"
            params["owner"] = owner
        if scheme:
            query += " AND scheme = :scheme"
            params["scheme"] = scheme
        query += " ORDER BY hit_id, owner, scheme"
        rows = await self.session.execute(text(query), params)
        out = []
        for r in rows:
            mapping = r._mapping
            out.append(
                MetaExtraction.model_validate(mapping).model_copy(
                    update={
                        "study_vars": _load_json(mapping.get("study_vars"), {}) or {},
                        "dv_metrics": _load_json(mapping.get("dv_metrics"), []) or [],
                        "prescreen": _load_json(mapping.get("prescreen"), None),
                    }
                )
            )
        return out

    async def get_extraction_for_hit(
        self, hit_id: int, owner: str | None = None, scheme: str | None = None
    ) -> MetaExtraction | None:
        """One extraction for a hit.

        ``owner``/``scheme`` narrow the lookup; without them the most recently
        written row wins. A coder may hold one extraction per scheme, so
        callers that know the scheme should pass it to avoid ambiguity.
        """
        stmt = select(tables.meta_extraction).where(tables.meta_extraction.c.hit_id == hit_id)
        if owner:
            stmt = stmt.where(tables.meta_extraction.c.owner == owner)
        if scheme:
            stmt = stmt.where(tables.meta_extraction.c.scheme == scheme)
        stmt = stmt.order_by(tables.meta_extraction.c.id.desc())
        row = (await self.session.execute(stmt)).first()
        if row is None:
            return None
        mapping = row._mapping
        return MetaExtraction.model_validate(mapping).model_copy(
            update={
                "study_vars": _load_json(mapping.get("study_vars"), {}) or {},
                "dv_metrics": _load_json(mapping.get("dv_metrics"), []) or [],
                "prescreen": _load_json(mapping.get("prescreen"), None),
            }
        )

    async def upsert_extraction(
        self,
        *,
        hit_id: int,
        owner: str,
        scheme: str,
        source_id: int | None = None,
        study_vars: dict | None = None,
        dv_metrics: list | None = None,
        prescreen: dict | None = None,
        model: str | None = None,
        prompt_hash: str | None = None,
        status: str = "prescreen_pending",
        missing_reason: str | None = None,
    ) -> MetaExtraction:
        now = _now()
        existing = (
            await self.session.execute(
                select(tables.meta_extraction).where(
                    tables.meta_extraction.c.hit_id == hit_id,
                    tables.meta_extraction.c.owner == owner,
                    tables.meta_extraction.c.scheme == scheme,
                )
            )
        ).first()
        if existing is None:
            await self.session.execute(
                insert(tables.meta_extraction).values(
                    hit_id=hit_id,
                    source_id=source_id,
                    owner=owner,
                    scheme=scheme,
                    study_vars=_json(study_vars),
                    dv_metrics=_json(dv_metrics),
                    prescreen=_json(prescreen),
                    model=model,
                    prompt_hash=prompt_hash,
                    status=status,
                    missing_reason=missing_reason,
                    created=now,
                    updated=now,
                )
            )
            await self.session.commit()
            return await self.get_extraction_for_hit(hit_id, owner, scheme) or MetaExtraction(
                hit_id=hit_id, owner=owner, scheme=scheme
            )
        await self.session.execute(
            update(tables.meta_extraction)
            .where(tables.meta_extraction.c.id == existing.id)
            .values(
                source_id=source_id if source_id is not None else existing.source_id,
                owner=owner,
                scheme=scheme,
                study_vars=_json(study_vars) if study_vars is not None else existing.study_vars,
                dv_metrics=_json(dv_metrics) if dv_metrics is not None else existing.dv_metrics,
                prescreen=_json(prescreen) if prescreen is not None else existing.prescreen,
                model=model if model is not None else existing.model,
                prompt_hash=prompt_hash if prompt_hash is not None else existing.prompt_hash,
                status=status,
                missing_reason=missing_reason,
                updated=now,
            )
        )
        await self.session.commit()
        return await self.get_extraction_for_hit(hit_id, owner, scheme) or MetaExtraction(
            hit_id=hit_id, owner=owner, scheme=scheme
        )

    # ── schemes ─────────────────────────────────────────────────────────

    async def list_schemes(self) -> list[MetaScheme]:
        rows = await self.session.execute(text("SELECT * FROM meta_scheme ORDER BY name"))
        return [MetaScheme.model_validate(r._mapping) for r in rows]

    async def get_scheme(self, scheme_id: int | None = None, name: str | None = None) -> MetaScheme | None:
        if scheme_id is not None:
            row = (
                await self.session.execute(
                    select(tables.meta_scheme).where(tables.meta_scheme.c.id == scheme_id)
                )
            ).first()
        elif name:
            row = (
                await self.session.execute(
                    select(tables.meta_scheme).where(tables.meta_scheme.c.name == name)
                )
            ).first()
        else:
            return None
        return MetaScheme.model_validate(row._mapping) if row else None

    async def add_scheme(
        self,
        *,
        name: str,
        label: str | None = None,
        description: str | None = None,
        prescreen_prompt: str | None = None,
        coding_prompt: str | None = None,
        codebook: str | None = None,
    ) -> MetaScheme:
        now = _now()
        result = await self.session.execute(
            insert(tables.meta_scheme).values(
                name=name,
                label=label,
                description=description,
                prescreen_prompt=prescreen_prompt,
                coding_prompt=coding_prompt,
                codebook=codebook,
                created=now,
                updated=now,
            )
        )
        await self.session.commit()
        row = (
            await self.session.execute(
                select(tables.meta_scheme).where(tables.meta_scheme.c.id == _inserted_pk(result))
            )
        ).first()
        assert row is not None
        return MetaScheme.model_validate(row._mapping)

    async def update_scheme(self, scheme_id: int, **fields: Any) -> MetaScheme | None:
        allowed = {"name", "label", "description", "prescreen_prompt", "coding_prompt", "codebook"}
        values = {k: v for k, v in fields.items() if k in allowed}
        if values:
            values["updated"] = _now()
            await self.session.execute(
                update(tables.meta_scheme)
                .where(tables.meta_scheme.c.id == scheme_id)
                .values(**values)
            )
            await self.session.commit()
        return await self.get_scheme(scheme_id=scheme_id)

    async def count_extractions_for_scheme(self, name: str) -> int:
        """Extractions still referencing a scheme by name (blocks deletion)."""
        return int(
            (
                await self.session.execute(
                    select(func.count())
                    .select_from(tables.meta_extraction)
                    .where(tables.meta_extraction.c.scheme == name)
                )
            ).scalar()
            or 0
        )

    async def delete_scheme(self, scheme_id: int) -> bool:
        row = (
            await self.session.execute(
                select(tables.meta_scheme.c.id).where(tables.meta_scheme.c.id == scheme_id)
            )
        ).first()
        if row is None:
            return False
        await self.session.execute(
            delete(tables.meta_scheme).where(tables.meta_scheme.c.id == scheme_id)
        )
        await self.session.commit()
        return True
