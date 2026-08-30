<!-- Release notes: the Release workflow publishes the `## vX.Y.Z` section of
     this file (from that heading to the next `## ` heading) as the GitHub
     release body for tag vX.Y.Z, appending auto-generated commit notes.
     Add a section like "## 0.3.0 (2026-09-01)" at the TOP of the file. -->

## 0.3.0 (2026-08-30)

Collaboration transition hardening — fixes the offline → online handoff that left the second rater with an empty project.

### Fixed

- **Collaboration transition could leave the second computer empty.** After `Enable online collaboration` on coder 1's offline project, coder 2 joining from a second machine rebuilt its local sandbox from the sidecar snapshot. On slow/shared folders (OneDrive, Syncthing, SMB) the snapshot could be absent, truncated or not yet flushed when the marker became visible, or the rebuild could otherwise conclude empty (conflicts/skipped rows). The opener now: (a) polls briefly for the sidecar to appear, (b) verifies the rebuilt sandbox is non-empty by probing `source`/`code_name` counts vs the cold `data.qda` archive and falls back to the archive when empty, (c) retries a busy WAL checkpoint before copying, and (d) rolls back the activation if the sidecar append was deferred (locked). The marker and sidecar writes are now `fsync`'d (file + directory, POSIX) so the second rater sees them immediately.
- **Activation durability.** `activate_collaboration` now only publishes the `.qcnext-project` marker after the full-state sidecar is durably on disk (verified non-empty), with a short retry for a deferred/locked sidecar.

**Full Changelog**: https://github.com/MicRaving/qualcodernext/compare/v0.2.1...v0.3.0

## 0.2.1 (2026-08-26)

Critical collaboration fix — everyone working in shared projects should
update.

### Fixed

- **New collaborators saw a completely empty project.** Opening an online
  project for the first time could race its activation: the marker that
  tells other machines "rebuild from the sync log" was written before the
  sync-log snapshot itself was complete. Activation now publishes the full
  snapshot first and writes the marker last, and if a rebuild still comes
  up empty, the new sandbox falls back to the project archive instead of
  staying blank.
- Hardened earlier collaboration fixes (coder registry on add/switch,
  change-sequence numbering, activation mode resolution) are included in
  this build; mixed 0.1.1/0.2.x sessions now behave correctly.

**Full Changelog**: https://github.com/MicRaving/qualcodernext/compare/v0.2.0...v0.2.1

## 0.2.0 (2026-08-25)

Collaboration hardening release — the multi-rater flow was verified with a
scripted **live two-instance test** (separate profiles and sandboxes sharing
one project folder), which surfaced and fixed three real sync bugs.

### Collaboration

- Fixed: adding a second coder could never activate collaboration on a fresh
  project (coder registry mismatch between settings and project database).
- Fixed: peers silently dropped every change exported after the activation
  snapshot (sequence-space collision between snapshot and incremental
  exports) — new data now reaches the other instance reliably.
- Fixed: a concurrent activation by the other instance left the UI stuck in
  single-coder mode; activation now resolves the real mode from the backend.
- Fixed: adding a coder right after a refused activation attempt silently
  skipped collaboration start; the follow-up attempt re-enables sync.
- Live-test coverage: offline→online conversion, second rater joining with
  their own coder, bidirectional data+coding rounds, convergence counts,
  live presence, sidecar integrity, zero conflicts.

### General

- Fixed: the displayed app version now follows the released version
  (previously every installer showed v0.1.0).
- Fixed: the built-in updater pointed at a wrong repository and always
  reported "Could not fetch a valid release JSON".
- Crafter left bar aligned with other views: search box plus inline
  rename/delete per worksheet.
- Fixed touchpad edge-swipes panning the whole interface past its border.
- Fixed a terminal window flashing when closing the app (Windows).

### Packaging & CI

- Releases now ship Windows setup, macOS dmg (Intel + Apple Silicon) with
  signed updater archives, and a Linux flatpak — cut automatically from
  CHANGELOG.md via the Release workflow.

