"""Coder management — create / switch / delete coders (user identities)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from qualcoder_api.api.v1.deps import ServiceDep
from qualcoder_api.services.user_settings import (
    get_codername,
    get_coders,
    set_codername,
    set_coders,
)

router = APIRouter(prefix="/coders", tags=["coders"])

# Must mirror tables.OWNER_TABLES so coder stats/delete/reassign cover every
# owner column (source, code_name, code_cat, attribute, … included).
OWNER_TABLES = (
    ("code_text", "owner"),
    ("code_image", "owner"),
    ("code_av", "owner"),
    ("case_text", "owner"),
    ("annotation", "owner"),
    ("cases", "owner"),
    ("attribute_type", "owner"),
    ("journal", "owner"),
    ("source", "owner"),
    ("code_name", "owner"),
    ("code_cat", "owner"),
    ("attribute", "owner"),
    ("manage_files_display", "owner"),
    ("files_filter", "owner"),
    ("link", "owner"),
    ("creative_item", "owner"),
    ("qtt_sheet", "owner"),
    ("qtt_item", "owner"),
    ("comment", "owner"),
    ("code_set", "owner"),
    ("dictionary", "owner"),
    ("r_script", "owner"),
)


async def _capture_owner_reassign(session, old: str, new: str) -> None:
    """Move every ``owner`` reference from *old* to *new* AND journal each
    touched row into ``sync_log`` so collaborators converge.

    A bare bulk ``UPDATE owner`` without capture left peers with stale owners:
    their coder roster (registry + live owners) kept showing the old name, so
    two instances displayed different coder counts for the same project, and a
    later reopen resurrected deleted coders from the stale owner rows.
    """
    from qualcoder_api.services.sync_schema import ENTITY_PKS

    for table, column in OWNER_TABLES:
        try:
            rows = (
                await session.execute(
                    text(f'SELECT * FROM "{table}" WHERE "{column}" = :from'),
                    {"from": old},
                )
            ).mappings().all()
        except Exception:
            continue
        if not rows:
            continue
        await session.execute(
            text(f'UPDATE "{table}" SET "{column}" = :to WHERE "{column}" = :from'),
            {"to": new, "from": old},
        )
        pk_name = ENTITY_PKS.get(table, "")
        if not pk_name or "," in pk_name:
            continue
        try:
            from qualcoder_api.services import sync as _sync_mod
        except Exception:
            continue
        for r in rows:
            data = {k: v for k, v in dict(r).items() if not k.startswith("_")}
            data[column] = new
            pk_value = data.get(pk_name)
            if pk_value is None:
                continue
            try:
                await _sync_mod.capture(
                    session, entity=table, action="update",
                    pk_name=pk_name, pk_value=pk_value, row=data,
                )
            except Exception:
                continue


# Coding-segment tables (text/image/AV codings). The coder flyout shows these
# as "coded segments" — NOT the raw owner-row total across every OWNER_TABLES
# (which would also count sources, codes, cases, attributes, ... and inflate
# the number far beyond the real coding count).
CODING_TABLES = ("code_text", "code_image", "code_av")


class CoderInfo(BaseModel):
    name: str
    coding_count: int = 0


class CodersResponse(BaseModel):
    current: str
    coders: list[CoderInfo] = Field(default_factory=list)


class CoderRequest(BaseModel):
    name: str


class CurrentCoderRequest(BaseModel):
    name: str


class DeleteCoderRequest(BaseModel):
    reassign_to: str | None = None


class RenameCoderRequest(BaseModel):
    new_name: str


class VisibilityRequest(BaseModel):
    visible: bool


async def _coding_counts(svc) -> dict[str, int]:
    """Count records per owner in the open project (empty when none open)."""
    if svc.engine is None:
        return {}
    _, factory = svc._ensure_engine()
    result: dict[str, int] = {}
    async with factory() as session:
        for table, column in OWNER_TABLES:
            # Double quotes: "case" is a SQL keyword.
            rows = await session.execute(
                text(f'SELECT "{column}", count(*) FROM "{table}" GROUP BY "{column}"')
            )
            for owner, count in rows:
                if owner:
                    result[owner] = result.get(owner, 0) + int(count)
    return result


async def _record_audit(svc, action: str, detail: dict) -> None:
    """Audit a coder mutation against the open project (best effort)."""
    from qualcoder_api.services import audit

    if svc.engine is None:
        return
    _, factory = svc._ensure_engine()
    async with factory() as session:
        await audit.record(
            session, user=get_codername(), action=action, entity="coder", detail=detail
        )


async def _all_coders(svc, counts: dict[str, int]) -> list[str]:
    """The coder list: per-machine coders (settings) merged with the project's
    ``coder_names`` registry and every owner found in the open project.
    Projects keep their own coder set (upstream ``coder_names``), so analysis
    and the coder switcher must show the project's coders even when they were
    never created on this machine — and a coder created on ANOTHER machine must
    appear here once its ``coder_names`` row has been synced in."""
    names = list(get_coders())
    if svc.engine is not None:
        try:
            _, factory = svc._ensure_engine()
            async with factory() as session:
                rows = await session.execute(
                    text("SELECT name FROM coder_names WHERE name != :sys ORDER BY name"),
                    {"sys": "system"},
                )
                for (name,) in rows:
                    if name not in names:
                        names.append(name)
        except Exception:  # pragma: no cover - pre-registry projects
            pass
    for owner in sorted(counts):
        if owner not in names:
            names.append(owner)
    return names


async def _ensure_project_coder(svc, name: str) -> None:
    """Register a coder in the open project's ``coder_names`` registry.

    Coders live per-machine in settings; the PROJECT keeps its own set in
    ``coder_names`` (delete/rename maintain it). Creation must register too —
    the collaboration gate counts exactly this table ("a second coder is
    required"), and with only settings-side coders that gate could never
    pass on a fresh project.
    """
    if svc.engine is None:
        return
    try:
        _, factory = svc._ensure_engine()
        async with factory() as session:
            await session.execute(
                text("INSERT OR IGNORE INTO coder_names(name, visibility) VALUES(:n, 1)"),
                {"n": name},
            )
            row = (
                await session.execute(
                    text("SELECT name, visibility FROM coder_names WHERE name = :n"),
                    {"n": name},
                )
            ).first()
            if row is not None:
                await _capture_coder(
                    session, "insert", row[0], {"name": row[0], "visibility": row[1]}
                )
            await session.commit()
    except Exception as err:  # pragma: no cover - pre-registry projects
        logging.getLogger(__name__).warning("coder_names registration failed: %s", err)


async def _segment_counts(svc) -> dict[str, int]:
    """Coding-segment counts per owner (text + image + AV codings).

    Used for the per-coder "coded segments" indicator in the coder flyout.
    ``_coding_counts`` (all owner tables) is what feeds the coder-list union
    and the delete/reassign guard — it is intentionally NOT the display count.
    """
    if svc.engine is None:
        return {}
    _, factory = svc._ensure_engine()
    result: dict[str, int] = {}
    async with factory() as session:
        for table in CODING_TABLES:
            rows = await session.execute(
                text(f'SELECT owner, count(*) FROM "{table}" GROUP BY owner')
            )
            for owner, count in rows:
                if owner:
                    result[owner] = result.get(owner, 0) + int(count)
    return result


def _response(current: str, names: list[str], seg_counts: dict[str, int]) -> CodersResponse:
    return CodersResponse(
        current=current,
        coders=[CoderInfo(name=n, coding_count=seg_counts.get(n, 0)) for n in names],
    )


async def _capture_coder(
    session, action: str, name: str, row: dict
) -> None:
    """Record a ``coder_names`` mutation into ``sync_log`` (no-op when sync
    is suspended, e.g. inside an import replay).  The coder roster must travel
    through the replays or a coder created on one machine never appears on
    the other raters' instances."""
    from qualcoder_api.services import sync

    await sync.capture(
        session,
        entity="coder_names",
        action=action,
        pk_name="name",
        pk_value=name,
        row=row,
    )


@router.get("", response_model=CodersResponse)
async def list_coders(svc: ServiceDep) -> CodersResponse:
    counts = await _coding_counts(svc)
    return _response(get_codername(), await _all_coders(svc, counts), await _segment_counts(svc))


@router.post("", response_model=CodersResponse, status_code=201)
async def create_coder(req: CoderRequest, svc: ServiceDep) -> CodersResponse:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="coder name must not be empty")
    names = get_coders()
    if name in names:
        raise HTTPException(status_code=409, detail=f'coder "{name}" already exists')
    set_coders([*names, name])
    await _ensure_project_coder(svc, name)
    await _record_audit(svc, action="coder.create", detail={"name": name})
    return _response(get_codername(), get_coders(), {})

