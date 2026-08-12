# QualCoder v4 — the rework

A modern reimplementation of [QualCoder](https://github.com/ccbogel/QualCoder), the
open-source qualitative data analysis (QDA) tool, rebuilt as a **FastAPI backend +
React/Tauri desktop frontend**. Same `.qda` project format, same workflows — a
faster, web-native, collaborative future.

> The upstream PyQt application is kept as a reference checkout under
> `upstreamQualcoder/`; this repository is the actively developed rework.

## Vision

Qualitative data analysis should stay in the hands of researchers — free,
local-first, and open. QualCoder v4 keeps the proven QualCoder data model (`.qda`
project folders, v14+ schema, REFI-QDA interoperability) while replacing the aging
desktop stack with:

- a **modern, fast, accessible UI** (React + Tauri 2),
- a **clean HTTP API** that future tools (R, Python, MCP agents) can talk to,
- **true collaboration** — raters working on their own copies of a project, joined
  through ordinary folder-sync tools,
- **optional on-device AI** (chat, semantic search, an MCP server) that never
  requires your data to leave the machine.

## Feature overview

**Coding & media**

- Text coding with overlays, annotations, edit mode (diff-match-patch position
  shifting), autocode (plain / regex / first / last / code-within-code), unmark/undo
- PDF coding: rendered pages, drag-rectangle regions, region editing, plain-text mode
- Image coding with zoomable canvas and editable rectangles
- Audio/video coding on a timeline with subtitle-synced transcripts
- Text + AV bookmarks, file/code memos

**Analysis model**

- Codes & categories with sub-codes (upstream v16), colour-palette editor, merge, memo
- Cases with file/span links; attributes (file & case scoped); journals; annotations
- Coders with per-rater attribution, visibility filtering, delete/reassign
- Audit log with undo/redo of changes (History view)

**Workspace & UX**

- Ribbon navigation: Dashboard / Files / Cases / Notes / Reports / Graphs, with
  History, AI and Settings panes on the right
- **Notes workspace** with three tabs — journal entries, annotations, memos — all
  with inline rename (Tab moves the editor between rows), search and row actions
- **Inspector details pane** for codes and files: stats, codes used, case
  assignment, annotations, memo editing
- Dashboard with recent projects and **auto-open of the last project** at startup
- **Settings without an open project** (appearance, language, AI, updates)

**Reports & visualization**

- Code frequencies, codes-by-segments, comparison matrix, co-occurrence, exact
  matches, file summary, coder comparison, interrater reliability (Cohen's κ,
  Krippendorff's α, Gwet's AC1)
- Code summary, code segments (code-in-all-files), coders-by-file, code relations
- Word cloud, cumulative / stacked / heatmap charts, codebook export
- Ad-hoc read-only SQL console with saved queries; CSV export on every report

**Code maps**

- Graph/code-map editor (SVG canvas: pan/zoom, draggable nodes for codes, categories,
  cases, files, free text, memos; relation lines with labels and arrow styles)
- Six analytical model generators: category hierarchy, file hierarchy, file
  comparison, case hierarchy, case comparison, co-occurrence network

**Import / export / interchange**

- Sources: txt, odt, docx, rtf, html, epub, md, pdf, tex, images, audio, video;
  external linking; text-file replacement with re-anchored codings
- REFI-QDA export/import (`.qdp`); RQDA, Taguette, RIS/Zotero (local API), survey CSV
  (with qualitative columns), plain-text codebook; merge another `.qda` project
- Pseudonyms (with auto-generation), speaker detection & marking in transcripts

**App updates**

- Automatic update checks against **GitHub Releases** (signed artifacts, static
  JSON manifest `qualcoder-latest.json`)
- Settings: check interval (daily / weekly / never), "install automatically"
  toggle, manual *Check now*
- Update status and download progress surface in the background-tasks flyout
  (top bar) and in Settings; publishing is one tagged release via the
  `release` workflow

**AI assistant (optional, local-first)**

- Chat with mode-specific prompt libraries (help, topic exploration, code analysis,
  text analysis — 31 shipped prompts)
- Semantic search with a persistent per-project vector index (pure Python)
- MCP (Model Context Protocol) JSON-RPC endpoint with read/write permission gating

**Languages** — English (reference), German (full), plus 12 generated locales from
the upstream gettext files (es, fr, eo, eu, fa, ht, it, ja, pt, ro, sv, zh) with
English fallback.

## Changelog since 3.8.2

**4.0.0 — the rework** (in development)

The upstream 3.8.2 PyQt application was rewritten from scratch. The `.qda`
project format and the analysis model are preserved (with schema migrations up to
v19); everything around them is new:

*Architecture*

- New **FastAPI + SQLAlchemy (async) + SQLite** backend, packaged with PyInstaller
  and embedded in a **Tauri 2** desktop shell (React 19 + TypeScript + Vite)
- All data access goes through a typed HTTP API (`backend/src/qualcoder_api`),
  opening the door for R/Python/MCP tooling
- Migration chain from legacy QualCoder databases (v14 → v19) with REFI-QDA
  interchange retained

*Coding*

- Text/PDF/image/audio/video coders rebuilt in the browser: overlay rendering,
  edit-mode position shifting, drag-rectangle regions, timeline segment coding
- Autocode, bookmarks, annotations, memos, unmark/undo — ported and reworked
- Inline renaming everywhere (codes, categories, files, journals, annotations)
  with **Tab navigation between rows** and namespace-aware id handling for
  legacy projects with category/code id collisions

*Workspace*

- Ribbon workspace with Dashboard (recent projects, auto-open), Files, Cases,
  Notes (journal / annotations / memos tabs), Reports, Graphs, History, AI
- Inspector details pane, bulk file operations, per-view search and filters
- Settings available without an open project (theme, language, AI,
  transcription, updates)

*Collaboration*

- **Sync** for raters on separate copies: row-level change capture, JSONL
  sidecar exchange, replay with last-write-wins and PK remapping (v19 schema)

*AI*

- Optional local AI assistant: chat with 31 prompts, semantic search with a pure
  Python vector index, MCP server with permission gating

*Quality & engineering*

- 237 backend tests (pytest), 157 frontend unit tests (vitest), 22 Playwright
  E2E scenarios against the real backend; ruff + mypy + eslint + tsc gates
- CI workflow (backend, frontend, E2E) and a release workflow that builds,
  signs and publishes installers + update manifest to GitHub Releases
- **Automatic app updates** from GitHub Releases with signed artifacts

## Collaboration

Raters work as **different coders on separate copies of the same `.qda` project
folder**, shared through any folder-sync tool (Nextcloud, ownCloud, Sync&Share,
Syncthing, Dropbox, ...). The SQLite database is **never merged by the sync tool**
— that corrupts projects. Instead:

1. Every mutation is captured into the project's `sync_log` (v19 schema) with full
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
artifacts (`project_in_use.lock`, `ai_index.sqlite3`, `backups/` — sync state lives
in `~/.qualcoder/sync/`).

> Direct LAN "server mode" is a possible future addition; the API is already fully
> HTTP-shaped for it.

## Repository layout

```
.github/workflows/ci.yml     GitHub Actions: backend tests+lint, frontend tests+lint+build, Playwright E2E
.github/workflows/release.yml  tag push (v*) → build, sign, publish release + update manifest
backend/                     FastAPI + SQLAlchemy async + Alembic (package: qualcoder_api)
  src/qualcoder_api/         api/v1 endpoints · persistence (schema, migrations, repositories)
                             services/ (coding, reports, sync, ai, graphs, import, merge, ...)
  tests/                     237 pytest tests
  scripts/gen_locales.py     locale generator (upstream .po → TypeScript dictionaries)
frontend/                    React 19 + TypeScript + Vite 6 + Tauri 2
  src/features/              per-feature views + pure logic modules with vitest tests
  tests-e2e/                 Playwright suite against the real backend (22 scenarios)
upstreamQualcoder/           reference checkout of the upstream PyQt application
compile.ps1 / compile.bat   full build (backend onedir + Tauri installers + update manifest)
```

## Development

```powershell
# backend (Python 3.11)
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
.\.venv\Scripts\python -m uvicorn qualcoder_api.main:app --port 8765

# frontend (Node 20+)
cd frontend
npm ci
npm run dev        # http://localhost:5173 (talks to the backend on 8765)
```

Quality gates:

```powershell
cd backend
.\.venv\Scripts\python -m ruff check src tests
.\.venv\Scripts\python -m mypy src
.\.venv\Scripts\python -m pytest tests

cd frontend
npm run typecheck
npm run lint
npm test
npm run test:e2e   # spawns the real backend + vite; needs `npx playwright install chromium`
```

## Building the app

`compile.ps1` (Windows) builds the PyInstaller backend onedir, then the Tauri
release app and its NSIS/MSI installers, and finally the update manifest. Use
`-SkipBackend` / `-SkipTauri` for partial rebuilds. Artifacts:

```
backend/dist/qualcoder-backend/                PyInstaller onedir
frontend/src-tauri/resources/backend/          onedir bundled into the Tauri app
frontend/src-tauri/target/release/qualcoder-tauri.exe
frontend/src-tauri/target/release/bundle/nsis/QualCoder_*-setup.exe
frontend/src-tauri/target/release/bundle/msi/QualCoder_*.msi
frontend/src-tauri/target/release/bundle/nsis/qualcoder-latest.json
```

Updater signing: with `updater.key` present (see below) the build also produces
`.sig` files and `qualcoder-latest.json`; without it (fresh checkout — the key is
gitignored) the build still succeeds but updater artifacts are skipped
(`createUpdaterArtifacts` is toggled off for that build and restored).

**Linux & macOS** — Tauri cannot cross-compile, so those binaries are built in
CI: the `release` workflow runs a four-job matrix
(windows-x86_64, linux-x86_64, darwin-x86_64, darwin-aarch64). Each job builds
the PyInstaller backend onedir and the platform installers:

```
Linux (ubuntu-22.04):   .AppImage (+ .sig, the updater bundle), .deb, .rpm
macOS (arm64 + x64):    QualCoder.app.tar.gz (+ .sig, the updater bundle), .dmg
```

The per-platform signatures are merged into the single `qualcoder-latest.json`
manifest (platforms: windows-x86_64 / linux-x86_64 / darwin-x86_64 /
darwin-aarch64) and uploaded with the release assets. macOS binaries are not
code-signed (Gatekeeper will warn); see Publishing updates below.

## Publishing updates

1. Generate a signing keypair once and keep `updater.key` secret:
   `npx tauri signer generate -w updater.key --ci` — commit `updater.key.pub`
   and keep `tauri.conf.json`'s `plugins.updater.pubkey` in sync with it.
2. Add the key content as the `TAURI_SIGNING_PRIVATE_KEY` repository secret.
3. Push a `v*` tag: the `release` workflow builds all platforms (Windows,
   Linux, macOS x64 + arm64), signs and uploads the installers + signatures
   + the merged `qualcoder-latest.json` to a GitHub release.
4. The app checks
   `https://github.com/MicRaving/qualcodernext/releases/latest/download/qualcoder-latest.json`
   (Settings → App updates) and offers to download & install the bundle for
   its own platform.

> macOS code-signing/notarization: to remove the Gatekeeper warning, add the
> standard Apple signing secrets (`APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`,
> `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`) and
> extend the workflow with `tauri-apps/tauri-action`-style signing steps.
> The repository is private, so the unauthenticated `latest/download` URLs the
> updater uses only resolve once the repo (or its releases) is public.

## License

QualCoder is distributed under the GNU LGPL-3.0 (see the upstream project). The
rework follows the same licensing intent; the upstream reference checkout carries
its own license text in `upstreamQualcoder/`.