## 0.1.1 (2026-08-25)

First tagged release of the reworked pipeline. Ships Windows (NSIS setup),
macOS (dmg + updater archives, Intel and Apple Silicon) and Linux (flatpak).

- CI: fully automated release flow — Run workflow cuts the tag, builds all
  platforms, signs updater artifacts (when TAURI_SIGNING_PRIVATE_KEY is set)
  and publishes this changelog section as the release body.
- Backend: fixed two concurrency races — project create/open/close are now
  serialized (a concurrent close could corrupt recent-projects with an empty
  path), and settings.json writes are locked + atomic (recent projects could
  vanish mid-session).
- E2E suite made deterministic on slow CI runners; full suite green.

## Summary
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
   counters collide). A sync chip in the toolbar shows pending changes, collaborators' presence,
   and last-sync times.

4. **Extended AI assistant.** Chat with per-mode context pickers (codes/files/memos), chat session
   history (with inline rename/delete), template library (Reconstructive SRP, Theme Generation),
   editable per-mode personas, customizable templates (built-in, app-wide "save globally" and
   project-scoped) and system wrapping prompts, **agentic chat** where the assistant calls the
   project's MCP tools to read and (with permission + approval) write codes/categories/codings/
   cases/attributes, semantic search integrated directly into the unified search flyout, AI code
   suggestions in the autocode dialog, AI sentiment/memo/paraphrase prompts, a prompt library, and
   a built-in MCP server. Providers: Ollama, LM Studio, opencode-go, Google Gemini, OpenAI GPT,
   Anthropic Claude and any OpenAI-compatible endpoint, with per-provider model polling and a live
   service probe.

5. **New analysis surface.** A statistics suite (code × attribute crosstabs with chi-square,
   Mann–Whitney U group comparisons, Spearman, mixed-methods matrices), multi-coder interrater
   reliability (Fleiss' Kappa, pairwise Cohen's Kappa and Krippendorff-style AC1 with coefficient
   toggles), MAXDictio-style **dictionary autocode** with term-frequency reports, **sentiment**
   reports (VADER or AI), **document comparison** charts (LCS alignment), **summary tables**
   and a **Smart Publisher** that exports reports to Word/Excel/PowerPoint.

6. **New importers and exporters.** REFI-QDA interchange (import + export with destination preview),
   ATLAS.ti compatibility, best-effort **NVivo (.nvpx)** and **Transana (.tprd)** import,
   **XLSX/SPSS (.sav)** survey import, Zotero/RIS references, and **URL import/scraping**:
   YouTube comment threads (as a 4-column CSV), articles and raw HTML/PDF capture.

7. **Productivity.** Unified **multi-entity search** flyout (exact regex + semantic), full project
   history with **undo/redo for every action family** (experimental), a background **task queue**
   (batch transcription/autocode with pause/reorder/clear), inline rename (no more pesky popups),
   drag & drop in files and code tree, and a dashboard start screen.

8. **New workspaces.** An in-app **Help** browser (guide docs + Ask AI toggle), a **Crafter
   workspace** to create questions-themes-theories worksheets incl. a Creswell 14-step
   mixed-methods template, **creative coding** scratchpad with promote-to-code, a graph editor
   with models, an **R console**, SQL reports, and a notes workspace (journal / annotations /
   memos with memo types).

### Minor changes

- **Memo gutter:** Word-style sidebar for viewing/editing memo cards aligned to coded segments.
  Toggle via "Memos" button in each coder's header. Cards stack at shared anchors with "+N more"
  overflow chip. When hidden, selecting a segment opens a floating bubble. Supports memo + weight
  editing, important flags, and delete. Integrated into TextCoder, HtmlCoder, AvCoder, PdfCoder.
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
- **Search & help:** unified ribbon search flyout (exact regex + semantic vector search) across all entities; in-app Help pane with Docs / Ask AI mode toggle.
- **AI sidebar:** categorized prompt templates, session history management with inline rename/delete, user-editable wrapping prompt with reset-to-default, LM Studio defaults, 15 s timeout protection.
- **Settings:** auto-update, compact-on-close maintenance, pseudonyms, initial R integration, top-bar bug reporting.
- **Accessibility options:** screenreaders, high contrast, reduced motion, and color-blindness accommodations.
- **Backend hygiene:** audit log for all mutations, maintenance compaction (WAL checkpoint +
  VACUUM + index rebuild), settings stored machine-level, duplicate-coding guards, no
  console-window popups from subprocesses on Windows.

