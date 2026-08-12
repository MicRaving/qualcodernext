# Gap Assessment \& Native Integration Plan — QCnext v4 vs. MAXQDA 26

For every gap identified in `MAXQDA-vs-QCnext.md`, this document assesses what already
exists in the QCnext codebase to build on, and lays out a concrete plan to integrate the
feature natively (backend + frontend + packaging + tests).

**Architecture facts the plans rely on (verified in the codebase):**

* Backend: FastAPI (async) routers in `backend/src/qualcoder\_api/api/v1/`, business logic in
`backend/src/qualcoder\_api/services/`, SQLite via SQLAlchemy async (`core/models.py`).
* Importer pattern: `importers.py` `\_run\_import()` — upload → `importer(session\_factory, path, owner) -> dict`
→ `audit.record("interchange.import", …)`; auto-detection in `POST /interchange/import/auto`.
* Every mutation is written to the audit log; collaboration sync (`services/sync.py`) replays
`changes.jsonl` sidecars (60 s cycle, last-write-wins) — new write-endpoints should record audit
entries so they flow through sync automatically.
* Codings: text (`pos0/pos1`), image (`x1/y1/width/height`), AV (`pos0/pos1` ms); each coding has
memo + `important` flag. `POST /codings/autocode` already does literal + regex, multi-code,
multi-term, all/first/last, per-file or project-wide.
* AI: `services/ai\_service.py` (OpenAI-compatible chat, modes + `ai\_prompts.py` library),
`ai\_index.py` (semantic index), `mcp\_service.py`. Frontend `AiView` (Chat/Search tabs).
* Reports: `api/v1/reports.py` + `services/report\_service.py`; chart datasets in
`GET /reports/charts?kind=…`; views registered in `features/analyze/`.
* Frontend: React 19 + zustand; views fill slots (ribbon/left/center/right/status) per
`frontend/src/DESIGN.md` — new workspaces must register there.
* `AvCoder.tsx`: has `mediaRef` (audio/video element), playback-rate control, transcript panel
with `\[mm:ss]` timestamp parsing, live-transcript polling, timeline marking. `TextCoder`/`PdfCoder`
already use `window.addEventListener("keydown", …)`.
* Tauri plugins installed: `dialog`, `updater` only.
* Packaging: PyInstaller onedir via `compile.ps1` → prefer pure-Python deps; avoid scipy/pandas
unless behind an optional import.

Legend: **S** = small (\~1–3 pd) · **M** = medium (\~3–6 pd) · **L** = large (>6 pd) (pd = person-days)

\---

## 1\. XLSX and SPSS .sav import — **M (3–5 pd)**

**Current state:** importers exist for REFI-QDA, RQDA, Taguette, RIS, survey CSV, codebook, .qda merge.
No Excel or SPSS. `emoji`, `Pillow`, `rispy`, `faster-whisper` are the only non-stdlib deps.

**Plan:**

1. Deps: add `openpyxl` (pure Python, PyInstaller-safe) and `pyreadstat` (C wheels for win/mac/linux;
verify in PyInstaller — its bundled libs usually work; fallback: `pandas`+`openpyxl` for .sav via
`pd.read\_spss` is heavier, avoid).
2. `services/import\_service.py`:

   * **XLSX:** each sheet becomes a table-ish text source. Options: (a) one source per sheet with
rows rendered as tab-separated text (round-trippable), (b) one source per row (survey-style,
like the existing survey CSV importer — reuse `survey` importer by converting xlsx→CSV in memory
and delegating). Reuse the survey importer for sheets detected as survey-shaped (first row =
header).
   * **SPSS .sav:** `pyreadstat.read\_sav()` → variable metadata becomes project attribute types
(case scope), each row becomes a case with values; optional designated qualitative columns
become text sources coded per row (same shape as survey importer).
3. Wire into `POST /interchange/import/auto` (magic-number sniff: `PK\\x03\\x04` + `xl/` → xlsx;
SPSS .sav starts with `$FL2`/`$FL3`).
4. Frontend: no new UI — InterchangeView already has the import picker + per-format help; add
help strings.

