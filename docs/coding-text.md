# Text coder

Code, annotate, link and edit plain-text sources.

## How to reach it

Files table → click a text file (non-PDF), or via Inspector → "Open in
coder", segment jumps, bookmarks, etc. `CodingWorkspace` dispatches
`media_type == "text"` (non-PDF) to `TextCoder`.

## Layout slots used

- Center: `TextCoder` — wrapping `ViewHeader` (file name + memo meta +
  controls) + scrollable document.
- Left bar: Sidebar in code mode (code tree); clicking a code assigns it to
  the pending selection (`qc:assign-code` event).
- Right bar: Inspector (file details; code details' recent segments jump
  here via `gotoSegment`).

## Features

- **Selection toolbar** (floating, appears on text selection): Code (primary;
  uses the active code from the sidebar, else opens the `CodePicker`),
  Annotate (inline memo popover → creates an annotation), Copy segment link
  (writes a qcnext link payload to the clipboard), Paste link here (if a
  link payload is on the clipboard), Send to QTT (pick a worksheet → store
  the span as a segment item).
- **Coded-segment rendering**: code-colored soft highlights (code tint),
  stacked colors for overlapping codes, per-segment hover title
  ("code — memo"), wavy-underline markers for outgoing segment links
  (click → jump to target file+span, flashing the span).
- **Segment details panel**: clicking a coded segment shows its coding rows —
  code color swatch, name, star for `important` codings, code memo, date,
  and a delete button (deleted codings go to the undo stack).
- **Unmark last**: restores the most recently deleted coding (undo stack of
  the last 20 removals via `POST /codings/undo`).
- **Annotations**: dashed-underline annotated fragments; clicking shows an
  annotation details panel with memo editing (inline textarea) and delete;
  annotations can also be managed from the Notes view.
- **Edit mode**: a transparent textarea over a live highlighted overlay —
  typing shifts coding/annotation positions in real time (debounced
  `POST /codings/shift-positions`); Save commits the text
  (`POST /codings/commit-edit`) and re-anchors everything; Ctrl/Cmd+S saves;
  Escape / Cancel discards (with confirm when dirty).
- **Autocode**: opens the shared `AutocodeDialog` (natural-language coding
  prompt, multi-code selection, suggest-new-codes option, dictionary
  autocode tab).
- **Bookmarks**: set bookmark at the current scroll ratio (one per project);
  go-to bookmark opens the bookmarked file (or scrolls if it's this file).
- **Hidden codes**: clicking a code label in the sidebar toggles that code's
  segments hidden in the document (`qc-seg-hidden`), several at once.
- **Flash/jump**: `gotoSegment` from the Inspector's recent segments and
  `qc:jump-span` events from segment links scroll the target into view and
  flash it; jumps to another file switch the coder view automatically.
- **Keyboard**: Escape closes the floating UI in order (QTT menu → picker →
  annotate → toolbar/selection). Ctrl+S in edit mode saves.
- **Code colors**: segments tinted with the code's color (fallback accent).

## API endpoints used

- `GET /sources/{id}`, `GET /codings/text/{fid}`, `GET /annotations/{fid}`,
  `GET /codes` (flat)
- `POST /codings/text`, `DELETE /codings/text/{ctid}`, `POST /codings/undo`
- `POST /annotations`, `PATCH /annotations/{anid}`, `DELETE /annotations/{anid}`
- `POST /codings/shift-positions`, `POST /codings/commit-edit`
- `POST /codings/autocode`, `POST /codings/dictionary-autocode`
- `GET/PUT /bookmarks`, `GET/POST/DELETE /links`, `GET /links/source/{fid}`
- QTT send: `GET /qtt`, `POST /qtt/{sheet_id}/send-segment`

## Screenshot:

(to be inserted)