---

## Full changelog

(This changelog was generated automatically based on the files changes.)

### Refactoring, centralization & bug-fix pass (2026-08-21)

Frontend — coder shared reality:

- New shared module set `features/coding/shared/`: `events.ts`
  (`useCodingsChanged` / `useAssignCode`), `useEscapeStack`, `useSplitResize`,
  `useUndoStack`, `useSegmentActions`, `useGutterRows`, `toolbarAnchor`,
  `WeightStepper`. All six coders (Text/Csv/Image/Html/Pdf/Av) migrated onto
  them; the duplicated PATCH-row fetch clones in HtmlCoder/PdfCoder and the
  hand-rolled undo stacks in Text/CsvCoder were deleted.
- **Recoverable deletes everywhere**: every coder now confirms AND pushes
  deleted codings onto an undo stack ("Unmark last" button in the header) —
  previously Html/Pdf/Av/Image deletes were unrecoverable.
- Layered Escape dismissal in all coders (popovers → drag/pending → details);
  AvCoder transcript popovers are now reachable by Escape at all.
- Graceful load degradation adopted; multi-pick coding races fixed
  (sequential creates + single refresh); silent memo-PATCH failure in the
  selection toolbar fixed (`res.ok` is now checked); image-coder media retry
  budget resets on file change; stale playback position no longer used when
  assigning codes from the sidebar.
- `hiddenCodes` now honored on HTML webpage marks and CSV table
  highlights/badges; CsvCoder forwards code-tree updates from its embedded
  TextCoder; TextCoder gutter gained the missing important-toggle.
- Details bubble fix: host click-away handlers no longer kill interactions
  inside the bubble (`data-gutter` exclusion).
- Missing `coder.memosToggle` locale key added (rendered raw before).

Frontend — reports & API surface:

- Four copied fetch clients (interrater/doc-compare/sentiment/publish)
  replaced by the shared `localRequest`/`localRequestBlob` primitives;
  duplicate CSV button removed; `reportKit` localized (Loading/Retry/CSV/
  No data keys); `EmptyData` adopted.

Frontend — stores & shell:

- `closeProject` now resets ALL project-scoped state (per-view UI bags,
  hidden codes, graph canvas data, right pane) — nothing leaks into the next
  project; background-task dispatcher re-queues failed starts (bounded
  retries) instead of leaving jobs "running" forever.

Backend:

- `api/v1/deps.py`: new `require_open_project` dependency replacing 27
  hand-written 409 guards across 12 route files (polling endpoints keep
  their deliberate `{ok:false}` contract).
- `sync_engine.py` split into `sync_schema/state/sidecar/replay/conflicts/
  status` behind a stable facade; late-bound health/sidecar hooks preserved.
- Sync race fixes: conflict resolution serialized under `SYNC_LOCK`;
  per-user `MAX(seq)+1` inserts retry inside a savepoint; natural-key replay
  matches NULL columns with `IS NULL` (no more cross-coder segment latching);
  transcript companion creation is atomic (no orphan companions on crash).
- Silent exception swallowing in sync row reads replaced with debug logging.

Known issues (pre-existing at commit 89c449e, left for the collaboration-
redesign owner): e2e specs `app.spec.ts:146`, `features.spec.ts:260`,
`sync.spec.ts:47/72/90` assert the pre-redesign sync flyout switch and
recent-projects behavior and need re-spec'ing against the new UX.

### Platform & architecture

