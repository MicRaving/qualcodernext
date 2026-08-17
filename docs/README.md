# QCnext — Documentation

This documentation describes **every screen, dialog and feature** of QCnext. It
is written for a researcher who wants to understand *what the software does, why
it works the way it does, and how to get work done* — not for someone reading the
source code. (For the technical build, see
[`frontend/src/DESIGN.md`](../frontend/src/DESIGN.md) and the repository
[`README.md`](../README.md).)

**For developers:** the authoritative UI spec is
[`frontend/src/DESIGN.md`](../frontend/src/DESIGN.md) — every screen must follow
it. UI-consistency / motion tracking lives in
[`ui-polish-plan.md`](ui-polish-plan.md).

## What is "coding"?

A **project** in QCnext is a folder containing your source material (text files,
PDFs, images, audio, video, web captures, spreadsheets) plus a database that
records your analytical work.

The core analytical act is **coding**: marking a passage of a document, a region
of an image, or a time range of an audio/video file, and attaching a **code** to
it. A code is a label — a theme, category, or concept. The marked passage plus
its code is a **coding** (also called a *segment* or *quote*). A researcher
typically:

1. **Imports** material (files, web pages, transcripts, survey data).
2. **Creates codes**, usually organised into **categories** (a hierarchical codebook).
3. **Reads** each document and codes meaningful passages.
4. **Writes memos** (analytical notes) on codes, files and passages.
5. **Explores** the coded data with reports, graphs and statistics.
6. **Exports** results (Word/Excel/PowerPoint, REFI-QDA, codebooks, CSV).

Around this core, QCnext adds research-adjacent tools: a journal for your
research log, annotations on passages, cases with attributes (for mixed-methods
work), a Questions-Themes-Theories workspace for building an argument, an AI
assistant, an R integration, and much more.

## Key concepts (glossary)

|Term|Meaning|
|-|-|
|**Project**|A folder (`.qda`) containing source files + a SQLite database with your codes, codings, notes and settings.|
|**Source / File**|One piece of material: text, PDF, image, audio, video, HTML capture, or CSV table.|
|**Code**|A label you attach to passages. Codes can be nested (sub-codes) and grouped in categories.|
|**Category**|A grouping node in the codebook tree that holds codes (or sub-categories).|
|**Coding / Segment**|One marked passage + its code. Position is stored precisely (character offsets in text, pixel rectangles in images/PDFs, milliseconds in AV).|
|**Coder**|A named person working in the project. Every coding records who made it.|
|**Memo**|A free-text analytical note attached to a code or a file.|
|**Annotation**|A note attached to a specific passage of a document (distinct from a code).|
|**Journal**|A dated research log (entries with free text).|
|**Case**|A study entity (person, school, organisation) that files can be linked to; cases carry **attributes** (structured variables) for mixed-methods analysis.|
|**Bookmark**|A saved position in a file or media, for quick return.|
|**Link**|A directed connection between two passages (MAXQDA-style "linked quotes").|

## How the application is organised

QCnext is a single window with a fixed structure (the "workspace layout"):

```
┌───────────────────────────────────────────────────────────────┐
│ Ribbon (navigation + coder switcher + task queue + toolbars)   │
├──────────────┬──────────────────────────────┬─────────────────┤
│ LEFT BAR     │  CENTER VIEW                 │  RIGHT BAR      │
│ (lists,      │  (the active screen: file    │  (Inspector,    │
│  code tree)  │   manager, coder, reports…)  │   AI, Settings, │
│              │                              │   History…)     │
├──────────────┴──────────────────────────────┴─────────────────┤
│ Status bar (project name · counts · version)                   │
└───────────────────────────────────────────────────────────────┘
```

