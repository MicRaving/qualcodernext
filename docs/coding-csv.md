# CSV / Table Coder — code inside spreadsheet cells

Delimited files (`.csv`, `.tsv`) open in a spreadsheet-like coder: the file is
parsed into a real table, and you code **inside individual cells** — only the
characters you mark get the code color, never a whole cell. A **Plain text**
toggle switches to the regular text coder for the same source.

![CSV coder](screenshots/07-coder-csv.png)

This is the coder used for imported data such as YouTube comments (which arrive
as a single CSV) and survey-style files.

## How to reach it

- File manager → click a `.csv` or `.tsv` file.

## Features

### The table view

- Parsed with a full RFC-4180 parser: quoted fields, escaped quotes, embedded
  newlines, CRLF/LF, and **TSV auto-detection** (tabs win when the header line
  has more unquoted tabs than commas). UTF-8 BOM is stripped.
- The **header row is sticky**; the body scrolls vertically and horizontally
  underneath it.
- The header shows the source name, its memo, and "N columns · M rows", plus
  the **Table** / **Plain text** toggles and an **Unmark last** undo button.

### Coding inside a cell

1. **Select text inside a single cell** (cross-cell selections are ignored —
   cells map to contiguous spans of the source text).
2. The floating toolbar appears with everything the text coder offers:
   **Code with active / Pick code**, **Annotate**, **In-vivo** (create a code
   from the selection), **Copy / Paste segment link**, **Send to QTT**.
3. Only the selected characters get the **code tint**; annotated spans get a
   dashed underline.
4. A **badge cluster** (up to two code chips with color dots, then "+N") is
   drawn at the top-right of any cell that has codings; hovering lists the
   distinct code names.
5. **Click a cell** (no selection) opens the details bars below the table
   showing every coding/annotation in that cell — delete, weight steppers
   (0–100), and annotation memo editing.

### More

- **Unmark last** removes the most recent coding (undo stack).
- Scroll, window blur or Escape dismisses the floating toolbar; Escape clears
  the details bars.
- **Plain text** toggle shows the same source as a normal text document
  (shared codings).

## High-level logic

The file on disk is still **plain text**, so all codings are ordinary text
codings with character offsets into the raw file. The parser builds a mapping
from each decoded cell character back to its raw source offset, which is what
lets the table turn a selection inside a cell into the correct `pos0`–`pos1`.
The table is a *view*; the source stays a text file.