- Complete rewrite of the upstream monolithic Python/PyQt6 codebase:
  - Backend: **FastAPI + SQLAlchemy (async) + SQLite** in `backend/` (modular
    `api/v1` routers, `services/`, `persistence/` per-entity repositories — every file < 1,000 lines).
  - Frontend: **React 19 + TypeScript + Vite** in `frontend/` (zustand stores, feature
    modules, no CSS framework — a hand-rolled design-token system). Cleaned up dead store
    re-exports to safeguard production builds.
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
- Single shared local fetch client (`localRequest`) replacing duplicate clients across features.
- Complete modularity audit and codebase micropass across persistence, services, and stores.
- Identifier `org.qcnext.desktop` (avoids macOS `.app` bundle conflicts).

### UI & shell

- **Workspace layout orchestrator** (`WorkspaceLayout`): ribbon / menu bar / left bar /
  center / right bar / status bar slots; views fill slots, never build their own bars.
- **Design orchestrator** (`components/ui/orchestrator.tsx`) + `DESIGN.md` design language:
  button variants, icon sizes, typography, table styles, popups, modals, toasts, toolbar cluster
  collapsing (`toolbarBtn` size), shadow elevation tokens, and standard status pills.
- **Dashboard** start screen: project creation, recent projects, quick stats.
- **Ribbon navigation**: Dashboard / Files / Coding / Cases / Notes / Crafter / Reports / Graphs.
- **Right-pane toggles**: Inspector / AI / History / Creative / Help / Settings.
- **Multi-entity search flyout**: ribbon search box searches **files, codes, categories,
  cases, journal, memos, attributes and comments** at once, with an **Exact** (regex-native)
  and **Semantic** mode (AI backend + optional vector index with inline build/delete indicator).
  Search results render in an anchored flyout with yellow substring highlight matching and
  per-hit offset navigation.
- **In-app help pane** (right bar): renders `docs/*.md` guides in markdown with a **Docs / Ask AI**
  toggle, full-text search (regex-native), scrollbar confined to the content area, and direct
  bug-report integration.
- **Coder switcher** flyout: switch/add/delete/rename coders, per-coder stats, collaboration
  presence indicators, sync-now, last-sync time.
- **Background task queue** flyout: batch transcribe/autocode with eligible counts,
  pause/clear/reorder/delete, progress bars, window-height clamping.
- **Inline rename** for every project element (codes, categories, files, cases, notes…).
- **Accessibility modes**: reduced motion, large-text zoom, full black/white high contrast,
  screen-reader focus rings; non-intrusive animation tokens (hover lift, transitions)
  honouring `prefers-reduced-motion`.
- **Settings pane** (right bar): appearance/theme, language (15 locales), auto-load project,
  auto-show segment details, a11y controls, Import/Export, pseudonyms, AI configuration
  (provider/model/base URL/API key/MCP permissions, live service probe, per-provider model
  polling, LM Studio defaults, 15 s timeouts), app updates (auto-update toggle + check interval +
  check-now/install), maintenance (compact on close, semantic index build/rebuild/purge),
  R status, About; bug-report button pinned to Settings top bar.
- **Bug report feature**: ribbon and pane button, html2canvas screenshot with paint-over
  highlight/redact/undo, prefilled last action + last error + environment block,
  GitHub issue submission (attachment upload + data-URI fallback + browser fallback URL),
  download-screenshot + copy, token-less primary flow, system-browser opener plugin.
- **Auto-updater** (Tauri): configurable check cadence (daily/weekly/never), auto-update
  on by default, download progress, install — signed bundles when a key is present,
  unsigned builds otherwise.

### Coders

- **Text coder**: selection toolbar (code / annotate / in-vivo / copy+paste segment link /
  send to Crafter), code picker modal with search + create, active-code quick coding,
  floating annotation and in-vivo popovers, edit mode with live shifted highlights,
  bookmark + go-to-bookmark, autocode dialog (multi-code + AI-suggested codes, shared for
  text/PDF/transcripts), segment weights with steppers, "important" star, hidden-code
  dimming, segment detail bars, unmark/undo stack, flash highlight from the inspector,
  keyboard-only flows (Ctrl+S in edit mode, Escape handling, capture-phase popover Escape).
