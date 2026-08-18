# QCnext - A Rework of Qualcoder

This is a rework of [QualCoder](https://github.com/ccbogel/QualCoder), the open-source qualitative data analysis (QDA) tool. The central focus of the software is to load text and multimedia files for qualitative coding. It can transcribe audio/video files, organize codes and files, generate reports like coding graphs and coder comparisons, and integrates LLMs to explore the data, support coding, and analyze the results.



!\\\[Active Project Dashboard](screenshots/dashboard.jpg)



QCnext uses a single-window **Workspace Layout** organized into

* a **ribbon** for navigating main views (*Dashboard*, *Coding*, *Cases*, *Journal*, *Crafter*, *Reports*),
* a **left bar** for workflow-supporting information (codes, files, report etc.),
* a **center view** for the main information, and
* a **right bar** for additional information or an active side-pane (AI Chat, Settings, Audit History, Creative Scratchpad).



This rework is based on the upstream QualCoder source code as per 10.08.2026 with the following major goals:

* **Simplified UI**: The rework tries to simplify and reorganize the UI as much as possible while retaining full functionality.
* **Simultaneous collaboration**: Simultaneous collaboration is now possible by saving the project in a shared folder and enabling collaboration in the coder flyout.
* **Reduce architectural debt**: The rework tried to make the codebase more modular and sleaker to eliminate the old, monolithic scripts to reduce redundancy and make maintaining easier.
* **Increase responsiveness**: The startup time is reduced from \~30s to to \~2s, the memory footprint is roughly cut in half (from 450mb to 200mb)
* **Full compatibility**: All of these changes do not break compatibility with your existing projects.
* **Minor features**: Undo/redo with a full project history. More reports and additional interrater agreements like Fleiss Kappa. A dashboard for quick access. Easier file management with multiselect etc.
* **(Future) Web apps**: The rework prepared to allow for a client-server structure with full web apps, although future iterations will always retain offline functionality.

## Installation

All releases are available on: [https://github.com/MicRaving/qualcodernext/releases](https://github.com/MicRaving/qualcodernext/releases)

* Windows: Download the portable version and unpack it or install the installer from
* Linux: Install the flatpack (untested)
* MacOS: Install the .dmg (untested)
* Compilation: Clone the repo and run compile.ps1 (Windows) to build the portable folder and installer. Scripts for Linux and MacOS will follow soon.

## Documentation

You can find the documentation here:

* [**Workspace Shell \& Collaboration Guide**](docs/workspace.md) — Layout, projects, asynchronous sync, audit history \& bug reporter.
* [**Files \& Material Import Guide**](docs/files.md) — Document management, web scraping, and QDA interchange (REFI-QDA, NVivo, SPSS, Zotero).
* [**Qualitative Coders Guide**](docs/coders.md) — Text, PDF, Image, CSV/Table, Webpage, and Audio/Video coders with Whisper auto-transcription.
* [**Cases \& Attributes Guide**](docs/cases.md) — Study units, participant metadata, and mixed-methods attributes.
* [**Notes, Worksheets \& Synthesis Guide**](docs/notes.md) — Journal, annotations, code memos, Crafter (QTT), and Creative Coding.
* [**Analysis, Reports \& Graphs Guide**](docs/analysis.md) — 11 analytical reports, interrater agreement, publishing (Word/Excel/PPT), SQL/R console \& visual code maps.
* [**AI Assistant \& Settings Guide**](docs/ai.md) — Local/Cloud LLM config, semantic vector search, MCP endpoints, and app preferences.



The typical workflow will look similar to this:

1. **Start QCnext**: Launch the application to view the [Dashboard](workspace.md).
2. **Create a Project**: Click **New project** and specify a `.qda` location or open an existing project.
3. **(optional) Collaborate**: Save the file in a shared location and enable [Collaboration Sync](workspace.md) in the ribbon to work simultaneously with team members via shared cloud folders.
4. **Import Material**: Open the [File Manager](files.md) and import your interview transcripts, PDFs, images, or media files.
5. **Define Codes**: Create codes and categories in the left-bar [Code Tree](coders.md).
6. **Code Your Data**: Open a source file in one of the specialized [Coders](coders.md), select passages or regions, and assign codes.
7. **Synthesize \& Memos**: Write analytical memos and synthesize findings in [Crafter](notes.md).
8. **Analyze \& Export**: Generate [Reports \& Visual Code Maps](reports.md), test interrater reliability, and publish reports to Word, Excel, or REFI-QDA.

\---

## Glossary

|Term|Description|
|-|-|
|**Project (`.qda`)**|A dedicated directory containing source files and a SQLite database storing codes, codings, cases, notes, and settings.|
|**Source / File**|Any primary material imported into the project (Text, PDF, Image, Audio, Video, HTML, CSV).|
|**Code**|An analytical label attached to data segments. Codes can be hierarchical (sub-codes) and grouped into **Categories**.|
|**Category**|A container node in the codebook tree used to group related codes logically.|
|**Coding (Segment)**|A marked passage or region bound to a specific code, recording exact position (character offsets, coordinates, or timestamps) and owner.|
|**Coder**|A registered researcher name. Every coding, note, and modification records the coder who created it.|
|**Memo**|Analytical commentary attached to a code, file, or project entity.|
|**Annotation**|A targeted note attached to a specific passage of a document (distinct from a code).|
|**Case**|A unit of analysis (e.g., participant, organization, school) linked to files/spans and carrying structured **Attributes**.|
|**QTT Worksheet**|A Crafter workspace for synthesizing Questions, Themes, and Theories into structured analytical arguments.|



## License

QualCoder is distributed under the GNU LGPL-3.0 (see the upstream project). QCnext follows the same licensing intent; the upstream reference checkout carries its own license text in `upstreamQualcoder/`.

## Future

Here is a non-exhaustive list of planned features

* Improve documentation and tutorials
* Fully implement client-server architecture
* Implement more use cases for LLMs
* Further refine the UI
* Organize History in hierarchical structure: Right now, every action can be undone regardless of whether it destroys other actions, too.
* Bug-fixing - You tell me!
* Rework the search: Include a search bar in the ribbon that lets users search for exact words in the projects (filter by categories) and via semantic search (move the build index button and the semantic search here).
* Implement a proper help bar with regex and semantic search.

## What will (likely) not be implemented

* ATLAS.ti: Closed format, other migration paths exist, not worth the effort.

