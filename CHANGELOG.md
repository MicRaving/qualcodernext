# QCnext — Changelog vs. upstream QualCoder

Baseline: [ccbogel/QualCoder](https://github.com/ccbogel/QualCoder) (`master`, snapshot of 10.08.2026, QualCoder 4.0 lineage — PyQt6 desktop app).
QCnext is a complete rework of that codebase, keeping full compatibility with existing `.qda` projects.

---


### Major changes

1. **Complete rewrite on a modern stack.** The monolithic PyQt6 desktop app was replaced by a
   **FastAPI + SQLAlchemy (async) + SQLite backend**, a **React 19 + TypeScript + Vite frontend**
   and a **Tauri 2 desktop shell**. All data access goes through a typed HTTP API. Benefits:
   startup time dropped from ~30 s to ~2 s, memory footprint from ~450 MB to ~200 MB, and the
   backend is now usable from R, Python or any MCP tooling.

2. **Simplified three-column UI.** The menu-heavy interface was replaced by a ribbon plus a
   three-column layout (left bar / center view / right bar / status bar), defined by a single
   layout orchestrator (`WorkspaceLayout`) and a written design language (`DESIGN.md`). Every
   element is renameable inline — no more popup dialogs for the most common actions.

3. **Simultaneous collaboration.** Raters work on separate copies of the same project in a
   shared folder; every mutation is captured to a change log and synced/replayed every 60 s
   (last-write-wins per row, natural-key fallback, automatic PK remapping when autoincrement
   counters collide). A sync chip in the toolbar shows pending changes and collaborators'
   last-sync times.

4. **Extended AI assistant.** Chat with per-mode context pickers (codes/files/memos), semantic
   search over a local embedding index, AI code suggestions in the autocode dialog, AI
   sentiment/memo/paraphrase prompts, a prompt library, and a built-in MCP server. Providers:
   Ollama, LM Studio, opencode-go, Google Gemini, OpenAI GPT, Anthropic Claude and any
   OpenAI-compatible endpoint, with per-provider model polling and a live service probe.

5. **New analysis surface.** A statistics suite (code × attribute crosstabs with chi-square,
   Mann–Whitney U group comparisons, Spearman, mixed-methods matrices), multi-coder interrater
   reliability (Fleiss' Kappa, pairwise Cohen's Kappa and Krippendorff-style AC1), MAXDictio-style
   **dictionary autocode** with term-frequency reports, **sentiment** reports (VADER or AI),
   **document comparison** charts (LCS alignment), **summary tables** and a **Smart Publisher**
   that exports reports to Word/Excel/PowerPoint.

6. **New importers and exporters.** REFI-QDA interchange (import + export), best-effort
   **NVivo (.nvpx)** and **Transana (.tprd)** import, **XLSX/SPSS (.sav)** survey import,
   Zotero/RIS references, and **URL import/scraping**: YouTube comment threads (as a 4-column
   CSV), articles and raw HTML/PDF capture.

7. **Productivity.** Full project history with **undo/redo for every action family** (experimental), a
   background **task queue** (batch transcription/autocode with pause/reorder/clear), inline
   rename (no more pesky popups), drag & drop in files and code tree, and a dashboard start screen.

8. **New workspaces.** A **Crafter workspace** to create questions-themes-theories
   worksheets incl. a Creswell 14-step mixed-methods template, **creative coding** scratchpad
   with promote-to-code, a graph editor with models, an **R console**, SQL reports, and a notes
   workspace (journal / annotations / memos with memo types).

## Minor changes

- **Coder details:** code weights (0–100) with steppers, "important" flags, segment flash
  highlights, bookmarks, hidden-code dimming, per-segment detail bars, in-vivo coding,
  unmark/undo stacks, "auto-show segment details" preference.
- **PDF/HTML/CSV coders:** plain-text/rendered split views with live-synced codings, offline
  HTML snapshots, a real CSV table view (RFC-4180/TSV, sticky header, cell-level coding with
  badges and sub-span marks), 4-level text-location fallback, robust segment clicking.
- **Audio/video:** manual transcription mode (media keys, F9/Space, timestamp insert),
  preset transcripts, automatic transcription (faster-whisper), speaker assignment, transcript
  cascade on media delete.
- **Files view:** filters, mass-delete/-transcribe/-autocode, bad-link repair, media format recognition.
- **Code tree:** pointer-based drag & drop, merge, subcodes, code sets (sidebar manager + tree filter), namespace-aware depth cap.
- **Settings:** auto-update, compact-on-close maintenance, pseudonyms, initial R integration (not really useful right now).
- Accessibility options for screenreaders and color-blindness (experimental - please give me feedback!)
- **Backend hygiene:** audit log for everything, maintenance compaction (WAL checkpoint +
  VACUUM + index rebuild), settings stored machine-level, 409s for duplicate codings, no
  console-window popups from subprocesses on Windows.

---

## 2. Full changelog

### 2.1 Platform & architecture

- Complete rewrite of the upstream monolithic Python/PyQt6 codebase:
  - Backend: **FastAPI + SQLAlchemy (async) + SQLite** in `backend/` (modular
    `api/v1` routers, `services/`, `persistence/` repositories — every file < 1,000 lines).
  - Frontend: **React 19 + TypeScript + Vite** in `frontend/` (zustand stores, feature
    modules, no CSS framework — a hand-rolled design-token system).
  - Shell: **Tauri 2** (`frontend/src-tauri`), packaged backend via PyInstaller **onedir**
    (no startup extraction) + embedded `qualcoder-backend.exe`.
- All data access goes through a **typed HTTP API** (`frontend/src/lib/api.ts` ↔
  `backend/src/qualcoder_api/api/v1/`) — the foundation for R/Python/MCP tooling.
- **Full project compatibility**: existing `.qda` SQLite projects open unchanged
  (versioned migration chain, `about`-marker validation, legacy schema upgrades).
- Startup reduced from ~30 s to ~2 s; RAM ~450 MB → ~200 MB.
- Port discovery protocol: the packaged shell writes `%TEMP%\qualcoder-port-<pid>.json`,
  the webview resolves the backend base URL dynamically and re-resolves on restarts
  (stale-base class fixed; `initApiBase` + `fetchSourceFile` helpers, all coders migrated).
- Single shared local fetch client (`localRequest`) replacing ~7 copy-pasted clients.
- Identifier `org.qcnext.desktop` (avoids macOS `.app` bundle conflicts).

### 2.2 UI & shell

- **Workspace layout orchestrator** (`WorkspaceLayout`): ribbon / menu bar / left bar /
  center / right bar / status bar slots; views fill slots, never build their own bars.
- **Design orchestrator** (`components/ui/orchestrator.tsx`) + `DESIGN.md` design language:
  button variants, icon sizes, typography, table styles, popups, modals, toasts.
- **Dashboard** start screen: project creation, recent projects, quick stats.
- Ribbon navigation (Dashboard / Files / Coding / Cases / Notes / Crafter / Reports / Graphs),
  right-pane toggles (Inspector / AI / History / Creative / Settings), bug-report button.
- **Coder switcher** flyout (switch/add/delete/rename coders, per-coder stats, collaboration
  rows, sync-now, last-sync time).
- **Background task queue** flyout: batch transcribe/autocode with eligible counts,
  pause/clear/reorder/delete, progress bars, window-height clamping.
- **Inline rename** for every project element (codes, categories, files, cases, notes…).
- **Full project history** (audit log): undo/redo for all action families (codes,
  categories, codings, sources, transcripts, cases, attributes, notes, links, comments,
  creative, autocode, transcription, bookmarks, speakers, pseudonyms, references, filters,
  SQL, coders, sync, dictionaries, code sets, R scripts, QTT, graphs, compaction).
- **Accessibility modes**: reduced motion, large-text zoom, full black/white high contrast,
  screen-reader focus rings; non-intrusive animation tokens (hover lift, transitions)
  honouring `prefers-reduced-motion`.
- **Settings pane** (right bar): appearance/theme, language (15 locales), auto-load project,
  auto-show segment details, a11y controls, Import/Export, pseudonyms, AI configuration
  (provider/model/base URL/API key/MCP permissions + live service status), app updates
  (auto-update toggle + check interval + check-now/install), maintenance (compact on close,
  semantic index build/rebuild/purge), R status, About — R above About, pinned to the bottom.
- **Bug report feature**: ribbon button, html2canvas screenshot with paint-over
  highlight/redact/undo, prefilled last action + last error + environment block,
  GitHub issue submission (attachment upload + data-URI fallback + browser fallback URL),
  download-screenshot + copy, token-less primary flow, system-browser opener plugin.
- **Auto-updater** (Tauri): configurable check cadence (daily/weekly/never), auto-update
  on by default, download progress, install — signed bundles when a key is present,
  unsigned builds otherwise.

### 2.3 Coders

- **Text coder**: selection toolbar (code / annotate / in-vivo / copy+paste segment link /
  send to Crafter), code picker modal with search + create, active-code quick coding,
  floating annotation and in-vivo popovers, edit mode with live shifted highlights,
  bookmark + go-to-bookmark, autocode dialog (multi-code + AI-suggested codes, shared for
  text/PDF/transcripts), segment weights with steppers, "important" star, hidden-code
  dimming, segment detail bars, unmark/undo stack, flash highlight from the inspector,
  keyboard-only flows (Ctrl+S in edit mode, Escape handling, capture-phase popover Escape).
- **PDF coder**: rendered canvas + plain-text split view with **live-synced codings**,
  text marking on the rendered page (y-flip corrected, re-render fix), 4-level
  text-location fallback with confidence, bottom bar rework (click = view, never creates;
  min-size guard, idempotent appends, read-only footer with inline errors), resilient
  load/refresh (CORS-on-500 + error-body parsing).
- **HTML/webpage coder**: rendered-page coding (view-model mapping, floating toolbar,
  right-click forwarding into the app context menu), offline HTML snapshots (inline
  CSS/images/fonts), live coding highlights (script-stripped srcDoc + postMessage,
  whitespace/entity-safe matching), charset-aware layout, PDF export removed in favour of
  the snapshot.
- **CSV table coder** (`.csv`/`.tsv`): real table view with sticky header (RFC-4180 parser
  with quoted fields/escaped quotes/embedded newlines, TSV auto-detection), Table / Plain
  text toggles, **cell-level coding**: text selection inside a cell maps onto the source
  text via per-cell raw offsets (shared SelectionToolbar), coded sub-spans are highlighted
  (only the marked characters — never the whole cell) with code badges, annotation dashed
  underlines, shared details bars, unmark/undo.
- **Image coder**: rectangular regions with inline coordinates.
- **AV coder**: timeline + waveform, transcript panel, **manual transcription mode**
  (media keys, F9/Space, timestamp insert, first-char auto timestamp), **preset
  transcripts**, automatic transcription (faster-whisper) with batch queue, speaker
  assignment, transcript cascade on media delete, auto-transcribe after transcript delete.

### 2.4 Coding model & code tree

- Hierarchical categories + subcodes, **namespace-aware tree with depth cap** (survives
  category/code id collisions in imported projects).
- **Pointer-based drag & drop** for the tree (replacements for unreliable HTML5 DnD):
  hierarchy indicator, merge-on-drop, position conservation, container drop safety net.
- Promote/demote (word-list style), merge, move, inline rename, context menus.
- **Code sets** (MAXQDA-style named subsets): sidebar manager, tree filter, CRUD.
- **Segment hyperlinks / linked quotes**: copy link payload, paste-link-here, wavy-underline
  markers, jump-to-span events between files.
- Code weights (0–100), in-vivo coding, hidden codes, bookmark per file.
- Code color palette + custom color-scheme support.

### 2.5 Collaboration & sync

- **Change-log sidecars over folder-sync tools** (Nextcloud, Syncthing, Dropbox, …):
  every mutation captured into `sync_log` (v19 schema) with full row snapshots; exported to
  `changes/<coder>/changes.jsonl`; imported + replayed every 60 s (or *Sync now*).
- Replay rules: INSERT/UPDATE/DELETE by primary key, last-write-wins per row,
  natural-key fallback for codings, automatic PK remapping on autoincrement collisions,
  replay never re-exports (no ping-pong).
- Sync auto-enable on shared-folder detection (3 s notice, per-project override),
  sync chip with pending-change counts + collaborators' last-sync times.
- Multi-coder: per-coder delete with reassignment, coder statistics, hidden-coder views.

### 2.6 AI assistant

- **Chat** with additive per-mode context pickers (codes/files/memos), shared thread,
  mode labels + pipeline help, pinned composer, `mcp_permissions`-gated context.
- **Semantic search** over a local embedding index (multilingual e5), index build/rebuild/
  purge in Settings → Maintenance, status inline (no layout shift).
- **AI autocode**: AI-suggested codes + multi-code autocode, prefilled prompts, batch jobs.
- **Prompt library** + AI memo chat/paraphrase/sentiment prompts.
- **MCP server** (tools exposed to the model) with read/write/full permission levels.
- **Providers**: Ollama, LM Studio, opencode-go, Gemini (x-goog-api-key / native
  `/v1beta/models`), GPT, Claude (x-api-key + anthropic-version), custom
  OpenAI-compatible; per-provider model URLs with v1 fallbacks; **model polling**
  (provider-filtered, deduped, cleared on provider switch, 60 s); live service probe
  (checking/ok/broken); key-required warnings; AI settings hidden + polling gated when
  the assistant is disabled.

### 2.7 Analysis & reports

- Code frequencies, code segments, file × code, code relations, coder comparison.
- **Interrater reliability**: N-rater Krippendorff Alpha, pairwise Cohen's Kappa and
  AC1, coefficient show/hide toggles.
- **Statistics suite**: code × attribute crosstabs (chi-square), group comparisons
  (Mann–Whitney U, Spearman), mixed-methods matrices, code-by-variable.
- **Dictionary report** (MAXDictio-style): term frequencies, per-document counts.
- **Summary tables** (document × code grid with coding memos).
- **Sentiment report** (VADER lexicon or AI) per mode/scope.
- **Document comparison** chart (LCS alignment).
- Exact matches, file summary, word frequencies, text corpus, codebook, references
  (Zotero/RIS), SQL reports (editor, saved queries).
- **Graphs**: code-map editor (SVG canvas) with drag/move/labels/font/bold, lines,
  models (graph generation), graph menu bar in the orchestrator slot, delete stale-grid
  fixes, node PATCH URL fixes.
- **Smart Publisher**: Word/Excel/PowerPoint export of report data.
- All reports exportable as CSV/PNG; R console integration (see 2.8).

### 2.8 R integration

- Rscript detection (PATH, R_HOME, standard install dirs) — probes run with
  `CREATE_NO_WINDOW` (no console popups on Windows).
- Background **R job engine**: `QC_PORT`/`QC_PROJECT`/`QC_EXCHANGE` env contract,
  script persistence, stdout/stderr tails, cancellation, artifact serving.
- `r_scripts` storage + CRUD, `/r/prepare-report` (report data to CSV + R stub).
- **R console** in the Analysis area: editor with templates, queue-integrated run,
  stdout/stderr, PNG/CSV outputs, saved scripts.
- Settings R status section.

### 2.9 Import / export / scraping

- **REFI-QDA** interchange import + export (with destination preview: per-format
  "will create" summary).
- **NVivo `.nvpx`** best-effort importer.
- **Transana `.tprd`** import (defensive schema probe, media + transcript + keyword
  mapping).
- **XLSX / SPSS `.sav`** survey import (openpyxl + pyreadstat), forced-format routes,
  survey import timeout + abort reconciliation.
- Zotero/RIS references, merge import.
- **URL import**: YouTube comment threads as a single 4-column CSV (author, likes,
  date, comment — RFC-4180 quoted, note rows when comments are unavailable; yt-dlp
  subprocess isolation with abort retry + 240 s timeout; captions never silently
  substituted), articles (trafilatura), raw HTML capture + PDF mode. Reddit scraping
  was added then **purged** (reddit URLs now route to article mode).
- File manager: drag & drop import (WebView2 native drops), import-in-tasks, import
  overlay manager with preview + force-format, mass-delete with live refresh,
  filters, shift-click range selection, session sort/filter memory, bad-link repair.

### 2.10 Workspaces

- **Notes**: journal / annotations / memos with memo types (MAXQDA-style icons),
  inline editing, Inspector right-click jumps to annotations/memos.
- **Cases** + attributes (types, value labels, code-by-variable).
- **Crafter (QTT)**: qual + Creswell 14-step mixed-methods worksheets, send-to-QTT from
  the coders, live sheet/item refresh.
- **Creative coding** scratchpad with promote-to-code.
- **Graphs** editor + models (see 2.7).
- **Inspector**: code/file/case details, recent segments with goto-highlight,
  comments (sync-propagated threads), memos, attribute grid.

### 2.11 Productivity & reliability

- Audit-log-based **undo/redo for every action family** (backend-authoritative, explicit
  exclusion list), history view with per-action filters.
- Background **task queue** with batch transcribe/autocode, pause/reorder/delete.
- Inline rename everywhere; no window.prompt/toast for renames.
- Project maintenance: checkpoint-on-close, **Compact project** (WAL flush, drop
  rebuildable indexes, VACUUM, recreate) via a raw autocommit connection, audit-recorded,
  compact-on-close setting + last-compact timestamp.
- Base-URL re-resolution, stale-response guards (model fetches, inspector selects,
  edits), CORS-safe 500 error bodies, duplicate-coding 409s, "never blank" error capture.
- **Testing**: 883 backend tests (pytest), 319 frontend unit tests (vitest), 50 e2e
  tests (Playwright, single worker) covering all major flows; CI + release workflows
  (Windows NSIS/MSI, Linux flatpak, macOS dmg; uploads only the NSIS setup.exe).

### 2.12 Packaging & distribution

- `compile.ps1` full release build: PyInstaller onedir → `src-tauri/resources/backend`
  → Tauri 2 build (portable `qcnext.exe`, NSIS setup, MSI).
- Cross-platform release matrix, platform icon set, portable spec, macOS updater
  bundles renamed `QCnext_darwin_*`.
- Release workflow degrades to unsigned builds when `TAURI_SIGNING_PRIVATE_KEY` is
  absent; manual `workflow_dispatch` trigger.
- Updater artifacts (`.sig`, `qualcoder-latest.json`) generated per build.
