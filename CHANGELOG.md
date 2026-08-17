## v0.2.2 (2026-08-17)

## What's Changed in v0.2.2

### Features
- [feature-scope] audit hardening + server-side search/summary, undoable predicate, redo markers (be53481)

---
**Full changelog**: https://github.com/MicRaving/qualcodernext/compare/v0.2.1...v0.2.2

---
## v0.2.1 (2026-08-17)

## What's Changed in v0.2.1

### Features
- [feature-scope] complete modularity audit implementation + micropass (55265b1)

### Other Changes
- docs: refine documentation hub READMEs and workspace/shell guide (fe4df78)
- Refactor persistence layer into per-entity repos, modularize importers/audit-undo, add api lib + new stores, update frontend & docs (7e47bb3)
- UI consistency sweep (Phase B): collapse ad-hoc toolbar clusters to the toolbarBtn size, add shadow elevation tokens, standardize status pills (55c6138)
- Graphs function bar contained to the center view (no longer spans the sidebars); DESIGN.md function-bar rule updated; image-coding e2e hardened with integer drag coordinates (e8b4c9f)
- Add full changelog vs upstream QualCoder (high-level summary + detailed area-by-area list) (b7df1c4)
- Settings: R + About pinned to the very bottom (About last); rebuild compiled artifacts; repo cleanup: drop unused design-tokens.json, planning docs and caches (48d0bde)
- Rebuild compiled artifacts (sub-span marks, settings headlines, no-window R probe) (593a299)
- CSV table: only the marked text is highlighted (sub-span marks via per-cell raw map) - no more whole-cell tint; settings back to headline sections (no tabs), maintenance keeps only the compact-on-close switch; R version probe + R jobs run without flashing a cmd window (CREATE_NO_WINDOW); e2e: integer drag coords + sub-span assertions (862e052)
- Rebuild compiled artifacts (CSV table coding, settings tabs, review fixes) (a1ef585)
- CSV table coding (cell selection -> shared toolbar, code badges, details bars, unmark/undo), settings tabs (General/AI/Updates/Maintenance with Auto-update label + interval beside toggle + compact project/index maintenance), review fixes: graph node PATCH 404 URLs, undo restore keeps weight/avid, api.undoCodings body shape, graph menu bar into orchestrator slot, shared localRequest client + Toggle/LoadError primitives, dead api methods removed, updates default True (backend) (a3075d7)
- Rebuild compiled artifacts (CSV table view, settings consistency) (ef7163f)
- CSV columns detected: CsvCoder table view (RFC-4180 parser, TSV auto-detect, Table/Plain-text toggles, sticky header, coded plain-text side) + routing; Settings consistency: compact inline LLM/index status indicators (no layout shift), GitHub settings removed, auto-update ON by default, AI settings hidden + model polling gated when AI disabled, duplicate export hint removed; urlImportMode test updated for the Reddit purge (848e62a)
- Rebuild compiled artifacts (youtube csv revert, reddit purge, bug report fixes) (74a78be)
- YouTube comments back to a single 4-column CSV file (structured per-comment import reverted), Reddit purged (backend mode, OAuth code, settings, UI option, tests; reddit URLs route to article), bug report: robust never-blank capture + Tauri opener plugin (system browser) + token-less primary flow + download-screenshot + copy, stray probe specs removed (b454f00)
- Rebuild compiled artifacts (reddit oauth, bug report feature) (d95634e)
- Reddit scraping rework (anonymous hardening with old.reddit fallback + Retry-After, optional OAuth app-only path via Settings credentials, actionable 403/429 messages), GitHub bug report feature (ribbon button, html2canvas screenshot, paint-over canvas with highlight/redact/undo, prefilled last action + last error + env block, labels/assignee/milestone, API submission with attachment upload + data-URI fallback, browser fallback URL ΓÇö probe-verified), AiSettingsRequest accepts reddit credentials (709b6de)
- Rebuild compiled artifacts (YouTube CSV, URL mode detect, PDF bottom-bar rework) (237c9a4)
- YouTube comments as real CSV columns (RFC-4180, note rows, .csv sources), URL mode auto-select (youtube/reddit hosts), PDF bottom-bar rework (click=view never creates; min-size guard, idempotent appends, read-only footer with inline errors) + backend 409 for duplicate text codings (b874838)
- Rebuild compiled artifacts (webpage coding, youtube notes, pdf locate, CORS/click fixes) (b7faccd)
- Remove stray debug spec (821560c)
- Webpage coding: select text on the rendered page to code it (view-model mapping, floating toolbar, active-code + picker), right-click forwarding into the app context menu (on codings/selections), highlights kept; YouTube 240s comments timeout + no silent caption fallback (explicit note rows); pdf-text-locate run-anchor fallback + actionable 422s; PDF segment-click fixed via CORS-on-500 + error-body parsing + resilient load/refresh (50 e2e passing) (a0fcf3c)
- Rebuild compiled artifacts (base-gate, pdf locate fallback, undo robustness, baked html marks, youtube fixes, session sort/shift-select) (a9b15c8)
- Stale API-base class fixed (App render gate + fetchSourceFile/fetchThumbnail helpers, all coders migrated), pdf-text-locate 4-level fallback with confidence, History undo robustness (no 500s on legacy rows, clear messages, 117-test matrix), HtmlCoder pre-computed marks baked into srcDoc + live re-mark, YouTube packaged-backend fixes (frozen-safe, per-call executor, comments never replaced by captions), session sort/filter memory + shift-click range selection in files (a87e569)
- Rebuild compiled artifacts (details polish, Crafter rename, PDF fetch fix, HtmlCoder) (fff58d0)
- HtmlCoder: remove Save-as-PDF button + dead state/imports/keys (live codings verified in real browser via probe: 2 marks rendered), e2e fixes for Crafter rename / new undo label / PDF overlay locator (49 passing) (56d356f)
- Remove stray vite log (cfd6ffe)
- Coder details polish (auto-show after assigning, weight buttons, date tooltip), PDF failed-to-fetch fix (await initApiBase + bounded retry), rename QTT to Crafter (UI labels + docs), AttributeEditor real button styling (8e52b50)
- Remove leftover probe script (d14bc01)
- Transcript cascade on media delete, YouTube comments-only output with corrected --write-comments flag, History undo gating inverted (backend-authoritative, 4 explicit exclusions), import destination preview, undo for every action family, HtmlCoder codings fix (8852065)
- Rebuild compiled artifacts (destination preview, undo-all, DnD fixes) (1ffa687)
- Import destination preview (per-format 'will create' summary), History undo for every action family (source import/delete/link/replace, autocode, transcribe/r cancel, bookmarks, speakers, pseudonyms, references, filters, SQL, coders, sync, dictionaries, code sets, R scripts, QTT, graphs), AvCoder auto-transcribe after transcript delete (job-aware mode + stale-commit guard), HtmlCoder live codings (whitespace/entity-safe matching, re-mark crash fix, robust script stripping + injection), YouTube comments 4-column contract, files drag&drop (Tauri dragDropEnabled=false restores WebView2 native drops + items fallback + document net), Sidebar pointer-drag arming fix (330d712)
- Rebuild compiled artifacts (maintenance + animations + pointer-drag) (c0b51c2)
- Project maintenance: checkpoint-on-close + Compact project (WAL flush, drop rebuildable indexes, VACUUM, recreate; maintenance settings + endpoint), non-intrusive animations (motion tokens consumed, button/input transitions, hover lift, modal/menu/toast animations, prefers-reduced-motion), Sidebar tree drag rewritten as pointer-based (replaces unreliable HTML5 DnD), e2e sync-button label update (49 passing) (d5c813f)
- Fix batch 4: AI Option A (additive per-mode context pickers, shared chat thread, mode labels + pipeline help, search layout aligned bottom, empty-prompt spacer, quick-action chips removed), sync button shows only last-sync time, History undo/redo for all action families (codes/categories/codings/sources/transcripts/cases/attributes/notes/links/comments/creative), survey import timeout + abort reconciliation, FileManager center DnD (WebView2 empty-types dragover fix + depth counter), AvCoder auto-transcribe after transcript delete (live-store derivation), HtmlCoder live coding highlights (script-stripped srcDoc + postMessage), YouTube comments as tab-separated columns (8832a77)
- AI chat mode separation assessment (docs/ai-chat-mode-assessment.md): keep memo/text/code separation with additive pickers + shared thread (Option A) (c56b405)
- Rebuild compiled artifacts (fix batch 3) (9cb2d24)
- Fix batch 3: AI search in mode dropdown + per-mode context pickers (codes/files/memos), sync time inside flyout button, code-tree DnD hardened (wrapper draggable, no setDragImage crash, container drop safety net, real e2e verification), import manager as overlay, mass-delete live refresh, default empty-transcript manual transcription (first-char auto timestamp, no toggle), offline HTML snapshots (inline CSS/images/fonts), URL Auto removed, YouTube subprocess isolation + 240s dialog timeout, e2e suite updated (49 passing) (9d4d18f)
- Rebuild compiled artifacts (fix batch 2) (c3e5463)
- Remove scratch reproduction script (repro-dnd.cjs) (c066aa3)
- Fix batch 2: AI chat overflow + per-mode context, local-provider model filtering + Gemini key-required message, flyout cleanup (tasks section removed, yellow sync-now, queue trashcans flush right + clamping), Sidebar DnD drop fix + human errors + promote/demote in context menu + files-leftbar drop, import manager overhaul (preview + force-format, ribbon to Settings), import-once bug fix, scrape PDF mode + YouTube abort guards + Reddit hardening, media format recognition (opus etc.), AV transcription auto-save, HtmlCoder charset-aware layout (e6ca3f1)
- Task queue flyout: window-height clamp + aligned fixed-width icon column (20d4606)
- Bugfix/UX batch: AI chat pinned composer + project context per mcp_permissions + models error detail, code tree drag&drop (hierarchy indicator, merge-on-drop, position conservation, promote/demote toolbar, context-menu cleanup, merge dropdown), import overlay for all formats + import-in-tasks + ribbon entry, sync auto-enable (shared-folder detection, 3s notice, per-project override), auto-load-project setting, task queue alignment, coder flyout refresh/collaboration rows, bars height pass, file drag&drop import, AV transcription (preset transcript, live timestamp, Tab segment, delete transcript), webpage PDF export + HTML split view, YouTube comments, Reddit 422 fixes, inline region coordinates (1255cb5)
- R integration phases 1+2: Rscript bridge (detection, background job engine with QC_PORT/QC_PROJECT/QC_EXCHANGE env contract, artifact serving), r_script storage (v30) + CRUD, /r/prepare-report (report data to CSV + R stub), R console analyze view (editor, templates, queue-integrated run, stdout/stderr, PNG/CSV outputs, saved scripts), Settings R status (dc916b1)
- R integration feasibility assessment (docs/r-integration-assessment.md): Rscript bridge recommended, CSV/SQLite-readonly/HTTP exchange methods, rpy2 excluded from packaged build, phase 1+2 scope; roadmap updated (7ced2d4)
- ATLAS.ti import assessment: REFI-QDA path documented as primary (already works), Mac XML export feasible as best-effort, .atlproj/.atlasti bundles not feasible (no public spec, no OSS parsers); Interchange help + docs + README + roadmap updated; verified open-source projects listed (b98ce21)
- Roadmap wave 4: comments (sync-propagated threads in Inspector), code weights 0-100 + in-vivo coding, memo types in Notes, NVivo .nvpx best-effort importer, code sets (sidebar manager + tree filter), e2e gap filling (49 passing), sync replay + OWNER_TABLES extended, History undo/redo refreshes open coders (512fd3f)
- Fix AI provider models (Gemini native /v1beta/models with x-goog-api-key, Claude x-api-key + anthropic-version), remove provider grey-out, interrater coefficient show/hide toggles, batch coding skips files with real transcripts (has_transcript), coder flyout exact-width clamp + open-above fallback, stylized promote/demote errors (63c09a0)
- CI/release fixes per owner notes: upload NSIS setup.exe only (no MSI), Linux builds flatpak-only, release workflow degrades to unsigned builds when TAURI_SIGNING_PRIVATE_KEY is absent, fix unused pid warning (lib.rs), macOS updater bundles renamed QCnext_darwin_* (ad3aca8)
- Compiled artifacts (development branch): backend onedir (PyInstaller, faster-whisper + roadmap deps), release qcnext.exe, QCnext 0.2.0 MSI/NSIS installers via git-lfs (76634c3)
- v0.2.0 build fixes: health/about version strings 0.2.0, PyInstaller spec hidden imports + data files for openpyxl/pyreadstat/pandas/vaderSentiment/yt-dlp/trafilatura/python-docx/python-pptx, e2e config (vite prewarm, reduced motion) (1ef4097)
- E2E suite updated to current UI (37/37 passing, new roadmap.spec coverage), README 0.2.0 changelog, full screen documentation in docs/ (18 files) (4ccd199)
- Roadmap wave 3: Smart Publisher (Word/Excel/PowerPoint report export), QTT workspace (qual + Creswell 14-step mixed-methods worksheets, send-to-QTT from coders), Transana .tprd import (defensive schema probe, media+transcript+keyword mapping) (274dc67)
- Roadmap wave 2: manual transcription mode (media keys, F9/Space, timestamp insert), sentiment report (VADER + AI), document comparison chart (LCS alignment), URL import (Reddit/YouTube/article/HTML capture), creative coding scratchpad with promote-to-code (4450ab5)
- Roadmap wave 1: XLSX/SPSS import (openpyxl+pyreadstat), AI memo chat/paraphrase/sentiment prompts, dictionary engine (CRUD, autocode, per-doc frequencies), attribute value labels, segment hyperlinks, stats suite (chi-square/Fisher-free MWU/Spearman, crosstabs, group compare, code-by-variable) + summary tables (32714f1)
- v0.2.0 alpha: code promote/demote (Word-list style), multi-coder interrater (N-rater Alpha + pairwise Kappa/AC1), coder flyout bounds + per-row delete + global task start/pause/clear, batch transcribe/autocode icons + eligible counts, batch-transcribe eligibility fix (av_text_id no longer gates), noScribe purge, PDF plain-text/PDF toggles with live-synced codings, Gemini models/probe fix, API key persistence, per-provider model filtering, greyed-out local providers, a11y large-text zoom + full black/white high contrast, bar height fixes, README roadmap (NVivo/ATLAS Maybe + open-source format research) (c6fdc53)
- Background task queue (batch transcribe/autocode, pause/clear/reorder/delete), a11y modes, PDF split view, sidebar drag-hide, Coding ribbon rename, per-provider AI models (35d072b)
- Identifier org.qcnext.desktop (avoid .app bundle conflict) (05d3a7e)
- Autocode prompt prefill verified; AI providers: LM Studio 127.0.0.1, per-provider models URLs (v1 fallbacks), Gemini Bearer auth per docs; about text + status version 0.1.0 (b398ac4)
- AI model polling (provider filters, dedupe, clear-on-switch, periodic), provider-aware status probe (Gemini x-goog-api-key), graph delete stale-grid fix, autocode prompt rework (AI-coded spans + prefilled prompt + fallback), rename to QCnext / version 0.1 (38c92d3)
- Graphs: fix double dialog (create/delete), dropdown cleanup; PDF text marking (shared plain-text codings, y-flip, re-render fix); autocode rework: multi-code + AI code suggestions, shared dialog for text/PDF/transcripts; settings: model polling per provider, service status button, HelpFlyout (698e948)
- PDF text marking (shared codings with plain-text mode), graph delete icon, Cases/Codes-used right-click jumps (ab92db3)
- Remove scratch playwright config (0129423)
- Add smoke e2e for reports menu bar, graphs-under-reports, journal ribbon (594b136)
- Reports menu-bar buttons, graphs under reports (center dropdown + models, import fix), segment goto highlight, Journal ribbon, inspector right-click to annotations/memos (c9ff59d)
- Add manual workflow_dispatch trigger to the release workflow (afeee80)

---
**Full changelog**: https://github.com/MicRaving/qualcodernext/compare/v0.1.1...v0.2.1

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


