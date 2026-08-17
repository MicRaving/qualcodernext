# QCnext — User Documentation

Disclaimer: As of 17.08.2026, most of this text (except for this Hub an the Workspace \& Shell Guide) is LLM-generated based on my notes. I will rework this in the coming weeks.



Welcome to the official documentation for **QCnext**, the open-source Qualitative Data Analysis (QDA) application. This documentation is written for qualitative researchers, students, analysts, and teams who want to understand how to use the software effectively for coding text, multimedia, survey data, web content, and mixed-methods research.

\---

## Quick Navigation

|Documentation Guide|Description|
|-|-|
|[**Workspace \& Shell Guide**](workspace-and-shell.md)|Start screen, workspace layout, project management, audit history, task queue \& real-time collaboration sync.|
|[**Files \& Material Import Guide**](files-and-import.md)|Importing documents, batch imports, web scraping, and QDA interchange (REFI-QDA, NVivo, RQDA, SPSS, RIS/Zotero).|
|[**The Qualitative Coders Guide**](coders.md)|Full guide to coding Plain Text, PDFs, Images, CSV/Spreadsheet cells, Webpages, and Audio/Video timelines with transcription.|
|[**Cases \& Attributes Guide**](cases-and-attributes.md)|Organizing study entities (participants, sites, schools), member files, and mixed-methods attribute variables.|
|[**Notes, Worksheets \& Synthesis Guide**](notes-and-synthesis.md)|Methodological journal, document annotations, code memos, Crafter (QTT worksheets), and Creative Coding scratchpad.|
|[**Analysis, Reports \& Graphs Guide**](analysis-and-reports.md)|11 analytical reports, interrater agreement (Krippendorff α, Cohen κ, Gwet AC1), publishing to Word/Excel/PPT, SQL/R console, and SVG visual code maps.|
|[**AI Assistant \& Settings Guide**](ai-and-settings.md)|Setting up Local/Cloud LLMs, semantic vector search, MCP tools, theme customization, anonymization pseudonyms, and updates.|

\---

## General Overview

A **project** in QCnext is a self-contained directory holding your raw source material (interview transcripts, PDFs, images, field notes, survey spreadsheets, audio/video recordings, and web captures) along with an integrated database that records your analysis.

The core activity is **coding**: highlighting a segment of text, drawing a region on an image or PDF, or marking a timestamp interval on audio/video, and attaching a **code** (a category, concept, or theme label) to it.



QCnext uses a single-window **Workspace Layout** organized into four primary slots:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Ribbon (Navigation · Active Coder Switcher · Background Task Queue · Pane Toggles)│
├─────────────────┬──────────────────────────────────────────────┬─────────────────┤
│ LEFT BAR        │ CENTER VIEW                                  │ RIGHT BAR       │
│ (Code Tree,     │ (Active Screen: Coder, File Manager,          │ (Inspector, AI, │
│  File List,     │  Reports, Crafter, Cases, Dashboard)         │  Settings,      │
│  Report List)   │                                              │  History)       │
└──────────────────────────────────────────────────────────────────────────────────┘
```

* **Ribbon**: Top bar for navigating main views (*Dashboard*, *Coding*, *Cases*, *Journal*, *Crafter*, *Reports*) and toggling utility panes (*History*, *AI*, *Creative*, *Bug Reporter, Settings*).
* **Left Bar**: Displays contextual sidebars such as the codebook tree, file explorer, case list, or report navigation list.
* **Center View**: The primary workspace where documents are read and coded, reports are generated, or worksheets are edited.
* **Right Bar**: Displays the **Inspector** (showing details of the currently selected element) or an active side-pane (AI Chat, Settings, Audit History, Creative Scratchpad).



The typical workflow will look similar to this:

1. **Start QCnext**: Launch the application to view the [Dashboard](workspace-and-shell.md#dashboard--start-screen).
2. **Create a Project**: Click **New project** and specify a `.qda` location or open an existing project.
3. **(optional) Collaborate**: Save the file in a shared location and enable [Collaboration Sync](workspace-and-shell.md#collaboration-sync) in the ribbon to work simultaneously with team members via shared cloud folders.
4. **Import Material**: Open the [File Manager](files-and-import.md) and import your interview transcripts, PDFs, images, or media files.
5. **Define Codes**: Create codes and categories in the left-bar Code Tree.
6. **Code Your Data**: Open a source file in one of the specialized [Coders](coders.md), select passages or regions, and assign codes.
7. **Synthesize \& Memos**: Write analytical memos and synthesize findings in [Crafter (QTT)](notes-and-synthesis.md#crafter-qtt-worksheets).
8. **Analyze \& Export**: Generate [Reports \& Visual Code Maps](analysis-and-reports.md), test interrater reliability, and publish reports to Word, Excel, or REFI-QDA.



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



