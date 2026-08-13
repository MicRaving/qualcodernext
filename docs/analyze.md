# Analysis — reports

The Analysis area: eleven analytical reports plus three tools. The registry
(`frontend/src/features/analyze/registry.ts`) drives both the left bar
(`ReportsList`) and the center (`AnalyzeView`) so they can never drift
apart. Every report renders its own action buttons into the ViewHeader
actions slot via `ReportMenuBar`; the header also carries the **Publish**
button (export the current report as Word / Excel / PowerPoint).

## How to reach it

Ribbon → Reports. The left bar replaces the standard Sidebar while active.

## Layout slots used

- Left bar: `ReportsList` (w-72) — "Reports" BarHeader + analysis entries,
  a Tools section, and a Graphs section.
- Center: `AnalyzeView` — ViewHeader ("Analysis · <report title>") + the
  report component.
- Right bar: Inspector; selecting "Graphs" swaps it for the graph inspector.

## Reports

### Code frequencies (`code-frequencies`)
Ranked bar list + details table (code, category, count), click a row for the
code summary card (total by text/image/AV + files + memo); "Cumulative"
mode shows the cumulative codings chart (PNG export) + table. CSV export.

### Code segments (`code-segments`)
All segments flat (file, code, category, segment text, coder, date) with a
code/coder picker; a single code switches to the rich endpoint (kind
Text/Image/AV with positions/geometry, memo); "Compare two coders" mode
shows a per-file coder A vs coder B segment table. CSV export.

### File × code (`file-code`)
Dimension picker (per file / per case) and view toggle: comparison table,
stacked "codings by source" chart, or coding heatmap (canvas). CSV export.

### Code relations (`code-relations`)
Co-occurrence matrix (code × code, "N files" tooltips, diagonal marked) and
Crossovers mode (code_a → code_b relation counts for a selected coder).
CSV export.

### Interrater (`interrater`)
Coder volume table (coder, codings, files); select 2+ coders as toggle
chips; computes Krippendorff's alpha over all selected coders plus a
pairwise table (kappa, Krippendorff, Gwet AC1, units, pairs, mean row) and,
for exactly two coders, the full agreement card (both/only A/only B/
neither, counts per measure + note).

### Text & corpus (`text-corpus`)
Tabs: **Word cloud** (source picker, canvas word cloud, frequency table),
**Exact matches** (identical coded segments across files), **File summary**
(name, type, codes, segments, cases, words), **Attributes** (attribute,
value with value-label resolution, scope, entity). CSV exports.

### Dictionary (`dictionary`)
MAXDictio-style dictionaries: create/delete, import (.txt/.csv), entries as
term → code name (datalist of existing codes), dictionary autocode (reports
total + per-code counts + unmatched code names), and the document × term
frequency matrix with normalize toggle and CSV export. Also usable from the
AutocodeDialog.

### Stats (`stats`)
Code × attribute statistics: attribute picker + code chips; **Crosstab**
(chi-square with/without Yates, df, p, Cramér's V, table with row/col
totals), **Group comparison** (Mann-Whitney U + descriptives for the code
present/absent groups), **Code by variable** (mixed-methods stacked bars +
table per variable value). CSV exports.

### Summary table (`summary-table`)
Document/case × code grid whose cells hold the coding memos; click a cell to
edit each coding's memo inline (saved via the coding PATCH endpoints); cells
with multiple memos show a count badge; scope file/case; CSV export.

### Sentiment (`sentiment`)
Sentiment of coded segments or whole text sources. Lexicon mode (VADER, run
in a backend worker): neg/neu/pos/compound per row; AI mode (disabled when
AI is not configured): labels + reasons via the chat provider. Scope picker,
mode picker (AI forces segments scope), source picker, distribution summary
chips + average compound, CSV export.

### Document compare (`doc-compare`)
Pick two text files: a two-column chart of code-colored blocks aligned by
LCS with connector lines; stats (Dice code-set similarity, sequence ratio
2·LCS/(n1+n2), aligned count, segments per file); per-code co-occurrence
table; click a block to jump to the segment in the coder; CSV of the
per-position alignment table.

### Codebook (`codebook`) — Tools
Plain-text codebook with "with memos" toggle, Download (codebook.txt) and
Copy to clipboard; rendered as a selectable pre block.

### References (`references`) — Tools
RIS references table (title, authors, year, type, linked sources): open a
linked source in the coder, detach it, attach a PDF/EPUB file, delete a
reference (confirm); CSV export.

### SQL (`sql`) — Tools
Run ad-hoc read-only SQL against the project database; results as a table;
save queries by title, load/delete saved queries. Backend rejects
non-SELECT statements.

## API endpoints used

- Reports: `GET /reports/code-frequencies`, `GET /reports/code-summary/{cid}`,
  `GET /reports/codes-by-segments`, `GET /reports/code-segments/{cid}`,
  `GET /reports/charts?kind=cumulative|heatmap-file-code|heatmap-case`,
  `GET /reports/co-occurrence`, `GET /reports/code-relations`,
  `POST /reports/interrater`, `GET /reports/coder-comparison`,
  `GET /reports/word-frequencies`, `GET /reports/exact-matches`,
  `GET /reports/file-summary`, `GET /reports/attributes`,
  `GET /reports/codebook`, `GET /reports/crosstab`,
  `GET /reports/group-compare`, `GET /reports/code-by-variable`,
  `GET /reports/summary-table`, `GET /reports/sentiment`,
  `GET /compare?fid1=&fid2=`
- Dictionaries: `GET/POST /dictionaries`, `PATCH/DELETE /dictionaries/{id}`,
  `POST /dictionaries/{id}/entries`, `DELETE /dictionaries/entries/{id}`,
  `POST /dictionaries/import`, `GET /dictionaries/{id}/frequencies`,
  `POST /codings/dictionary-autocode`
- SQL: `POST /sql-reports/run` (path `/sql/run`), `GET/POST /sql/saved`,
  `DELETE /sql/saved/{title}`
- Publish: `POST /publish/from-report`
- References: `GET/DELETE /tools/references`, `POST /tools/references/{risid}/attach`,
  `DELETE /tools/references/{risid}/attach/{source_id}`
- Coder comparison: `GET /reports/coder-comparison`

## Screenshot:

(to be inserted)
