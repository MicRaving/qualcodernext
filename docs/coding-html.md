# Webpage Coder — code captured HTML pages

Captured webpages (via URL import, see [files.md](files.md)) open in a
split-pane coder: a **plain-text pane** for the extracted article text and a
**webpage pane** that renders the saved HTML snapshot with your codings
highlighted live on the page. You can also select text directly on the rendered
page to code it.

## How to reach it

- File manager → click a `.html` / `.htm` file (a captured webpage snapshot).

## The layout on this screen

- **Center**: two panes with a draggable divider — *Plain text* and *Webpage*.
- **Left bar**: the code tree.
- **Right bar**: the Inspector.

## Features

### The two panes

- **Plain text**: a full text coder over the backend-extracted text. Codings
  made here appear highlighted on the rendered page.
- **Webpage**: the saved HTML snapshot rendered in a **sandboxed iframe**
  (scripts are stripped before rendering — a safety measure; only QCnext's own
  highlighting runs). Codings render as code-colored `<mark>` highlights baked
  into the page, and are kept up to date live as you code.
- The toggles turn each pane on/off independently (never both off), and the
  divider resizes the split.

### Coding on the rendered page

- **Select text on the page** → a floating toolbar appears with **Code with
  active** / **Pick code**. The selection is mapped back to the source text
  and stored as a regular text coding.
- **Click a highlight mark** → the segment-details footer opens at the bottom:
  code swatch + name, excerpt, an inline **memo editor**, **weight steppers**,
  an **important star**, and **delete**.
- **Right-click** on the page opens QCnext's context menu (never the browser
  menu): "View details" and "Remove …" for codings under the cursor, plus the
  coding options when a selection is pending.

### Fallbacks

- If the raw snapshot can't be fetched (e.g. an article-only import), the
  webpage pane shows "No snapshot" with a retry button while the plain-text
  pane stays fully usable.

## High-level logic

The stored file is the raw HTML snapshot; the backend also extracts a plain
text for coding. QCnext builds a **collapsed text layer** over the rendered
page (whitespace collapsed, with a per-character map back to the source), so a
selection on the page translates into precise source character offsets. The
iframe runs sandboxed with scripts stripped — the snapshot file on disk is
never modified.