@router.put("/current", response_model=CodersResponse)
async def switch_coder(req: CurrentCoderRequest, svc: ServiceDep) -> CodersResponse:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="coder name must not be empty")
    counts = await _coding_counts(svc)
    if name not in await _all_coders(svc, counts):
        raise HTTPException(status_code=404, detail=f'coder "{name}" does not exist')
    set_codername(name)
    # Switching to a coder that exists only in settings (e.g. created on
    # another machine before this project was opened) registers it here.
    await _ensure_project_coder(svc, name)
    return _response(name, await _all_coders(svc, counts), await _segment_counts(svc))


@router.patch("/{name}", response_model=CodersResponse)
async def rename_coder(name: str, req: RenameCoderRequest, svc: ServiceDep) -> CodersResponse:
    """Rename a coder everywhere: owner columns, visibility registry,
    per-machine settings and the sync change folder."""
    new_name = req.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="coder name must not be empty")
    if new_name == name:
        return _response(get_codername(), get_coders(), {})
    names = get_coders()
    if name not in names:
        raise HTTPException(status_code=404, detail=f'coder "{name}" does not exist')
    if new_name in names:
        raise HTTPException(status_code=409, detail=f'coder "{new_name}" already exists')

    if svc.engine is not None:
        _, factory = svc._ensure_engine()
        async with factory() as session:
            try:
                await _capture_owner_reassign(session, name, new_name)
                old_vis = (
                    await session.execute(
                        text("SELECT visibility FROM coder_names WHERE name = :n"),
                        {"n": name},
                    )
                ).first()
                visibility = int(old_vis[0]) if old_vis is not None else 1
                await session.execute(
                    text("UPDATE coder_names SET name = :to WHERE name = :from"),
                    {"to": new_name, "from": name},
                )
                # Propagate the roster rename: the old name is gone, the new name
                # appears (visibility preserved).  Owner rows are journaled above
                # so peers converge instead of keeping the stale owner.
                await _capture_coder(session, "delete", name, {"name": name, "visibility": 0})
                await _capture_coder(
                    session, "insert", new_name,
                    {"name": new_name, "visibility": visibility},
                )
                await session.commit()
            except Exception:
                import contextlib as _ctx

                with _ctx.suppress(Exception):
                    await session.rollback()
                raise
        # Rename the coder's sync sidecar folder so future exports land in
        # the new name (other raters import them unchanged).
        from qualcoder_api.services.sync import SYNC_DIR_NAME, load_state, save_state

        changes_root = svc.project_path and f"{svc.project_path}/{SYNC_DIR_NAME}"
        if changes_root:
            old_dir = f"{changes_root}/{name}"
            new_dir = f"{changes_root}/{new_name}"
            import os

            if os.path.isdir(old_dir) and not os.path.isdir(new_dir):
                os.rename(old_dir, new_dir)
        # Carry the export/import watermarks over to the new name, so the
        # renamed coder does not re-export its whole backlog from scratch.
        if svc.project_path:
            state = load_state(svc.project_path)
            for bucket in ("exports", "imports"):
                if bucket in state and name in state[bucket]:
                    state[bucket][new_name] = state[bucket].pop(name)
            save_state(svc.project_path, state)

    renamed = [new_name if n == name else n for n in names]
    set_coders(renamed)
    if get_codername() == name:
        set_codername(new_name)
    await _record_audit(svc, action="coder.rename", detail={"from": name, "to": new_name})
    return _response(get_codername(), renamed, await _segment_counts(svc))


