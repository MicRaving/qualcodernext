# History / Audit — Developer Reference

This document describes the **audit log** (the project *History* pane) and its
**undo / redo** machinery. It is the contract that lets a contributor add a
new undoable action without guessing.

## Overview

Every user-driven mutation records one row in `audit_log`. The History pane
(`frontend/src/features/history/HistoryView.tsx`) lists those rows and offers
undo (and redo). Undo/redo is implemented on the **backend** as a registry of
inverters:

```
GET  /audit                        list (filters + server-side search + summary)
GET  /audit/stats                  action counts
GET  /audit/users                  distinct coders (project-wide user filter)
GET  /audit/{id}                   one full row (detail modal)
GET  /audit/{id}/undoable          grey-out predicate (no mutation)
GET  /audit/redo-pending           redo stack reconstructed from markers
POST /audit/undo                   invert one row (records an audit.undo marker)
POST /audit/redo                   re-apply one row (records an audit.redo marker)
```

Files:

- `backend/src/qualcoder_api/services/audit.py` — `record()` inserts a row.
- `backend/src/qualcoder_api/services/audit_undo/` — the undo machinery.
  - `apply.py` — dispatch `apply(session, row, undo=bool)`.
  - `base.py` — shared helpers, `MISSING_DATA_MESSAGE`, `_NOT_INVERTIBLE_MESSAGES`,
    `_REQUIRED` (detail-key contract), `can_undoable()`.
  - `registry.py` — `HANDLERS[action]`; `@register("a", "b")` decorator.
  - `handlers/*.py` — one module per family (coding, code, source, graph, …).
- `backend/src/qualcoder_api/api/v1/audit.py` — the REST surface above.
- `frontend/src/features/history/HistoryView.tsx` — the History pane.

## `audit_log` schema

```sql
CREATE TABLE audit_log (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        TEXT,      -- ISO-ish timestamp (from core.timeutil.now)
  user      TEXT,      -- acting coder
  action    TEXT,      -- e.g. "coding.create", "source.edit"
  entity    TEXT,      -- table name the change targeted (e.g. "code_text")
  entity_id INTEGER,   -- pk of the affected row (may be NULL)
  source_id INTEGER,   -- source file id when relevant
  detail    TEXT       -- action-specific JSON (see REQUIRED_KEYS)
);
```

Indexes: `action`, `user`, `source_id`, and `(entity, entity_id, id)`
(migration v33). The list query orders by `id DESC` (PK index).

## The undo contract

Undo/redo is **data-driven**: `apply()` looks up `HANDLERS[action]`, and each
handler inverts the change using only what was recorded in `detail`. A handler
must be invertible in **both** directions (`undo=True` restores the prior
state; `undo=False` re-applies the original change) or it must raise
`UnsupportedAction` with a clear reason.

Every `@register("...")` decorator registers one function for one or more
action strings. To be undoable, a handler must:

1. Be registered in a `handlers/*.py` module (imported by `apply.py` via
   `from . import handlers`).
2. Read its inputs from `detail` via the shared helpers in `base.py`
   (`_detail`, `_ensure`, `_insert_row`, `_delete_by_id`, `_update_row`,
   `_sync_capture`, `_revert_row_pair`, `_revert_row_update`).
3. Write its inverse rows and call `_sync_capture(...)` after each write so
   the collaboration `sync_log` learns about the change.
4. Declare its essential `detail` keys in `_REQUIRED[action]` (see below) so
   the `/undoable` predicate and the UI can grey out unsupported rows.
5. Have an i18n label `history.action.<action>` in every locale file.

### `_REQUIRED` (the detail-key contract)

`base._REQUIRED[action]` is a dict with `"undo"` and `"redo"` entries. Each
entry is either:

- a **list** of required keys — a plain string means "this detail key must be
  present and non-None"; a tuple means "any one of these must be present";
- a **string** — that direction is never invertible; the string is the
  user-facing reason (e.g. `source.import` redo → `"import the file again"`).

A legacy row recorded before the undo data existed carries an empty `detail`,
so the required keys are what lets the UI tell "not undoable" from "missing
legacy data". `can_undoable(action, detail, undo=bool)` in `base.py` combines
`_NOT_INVERTIBLE_MESSAGES`, `_REQUIRED` and `_CONDITIONAL` into a
`(undoable: bool, reason: str | None)` verdict used by `GET /audit/{id}/undoable`.

## Known non-invertible actions

`base._NOT_INVERTIBLE_MESSAGES` lists actions that are never undoable and the
reason shown: `interchange.import`, `scrape.import`, `project.compact`,
`r_script.prepare_report`, and the `audit.undo` / `audit.redo` marker rows
themselves. Several others are one-directional (imports cannot be redone;
background jobs can only be cancelled while queued/running).

## Undo/redo markers and the redo stack

`POST /audit/undo` and `POST /audit/redo` record an extra `audit_log` row with
`action="audit.undo"` / `"audit.redo"` and `entity="audit_log"`,
`entity_id=<the affected audit row id>`. This makes redo **survive a pane
reload** — the UI reconstructs the stack with `GET /audit/redo-pending`, which
returns the most recent `audit.undo` that has no later `audit.redo` for the
same `entity_id`, plus a count.

## Design decisions (read before changing)

- **`audit.record()` commits internally.** It is the only thing that persists
  the audit row; the repositories already commit the underlying mutation
  before `record()` is called. Removing the inner commit would break ~100 call
  sites (no request-level auto-commit in `get_db`), so it is kept.
- **There are no "state guard" checks** (e.g. refusing to undo when a newer
  change exists, or refusing a delete when the row is gone). The test suite
  explicitly relies on idempotent deletes and on undoing older actions after
  newer ones (reverse-order undo). Adding such guards broke 14 tests.
- **Comments are cleaned on undo only where the undo deletes the owner.**
  `coding.create` undo and `code.create` undo remove comments attached to the
  codings (and code) being deleted, so none are orphaned. Source deletes are
  NOT extended: the repository's `delete_source` leaves comments in place, so
  restoring them on undo would create duplicates.

## Recipe: add a new undoable action

1. In the handler, decorate the inverter with `@register("my.action")`.
   Implement both `undo` and `redo` branches; raise `UnsupportedAction(reason)`
   for any non-invertible direction.
2. Record enough in `detail` at the call site (`api/v1/*.py` →
   `audit.record(...)`) for both directions to invert themselves.
3. Add `"my.action": {"undo": [...], "redo": [...]}` to `_REQUIRED` in
   `base.py`.
4. Add `"history.action.my.action"` to every locale file
   (`frontend/src/lib/locales/en.ts`, `de.ts`, …).
5. Add a test to `backend/tests/test_audit_undo_all.py` (undo + redo round
   trip) and, if it can fail on missing data, a row to `LEGACY_MATRIX` in
   `test_audit_undo_robustness.py`.
6. Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_audit_undo_all.py
   tests/test_audit_undo_robustness.py` and the frontend checks
   (`npx tsc --noEmit`, `npx eslint src --max-warnings 0`, `npm test`).
