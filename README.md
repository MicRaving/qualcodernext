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

**AI assistant (optional, local-first)**

- Chat with mode-specific prompt libraries (help, topic exploration, code analysis,
  text analysis — 31 shipped prompts)
- Semantic search with a persistent per-project vector index (pure Python)
- MCP (Model Context Protocol) JSON-RPC endpoint with read/write permission gating

**Languages** — English (reference), German (full), plus 12 generated locales from
the upstream gettext files (es, fr, eo, eu, fa, ht, it, ja, pt, ro, sv, zh) with
English fallback.

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
.github/workflows/ci.yml   GitHub Actions: backend tests+lint, frontend tests+lint+build, Playwright E2E
backend/                   FastAPI + SQLAlchemy async + Alembic (package: qualcoder_api)
  src/qualcoder_api/       api/v1 endpoints · persistence (schema, migrations, repositories)
                           services/ (coding, reports, sync, ai, graphs, import, merge, ...)
  tests/                   229 pytest tests
  scripts/gen_locales.py   locale generator (upstream .po → TypeScript dictionaries)
frontend/                  React 19 + TypeScript + Vite 6 + Tauri 2
  src/features/            per-feature views + pure logic modules with vitest tests
  tests-e2e/               Playwright suite against the real backend (21 scenarios)
upstreamQualcoder/         reference checkout of the upstream PyQt application
compile.ps1 / compile.bat   full build (backend exe + Tauri installers)
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

`compile.ps1` (Windows) builds the PyInstaller backend exe, then the Tauri release
app and its NSIS/MSI installers. Use `-SkipBackend` / `-SkipTauri` for partial
rebuilds. Artifacts:

```
backend/dist/qualcoder-backend.exe
frontend/src-tauri/target/release/qualcoder-tauri.exe
frontend/src-tauri/target/release/bundle/nsis/QualCoder_*-setup.exe
frontend/src-tauri/target/release/bundle/msi/QualCoder_*.msi
```

## License

QualCoder is distributed under the GNU LGPL-3.0 (see the upstream project). The
rework follows the same licensing intent; the upstream reference checkout carries
its own license text in `upstreamQualcoder/`.