@router.get("/{name}/stats")
async def coder_stats(name: str, svc: ServiceDep) -> dict:
    """Per-entity statistics for one coder in the open project."""
    if svc.engine is None:
        raise HTTPException(status_code=409, detail="no project is open")
    counts = await _coding_counts(svc)
    if name not in await _all_coders(svc, counts):
        raise HTTPException(status_code=404, detail=f'coder "{name}" does not exist')
    _, factory = svc._ensure_engine()
    async with factory() as session:
        rows = []
        for table, column in OWNER_TABLES:
            row = (
                await session.execute(
                    text(
                        f'SELECT count(*) FROM "{table}" WHERE "{column}" = :owner'
                    ),
                    {"owner": name},
                )
            ).first()
            rows.append((table, int(row[0]) if row else 0))
    labels = {
        "code_text": "Text codings",
        "code_image": "Image codings",
        "code_av": "AV codings",
        "case_text": "Case links",
        "annotation": "Annotations",
        "cases": "Cases",
        "attribute_type": "Attribute types",
        "journal": "Journal entries",
    }
    return {
        "coder": name,
        "tables": [{"entity": labels.get(t, t), "count": n} for t, n in rows],
        "total": sum(n for _, n in rows),
    }


@router.delete("/{name}", response_model=CodersResponse)
async def delete_coder(
    name: str,
    svc: ServiceDep,
    req: DeleteCoderRequest | None = None,
) -> CodersResponse:
    names = get_coders()
    if name not in names:
        raise HTTPException(status_code=404, detail=f'coder "{name}" does not exist')
    if name == get_codername():
        raise HTTPException(status_code=409, detail="cannot delete the current coder — switch first")
    if len(names) <= 1:
        raise HTTPException(status_code=409, detail="cannot delete the last coder")

    counts = await _coding_counts(svc)
    count = counts.get(name, 0)
    reassign_to = (req.reassign_to if req else None) or None
    if count > 0 and not reassign_to:
        raise HTTPException(
            status_code=409,
            detail=f'coder "{name}" owns {count} records — pass reassign_to to move them',
        )

    if reassign_to:
        if reassign_to not in names:
            raise HTTPException(status_code=404, detail=f'target coder "{reassign_to}" does not exist')
        _, factory = svc._ensure_engine()
        async with factory() as session:
            try:
                await _capture_owner_reassign(session, name, reassign_to)
                await session.commit()
            except Exception:
                import contextlib as _ctx2

                with _ctx2.suppress(Exception):
                    await session.rollback()
                raise

    # Remove the coder from the coder_names table too (visibility registry).
    if svc.engine is not None:
        _, factory = svc._ensure_engine()
        async with factory() as session:
            try:
                await session.execute(
                    text("DELETE FROM coder_names WHERE name = :n"), {"n": name}
                )
                await _capture_coder(session, "delete", name, {"name": name, "visibility": 0})
                await session.commit()
            except Exception:
                import contextlib as _ctx3

                with _ctx3.suppress(Exception):
                    await session.rollback()
                raise

    set_coders([n for n in names if n != name])
    await _record_audit(
        svc, action="coder.delete", detail={"name": name, "reassign_to": reassign_to}
    )
    return _response(get_codername(), get_coders(), await _segment_counts(svc))


