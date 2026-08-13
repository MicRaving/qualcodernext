# History — audit log and undo/redo

The audit log as a right-bar pane: every change to the project, filterable
by action and coder, with per-row undo (and a redo stack).

## How to reach it

Ribbon → History (clock icon, right side). Toggles the right-bar pane; the
center view stays whatever it showed.

## Layout slots used

- Right bar only: `HistoryView` (LeftBar `borderSide="l"`, wide) — BarHeader
  + filter bar + search bar + change cards.
- Center/left bar: unchanged.

## Features

- **Filter bar**: action select (populated from the audit stats endpoint,
  each with its count) and coder select, plus a refresh button.
- **Search**: client-side text search over the loaded page (user, entity,
  action label, raw detail JSON).
- **Change cards**: action label, timestamp, user, entity name + id, and a
  detail summary (e.g. "cid 5 · 100–240" for codings, "123 → 456 chars" for
  source edits, "N segments" for autocode, "import" for interchange).
- **Undo**: rows whose action the backend can invert carry an undo icon
  (coding.create/delete, annotation.create/delete, source.edit, code.rename/
  create/delete, case.create, journal.create). Undoing pushes the row onto a
  redo stack (last 10).
- **Redo**: the header's redo button (mirrored undo icon) replays the most
  recently undone row; both refresh the project and the log afterwards.
- **Detail modal**: click a card to inspect it — source edits show a
  before/after diff (danger/success pre blocks), everything else the raw
  detail JSON.
- **Pagination**: 100 rows per page with prev/next and a range/total
  readout; race-guarded so a stale response never overwrites a newer page.

## API endpoints used

- `GET /audit` (limit/offset/action/user), `GET /audit/stats`
- `POST /audit/undo`, `POST /audit/redo`

## Screenshot:

(to be inserted)
