# Files — file manager

Browse, search, import and manage project sources.

## How to reach it

Ribbon → Files. The left sidebar's Import button also triggers this screen's
file picker (via the store's `importTick`).

## Layout slots used

- Center: `FileManager` (`ViewHeader` + virtualized table).
- Left bar: the standard `Sidebar` file-groups list (Text documents / PDF
  documents / Images / Audio / Video) — its search box is shared with the
  center table (`fileQuery` in the store).
- Right bar: Inspector (file details when a file is selected/opened).

## Features

- **Import files**: hidden `<input type=file multiple>`; imports sequentially
  with a progress bar in the ribbon queue flyout; duplicates are skipped and
  reported in a warning banner ("already exists").
- **File table**: name / type / date / owner / memo columns, sortable by
  name, type, date and owner; virtualized scrolling (only visible rows are
  mounted, O(visible) DOM).
- **Search**: the sidebar search filters both sidebar groups and the table.
- **Row click**: opens the file in the matching coder.
- **Selection**: checkboxes per row + select-all; with a selection the header
  shows:
  - **Batch transcribe** button — disabled unless AV media is selected; shows
    "eligible/total" counts; opens `TranscribeDialog` in batch mode.
  - **Batch autocode** button — disabled unless text sources are selected;
    opens `AutocodeDialog` in batch mode (queued background jobs).
  - **Delete selected** (danger, confirm dialog).
- **Row context menu** (right-click): Details (opens Inspector), Rename
  (prompt), Edit memo, Delete, Assign to case (prompt with a case name),
  Replace file (text sources only — pick a new file, media path updated).
- **Saved filters**: header dropdown of named search filters; save the
  current query as a filter, delete an applied filter.
- **URL import** (globe icon): opens `UrlImportDialog` — import a web
  resource as a new source: Reddit thread, YouTube (metadata/captions/
  comments), article text, or raw HTML; mode selector (auto/reddit/youtube/
  article/html).
- **Broken links repair** (link icon): modal listing sources whose media
  file is missing on disk (name + stored path); per row "Fix" prompts for a
  new path; also offers **Bulk rename path** (replace a path prefix across
  all sources, reports how many updated).
- **Empty states**: no files → Import button; no search match → hint.

## API endpoints used

- `GET /sources`, `POST /sources/import`, `PATCH /sources/{id}` (rename,
  memo), `DELETE /sources/{id}`, `GET /sources/{id}` (row details via
  Inspector), `GET /sources/{id}/details`
- `GET /sources/bad-links`, `PATCH /sources/{id}/mediapath`,
  `POST /sources/bulk-rename-path`, `POST /sources/{id}/replace`
- `GET/POST/DELETE /sources/filters`
- `POST /scrape/import` (URL import)
- `POST /transcribe` (batch, `start:false`), `POST /codings/autocode/batch`,
  `POST /codings/autocode/jobs/{id}/{action}` (job control)
- `GET /cases` + `POST /cases/{caseid}/files` (assign to case)

## Screenshot:

(to be inserted)