**Tests:** fixture files (small xlsx via openpyxl, generated .sav via pyreadstat write is not
available — craft minimal .sav byte fixture or use `pyreadstat.write\_sav` in tests if exposed).
**Risk:** pyreadstat wheel availability for the packaged build; verify in `compile.ps1` pipeline.

\---

## 2\. Web page capture — **M (4–6 pd)**

**Current state:** HTML import works (text extraction on import). No capture tool.

**Plan (native, no browser extension — Tauri owns a WebView2):**

1. New Tauri child `WebviewWindow` (`webviewWindow` API already available via `@tauri-apps/api/webviewWindow`):

   * "Open capture" button in FileManager toolbar + Dashboard → opens a window with a URL bar.
2. Capture JS injected into the child webview: serialize `document.documentElement.outerHTML`,
inline same-origin CSS (`<style>` blocks + `fetch()` of stylesheet links) and images
(canvas-draw → `toDataURL`); store as `.html` blob, pass path back to the main window.

   * Fallback for pages blocking fetch: capture visible DOM only (acceptable degradation).
3. Reuse existing source import (`POST /sources/import`) with the saved `.html` — text extraction
already exists. Optionally auto-open the text coder after capture.
4. Tauri: add `"webview": \[]` capability for the capture window.

**Tests:** e2e — capture a data-URL page, assert a source is created and text extracted.
**Risk:** anti-scraping pages / heavy SPAs (SPA capture = current DOM state only). Document limitation.

\---

## 3\. Scrape Reddit / YouTube / Instagram / Twitter/X / TikTok — **M–L (5–10 pd)**

**Honest feasibility assessment:**

|Platform|Native approach|Feasibility|
|-|-|-|
|Reddit|`GET https://www.reddit.com/r/X/comments.json` (anonymous JSON API, still functional)|✓ feasible, no key|
|YouTube|`yt-dlp` (pure Python, PyInstaller-friendly): video metadata, captions, comments|✓ feasible; YouTube Data API not needed|
|Generic article|`trafilatura` (pure Python): URL → clean text|✓ feasible|
|Instagram / TikTok|no public read API; heavy anti-bot|✗ not feasible reliably; import platform CSV/JSON export instead|
|Twitter/X|public API removed (2023); requires paid API|✗ not feasible; import X archive/export files|

**Plan:**

1. `POST /sources/import-url` endpoint: `{url, mode}` → platform dispatch:

   * reddit → comments.json → thread text + comments as one source (or source + coded segments);
   * youtube → `yt-dlp --skip-download --write-subs`-style extraction in-process (yt-dlp as lib):
title/description/captions/comments → text source (+ optional audio download for analysis);
   * default → trafilatura extract.
   * Instagram/X/TikTok → return 422 with "use CSV/JSON export import" help text; add a generic
JSON-export importer (many platforms export JSON) — reuse RIS/survey importer machinery.
2. Background job for long downloads (reuse `transcription` job pattern: `jobs` table + polling).
3. Frontend: "Import from URL" dialog in FileManager; job indicator reuses the existing background-task
queue.

**Tests:** mock HTTP layer (respx/httpx MockTransport) for reddit/trafilatura paths; yt-dlp behind
a test double. **Risk:** yt-dlp extraction changes with site updates — pin version.

\---

## 4\. Drag \& drop coding — **S (2–3 pd)**

**Current state:** coding is created from a selection + active code/click. All coders already manage
selections; sidebar code tree exists.

**Plan (frontend-only):**

1. Sidebar code items (`Sidebar.tsx`): `draggable`, `dataTransfer.setData("qc/code", codeId)`;
include memo/color in the drag image.
2. Drop targets:

   * `TextCoder`: existing text selection → `POST /codings/text` on drop over the selection
(or over the document with a range-set; keep it simple: drop onto selected text, same as click-code).
   * `ImageCoder`/`PdfCoder`: drop onto canvas arms the dragged code → next drag creates the region
