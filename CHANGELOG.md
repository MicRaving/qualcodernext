<!-- Release notes: the Release workflow publishes the `## vX.Y.Z` section of
     this file (from that heading to the next `## ` heading) as the GitHub
     release body for tag vX.Y.Z, appending auto-generated commit notes.
     Keep the section SHORT — one-line bullets ("Improved animations.") that
     briefly describe the changes. The detail lives behind the **Full
     Changelog** compare link below the bullets, which every section must
     include (first releases have no base tag, so no link). Add a section
     like "## 0.1.1 (2026-08-31)" at the TOP of the file. -->

## 0.2.1 (2026-10-15)

- Faster startup: numpy and Pillow now load only when a meta-analysis or figure actually runs, and the app's feature views load on demand instead of at launch.
- Security: raised urllib3 and PyJWT past their published advisories and refreshed the backend and frontend dependency sets (no known npm advisories).

**Full Changelog**: https://github.com/MicRaving/qualcodernext/compare/v0.2.0...v0.2.1

## 0.2.0 (2026-10-12)

- New Meta-analysis workspace: search-hit table with abstract screening, paper download and data extraction, each optionally automated with the AI backend.
- Screening verdicts per criterion/coder with certainty and rationale; configurable inclusion criteria.
- Paper retrieval via OpenAlex, Unpaywall, Crossref landing pages, local Zotero reuse and manual PDF assignment.
- Scheme-driven extraction with metafor-completeness validation, optional publish to cases/codes and CSV/Excel export.
- Streamlined Meta layout: abstract screening in the center, per-tab actions in the menubar and study left bar, batch PDF import, multi-select autocoding and an in-app PDF viewer.
- Reworked coding-scheme editor with group, type and editor selectors and a dropdown-option list editor.
- Meta-analysis: editor-creatable screening criteria (verdict/classify/number, pass values, exclusion reasons, gating) with stage, filters, progress and blind screening.
- Meta-analysis: editor-creatable extraction schema — typed fields, multiselect/object-list/key-value editors, repeatable contrast metrics and role-based effect sizes, plus a scheme-driven edit form.
- Meta-analysis: multi-coder reliability (Gwet AC1/AC2) with conflict resolution for screening and extraction.
- Meta-analysis: pooled random-effects analysis (heterogeneity, subgroup/moderator, Egger, leave-one-out, forest), PRISMA counts, level summaries and Markdown/DOCX reports.
- Meta-analysis: Bayesian random-effects pooling with Bayes factors and prior sensitivity, plus PET-PEESE, trim-and-fill and p-curve publication-bias diagnostics.
- Meta-analysis: PRISMA and forest figures, and a PowerPoint (PPTX) report export.
- Meta-analysis: specification multiverse (spec table + spec curve), funnel and posterior figures, and an extraction-variable audit.
- Meta-analysis bugfixes: scheme prompts are now actually sent to the AI; full-text screening no longer overwrites abstract verdicts; per-scheme extractions no longer overwrite; analysis model/domain/family filters work; agreement, PRISMA, summary and moderator screens render reliably.
- Meta-analysis controls: CSV export, hit deletion and pagination, job pause/resume, keyboard screening, import search-run suggestions and extraction input controls.
- Meta-analysis: the Analyze menubar now holds the frequentist/Bayes switch and estimator, Analyze no longer picks a scheme, and every coded variable is available as a moderator (with a per-field "use as moderator" toggle in the scheme editor).
- Meta-analysis: a ready-to-open sample project with import files, criteria, scheme, screening, extractions and PDFs under `samples/meta/`.
- Meta-analysis: quick coding — `Y`/`N`/`U` (and `Tab`/`Shift+Tab`) for screening, level-number/`Enter`/`Tab` entry for extraction fields.
- Meta-analysis: the Extract tab is a three-pane workspace (study list, coding form, linked paper in the right bar) with the schema editor in the menubar; conflict settling is now an Agreement tab.
- Meta-analysis: analyses now combine all coders into a consensus (unresolved conflicts excluded and counted); the Analyze left bar has no coder picker.
- Meta-analysis: the Extraction tab shows full-text exclusion criteria per project criterion with reasons; the Screening left bar has no Agreement shortcut.
- Meta-analysis: the Extract tab now uses the Coding split view (scheme form left, canvas PDF right); the full-text panel is collapsed and never auto-fills; progress matches the To-screen/Screened filters; the menubar Agreement shortcuts are gone.
- Meta-analysis: import a CodingStudio project folder (hits, abstract + full-text screening, scheme, extractions and PDFs), idempotently.
- Meta-analysis: paper retrieval tries every open-access candidate (repository mirrors first, Europe PMC) and reports why a download failed; the Download tab shows a downloaded/failed indicator.
- Meta-analysis: CodingStudio import covers the current v3.1 schema — new roles, module fields as moderators, controlled vocabularies, per-coder full-text and the workbook base rater.
- Meta-analysis: CodingStudio import keys accession-less workbook rows as `row-N` (matching the reference) so their screening rows import, reports unmatched PDFs, and caps the error list.
- Meta-analysis: multi-label study fields (intervention types, countries, publication types) are now usable as subgroup/moderator variables, exploded per label.
- Meta-analysis: the PDF viewer renders crisp on HiDPI displays and lazily (no re-render on scroll, no per-page text extraction), fixing blurry/slow rendering.
- Meta-analysis: large analyses run off the request loop with a 120 s client budget, so the app stays responsive and no longer reports "Backend unreachable"; analysis loading is much faster (extracted rows only, per-scheme codebook reuse, off-loop JSON decode).
- Meta-analysis: the right side bar now resizes up to two-thirds of the window; the CodingStudio import button reads "CS-Import".
- Meta-analysis: Screening records abstract verdicts while full-text exclusion moved to an Extraction dropdown; blind screening moved to the menubar.
- Meta-analysis: moderators are picked from collapsible per-group checklists; the report preview renders markdown; the Analyze left bar explains each section.
- Meta-analysis: the Agreement left bar uses one row of switches; the Extract menubar exports Excel only.
- Fixed the Crafter (QTT) left bar spilling over the window; it now scrolls internally like the other left bars.
- Meta-analysis: moderator interactions (`A * B`) plus a multi-term moderator builder; the Analyze menubar holds the model switch, estimator and subgroup selector; aligned tables and left bar, select-all on Screen, and progress on Download/Extract.
- Meta-analysis: the linked paper now uses the app's themed PDF viewer and opens in the right bar from both Download and Extract.
- Meta-analysis: coding follows the app's current coder; the Extract left bar no longer carries coder/scheme pickers (the scheme moved to the menubar), and the Agreement tab sits between Extract and Analyze.
- Meta-analysis: the PRISMA diagram's "other methods" title no longer overflows its box.

**Full Changelog**: https://github.com/MicRaving/qualcodernext/compare/v0.1.17...v0.2.0

## 0.1.17 (2026-09-07)

- Backend updates install again: the app shell permits its own commands.
- Nightly patches are only offered on their own base; everyone else gets the full update.
- Patched screens appear immediately, without an app restart.
- Reduced installer and app size.
- Added OLED dark mode.
- Many bugfixes and coherence improvements.

**Full Changelog**: https://github.com/MicRaving/qualcodernext/compare/v0.1.0...v0.1.17

## 0.1.0 (2026-08-25)

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
