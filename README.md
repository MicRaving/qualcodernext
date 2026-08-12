# QCnext - A Rework of Qualcoder

This is a rework of [QualCoder](https://github.com/ccbogel/QualCoder), the open-source qualitative data analysis (QDA) tool:



"Text files can be typed in manually or loaded from txt, odt, docx, html, htm, md, epub, rtf and PDF files. Images, video, and audio can also be imported for coding. Codes can be assigned to text, images, and a/v selections and grouped into categories in a hierarchical fashion. Various types of reports can be produced including visual coding graphs, coder comparisons, and coding frequencies. AI models like GPT-4 from OpenAI can be used to explore your data and analyze the results."



QualCoder is awesome but always felt to me like having some shortcomings. I therefore tried to rework the codebase with the following major goals:

* **Simplified UI**: This was the main point behind the rework. I used QualCoder a lot but was never able to convince my students and fellow researchers because the UI was always unintuitive with many functions hidden behind menus and requiring just one too many clicks. The rework tries to simplify and reorganize the UI as much as possible while retaining full functionality.
* **Simultaneous collaboration**: Nowadays, qualitative projects have grown substantially, heavily relying on many coders. While I understood the limitations of SQLite, I was never happy with not being able to work on projects simultaneously. In the rework, your just have to save the project in a shared folder, enable collaboration in the coder flyout on the top right and you're good to go. Projects sync every minute, just make sure you're not working as the same coder with multiple computers.
* **Reduce architectural debt**: QualCoder is organized in few monolithic Python scripts (2,000-8,000 lines of code each) that are hard to handle, partially redundant, and prone to bugs. I therefore tried to make the codebase more modular and sleaker, with all files <1,000 lines of code.
* **Increase responsiveness**: Qualcoder takes a long time to start (30-60s). I reduced the startup time to 2s.
* Reduce memory footprint: This is honestly not that much of a deal but QualCoder 3.8 uses 450mb RAM, while the rework clocks in at 200mb
* **Full compatibility**: All of these changes do not break compatibility with your existing projects.
* **(Future) Web apps**: With more and more people relying on tablets and smartphones, using offline apps becomes less practical. The rework did not fully implement a client-server structure and future iterations will always retain offline functionality, but it lays the groundwork for running QualCoder in a browser.

## Vision

Qualitative data analysis should stay in the hands of researchers — free,
local-first, and open. QualCoder v4 keeps the proven QualCoder data model (`.qda`
project folders, v14+ schema, REFI-QDA interoperability) while replacing the aging
desktop stack with:

* a **modern, fast, accessible UI** (React + Tauri 2),
* a **clean HTTP API** that future tools (R, Python, MCP agents) can talk to,
* **true collaboration** — raters working on their own copies of a project, joined
through ordinary folder-sync tools,
* **optional on-device AI** (chat, semantic search, an MCP server) that never
requires your data to leave the machine.

## Feature overview

**Coding \& media**

* Text coding with overlays, annotations, edit mode (diff-match-patch position
shifting), autocode (plain / regex / first / last / code-within-code), unmark/undo
* PDF coding: rendered pages, drag-rectangle regions, region editing, plain-text mode
* Image coding with zoomable canvas and editable rectangles
* Audio/video coding on a timeline with subtitle-synced transcripts
* Text + AV bookmarks, file/code memos

**Analysis model**

* Codes \& categories with sub-codes (upstream v16), colour-palette editor, merge, memo
* Cases with file/span links; attributes (file \& case scoped); journals; annotations
* Coders with per-rater attribution, visibility filtering, delete/reassign
* Audit log with undo/redo of changes (History view)

**Workspace \& UX**

* Ribbon navigation: Dashboard / Files / Cases / Notes / Reports / Graphs, with
History, AI and Settings panes on the right
* **Notes workspace** with three tabs — journal entries, annotations, memos — all
with inline rename (Tab moves the editor between rows), search and row actions
* **Inspector details pane** for codes and files: stats, codes used, case
assignment, annotations, memo editing
* Dashboard with recent projects and **auto-open of the last project** at startup
* **Settings without an open project** (appearance, language, AI, updates)

**Reports \& visualization**

* Code frequencies, codes-by-segments, comparison matrix, co-occurrence, exact
matches, file summary, coder comparison, interrater reliability (Cohen's κ,
Krippendorff's α, Gwet's AC1)
* Code summary, code segments (code-in-all-files), coders-by-file, code relations
* Word cloud, cumulative / stacked / heatmap charts, codebook export
* Ad-hoc read-only SQL console with saved queries; CSV export on every report

**Code maps**

* Graph/code-map editor (SVG canvas: pan/zoom, draggable nodes for codes, categories,
cases, files, free text, memos; relation lines with labels and arrow styles)
* Six analytical model generators: category hierarchy, file hierarchy, file
comparison, case hierarchy, case comparison, co-occurrence network

**Import / export / interchange**

* Sources: txt, odt, docx, rtf, html, epub, md, pdf, tex, images, audio, video;
external linking; text-file replacement with re-anchored codings
* REFI-QDA export/import (`.qdp`); RQDA, Taguette, RIS/Zotero (local API), survey CSV
(with qualitative columns), plain-text codebook; merge another `.qda` project
* Pseudonyms (with auto-generation), speaker detection \& marking in transcripts

**App updates**

* Automatic update checks against **GitHub Releases** (signed artifacts, static
JSON manifest `qualcoder-latest.json`)
* Settings: check interval (daily / weekly / never), "install automatically"
toggle, manual *Check now*
* Update status and download progress surface in the background-tasks flyout
(top bar) and in Settings; publishing is one tagged release via the
`release` workflow

**AI assistant (optional, local-first)**

* Chat with mode-specific prompt libraries (help, topic exploration, code analysis,
text analysis — 31 shipped prompts)
* Semantic search with a persistent per-project vector index (pure Python)
* MCP (Model Context Protocol) JSON-RPC endpoint with read/write permission gating

**Languages** — English (reference), German (full), plus 12 generated locales from
the upstream gettext files (es, fr, eo, eu, fa, ht, it, ja, pt, ro, sv, zh) with
English fallback.

## Changelog since 3.8.2

**4.0.0 — the rework** (in development)

The upstream 3.8.2 PyQt application was rewritten from scratch. The `.qda`
project format and the analysis model are preserved (with schema migrations up to
v19); everything around them is new:

*Architecture*

* New **FastAPI + SQLAlchemy (async) + SQLite** backend, packaged with PyInstaller
and embedded in a **Tauri 2** desktop shell (React 19 + TypeScript + Vite)
* All data access goes through a typed HTTP API (`backend/src/qualcoder\_api`),
opening the door for R/Python/MCP tooling
* Migration chain from legacy QualCoder databases (v14 → v19) with REFI-QDA
interchange retained

*Coding*

* Text/PDF/image/audio/video coders rebuilt in the browser: overlay rendering,
edit-mode position shifting, drag-rectangle regions, timeline segment coding
* Autocode, bookmarks, annotations, memos, unmark/undo — ported and reworked
* Inline renaming everywhere (codes, categories, files, journals, annotations)
with **Tab navigation between rows** and namespace-aware id handling for
legacy projects with category/code id collisions

*Workspace*

* Ribbon workspace with Dashboard (recent projects, auto-open), Files, Cases,
Notes (journal / annotations / memos tabs), Reports, Graphs, History, AI
* Inspector details pane, bulk file operations, per-view search and filters
* Settings available without an open project (theme, language, AI,
transcription, updates)

*Collaboration*

* **Sync** for raters on separate copies: row-level change capture, JSONL
sidecar exchange, replay with last-write-wins and PK remapping (v19 schema)

*AI*

* Optional local AI assistant: chat with 31 prompts, semantic search with a pure
Python vector index, MCP server with permission gating

*Quality \& engineering*

* 237 backend tests (pytest), 157 frontend unit tests (vitest), 22 Playwright
E2E scenarios against the real backend; ruff + mypy + eslint + tsc gates
* CI workflow (backend, frontend, E2E) and a release workflow that builds,
signs and publishes installers + update manifest to GitHub Releases
* **Automatic app updates** from GitHub Releases with signed artifacts

## Collaboration

Raters work as **different coders on separate copies of the same `.qda` project
folder**, shared through any folder-sync tool (Nextcloud, ownCloud, Sync\&Share,
Syncthing, Dropbox, ...). The SQLite database is **never merged by the sync tool**
— that corrupts projects. Instead:

1. Every mutation is captured into the project's `sync\_log` (v19 schema) with full
row snapshots.
2. Every 60 seconds (or via *Sync now*) the app appends your local changes to
`changes/<your-coder-name>/changes.jsonl` inside the project folder — the sync
tool carries those files.
3. Every 60 seconds the app imports your collaborators' sidecar files and replays
them: INSERT/UPDATE/DELETE by primary key, last-write-wins per row, natural-key
fallback for codings, and automatic PK remapping when autoincrement counters
collide between raters. Replay never re-exports (no ping-pong).
4. The toolbar sync chip shows pending changes and collaborators' last-sync times.

Rules of thumb: give every rater a **unique coder name**; do not sync per-machine
artifacts (`project\_in\_use.lock`, `ai\_index.sqlite3`, `backups/` — sync state lives
in `\~/.qualcoder/sync/`).

## Installation

All releases are available on: [https://github.com/MicRaving/qualcodernext/releases](https://github.com/MicRaving/qualcodernext/releases)

* Windows: Download the portable version and unpack it or install the installer from
* Linux: Install the flatpack (untested)
* MacOS: Install the .dmg (untested)
* Compilation: Clone the repo and run compile.ps1 (Windows) to build the portable folder and installer. Scripts for Linux and MacOS will follow.

## License

QualCoder is distributed under the GNU LGPL-3.0 (see the upstream project). The
rework follows the same licensing intent; the upstream reference checkout carries
its own license text in `upstreamQualcoder/`.



## Future

Here is a non-exhaustive list of planned features

* Fully implement client-server architecture
* Implement more use cases for LLMs
* Further refine the UI
* Bugs: You tell me