@router.get("/visibility")
async def coder_visibility(svc: ServiceDep) -> dict:
    """Visibility flags (0 = hidden, 1 = visible) per coder in the project."""
    if svc.engine is None:
        return {"visibility": {}}
    _, factory = svc._ensure_engine()
    async with factory() as session:
        rows = await session.execute(
            text("SELECT name, visibility FROM coder_names ORDER BY name")
        )
    return {"visibility": {r[0]: r[1] for r in rows}}


@router.put("/{name}/visibility")
async def set_coder_visibility(name: str, req: VisibilityRequest, svc: ServiceDep) -> dict:
    """Hide/show a coder's codings and annotations across the project.

    The ``*_visible`` SQL views exclude hidden coders from coding lists and
    every report; a hidden coder's own rows are untouched.
    """
    if svc.engine is None:
        raise HTTPException(status_code=409, detail="no project is open")
    counts = await _coding_counts(svc)
    if name not in await _all_coders(svc, counts):
        raise HTTPException(status_code=404, detail=f'coder "{name}" does not exist')
    _, factory = svc._ensure_engine()
    async with factory() as session:
        old = (
            await session.execute(
                text("SELECT visibility FROM coder_names WHERE name = :n"), {"n": name}
            )
        ).first()
        before = bool(old[0]) if old is not None else None
        await session.execute(
            text(
                "INSERT INTO coder_names (name, visibility) VALUES (:n, :v) "
                "ON CONFLICT(name) DO UPDATE SET visibility = :v"
            ),
            {"n": name, "v": 1 if req.visible else 0},
        )
        await _capture_coder(
            session, "update", name, {"name": name, "visibility": 1 if req.visible else 0}
        )
        await session.commit()
    await _record_audit(
        svc, action="coder.visibility",
        detail={"name": name, "visible": req.visible, "before": before},
    )
    return {"ok": True, "name": name, "visible": req.visible}
