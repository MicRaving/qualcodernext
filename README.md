# QCnext - A Rework of Qualcoder

This is a rework of [QualCoder](https://github.com/ccbogel/QualCoder), the open-source qualitative data analysis (QDA) tool. The central focus of the software is to load text and multimedia files for qualitative coding. It can transcribe audio/video files, organize codes and files, generate reports like coding graphs and coder comparisons, and integrates LLMs to explore the data, support coding, and analyze the results.

> **Current development branch: `alpha-0.2.0`** — the roadmap wave described below
> (dictionary autocode, stats/sentiment reports, QTT, creative coding, ...) is
> implemented and covered by the e2e suite (`frontend/tests-e2e`).



### Scope of the Rework

I really love QualCoder but always felt like it had some shortcomings. I therefore tried to rework the codebase with the following major goals:

* **Simplified UI**: This was the main point behind the rework. I used QualCoder a lot but was never able to convince my students and fellow researchers because the UI was always unintuitive with many functions hidden behind menus and requiring just one too many clicks. The rework tries to simplify and reorganize the UI as much as possible while retaining full functionality.
* **Simultaneous collaboration**: Nowadays, qualitative projects have grown substantially, heavily relying on many coders. While I understood the limitations of SQLite, I was never happy with not being able to work on projects simultaneously. In the rework, your just have to save the project in a shared folder, enable collaboration in the coder flyout on the top right and you're good to go. Projects sync every minute, just make sure you're not working as the same coder with multiple computers.
* **Reduce architectural debt**: QualCoder is organized in few monolithic Python scripts (2,000-8,000 lines of code each) that are hard to handle, partially redundant, and prone to bugs. I therefore tried to make the codebase more modular and sleaker, with all files <1,000 lines of code.
* **Increase responsiveness**: Qualcoder takes a long time to start (\~30s). I reduced the startup time to 2s.
* **Reduce memory footprint**: This is honestly not that much of a deal but QualCoder 3.8 uses 450mb RAM, while the rework clocks in at 200mb
* **Full compatibility**: All of these changes do not break compatibility with your existing projects.
* **Minor features**: Undo/redo with a full project history. More reports and additional interrater agreements like Fleiss Kappa. Implemented a dashboard for quick access. Easier file management with multiselect etc
* **(Future) Web apps**: With more and more people relying on tablets and smartphones, using offline apps becomes less practical. The rework did not fully implement a client-server structure and future iterations will always retain offline functionality, but it lays the groundwork for running QualCoder in a browser.

## Changelog

Based on the upstream QualCoder as per 10.08.2026 that was completely reworked with preserving compatibility for projects:

* **FastAPI + SQLAlchemy (async) + SQLite** backend, packaged with PyInstaller and embedded in a **Tauri 2** desktop shell (React 19 + TypeScript + Vite)
* All data access goes through a typed HTTP API (`backend/src/qualcoder\\\_api`), preparing R/Python/MCP tooling
* The whole UI is now simplified, featuring a ribbon and three-column layout (left bar, right bar, center view) that each contain a menu bar
* Refactored the monolithic Python scripts
* Full project history
* Rename every project element inline
* Collaboration with automatic sync between multiple simultaneously working coders
* Extended local AI assistant
* Included an updater

### 0.2.0 alpha — roadmap wave

* Code **promote/demote** via the code-tree context menu (Word-list style hierarchy moves)
* **Multi-coder interrater** reliability (N-rater Alpha, pairwise Kappa / AC1)
* **Dictionary autocode**: MAXDictio-style word dictionaries with term-frequency report, used from the autocode dialog and the Dictionary report
* **Sentiment report** (VADER lexicon or AI) and **document comparison** chart (LCS alignment)
* **Statistics** suite: code × attribute crosstabs with chi-square, group comparisons (Mann-Whitney U), mixed-methods matrix
* **Summary tables** (coding memos as a document × code grid) and the **smart publisher** (Word/Excel/PowerPoint export of reports)
* **Segment hyperlinks / linked quotes** between documents (copy/paste link payloads)
* **Creative coding** scratchpad with promote-to-code
* **QTT workspace** (MAXQDA-style questions-themes-theories worksheets, qualitative + Creswell 14-step mixed template, send-to-QTT from the coders)
* **URL import / scraping** (Reddit threads, YouTube metadata/captions/comments, articles, raw HTML)
* **Manual transcription mode** (media keys, F9/Space, timestamp insert)
* **Attribute value labels** (labelled dropdowns in the case/file properties)
* **XLSX/SPSS .sav import** and **Transana `.tprd` import**
* Coder flyout with per-coder delete + background-task queue controls; batch transcribe/autocode buttons with eligible counts

## Collaboration

Raters work as **different coders on separate copies of the same `.qda` project
folder**, shared through any folder-sync tool (Nextcloud, ownCloud, Sync\&Share,
Syncthing, Dropbox, ...). The SQLite database is **never merged by the sync tool**
— that corrupts projects. Instead:

1. Every mutation is captured into the project's `sync\\\_log` (v19 schema) with full
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
artifacts (`project\\\_in\\\_use.lock`, `ai\\\_index.sqlite3`, `backups/` — sync state lives
in `\\\~/.qualcoder/sync/`).

## Installation

All releases are available on: [https://github.com/MicRaving/QCnext/releases](https://github.com/MicRaving/QCnext/releases)

* Windows: Download the portable version and unpack it or install the installer from
* Linux: Install the flatpack (untested)
* MacOS: Install the .dmg (untested)
* Compilation: Clone the repo and run compile.ps1 (Windows) to build the portable folder and installer. Scripts for Linux and MacOS will follow soon.

## License

QualCoder is distributed under the GNU LGPL-3.0 (see the upstream project). The
rework follows the same licensing intent; the upstream reference checkout carries
its own license text in `upstreamQualcoder/`.



## Future

Here is a non-exhaustive list of planned features

* Fully implement client-server architecture
* Implement more use cases for LLMs
* Implementation with R/Python
* Further refine the UI
* Bugs: You tell me

### Roadmap

Items shipped in the current `alpha-0.2.0` branch are listed in the changelog
above; the remaining planned work:

* Import of NVivo, ATLAS.ti → **Maybe** — depends on format research (see the open-source mapping projects below)
* Cloud collaboration (shared projects, web access, comments) → **not planned** for the desktop app; comments via the existing folder-sync are assessed and deferred
* Chat with memos
* AI paraphrase

### Open-source format research — NVivo / ATLAS.ti

NVivo (`.nvpx`/`.nvp`, a ZIP of XML files) and ATLAS.ti (`.atlproj24`, ZIP of XML) are proprietary formats. Import is only feasible by reusing the mapping work of open-source projects instead of reverse-engineering from scratch:

* [REFI-QDA standard](https://www.qdasoftware.org/) — the open exchange format for QDA projects (`.qdp`/`.qdc`); implemented by NVivo, ATLAS.ti, MAXQDA and others as export/import fallback
* [openqda/refi-tools](https://github.com/openqda/refi-tools) (AGPL-3.0) — utilities, XSD schemas and the spec PDFs for implementing the REFI standard
* [cbrincoveanu/pyrefiqda](https://github.com/cbrincoveanu/pyrefiqda) (MIT) — Python/Pydantic models mapping REFI-QDA `.qdpx` files
* [vmnacar/refio](https://github.com/vmnacar/refio) (MIT) — read, write and convert REFI-QDA `.qdpx`/`.qde`/`.qdc` files in Python
* [BarraQDA/nvivotools](https://github.com/BarraQDA/nvivotools) (GPL-3.0) — Python tooling around NVivo, incl. its XML export
* [SecurityEssentials/Teams2NVivo](https://github.com/SecurityEssentials/Teams2NVivo) (MIT) — writes NVivo XML project files (documents the format)
* [borisbachmann/atlas-qdpx](https://github.com/borisbachmann/atlas-qdpx) (MIT) — extracts annotations from ATLAS.ti REFI-QDA exports
* Transana — the old GPL code lives on [SourceForge](https://sourceforge.net/projects/transana/) (current versions are commercial); single-user `.tprd` projects are SQLite — **shipped in 0.2.0** (defensive schema probe, media + transcript + keyword mapping)

