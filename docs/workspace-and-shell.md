# Workspace Shell, Projects \& Collaboration

[← Back to Documentation Hub](README.md)

This guide covers the core application structure of QCnext: project creation and management, the 5-slot workspace layout, background job execution, asynchronous multi-coder collaboration sync, the full audit history with per-row undo/redo, and the integrated bug reporter.

\---

## Dashboard \& Project Management

The **Dashboard** is the application home screen for opening / creating projects and showing basic project statistics and shortcuts.

!\[Active Project Dashboard](screenshots/02-dashboard-project.png)

* **New Project**: Opens the project creation dialog. Keep in mind that projects are hosted in folders.
* **Open Project**: Opens the system folder picker to open an existing project folder.
* **Recent Projects**: Displays recently opened projects.
* **Accessibility Controls**: Quick dropdown to select high-contrast, screenreader, large-text, reduced-motion, or colorblind-friendly modes (experimental).

> \[!NOTE]
> \*\*Project Lock Protection\*\*: If a project folder is currently opened by another running instance of QCnext, a warning banner will notify you of the active lock to prevent database corruption. Your changes will then be saved in a separate folder and merged by the other QualCoder instance.

\---

## The General Layout

QCnext's layout is divided into a ribbon, left bar, center view, and right bar

You can resize and hide the sidebars by dragging their inner border (may occasionally distort the layout).



The top navigation bar, **The Ribbon**, contains buttons for QCnext's main windows: *Dashboard*, *Coding* (File Manager), *Cases*, *Journal*, a worksheet *Crafter*, and *Reports* (Analysis). 



It also contains a **Task Queue Indicator** that displays background execution status of long tasks (automatic transcription and coding) with a progress ring. Clicking on it opens a flyout in which tasks can be re-prioritized, paused and canceled.



The **Collaboration** flyout allows switching the active coder and toggling collaboration sync. Multiple raters can work on the **same project simultaneously** without requiring a dedicated server. QCnext automatically detects potential shared folders and turns sync on/off, but you can always override this setting.

When turned on, raters work as **different coders on separate copies of the same `.qda` project folder**, shared through any folder-sync tool (Nextcloud, ownCloud, Sync\&Share, Syncthing, Dropbox, ...). Instead of merging the SQLite database via the sync tool, every instance writes its own change journal (`changes/<coder>/changes.jsonl`) and merges each other's changes on an **asynchronous ~60-second cycle** (plus on demand via the "Sync now" button). Changes converge eventually — this is *not* real-time editing: two raters editing the same segment within one cycle can overwrite each other, and conflicts are reported in the flyout and retried on later cycles.

> \\\[!WARNING]
> Give every rater a **unique coder name**; **NEVER** work as the same coder on multiple instances simultaneously - you WILL lose data! When you open a project that another instance already has open under the same coder name, QCnext shows a warning — switch to a unique coder name before continuing.



**The Left Bar** holds view-specific navigation. You will usually see the files list if no file is open, the codes if a file is open, the case list in Cases, report list in Analysis, or worksheet list in Crafter.



**The Center View** is the primary area where coding, analysis, editing, and report generation take place.



**The Right Bar** shows detail pages with additional information by default:

* For files, it shows  metadata, memo, linked cases, and character count.
* For codes, it shows code details, parent category, memo, color swatch, and recent segment shortcuts.

Adding specific memos and comments, assigning to cases, or just viewing stats for the specific code/file is assembled here.



You can also toggles between the following panes:

* 🕒 **History**: Opens the project history for undoing every step in this project (experimental!).Every action in QCnext is logged in an immutable project audit history. You can filter log entries by action type (coding create, code delete, text edit), coder name, or text query. Unlike traditional full-project rollbacks, clicking the undo icon on a log entry safely reverts that specific change (e.g., restoring a deleted coding or reverting a code rename) without affecting other work. You can also redo up to 10 recently undone actions. Clicking an entry also displays  details on the exact step.
* ✨ **AI Assistant**: Opens the AI chat and semantic search pane.
* 💡 **Creative Coding**: Opens the creative scratchpad pane.
* 🐞 **Report Bug**: QCnext is beta software and will contain bugs. If you encounter an issue or wish to submit feedback, QCnext includes a built-in issue composer. It automatically takes a screenshot that you can redact, automatically tries to populate your report with context, and generally simplifies the ticket submission.
* ⚙️ **Settings**: Opens application settings (theme, AI config, updates).

\---

[← Back to Documentation Hub](README.md)

