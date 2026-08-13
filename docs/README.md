# QualCoder v4 — Documentation

This is the screen-by-screen documentation of the QualCoder v4 rework
(QCnext). Every screen, dialog and feature of the application is described
here, derived from the codebase (`frontend/` and `backend/`). The UI design
language itself lives in `frontend/src/DESIGN.md`; these pages describe what
each screen does and how it is built out of the `WorkspaceLayout` slots.

## Screen map

| Screen / feature | File |
|---|---|
| Shell: ribbon, status bar, task queue, coder switcher, Inspector | [shell.md](shell.md) |
| Dashboard (start screen, projects, recent, a11y) | [dashboard.md](dashboard.md) |
| File manager (import, filters, URL import, batch jobs, links repair) | [files.md](files.md) |
| Text coder | [coding-text.md](coding-text.md) |
| PDF coder | [coding-pdf.md](coding-pdf.md) |
| Image coder | [coding-image.md](coding-image.md) |
| Audio/video coder (timeline, transcript, manual transcription, speakers) | [coding-av.md](coding-av.md) |
| Cases + attributes | [cases.md](cases.md) |
| Notes (journal, annotations, memos) | [notes.md](notes.md) |
| Analysis area — all reports (frequencies … doc-compare, codebook, references, SQL) | [analyze.md](analyze.md) |
| QTT workspace (Questions-Themes-Theories) | [qtt.md](qtt.md) |
| Graph editor + models | [graphs.md](graphs.md) |
| Creative coding panel | [creative.md](creative.md) |
| AI chat, semantic search, settings, MCP | [ai.md](ai.md) |
| Settings pane (theme, a11y, AI config, pseudonyms, updates) | [settings.md](settings.md) |
| Import/export (interchange) | [interchange.md](interchange.md) |
| Audit log (history) + undo/redo | [history.md](history.md) |
| Background tasks, queue, collaboration sync | [status-and-tasks.md](status-and-tasks.md) |

## Coverage checklist

- WorkspaceView kinds: dashboard, files, coding, cases, notes, qtt, analyze,
  graphs, history, settings, ai — all covered.
- RightPane values: inspector (shell.md), ai (ai.md), settings (settings.md),
  history (history.md), creative (creative.md) — all covered.
- ReportIds: code-frequencies, code-segments, file-code, code-relations,
  interrater, text-corpus, dictionary, stats, summary-table, sentiment,
  doc-compare, codebook, references, sql, graphs — all covered in analyze.md
  and graphs.md.