with that code (mirrors MAXQDA); dropping onto an existing region re-codes it (`PATCH /codings/image`).
   * `AvCoder`: drop onto timeline marks the current in/out range with the code (mirrors existing flow);
drop onto a transcript selection codes it as text.
3. Visual affordance: `dragover` highlight on the segment/timeline.

**Tests:** vitest component tests for drop handlers (jsdom drag events) + e2e.
**Risk:** low; keep DnD as an accelerant — click-coding remains.

\---

## 5\. Creative coding (scratchpad → codes) — **M (4–6 pd)**

**Current state:** memos (code/file/coding/case), notes workspace, graphs (free-text nodes). No scratchpad.

**Plan:**

1. New table `creative\_item(id, text, source\_fid, pos0, pos1, note, created)` — pure SQLite,
migrated via existing migration chain. (A real table beats abusing memos: distinct lifecycle.)
2. `api/v1/creative.py`: CRUD + `POST /creative/promote {item\_id, code\_name, category\_id}` →
creates the code and, when the item has source refs, the coding (reuse `coding\_service`).
3. Frontend: "Creative coding" panel (right bar slot): collect selected segments ("Send to
scratchpad" in coder selection toolbar + right-click), free-text notes, merge items, promote to
code. Register view per DESIGN.md.
4. Audit + sync: standard `audit.record` calls → sync sidecars pick it up.

**Tests:** backend CRUD + promote; e2e smoke. **Risk:** none significant.

\---

## 6\. Autocode via dictionary — **S (2–3 pd)**

**Current state:** `POST /codings/autocode` supports literal + regex, multiple codes, multiple
find-texts, all/first/last, project-wide. MAXDictio dictionaries = word lists grouped per code.

**Plan:**

1. Dictionary format: text/CSV file (`code,term1,term2,…`) or a simple in-app dictionary editor
(list of {code, terms}). Import endpoint `POST /codings/dictionary-import` (parse file) + CRUD
`GET/PUT/DELETE /dictionaries` (store as JSON sidecar or a `dictionary` table).
2. `POST /codings/dictionary-autocode`: for each entry, call the existing autocode engine with
word-boundary literal mode (case-insensitive), accumulate created codings + per-document
term counts (feeds feature #13). No new coding logic — reuse `autocode\_jobs.py`/`coding\_service`.
3. Frontend: "Dictionary autocode" section inside the existing AutocodeDialog (code-picker reuse).

**Tests:** dictionary parse + autocode equivalence with manual multi-term autocode.
**Risk:** none.

\---

## 7\. Manual transcription mode — **M (3–5 pd) + pedal feasibility**

**Current state:** `AvCoder` has the media element, playback-rate control, transcript panel with
`\[mm:ss]` parsing, and live auto-transcription preview. What's missing: an editable transcript +
start/pause transport for manual typing.

**Plan:**

1. Add a "Transcription mode" toggle in the transcript panel header (mirrors the 26.3 mode
switcher): transcript becomes a contentEditable textarea where Enter inserts a new line
prefixed `\[mm:ss] ` with the current playback position (existing `transcriptTimestamp(ms)`).
2. **Keyboard start/pause — feasible:**

   * In-app: `window keydown` handlers already exist in the coders; add Space (when the media
element/focused) + `F9`/`F10` accelerators → `mediaRef.current.paused ? play() : pause()`.
   * Media keys (Play/Pause, Prev/Next): WebView2 is Chromium → `navigator.mediaSession`
`setActionHandler("play"|"pause"|…)` receives OS multimedia keys while the webview has focus;
wire them to the same transport. No new Tauri plugin needed. (Known limitation: media keys only
arrive while the webview is focused.)
   * **Pedal feasibility assessment:** two pedal classes —
*keyboard-type pedals* (most common: Infinity, VEC, generic USB pedals that type a key like
F9/Enter): work via `keydown` in-window; add optional **system-wide** capture via the
`tauri-plugin-global-shortcut` Rust plugin (needs one plugin addition to `src-tauri` +
capability entry) so the pedal works even when the app is unfocused.
*HID-type pedals* (raw HID reports): require a custom Rust plugin (`tauri-plugin-hid` is
community-maintained) — defer; document as future work.
3. Save: on pause/save, `PUT /sources/{id}` (text edit) or dedicated `POST /sources/{id}/transcript`
— reuse `commit-edit` re-anchoring so existing codings stay aligned.
4. Manual transcription shares the transcript panel; auto-transcription and manual mode mutually
exclusive per source.

**Tests:** unit test timestamp insertion + caret handling; e2e with mocked media.
**Risk:** mediaSession delivery varies across WebView2 versions — ship F9/Space as guaranteed path.

\---

## 8\. Statistical analysis — **M (5–8 pd)**

**Current state:** `reports.py` has frequencies, coder stats, attributes report, charts. No
inferential stats. **Constraint:** scipy/pandas are heavy for the PyInstaller onedir — avoid.

**Plan (pure-Python statistics, no scipy):**

1. `services/stats\_service.py` (\~250 lines, stdlib only):

   * chi-square (with Yates correction) + Fisher's exact (2×2), Cramér's V;
   * Mann–Whitney U + Spearman rank (for numeric variables vs. code presence);
   * group means/sd/medians by variable value.
2. Endpoints:

   * `GET /reports/crosstab` — code × variable-value contingency table + chi-square/V.
   * `GET /reports/group-compare` — numeric variable by code presence → Mann–Whitney U + effect.
   * Reuse `report\_service` data pulls (attributes, codings per case).
3. Frontend: two new entries in the Analyze registry; CSV + PNG export via reportKit.

**Tests:** against hand-computed fixtures (published textbook examples) — critical for correctness.
**Risk:** none for packaging. **Note:** overlap with #12 — build once, ship both.

\---

## 9\. Sentiment analysis — **S–M (2–4 pd)**

**Current state:** AI chat exists; no sentiment.

**Plan (two native modes):**

1. **Local lexicon (offline, default):** add `vaderSentiment` (pure Python, \~0 weight) — score each
coded segment / source. New endpoint `POST /reports/sentiment {scope}` → per-source or
per-segment scores + distribution chart data (reuse `/reports/charts`).
2. **AI mode (existing provider):** new prompt in `ai\_prompts.py` ("classify sentiment of the given
segment as positive/negative/neutral + brief rationale"), batch via `ai\_service`; results merged
into the same report shape. Optional AI → store on the coding (extend coding payload, e.g.
`sentiment` column) for later retrieval.
3. Frontend: sentiment report entry in Analyze + optional per-segment badge in coders.

**Tests:** lexicon unit tests with labeled fixture texts. **Risk:** lexicon quality vs. MAXQDA's
AI-based sentiment — document that AI mode is the parity path.

\---

## 10\. Segment hyperlinks / linked quotes — **M (3–5 pd)**

**Current state:** no link entity. Coders have goto/flash ("goto-segment") and the graph editor
stores typed lines (pattern for a new table).

**Plan:**

1. Table `link(id, from\_fid, from\_pos0, from\_pos1, to\_fid, to\_pos0, to\_pos1, memo)` + migration.
2. `api/v1/links.py`: `POST /links`, `GET /links?fid=`, `DELETE /links/{id}` (audit-recorded →
sync-safe). Text-segment links only (media links deferred).
3. Frontend:

   * Coders: "Copy segment link" in the segment context menu; "Paste link at selection" creates
the link with a marker underline (like annotations);
   * click marker → resolves target segment and jumps (`goto-segment` flash already exists in TextCoder).
4. Inspector shows outgoing/incoming links for the selected segment.

**Tests:** backend CRUD + position validity; e2e link-jump.
**Risk:** position drift after text edits — reuse `commit-edit` re-anchoring for link positions.

\---

## 11\. Value labels — **S (1–2 pd)**

**Current state:** `AttributeType.value\_type` (text/number/date/boolean); `Attribute` values;
`AttributesView` grid + attribute report. No value lists.

**Plan:**

1. Migration: add `value\_labels` JSON column to `attribute\_type` (map `value → label`).
2. `api/v1/entities.py`: accept `value\_labels` in POST/PATCH attribute types; return in GET.
3. Frontend: attribute-type editor gains a label editor (key–label rows); the value editor renders a
`<select>` when labels exist (stores raw value); attribute report + CSV export show labels.
4. Import/export: survey importer can auto-suggest labels from its header/value stats (nice-to-have).

**Tests:** CRUD + report rendering. **Risk:** none.

\---

## 12\. Mixed methods: quantify codes by variable, group comparisons — **M (3–5 pd)**

**Current state:** case heatmap + attribute report exist; codings link to cases via `case\_text`
(span) or whole-file links.

**Plan (builds directly on #8):**

1. `GET /reports/code-by-variable {attr\_name}` — counts of codings per code grouped by case-variable
value (uses case↔file/span links, which exist); matrix table + stacked bars (reuse chart kinds).
2. Group comparison reuses `stats\_service` (#8): e.g. Kruskal–Wallis/ANOVA-style medians by code
presence.
3. Frontend: one "Mixed methods" section in Analyze with code×variable matrix + stats output.

**Tests:** synthetic project with cases+attributes → known counts.
**Risk:** none. **Note:** MAXQDA's full Analytics Pro (R) is out of scope; pure-Python stats cover
the common teacher/researcher workflows.

\---

## 13\. Dictionary-based content analysis — **S–M (3–4 pd)**

**Current state:** word-frequency engine (stopwords, per-source/corpus), autocode (#6 plan).

**Plan:**

1. Reuse the dictionary model from #6.
2. `GET /reports/dictionary-freq` — per document × dictionary-term (or code-group) frequency
matrix; row/column totals; optional relative (%) view; CSV export. Built on the existing
word-frequency extraction, not on coding counts.
3. Optional KWIC view: existing `codes-by-segments`-style table with term context ±20 words.
4. Frontend: entry in Analyze ("Dictionary analysis") shared with #6's dictionary editor.

**Tests:** fixture corpus with known term counts. **Risk:** none.

\---

## 14\. Document Portrait — **S (2–3 pd)**

**Current state:** all codings (text/image/AV) are already retrievable per source with colors;
chart endpoint exists with kinds.

**Plan:**

1. `GET /reports/charts?kind=portrait\&sources=…\&codes=…` → per source: ordered list of
`{pos0, pos1 (or page/ms), color, code\_name, memo}` segments (text codings for portraits;
image/PDF optionally as page-index bars).
2. Frontend: new "Document Portrait" report — SVG strips (one per document), segments as
code-colored bars at proportional offsets; hover tooltip (code + memo), click → opens source
and flashes the segment (goto exists).
3. CSV/PNG export via reportKit.

**Tests:** chart payload unit test. **Risk:** none.

\---

## 15\. Document Comparison Chart — **M (3–4 pd)**

**Current state:** comparison matrix (file × code) + heatmaps exist; no sequence alignment.

**Plan:**

1. Backend `report\_service` addition: for 2 selected documents, build the code-sequence per
document (chronological segments), compute alignment (LCS on code sequences; reuse
`diff-match-patch` already in deps for text, or implement LCS in \~40 lines) and a similarity
index (Dice coefficient over code sets / aligned segments).
2. `GET /reports/document-compare?fid1=\&fid2=` → aligned segment pairs + unmatched + score.
3. Frontend: two-column synchronized chart (MAXQDA-style): code-colored blocks with connector
lines for matches; jump-to-segment on click.

**Tests:** hand-built fixture docs with known overlaps.
**Risk:** alignment semantics for overlapping codes — define priority (first code per position).

\---

## 16\. Summary Tables — **S–M (2–3 pd)**

**Current state:** coding memos exist (`PATCH /codings/text/{ctid}` memo), comparison matrix exists.

**Plan:**

1. `GET /reports/summary-table {fid?, cid?, scope: case|file}` → rows = docs (or cases), columns =
codes, cell = the coding's memo text (first/non-empty; concatenate with separators). No new
storage — memos already hold paraphrase/summary content (MAXQDA's Summary Table cell = summary
of the segment; ours = coding memo).
2. Frontend: "Summary Table" report — editable cells (`PATCH` coding memo inline), CSV export.
A "Write summary for segment" quick action in the segment context menu (opens memo editor)
closes the loop.

**Tests:** report assembly with multi-coding cells. **Risk:** none.

\---

## 17\. Smart Publisher (report publishing) — **L (6–10 pd)**

**Current state:** CSV + PNG exports only. No .docx/.pptx/.pdf generation.

**Plan:**

1. Deps: `python-docx` (pure Python, PyInstaller-safe); PDF via frontend print (Tauri webview
`window.print()` / browser print dialog) rather than a Python PDF lib — simplest robust path;
PPTX optional via `python-pptx` (also pure Python).
2. `services/publish\_service.py`:

   * `build\_docx(spec)`: spec = sections {title, intro text, tables, segment quotes
(code, doc, text, memo), images (chart PNGs via reportKit)} → .docx assembled with heading
styles.
   * Endpoint `POST /publish/docx` (spec from the active report) → file download; `POST /publish/pdf` returns HTML (reuse existing report render) for the print flow.
3. Frontend: "Publish" button on report headers (Analyze registry) — picks the active report,
sends its data to /publish, saves via Tauri dialog.
4. Full-parity "Smart Publisher" (customizable templates, Word styles, table-of-contents) is a
larger project — scope v1 to structured default templates.

**Tests:** docx assembly against golden files (python-docx round-trip). **Risk:** docx fidelity —
keep templates simple.

\---

## 18–20. QTT workspace + Mixed Methods QTT Worksheet + Send-to-QTT — **L (6–12 pd total)**

**Current state:** no QTT. Graph persistence (typed items/lines) is the closest storage pattern.

**Plan:**

1. Tables: `qtt\_sheet(id, title, kind \[qual|mixed], research\_question, purpose, framework, meta)`
and `qtt\_item(id, sheet\_id, section, kind \[segment|chart|note|image|link], payload\_json, order)`.
`kind=mixed` seeds the Creswell 14-step sections (research questions, data collection,
qual analysis, quant analysis, joint display, meta-inference…) as ordered template rows.
2. `api/v1/qtt.py`: CRUD for sheets + items; `POST /qtt/send` generic collector
(payload: report/chart ref, segment ref, note text).
3. Frontend: new top-level view registered in `ProjectShell` (ribbon slot, between Notes and
Analyze). Two-pane layout: sheet tree + section content; "Send to QTT" button added to report
headers (reuses the #17 Publish button row) and coder segment context menus; sheets render
collected content inline (charts via img/PNG, segments as quotes with goto).
4. Send-to-QTT shares the #18 workspace — implement together.

**Tests:** sheet/items CRUD + template seeding; e2e send-to-QTT from a report.
**Risk:** none technically; UI scoping is the main effort.

\---

## 21\. Import of NVivo, ATLAS.ti, Transana — **L (8–15 pd, phased)**

**Current state:** REFI-QDA import/export (the industry-standard interchange path), RQDA/Taguette
SQLite importers as precedent for DB-based formats.

**Honest assessment per format:**

|Format|Container|Feasibility|
|-|-|-|
|Transana `.tprd`|SQLite|✓ feasible — same pattern as RQDA importer|
|NVivo `.nvpx`|ZIP of XML files|\~ feasible — XML mapping is large but mechanical; NVivo's own REFI-QDA export exists as fallback|
|ATLAS.ti `.atlproj24`|ZIP of XML|\~ feasible, large mapping; older `.proj` (proprietary binary/SQLite) — skip|
|Recommendation||Prefer "Export to REFI-QDA in the source tool" as the primary path; native importers as convenience|

**Plan (phase order):**

1. **Phase 1 — Transana (2–4 pd):** `services/importers/transana.py` — read .tprd SQLite:
sources (text/transcript + media), codes, codings, cases; map to existing tables; register in
`/interchange/import/auto` (SQLite header sniff + table presence).
2. **Phase 2 — NVivo .nvpx (4–6 pd):** unzip → parse XML nodes (`Node`, `Document`, `Coding`,
cases, attributes); map via existing import services; document REFI fallback in the help UI.
3. **Phase 3 — ATLAS.ti .atlproj24 (4–6 pd):** zip → XML (documents, codes, quotations, memos,
links); reuse phase-2 mapping skeleton.

**Tests:** fixture projects generated from the source tools (small); golden-count assertions.
**Risk:** format drift between tool versions — pin supported versions, degrade gracefully.

\---

## 22\. MS Office export — **M (3–5 pd)**

**Current state:** CSV-only report export. #17 already adds python-docx; xlsxwriter/openpyxl
added in #1.

**Plan:**

1. Excel: `POST /interchange/export/xlsx` — generic table dumper (report tables, codebook,
attributes, coder stats) via `openpyxl`/`xlsxwriter` (multiple sheets, styled header row).
2. Word: reuse `publish\_service` (#17) — same .docx builder, "Export current report to Word".
3. PowerPoint: optional `python-pptx` — one slide per code with segments; mark optional/phase 2.
4. Frontend: export menu on report headers (CSV/PNG/Word/Excel) in reportKit.

**Tests:** openpyxl round-trip assertions. **Risk:** none.

\---

## 23\. Cloud collaboration (shared projects, web access, comments) — **L (10–20 pd, phased)**

**Current state:** the strongest existing piece — folder-sync collaboration
(`services/sync.py`, JSONL sidecars, LWW replay) + multi-instance presence. No accounts, no
comments, no hosted server, no web client.

**Honest assessment:** a full TeamCloud (hosted accounts, cloud sync, web app) is a product in
itself and cannot be "natively integrated" into a local desktop app without a hosted component.
Feasible native scope, in phases:

**Phase 1 — Comments (native, local, 3–5 pd):**

1. Table `comment(id, target\_kind \[source|coding|case|annotation|qtt\_item], target\_id, body, coder, created)`; CRUD endpoints (audit-recorded → **flows through the existing sync
automatically**, giving the collaboration model MAXQDA gets from TeamCloud: threaded comments
exchanged between machines).
2. Frontend: comment threads in the Inspector for the selected element; unread badge per coder.

**Phase 2 — Optional self-hosted relay (5–8 pd):**

1. uvicorn supports websockets already (uvicorn\[standard]); add `WS /sync/ws` to the existing
backend: push/pull of the same changes.jsonl batches — replaces the 60 s folder polling when a
relay URL is configured (`PUT /sync/settings` extension: `relay\_url`). Two peers behind the
same relay get near-realtime exchange without a vendor cloud.
2. Ship an optional `relay-server/` (tiny FastAPI app, \~150 lines) in the repo for self-hosters.

**Phase 3 — Accounts + hosted web access (out of desktop scope):** document as a separate product
(host the existing REST API; add auth + per-project ACLs). The backend is already a clean HTTP API
— the web client could reuse the frontend's non-Tauri code path.

**Tests:** comments sync round-trip (two project copies); relay integration test.
**Risk:** websocket + LWW conflict semantics — reuse existing replay logic unchanged.

\---

## 24\. Chat with memos — **S (1–2 pd)**

**Current state:** `POST /ai/chat` (modes + prompt\_id), `GET /memos` (all code + file memos).
**Plan:**

1. `ai.py`: new mode `memo\_analysis`; request gains optional `memo\_ids: \[int]` → `ai\_service`
fetches memos (title + body, labeled) and injects them into the system prompt/context
(token-truncate like the text\_analysis mode does).
2. `ai\_prompts.py`: add "Memo analysis" prompt (summarize group, find patterns/themes — mirrors
26.3 memo chat).
3. Frontend `AiChatPanel`: mode dropdown gains "Memos"; a multi-select list of memos (from
`GET /memos`, grouped code/file) with search.
**Tests:** service-level prompt assembly + truncation. **Risk:** none.

\---

## 25\. AI paraphrase — **S (1–2 pd)**

**Current state:** chat with `text\_analysis` mode exists; segment context menus exist in all coders.
**Plan:**

1. `ai\_prompts.py`: "Paraphrase in the researcher's own words (keep meaning, drop quotes)" prompt.
2. Frontend: coder segment context menu + selection toolbar action "AI paraphrase" → calls
`POST /ai/chat {mode: text\_analysis, prompt\_id: paraphrase, message: <segment text>}` with a
loading state; result inserted into the segment memo (prefilled, user saves) — mirrors MAXQDA's
paraphrase+summary-table workflow.
**Tests:** minimal (prompt assembly). **Risk:** none.

\---

## 26\. AI sentiment — **S–M (1–3 pd)**

**Current state:** shares #9's report shape and #25's call pattern.
**Plan:**

1. Extend #9's sentiment report with an "AI mode" execution path: batch segments through
`ai\_service` with the sentiment prompt; store/display alongside lexicon scores; optional
persistence per coding (same column as #9).
2. Survey-workflow parity (MAXQDA surveys): apply to survey-imported text sources
(`#1` survey importer) — one report = sentiment distribution per open question.
**Tests:** service-level with mocked provider. **Risk:** token cost on large corpora — batch limit.

\---

## Summary \& suggested roadmap

|Priority|Feature|Effort|Depends on|
|-|-|-|-|
|**Quick wins (S)**|Value labels (11)|1–2 pd|—|
||Chat with memos (24)|1–2 pd|—|
||AI paraphrase (25)|1–2 pd|—|
||Drag \& drop coding (4)|2–3 pd|—|
||Dictionary autocode (6)|2–3 pd|—|
||Document Portrait (14)|2–3 pd|—|
||Summary Tables (16)|2–3 pd|coding memos ✓|
||AI sentiment (26)|1–3 pd|#9|
||Dictionary content analysis (13)|3–4 pd|#6|
||XLSX + SPSS import (1)|3–5 pd|openpyxl/pyreadstat|
|**Core parity (M)**|Document Comparison Chart (15)|3–4 pd|—|
||Sentiment (lexicon) (9)|2–4 pd|vaderSentiment|
||Segment links (10)|3–5 pd|commit-edit re-anchoring|
||Manual transcription (7)|3–5 pd|AvCoder ✓|
||Web page capture (2)|4–6 pd|Tauri WebviewWindow|
||Statistical analysis (8)|5–8 pd|#12 shares|
||Mixed methods quantify (12)|3–5 pd|#8|
||Creative coding (5)|4–6 pd|—|
||MS Office export (22)|3–5 pd|#1, #17|
|**Phased / large (L)**|Smart Publisher (17)|6–10 pd|python-docx|
||QTT + Mixed Methods QTT + Send-to-QTT (18–20)|6–12 pd|#17 (chart PNGs)|
||NVivo/ATLAS.ti/Transana (21)|8–15 pd|importers pattern|
||Social scraping (3)|5–10 pd|yt-dlp/trafilatura; IG/X/TikTok = export-import only|
||Cloud collaboration (23)|10–20 pd|sync.py ✓; hosted phase = separate product|

**Suggested build order (4 sprints):**

1. **Sprint 1 (quick parity):** 11, 24, 25, 4, 6, 14, 16, 26 — small wins, no new deps except
vaderSentiment.
2. **Sprint 2 (data \& media):** 1, 7, 9, 2, 10 — importer + transcription + links.
3. **Sprint 3 (analysis):** 8+12, 13, 15, 5, 22 — statistics + visualizations + exports.
4. **Sprint 4 (workspaces \& interop):** 17, 18–20, 21, 3 — publishing, QTT, legacy imports.
5. **Continuous/optional:** 23 phase 1 (comments) anytime; phase 2 relay after sync is stable.

**Cross-cutting rules for every feature:** new write endpoints must `audit.record()` (keeps sync
working); new tables go through the existing migration chain; new deps must be pure-Python or
wheel-verified under PyInstaller (`compile.ps1`); frontend additions register views/slots per
`DESIGN.md`; backend verified with `pytest + ruff + mypy`, frontend with `tsc + eslint + vitest + playwright`.

