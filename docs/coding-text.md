# Text Coder — read, code, annotate and edit plain-text sources

The text coder is the central workspace for plain-text material: interview
transcripts, field notes, survey responses, any `.txt`/`.md`/`.docx`/… file.
Select text → code it, annotate it, link it, or send it to a worksheet.

![Text coder](screenshots/04-coder-text.png)

## How to reach it

- File manager → click a text file (anything that isn't a PDF/HTML/CSV).
- Or from the Inspector's "Open in coder", a bookmark, or a segment jump.

## The layout on this screen

- **Center**: the document. The header shows the file name, its memo, and the
  coder controls.
- **Left bar**: the **code tree** in code mode. Clicking a code makes it the
  *active code* and assigns it to any pending selection.
- **Right bar**: the Inspector (file details; code details' recent segments
  jump here).

## Core workflow: coding

1. **Select text** in the document. A floating **toolbar** appears.
2. The toolbar offers:
   - **Code** (primary) — codes the selection with the **active code** from
     the sidebar; if none is active, the CodePicker opens (search + create-new
     code).
   - **In-vivo** — create a new code directly from the selected text (with an
     optional category) and code it immediately.
   - **Pick code** — open the CodePicker.
   - **Annotate** — add a note to the passage (a memo popover).
   - **Copy segment link** — copies a `qcnext-link://` payload for the passage
     to the clipboard.
   - **Paste link here** — if a link payload is on the clipboard, creates a
     link from this passage to the target.
   - **Send to QTT** — pick a worksheet; the passage is stored there as a
     segment item (see [qtt.md](qtt.md)).
3. The coded passage gets a **soft highlight** in the code's color; multiple
   overlapping codes stack their colors.

You can also **click a code in the sidebar** to code the pending selection
without touching the toolbar.

## Understanding the coded document

- **Coded segments**: code-colored highlights. Hovering shows
  "code — memo"; clicking opens the **segment details** panel: code color
  swatch, name, a star for important codings, code memo, date, and a delete
  button (deletions go to the undo stack).
- **Annotations**: passages with a dashed underline; clicking opens an
  annotation panel with an inline memo editor and delete.
- **Outgoing segment links**: passages show a wavy underline; clicking jumps
  to the target file+passage and flashes it. If the target is in another
  file, QCnext switches to that file automatically.
- **Bookmarks**: set a bookmark at the current scroll position (one per
  project); go-to scrolls to it (or opens the bookmarked file).

## Working with the code tree

- Click a code → sets active code + opens its Inspector details.
- Click a code's **color swatch** → toggles hiding/showing that code's
  segments in the document (several at once).
- Add code / category, rename, delete, merge, promote/demote, drag & drop —
  all from the tree (see [shell.md](shell.md) → Inspector and the sidebar
  context menu).

## Editing a document

The **Edit mode** overlays a transparent textarea on a live highlighted
preview:

- Typing **shifts coding/annotation positions in real time** (debounced).
- **Save** (or Ctrl/Cmd+S) commits the text; every coding and annotation is
  re-anchored.
- **Escape / Cancel** discards (with a confirm when the draft is dirty).

This is how you fix typos in a transcript without losing your coding.

## Autocode

The **Autocode** button opens the shared autocode dialog, with two tabs:

- **Natural language**: a coding prompt (e.g. `"happy"` as a quoted literal, or
  a free-form instruction), a target code (or several), and an optional
  "suggest new codes" option. On a single source this runs directly; in batch
  mode it queues one background job per file.
- **Dictionary**: MAXDictio-style word dictionaries (see
  [analyze.md](analyze.md) → Dictionary) — pick a dictionary and QCnext codes
  every occurrence of its terms with the mapped codes.

## Keyboard shortcuts

- **Escape** closes the floating UI in order (QTT menu → picker → annotate →
  toolbar/selection).
- **Ctrl/Cmd+S** saves while editing.
- Clicking the document dismisses floating toolbars.

## High-level logic

- Coding positions are stored as **character offsets** (`pos0`–`pos1`) into
  the raw file text. That is why editing the text requires re-anchoring, and
  why QCnext can jump precisely between files and reports.
- "Unmark last" restores the most recently deleted coding from a small undo
  stack; the project-wide History pane (see [history.md](history.md)) can undo
  far more.