* The **ribbon** at the top switches between the main areas: Dashboard,
Coding (file manager), Cases, Journal (notes), Crafter (QTT), Reports
(analysis), plus right-side tool buttons (History, AI, Creative, Settings,
report-a-bug).
* The **left bar** shows context-appropriate lists: your files, your code
tree, cases, notes, worksheets, or reports.
* The **center view** is where the work happens.
* The **right bar** shows the **Inspector** (details of whatever you clicked),
or one of the toggleable panes: AI chat/search, Settings, History, Creative.
* The **status bar** shows the project name, file/code/case counts and the app
version.

The bars are resizable (drag the inner border; drag past the minimum to hide a
bar — a small edge tab recalls it).

## Screen map

Every screen and dialog is documented in its own page:

|Screen / feature|Page|
|-|-|
|The workspace shell: ribbon, bars, coder switcher, task queue, Inspector|[shell.md](shell.md)|
|Dashboard — start screen, projects, recent projects|[dashboard.md](dashboard.md)|
|File manager — import, organise, URL import, batch jobs|[files.md](files.md)|
|**Text coder** — code, annotate, edit plain text|[coding-text.md](coding-text.md)|
|**PDF coder** — code PDF pages and extracted text|[coding-pdf.md](coding-pdf.md)|
|**Image coder** — code rectangular regions of images|[coding-image.md](coding-image.md)|
|**CSV/table coder** — code inside spreadsheet cells|[coding-csv.md](coding-csv.md)|
|**Webpage coder** — code captured HTML pages|[coding-html.md](coding-html.md)|
|**Audio/video coder** — timeline coding, transcripts, transcription|[coding-av.md](coding-av.md)|
|Cases + attributes|[cases.md](cases.md)|
|Notes — journal, annotations, memos|[notes.md](notes.md)|
|Crafter — Questions-Themes-Theories worksheets|[qtt.md](qtt.md)|
|Analysis — all reports and statistics|[analyze.md](analyze.md)|
|Graphs — the code-map editor and model generators|[graphs.md](graphs.md)|
|Creative coding scratchpad|[creative.md](creative.md)|
|AI assistant — chat, semantic search, configuration|[ai.md](ai.md)|
|Settings — appearance, language, AI, pseudonyms, updates|[settings.md](settings.md)|
|Import / Export (interchange with other QDA tools)|[interchange.md](interchange.md)|
|History — the audit log and undo/redo|[history.md](history.md)|
|Background tasks, the task queue, and collaboration sync|[status-and-tasks.md](status-and-tasks.md)|
|Reporting bugs|[bug-report.md](bug-report.md)|

## Coverage checklist

* **WorkspaceView kinds**: dashboard, files, coding, cases, notes, qtt,
analyze, graphs, history, settings, ai — all covered (coding splits into the
five coder pages: text, PDF, image, CSV, HTML, AV).
* **RightPane values**: inspector (shell.md), ai (ai.md), settings
(settings.md), history (history.md), creative (creative.md) — all covered.
* **ReportIds**: code-frequencies, code-segments, file-code, code-relations,
interrater, text-corpus, dictionary, stats, summary-table, sentiment,
doc-compare, codebook, references, sql, r-console, graphs — all covered in
analyze.md and graphs.md.
* **Other surfaces**: task queue + sync (status-and-tasks.md), bug report
(bug-report.md), interchange/import-export (interchange.md).

## A typical first session

1. **Start** the app → the Dashboard appears.
2. **Create or open a project** (see [dashboard.md](dashboard.md)).
3. **Import files** (see [files.md](files.md)) — text, PDF, image, audio/video,
CSV, HTML, or from a URL.
4. **Create codes** in the left bar's code tree (the `Code` button).
5. **Open a file** and select text (or drag a rectangle / timeline range) →
the floating toolbar lets you code it with the active code, pick another
code, create a new code from the text ("in-vivo"), annotate, or link it.
See the [coding-\*.md](coding-text.md) pages.
6. **Write memos** and explore with **Reports** as your coding grows.
7. **Collaborate**: enable sync in the coder switcher flyout to share the
project with other coders via a synced folder.