- **PDF coder**: rendered canvas + plain-text split view with **live-synced codings**,
  text marking on the rendered page, 4-level text-location fallback with confidence,
  bottom bar with segment views, read-only footer with inline status, resilient load/refresh.
- **HTML/webpage coder**: rendered-page coding (view-model mapping, floating toolbar,
  right-click forwarding into the app context menu), offline HTML snapshots (inline
  CSS/images/fonts), live coding highlights (script-stripped srcDoc + postMessage,
  whitespace/entity-safe matching), charset-aware layout.
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

### Coding model & code tree

- Hierarchical categories + subcodes, **namespace-aware tree with depth cap** (survives
  category/code id collisions in imported projects).
- **Pointer-based drag & drop** for the tree: hierarchy indicator, merge-on-drop, position
  conservation, container drop safety net.
- Promote/demote (word-list style), merge, move, inline rename, context menus.
- **Code sets** (MAXQDA-style named subsets): sidebar manager, tree filter, CRUD.
- **Segment hyperlinks / linked quotes**: copy link payload, paste-link-here, wavy-underline
  markers, jump-to-span events between files.
- Code weights (0–100), in-vivo coding, hidden codes, bookmark per file.
- Code color palette + custom color-scheme support.

### Collaboration & sync

- **Change-log sidecars over folder-sync tools** (Nextcloud, Syncthing, Dropbox, …):
  every mutation captured into `sync_log` (v19 schema) with full row snapshots; exported to
  `changes/<coder>/changes.jsonl`; imported + replayed every 60 s (or *Sync now*).
- Replay rules: INSERT/UPDATE/DELETE by primary key, last-write-wins per row,
  natural-key fallback for codings, automatic PK remapping on autoincrement collisions,
  replay never re-exports (no ping-pong).
- Sync auto-enable on shared-folder detection (3 s notice, per-project override),
  sync chip with pending-change counts + collaborators' presence indicators and last-sync times.
- Multi-coder: per-coder delete with reassignment, coder statistics, hidden-coder views.
- **Golden Master + local sandbox collaboration mode** (`.qcnext-project` marker):
  single-coder projects keep opening `data.qda` directly; with a second coder and sync on,
  collaboration activates and the live database moves to a local sandbox
  (`~/.qualcoder/projects/<uuid>/sandbox.sqlite`), leaving `data.qda` in the shared folder as a
  cold, rollback-journal archive refreshed on close (and on demand). Activation copies the
  current DB into the sandbox and exports a full-state snapshot to the sidecar; a lost/corrupt
  sandbox is rebuilt from the sidecars. Reverting consolidates back to `data.qda` and removes
  the marker, sandbox and sidecars. New API: `GET/POST /projects/mode`,
  `/projects/activate-collaboration`, `/projects/revert-collaboration`, `/projects/consolidate`.
  Full-state export/rebuild supports composite-PK tables (e.g. `code_set_member`).

### AI assistant

- **Chat** with additive per-mode context pickers (codes/files/memos), shared thread,
  mode labels + pipeline help, pinned composer, `mcp_permissions`-gated context.
- **AI sidebar**:
  - Instruction templates grouped into **Analysis / Specialized / My templates**,
    with built-in templates **Reconstructive SRP** (Lieder/Schäffer, 2024) and
    **Theme Generation** (Friese, 2024).
  - **Chat history**: accessible via an hourglass icon with **inline rename and
    delete** per session, persisted directly in the project database.
  - **User-editable wrapping prompt** (system-level directive) appended to every
    chat turn (default asks for short and concise output), exposed in the template
    editor with a reset-to-default option.
- **Semantic search**: integrated directly into the unified ribbon search flyout
  (Exact/Semantic toggle) powered by a local embedding index (multilingual e5);
  includes inline index build/delete indicators and maintenance controls in
  Settings → Maintenance.
