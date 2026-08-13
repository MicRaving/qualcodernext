# QTT — Questions-Themes-Theories workspace

MAXQDA-style worksheets that collect insights (segments, notes, chart
references, links) under themed sections. The name and the workflow mirror
the classic QTT analysis approach: a worksheet defines the research
question, purpose and framework, then gathers evidence.

## How to reach it

Ribbon → QTT. Worksheet selection is shared via the store (`qttUi`).

## Layout slots used

- Left bar: `QttList` (w-72) — worksheet list with total item count badge.
- Center: `QttView` — the selected worksheet (info block + section cards).
- Right bar: Inspector.

## Features

- **Worksheet list**: rows show name, kind badge (Qual / Mixed), and item
  count; context menu (Details / Rename / Delete); inline rename input.
- **Create worksheet**: Add opens a dialog with a name input and a template
  kind selector — **Qualitative** (single-column sections) or **Mixed**
  (two-column grid). The template seeds the sections (14 steps modeled on
  the classic QTT procedure).
- **Worksheet info block**: research question, purpose and framework editors
  (Save enabled when dirty; drafts survive reloads).
- **Section cards**: each card has a header (name + item count badge), a
  "new note" input (Enter or + to add), and the item list.
- **Item kinds**:
  - *Segment* (quote): quote text plus a source chip; clicking it jumps into
    the coder and flashes the span (`jumpToSpan`).
  - *Note*: free text.
  - *Chart*: a report reference (report name + params JSON).
  - *Link*: an external URL (opens in a new tab).
- **Item actions**: a section dropdown moves an item to another section
  (same sheet); a delete button removes it.
- **Send-to-QTT from the coders**: the text coder's selection toolbar offers
  "Send to QTT" → pick a worksheet → the selected span is stored as a
  segment item (with the source text). An open QTT workspace refreshes
  automatically (store tick).

## API endpoints used

- `GET /qtt`, `POST /qtt`, `PATCH /qtt/{sheet_id}`, `DELETE /qtt/{sheet_id}`,
  `GET /qtt/{sheet_id}`
- `POST /qtt/{sheet_id}/items`, `PATCH /qtt/items/{item_id}`,
  `DELETE /qtt/items/{item_id}`
- `POST /qtt/{sheet_id}/send-segment` (from the coders)

## Screenshot:

(to be inserted)
