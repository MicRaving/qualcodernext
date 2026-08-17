# QCnext - A Rework of Qualcoder

This is a rework of [QualCoder](https://github.com/ccbogel/QualCoder), the open-source qualitative data analysis (QDA) tool. The central focus of the software is to load text and multimedia files for qualitative coding. It can transcribe audio/video files, organize codes and files, generate reports like coding graphs and coder comparisons, and integrates LLMs to explore the data, support coding, and analyze the results.

### Scope of the Rework

I really love QualCoder but always felt like it had some shortcomings. Based on the upstream QualCoder as per 10.08.2026, I tried to rework the codebase with the following major goals:



* **Simplified UI**: This was the main point behind the rework. I used QualCoder a lot but was never able to convince my students and fellow researchers because the UI was always unintuitive with many functions hidden behind menus and requiring just one too many clicks. The rework tries to simplify and reorganize the UI as much as possible while retaining full functionality.
* **Simultaneous collaboration**: Nowadays, qualitative projects have grown substantially, heavily relying on many coders. While I understood the limitations of SQLite, I was never happy with not being able to work on projects simultaneously. In the rework, your just have to save the project in a shared folder, enable collaboration in the coder flyout on the top right and you're good to go. Projects sync every minute, just make sure you're not working as the same coder with multiple computers.
* **Reduce architectural debt**: QualCoder is organized in few monolithic Python scripts (2,000-8,000 lines of code each) that are hard to handle, partially redundant, and prone to bugs. I therefore tried to make the codebase more modular and sleaker, with all files <1,000 lines of code.
* **Increase responsiveness**: Qualcoder takes a long time to start (\~30s). I reduced the startup time to 2s.
* **Reduce memory footprint**: This is honestly not that much of a deal but QualCoder 3.8 uses 450mb RAM, while the rework clocks in at 200mb
* **Full compatibility**: All of these changes do not break compatibility with your existing projects.
* **Minor features**: Undo/redo with a full project history. More reports and additional interrater agreements like Fleiss Kappa. Implemented a dashboard for quick access. Easier file management with multiselect etc
* **(Future) Web apps**: With more and more people relying on tablets and smartphones, using offline apps becomes less practical. The rework did not fully implement a client-server structure and future iterations will always retain offline functionality, but it lays the groundwork for running QualCoder in a browser.

## Installation

All releases are available on: [https://github.com/MicRaving/QCnext/releases](https://github.com/MicRaving/QCnext/releases)

* Windows: Download the portable version and unpack it or install the installer from
* Linux: Install the flatpack (untested)
* MacOS: Install the .dmg (untested)
* Compilation: Clone the repo and run compile.ps1 (Windows) to build the portable folder and installer. Scripts for Linux and MacOS will follow soon.

## Documentation

You can find the documentation here:

* [**Documentation Hub**](docs/README.md) — Start screen, workflow diagrams, and glossary.
* [**Workspace Shell \& Collaboration Guide**](docs/workspace-and-shell.md) — Layout, projects, asynchronous sync, audit history \& bug reporter.
* [**Files \& Material Import Guide**](docs/files-and-import.md) — Document management, web scraping, and QDA interchange (REFI-QDA, NVivo, SPSS, Zotero).
* [**Qualitative Coders Guide**](docs/coders.md) — Text, PDF, Image, CSV/Table, Webpage, and Audio/Video coders with Whisper auto-transcription.
* [**Cases \& Attributes Guide**](docs/cases-and-attributes.md) — Study units, participant metadata, and mixed-methods attributes.
* [**Notes, Worksheets \& Synthesis Guide**](docs/notes-and-synthesis.md) — Journal, annotations, code memos, Crafter (QTT), and Creative Coding.
* [**Analysis, Reports \& Graphs Guide**](docs/analysis-and-reports.md) — 11 analytical reports, interrater agreement, publishing (Word/Excel/PPT), SQL/R console \& visual code maps.
* [**AI Assistant \& Settings Guide**](docs/ai-and-settings.md) — Local/Cloud LLM config, semantic vector search, MCP endpoints, and app preferences.

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

## What will (likely) not be implemented

* ATLAS.ti: Closed format, other migration paths exist, not worth the effort.