- **AI autocode**: AI-suggested codes + multi-code autocode, prefilled prompts, batch jobs.
- **Prompt library** + AI memo chat/paraphrase/sentiment prompts.
- **MCP server** (tools exposed to the model) with read/write/full permission levels.
- **MCP tools in the AI sidebar**: a collapsible "Tools & permissions" panel lists every
  read/write tool the assistant can call and hosts the access-level selector (read-only /
  read+write / full access); the AI settings tab no longer shows permissions or the manual
  service-status row. A **service indicator** next to the AI header auto-probes the provider
  while AI is enabled; the settings tab shows the API key **only for online providers**, and
  the "Enable AI assistant" toggle was renamed to "Enable". When the assistant is off, the
  sidebar banner is clickable and jumps to AI settings.
- **Providers & connectivity**: Ollama, LM Studio, opencode-go, Gemini (`x-goog-api-key` / native
  `/v1beta/models`), GPT, Claude (`x-api-key` + `anthropic-version`), custom
  OpenAI-compatible; per-provider model URLs with v1 fallbacks; **model polling**
  (provider-filtered, deduped, cleared on provider switch, 60 s); live service probe
  (checking/ok/broken); key-required warnings; snappy 15 s timeouts; AI settings
  hidden + polling gated when the assistant is disabled.

### Analysis & reports

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
  models (graph generation), graph menu bar in the orchestrator slot.
- **Smart Publisher**: Word/Excel/PowerPoint export of report data.
- All reports exportable as CSV/PNG; R console integration.

### R integration

- Rscript detection (PATH, R_HOME, standard install dirs) — probes run with
  `CREATE_NO_WINDOW` (no console popups on Windows).
- Background **R job engine**: `QC_PORT`/`QC_PROJECT`/`QC_EXCHANGE` env contract,
  script persistence, stdout/stderr tails, cancellation, artifact serving.
- `r_scripts` storage + CRUD, `/r/prepare-report` (report data to CSV + R stub).
- **R console** in the Analysis area: editor with templates, queue-integrated run,
  stdout/stderr, PNG/CSV outputs, saved scripts.
- Settings R status section.

### Import / export / scraping

- **REFI-QDA** interchange import + export (with destination preview: per-format
  "will create" summary).
- **ATLAS.ti compatibility**: REFI-QDA import/export fully supported; Mac XML best-effort import.
- **NVivo `.nvpx`** best-effort importer.
- **Transana `.tprd`** import (defensive schema probe, media + transcript + keyword
  mapping).
- **XLSX / SPSS `.sav`** survey import (openpyxl + pyreadstat), forced-format routes,
  survey import timeout + abort reconciliation.
- Zotero/RIS references, merge import.
- **URL import**: YouTube comment threads as a single 4-column CSV (author, likes,
  date, comment — RFC-4180 quoted, note rows when comments are unavailable; yt-dlp
  subprocess isolation with abort retry + 240 s timeout; captions never silently
  substituted), articles (trafilatura), raw HTML capture + PDF mode.
- File manager: drag & drop import (WebView2 native drops), import-in-tasks, import
  overlay manager with preview + force-format, mass-delete with live refresh,
  filters, shift-click range selection, session sort/filter memory, bad-link repair.

### Workspaces

- **In-app Help**: `docs/*.md` guide browser with Docs / Ask AI switcher, full-text
  search, and direct issue reporting.
- **Notes**: journal / annotations / memos with memo types (MAXQDA-style icons),
  inline editing, Inspector right-click jumps to annotations/memos.
- **Cases** + attributes (types, value labels, code-by-variable).
- **Crafter (QTT)**: qual + Creswell 14-step mixed-methods worksheets, send-to-QTT from
  the coders, live sheet/item refresh.
- **Creative coding** scratchpad with promote-to-code.
- **Graphs** editor + models.
- **Inspector**: code/file/case details, recent segments with goto-highlight,
  comments (sync-propagated threads), memos, attribute grid.

### Productivity & reliability

- Audit-log-based **undo/redo for every action family** (backend-authoritative, explicit
  exclusion list), history view with per-action filters and server-side search/summary.
