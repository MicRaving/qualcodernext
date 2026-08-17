# Notes — Journal, Annotations, and Memos

The Notes area gathers three kinds of writing:

- **Journal** — a dated research log (the classic methodological notebook).
- **Annotations** — notes attached to specific passages of files.
- **Memos** — analytical notes attached to **codes** (and files).

The left bar holds a per-type list; the center shows the editor for the
selected item. The three tabs are independent.

![Notes — journal](screenshots/10-notes-journal.png)

## How to reach it

- Ribbon → **Journal** (the notes screen; the ribbon label is "Journal").
  Re-entering from the ribbon resets to the journal tab.
- The annotations and memos tabs are also opened from the file inspector and
  coder context menus.

## The layout on this screen

- **Left bar**: `NotesList` — a header with a type-dependent Add button, a
  search box, and the per-type list.
- **Center**: the editor for the selected item.
- **Right bar**: the Inspector.

## Journal

- **List**: entries with name + date; search matches name and entry text;
  inline rename (Tab cycles); delete (confirm); context menu (Details /
  Rename / Delete). Add creates an untitled entry.
- **Editor**: the name is editable inline in the header (Enter saves); the
  body is a full textarea with **Save** (disabled when clean) and **Delete**.
  Unsaved drafts survive background refreshes — your typing is never
  overwritten.

## Annotations

- **List**: every annotation in the project (memo preview, file name,
  pos0–pos1, date); search matches file name and memo; inline memo editing;
  delete; context menu (Details / Open file / Rename / Delete).
- **Details**: a file picker (moving an annotation to another file is
  create + delete), a position badge, **Open file**, Save (in edit mode),
  Delete. New annotations open in edit mode automatically. The Add button in
  the list header creates an annotation at the start of the first source.

## Memos

- **List**: code memos as a **collapsible tree** (mirroring the codebook,
  namespace-aware, depth-capped) plus a **"Files with memos"** section; search
  matches name/memo; context menu (Details / Open file / Rename). Add selects
  the current selection or the first code without a memo.
- **Editor**: target name + a kind badge (code/file), **Open file** for file
  memos, Save, Delete (clears the memo, confirm). Drafts survive refreshes.

## High-level logic

Journal entries, annotations and memos are distinct data, but they share a
single mental model: **write a note attached to something**. Annotations are
tied to a file passage (position offsets); memos are tied to a code or file;
journal entries are standalone dated notes. Editing a memo from anywhere
(the Inspector, the sidebar context menu, or here) opens the **same inline
editor** — there is only ever one memo-editing UI.
