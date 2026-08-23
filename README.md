# QCnext - A Rework of Qualcoder

This is a rework of [QualCoder](https://github.com/ccbogel/QualCoder), an awesome open-source qualitative data analysis (QDA) tool. The central focus of the software is to load text and multimedia files for qualitative coding. It can transcribe audio/video files, organize codes and files, generate reports like coding graphs and coder comparisons, and integrates LLMs to explore the data, support coding, and analyze the results.

> [!NOTE]
> This software is currently in beta. While I consider it mostly feature-complete and use it as my daily driver, you may encounter bugs or visual quirks, etc. Please report any issues and suggestions for improvements!

!\[Active Project Dashboard](docs/screenshots/dashboard.jpg)



QCnext uses a single-window **Workspace Layout** organized into

* a **ribbon** for navigating main views (*Dashboard*, *Coding*, *Cases*, *Journal*, *Crafter*, *Reports*),
* a **left bar** for workflow-supporting information (codes, files, report etc.),
* a **center view** for the main information, and
* a **right bar** for additional information or an active side-pane (AI Chat, Settings, Audit History, Creative Scratchpad).



This rework is loosely based on the QualCoder 4.0 beta source code (\~2% copied, \~12% adapted) with the following major goals (full [changelog](Changelog.md)):

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
* Compilation: Clone the repo and run `release.ps1 -Compile` (Windows) to build the portable folder and installer. Scripts for Linux and MacOS will follow soon.

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

1. **Start QCnext**: Launch the application to view the [Dashboard](docs/workspace.md).
2. **Create a Project**: Click **New project** and specify a `.qda` location or open an existing project.
3. **(optional) Collaborate**: Save the file in a shared location and enable [Collaboration Sync](docs/workspace.md) in the ribbon to work simultaneously with team members via shared cloud folders.
4. **Import Material**: Open the [File Manager](docs/files.md) and import your interview transcripts, PDFs, images, or media files.
5. **Define Codes**: Create codes and categories in the left-bar [Code Tree](docs/coders.md).
6. **Code Your Data**: Open a source file in one of the specialized [Coders](docs/coders.md), select passages or regions, and assign codes.
7. **Synthesize \& Memos**: Write analytical memos and synthesize findings in [Crafter](docs/notes.md).
8. **Analyze \& Export**: Generate [Reports \& Visual Code Maps](docs/reports.md), test interrater reliability, and publish reports to Word, Excel, or REFI-QDA.

\---



## License

QualCoder is distributed under the [GNU LGPL-3.0](LICENSE.txt), QCnext follows the same licensing intent.

## Authors

QCnext is a rework by Marvin Fendt ([Ludwig Maximilians University Munich](https://www.lmu.de/psy/de/personen/kontaktseite/marvin-fendt-b5fc2511.html)). It is based on the QualCoder 4.0 beta source code by [**Dr. Colin Curtain**](https://www.utas.edu.au/profiles/staff/umore/colin-curtain), [**Dr. rer. soc. Kai Dröge,**](https://www.hslu.ch/de-ch/hochschule-luzern/ueber-uns/personensuche/profile/?pid=823), [**Dr. Justin Missaghieh--Poncet**](https://www.univ-pau.fr/fr/index.html), and [**Dr. Lorenzo Salomón**](https://www.uas.edu.mx/).

## Future

This is a non-exhaustive, unsorted list of planned features:

* Expand the rudimentary Creative Coding and Crafter
* Working web app and server
* Make confirming code deletion an in-app dialog instead of system.
* Further improvements for collaboration and AI (particularly MCP)
* Further refine the UI
* Support other languages than EN/DE
* Bug-fixing - You tell me!