- **Multi-entity unified search**: instant regex and semantic search flyout across all data entities.
- **Agentic AI chat**: the sidebar assistant can call the project's MCP tools mid-conversation —
  read the code tree/sources/cases to ground answers and (with MCP write permission) create/rename/delete
  codes, categories, codings, cases and attribute values. Executed tools appear as *Tools used* lines
  under the answer (read-only calls carry no approval tag); a **Confirm writes** toggle pauses before
  any change for Approve/Reject; every write is audit-logged. Backends without tool support fall back
  to plain chat automatically. The sidebar also exposes the MCP access toggle (read / read+write / full),
  the same setting as in Settings.
- **Editable AI personas + templates**: the template editor now has a **Personas** tab where the
  system prompt of every chat mode can be edited (saved for all projects, Reset to default restores
  the shipped text) plus the wrapping prompt. The **Templates** tab lists the built-in instruction
  templates alongside app-wide and project templates: built-ins are edited via an app-wide override
  ("Reset to default" restores the shipped text), new **app templates** are stored in the user settings
  and available in every project, and project templates can be copied to the app store with
  "Save globally".
- **Chat readability + data control**: assistant replies are rendered as **Markdown** (headings,
  lists, tables, code, bold/italic). The context selector above the composer gains an **All** toggle
  (on by default) that exposes every memos/code/file at once, and the whole selector can be
  **collapsed/expanded** via the arrow in its `Mode:` header.
- **Search + help polish**: the search flyout is wider and centered in the window; a bare `*` in
  search or help now acts as a wildcard (`LM*` = "LM" + anything) while `\*` stays a literal
  asterisk; help search results highlight the matched span like the flyout; the Instructions
  dropdown in the AI pane is wider (minimal gap to the "AI" heading); "Import from URL" moved to the
  files leftbar as a **URL** button next to **Import**; clicking a coded segment (text/PDF/image/AV)
  now also shows the code's details in the right-bar Inspector.
- **Search/help hit color + clearing**: search and help highlights now use the app's orange accent
  at ~30% transparency (`bg-accent/30`, was plain browser-yellow — the old `color-mix` arbitrary
  class never compiled). The search flyout no longer has a "Search sources" header bar; the query
  stays in the ribbon input, which gains an **X** (`search.clear`) to clear it. The help Browse
  search box gains the same **X** to clear its query.
- Background **task queue** with batch transcribe/autocode, pause/reorder/delete.
- Inline rename everywhere.
- Project maintenance: checkpoint-on-close, **Compact project** (WAL flush, drop
  rebuildable indexes, VACUUM, recreate) via a raw autocommit connection, audit-recorded,
  compact-on-close setting + last-compact timestamp.
- Base-URL dynamic resolution, request guards, 409 duplicate coding status codes,
  and robust error capture.
- **Testing & quality**: 994 backend tests (pytest), 336 frontend unit tests (vitest), 53 e2e
  tests (Playwright, single worker, 12 specs incl. sync + tasks/a11y + coverage-wave) covering all
  major flows; CI + release workflows (Windows NSIS/MSI, Linux flatpak, macOS dmg; uploads only
  the NSIS setup.exe).

### Packaging & distribution

- `release.ps1` single pipeline: `release.ps1` (full release) or `release.ps1 -Compile`
  (build only) — PyInstaller onedir → `src-tauri/resources/backend` → Tauri 2 build
  (portable `qcnext.exe`, NSIS setup, MSI) + update manifest.
- Cross-platform release matrix, platform icon set, portable spec, macOS updater
  bundles named `QCnext_darwin_*`.
- Release workflow degrades to unsigned builds when `TAURI_SIGNING_PRIVATE_KEY` is
  absent; manual `workflow_dispatch` trigger.
- Updater artifacts (`.sig`, `qcnext-latest.json`) generated per build; GitHub releases
  carry the generated artifacts (portable `qcnext.exe`, NSIS `setup.exe` + signature, update manifest).