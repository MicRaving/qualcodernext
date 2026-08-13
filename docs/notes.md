# Notes — journal, annotations, memos

Three note types in one workspace: the journal (research log), annotations
(text spans) and memos (code/file notes). The left bar has a per-type list,
the center the editor; the type is stored in `notesUi.tab`.

## How to reach it

Ribbon → Notes (journal tab; the ribbon resets the tab to Journal when
re-entered). The annotations and memos tabs are also opened from the file
inspector / coder context menus.

## Layout slots used

- Left bar: `NotesList` (w-72) — header with type-dependent Add button, a
  search box, and the per-type list.
- Center: `NotesEditor` — per-tab editor.
- Right bar: Inspector.

## Features

### Journal
- **JournalList**: entries with name + date; search matches name and entry
  text; inline rename (Tab cycles), delete (confirm); context menu
  (Details / Rename / Delete); Add button creates an untitled entry.
- **JournalEditor**: inline name input in the header (Enter saves), full
  textarea for the entry, Save (disabled when clean) and Delete; the draft
  survives background refreshes (unsaved edits are never overwritten).

### Annotations
- **AnnotationItems**: list of all annotations (memo preview, file name,
  pos0–pos1, date); search matches file name and memo; inline memo editing;
  delete; context menu (Details / Open file / Rename / Delete).
- **AnnotationDetails**: header with a file picker (moving an annotation to
  another file is create+delete), position badge, Open file, Save (in edit
  mode), Delete. The memo is a click-to-edit button; new annotations open in
  edit mode automatically (`newAnnotation` flag). Add button in the list
  header creates an annotation at the start of the first source.

### Memos
- **MemoItems**: code memos as a collapsible tree (namespace-aware, depth
  cap 64; color swatches, "memo" badge) plus a "Files with memos" section;
  search matches name/memo; context menu (Details / Open file / Rename);
  Add button selects the current selection or the first code without a memo.
- **MemoEditor**: target name + kind badge (code/file), Open file button for
  files, Save, Delete (clears the memo, confirm); draft survives refreshes.

## API endpoints used

- `GET /journals`, `POST /journals`, `PATCH /journals/{jid}`,
  `DELETE /journals/{jid}`
- `GET /annotations` (all), `GET /annotations/{fid}`, `POST /annotations`,
  `PATCH /annotations/{anid}`, `DELETE /annotations/{anid}`
- `PATCH /codes/{cid}` and `PATCH /sources/{id}` (memo fields)
- `GET /sources`, `GET /codes` (lists backing the memo tree)

## Screenshot:

(to be inserted)
