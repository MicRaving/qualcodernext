# Import / Export (interchange)

Export the project in REFI-QDA and import interchange files with automatic
format detection. Rendered standalone (its own view with a ViewHeader) or
embedded in the Settings pane (chrome-free variant).

## How to reach it

Standalone: Settings → Import/Export (the embedded variant). There is no
ribbon entry; the pane is part of the Settings right bar.

## Layout slots used

- Right bar (embedded in SettingsView) or a standalone center layout with
  `ViewHeader` — the component renders either way (`embedded` prop).

## Features

- **Export**: one-click REFI-QDA export — a download link for
  `GET /interchange/export/refi` (codebook, sources, codings and cases);
  help flyout.
- **Import**: file picker; after picking, an import menu card shows the
  detected format (by extension) with Import / Cancel; the backend
  auto-detects the real format.
- **Supported formats** (help flyout lists them):
  - REFI-QDA (`.qdp` / `.qdc`) — codebook, sources, codings and cases from
    other REFI-compliant tools.
  - RQDA (`.rqda`) — a QualCoder v3 project file.
  - Taguette (`.tag` / `.json`) — codes and coded excerpts.
  - Transana (`.tprd`) — SQLite database with media transcripts, keyword
    codes and time-based codings.
  - RIS (`.ris`) — bibliographic references imported as journal references.
  - Survey (`.csv`) — spreadsheet columns imported as cases with
    attributes; qualitative columns become text files per row.
  - Excel (`.xlsx`) — multi-column sheets imported like a survey CSV; other
    sheets become one text file per sheet.
  - SPSS (`.sav`) — variable columns imported as case attributes; qualitative
    string variables become text files per row.
  - Codebook (`.txt` / `.csv`) — plain-text codebook with
    `category>>subcategory>>code` lines.
  - Project merge (`.zip`) — merge another `.qda` project into the open one.
  - Zotero — import references from the local Zotero API
    (localhost:23119, Zotero 7+).
- **Result card**: after a successful import — counts of codes, categories,
  files, codings, cases, references, attributes (whichever the importer
  produced) + any message; the project refreshes when content changed.
- Errors surface inline; a busy spinner shows during the import.

## API endpoints used

- `GET /interchange/export/refi`
- `POST /importers/auto` (auto-detected import dispatch)
- `POST /importers/rqda`, `/importers/taguette`, `/importers/transana`,
  `/importers/ris`, `/importers/survey`, `/importers/xlsx`,
  `/importers/sav`, `/importers/codebook`, `/importers/merge`,
  `/importers/zotero`
- `POST /interchange/import/refi`

## Screenshot:

(to be inserted)
