# Workspace Shell, Projects & Collaboration Guide

[← Back to Documentation Hub](README.md)

This guide covers the core application structure of QCnext: project creation and management, the 5-slot workspace layout, background job execution, real-time multi-coder collaboration sync, the full audit history with per-row undo/redo, and the integrated bug reporter.

---

## Table of Contents
- [Dashboard & Project Management](#dashboard--project-management)
- [The 5-Slot Workspace Layout](#the-5-slot-workspace-layout)
- [Background Tasks & Queue](#background-tasks--queue)
- [Real-Time Collaboration Sync](#real-time-collaboration-sync)
- [Audit History & Undo/Redo](#audit-history--undoredo)
- [In-App Bug Reporter & Screenshot Tool](#in-app-bug-reporter--screenshot-tool)

---

## Dashboard & Project Management

The **Dashboard** is the application home screen. When launching QCnext without a project, it serves as the welcome landing page; when a project is open, it presents real-time project statistics and quick-access tools.

### Welcome Screen (No Project Open)

![Dashboard Welcome Screen](screenshots/01-dashboard-no-project.png)

- **QCnext Version & Status**: Displays application title, current version, and backend status.
- **Stat Cards**: Displays placeholder indicators (`—`) for Files, Codes, Code Categories, Cases, Attribute Types, and Journal Entries.
- **New Project**: Primary button opening the project creation dialog. In the desktop application, this defaults to `<picked-folder>\NewProject.qda`.
- **Open Project**: Native folder picker to immediately open an existing `.qda` project directory.
- **Recent Projects**: Displays recently opened projects with one-click re-opening.
- **Accessibility Controls**: Quick dropdown to select high-contrast, screenreader, large-text, reduced-motion, or colorblind-friendly modes.

### Active Project Dashboard

![Active Project Dashboard](screenshots/02-dashboard-project.png)

- **Header Info**: Shows the active project name, database version, and creation date.
- **Live Statistics**: Displays real counts for all project entities (Files, Codes, Categories, Cases, Attributes, Notes).
- **Project Switcher**: Allows opening or creating another project at any time.

> [!NOTE]
> **Project Lock Protection**: If a project folder is currently opened by another running instance of QCnext, a warning banner will notify you of the active lock to prevent database corruption.

---

## The 5-Slot Workspace Layout

QCnext enforces a responsive, ergonomic 5-slot layout across all views:

```
┌──────────────────────────────────────────────────────────────────┐
│ RIBBON — Dashboard · Coding · Cases · Journal · Crafter · Reports│
│         ─── divider ─── [task chip] [coder switcher] [⌛ AI ✨ ⚙ 🐞]│
├──────────────┬─────────────────────────────────┬─────────────────┤
│ LEFT BAR     │ CENTER VIEW                     │ RIGHT BAR       │
│ w-64/w-72    │ flex-1                          │ w-72            │
│ (Contextual  │ (Active workspace screen)       │ (Inspector or   │
│  sidebar)    │                                 │  utility pane)  │
├──────────────┴─────────────────────────────────┴─────────────────┤
│ STATUS BAR — project name · entity counts · sync status · version │
└───────────────────────────────────────────────────────────────────┘
```

### 1. The Ribbon
The top navigation bar contains:
- **Navigation Buttons**: *Dashboard*, *Coding* (File Manager), *Cases*, *Journal* (Notes), *Crafter* (QTT Worksheets), and *Reports* (Analysis).
- **Task Queue Chip**: Displays background execution status with a circular progress ring.
- **Coder Switcher**: Flyout menu for switching active coder identity and toggling collaboration sync.
- **Right-Side Utility Toggles**:
  - 🕒 **History**: Opens the audit log and undo/redo pane.
  - ✨ **AI Assistant**: Opens the AI chat and semantic search pane.
  - 💡 **Creative Coding**: Opens the creative scratchpad pane.
  - 🐞 **Report Bug**: Opens the screenshot issue composer.
  - ⚙️ **Settings**: Opens application settings (theme, AI config, updates).

### 2. Left Bar
Holds view-specific navigation: Codebook tree in coders, file list in File Manager, case list in Cases, report list in Analysis, or worksheet list in Crafter.
- **Resizable**: Drag the inner border (clamped between 200px and 520px). Dragging past ~140px collapses the bar completely; a small edge tab restores it.

### 3. Center View
The primary area where coding, analysis, editing, and report generation take place.

### 4. Right Bar & Inspector
Displays contextual details via the **Inspector**:
- **File Inspector**: Shows file metadata, memo, linked cases, and character count.
- **Code Inspector**: Shows code details, parent category, memo, color swatch, and recent segment shortcuts.
- **Utility Panes**: Toggles between AI, Settings, History, or Creative Coding.

### 5. Status Bar
Displays the project name, active counts (files, codes, codings), collaboration sync status, and application version.

---

## Background Tasks & Queue

QCnext executes long-running processes—such as audio/video transcription, batch autocoding, R statistical scripts, and large file imports—in a **sequential background queue**.

- **Sequential Execution**: Jobs run one at a time to prevent resource contention.
- **Task Queue Flyout**: Clicking the progress ring chip in the ribbon opens the task queue manager.
- **Controls**: Pause/resume queue execution, reorder queued jobs via drag-and-drop, cancel jobs, or clear completed items.
- **Background Persistence**: Jobs like Whisper auto-transcription continue running smoothly even while you navigate other parts of the application.

---

## Real-Time Collaboration Sync

QCnext enables multiple raters to work on the **same qualitative project simultaneously** without requiring a dedicated server.

### How Collaboration Sync Works

Rather than sharing a single SQLite database over a network share (which causes database locks and corruption), each researcher works on **their own copy of the project folder** synchronized via standard folder-sync services (e.g., Nextcloud, ownCloud, Syncthing, Dropbox, Google Drive).

```
Coder A's Computer                                Coder B's Computer
┌─────────────────────┐                          ┌─────────────────────┐
│ Local QCnext App    │                          │ Local QCnext App    │
│  └── Local SQLite   │                          │  └── Local SQLite   │
│  └── sync_log       │                          │  └── sync_log       │
└──────────┬──────────┘                          └──────────┬──────────┘
           │ Writes sidecar file                            │ Writes sidecar file
           ▼                                                ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │ Folder-Sync Service (Nextcloud / Syncthing / Dropbox)           │
 │  ├── changes/coder_a/changes.jsonl                               │
 │  └── changes/coder_b/changes.jsonl                               │
 └──────────────────────────────────────────────────────────────────┘
```

1. **Local Mutation Logging**: Every creation, modification, or deletion is recorded in a local `sync_log` database table with full row snapshots.
2. **Sidecar Export**: Every 60 seconds (or upon clicking **Sync now**), QCnext appends local changes to `changes/<coder-name>/changes.jsonl` within the project directory. The folder-sync tool syncs these text files.
3. **Replay & Merge Engine**: Every 60 seconds, QCnext reads sidecar files produced by collaborators and replays them locally:
   - Primary key lookup with last-write-wins per row.
   - Natural key matching for codings (file, code, positions).
   - Automatic primary-key remapping when autoincrement IDs collide across coders.
   - Replayed changes are never re-exported (prevents infinite ping-pong loops).
4. **Blind Coding Support**: In the coder switcher menu, you can toggle visibility for individual coders to conduct blind interrater reliability checks.

> [!IMPORTANT]
> **Collaboration Best Practices**:
> 1. **Unique Coder Names**: Ensure every team member sets a unique coder name in the ribbon flyout.
> 2. **Exclude Local Files**: Configure your folder-sync tool to ignore per-machine files (`project_in_use.lock`, `ai_index.sqlite3`, `backups/`).

---

## Audit History & Undo/Redo

Every action in QCnext is logged in an immutable project audit history.

- **Opening History**: Click the 🕒 **History** icon in the ribbon.
- **Filter & Search**: Filter log entries by action type (coding create, code delete, text edit), coder name, or text query.
- **Granular Undo**: Unlike traditional full-project rollbacks, QCnext supports **per-row action inversion**. Clicking the undo icon on a log entry safely reverts that specific change (e.g., restoring a deleted coding or reverting a code rename) without affecting work done by collaborators.
- **Redo Stack**: Maintains a 10-step redo stack for recently undone actions.
- **Diff Viewer**: Clicking a text-edit log entry displays a visual side-by-side diff showing exact insertions and deletions.

---

## In-App Bug Reporter & Screenshot Tool

If you encounter an issue or wish to submit feedback, QCnext includes a built-in issue composer.

1. **Launch**: Click the 🐞 **Bug** icon on the right side of the ribbon.
2. **Automatic Capture**: QCnext captures a clean screenshot of the application state before displaying the dialog.
3. **Annotation Editor**: Use drawing tools (red pen, yellow highlight, black redaction brush, eraser) to highlight issues or obscure sensitive data.
4. **Environment Auto-Fill**: Automatically attaches app version, operating system details, active view, and recent error stack traces.
5. **Submission**:
   - **Default**: Opens a pre-filled GitHub issue page in your browser with system diagnostics attached.
   - **API Mode**: If a GitHub token is configured in settings, submits the issue directly to GitHub with the screenshot attached.

---

[← Back to Documentation Hub](README.md)
