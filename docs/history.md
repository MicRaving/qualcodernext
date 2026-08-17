# History — the audit log and undo/redo

Every change to the project is recorded in an **audit log**: who did what,
when, and to which entity. The History pane shows that log — filterable by
action and coder, searchable — and lets you **undo** individual changes (with
a redo stack).

## How to reach it

- Ribbon → **History** (clock icon, right side). Toggles the right-bar pane;
  the center view stays whatever it showed.

## The pane

- **Filter bar**: an action select (populated from the audit stats, each with
  its count) and a coder select, plus a refresh button.
- **Search**: client-side text search over the loaded page (user, entity,
  action label, raw detail JSON).
- **Change cards**: action label, timestamp, user, entity name + id, and a
  detail summary (e.g. "cid 5 · 100–240" for codings, "123 → 456 chars" for
  source edits, "N segments" for autocode, "import" for interchange).
- **Pagination**: 100 rows per page with prev/next and a range/total readout.

## Undo / redo

- Rows whose action the backend can invert carry an **undo icon**
  (coding create/delete, annotation create/delete, source edit, code
  rename/create/delete, case create, journal create). Undoing pushes the row
  onto a redo stack (last 10).
- The header's **redo** button replays the most recently undone row; both
  actions refresh the project and the log afterwards.

## Detail modal

Click a card to inspect it: source edits show a **before/after diff**
(danger/success blocks); everything else shows the raw detail JSON.

## High-level logic

Every mutation (create, update, delete across codes, codings, sources, cases,
annotations, journals, links, …) is recorded with before/after snapshots.
Undo is not a whole-project rollback — it is **per-row inversion** of the
specific logged change, which is far safer in a collaborative setting. The
same log powers the "last action" context in bug reports and the undo stack in
the coders.
