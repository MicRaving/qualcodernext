# Shell — workspace layout, ribbon, status bar, task queue, coder switcher

The shell is the app skeleton around every screen. It is implemented by
`frontend/src/components/shell/WorkspaceLayout.tsx` (layout engine) and
`frontend/src/components/shell/ProjectShell.tsx` (content wiring).

## How to reach it

Always visible. With a project open the full five-slot layout renders; without
one only the ribbon (navigation disabled) and the dashboard empty state show.

## Layout slots used

All slots, always: ribbon, optional menu bar, left bar, center, right bar,
status bar. Left and right bars are resizable by dragging their inner border
(clamped 200–520 px; dragging past ~140 px hides the bar, recalled from an
edge tab). The center is `flex-1 overflow-hidden`.

## Features

- **Ribbon** (h-11): nav buttons Dashboard / Files / Cases / Notes / QTT /
  Reports (icon 20 + label, active = accent) followed by a divider, then the
  task-queue chip (circular progress + active job count, opens the queue
  flyout), the coder switcher, and the right icon buttons History / AI /
  Creative (20 px, toggle right-bar panes) and Settings (available even
  without a project — theme/AI/transcription options are machine-level).
- **Menu bar** (optional, h-10): the view's function bar — currently only the
  Graphs toolbar uses it.
- **Left bar**: per-view list (Sidebar, CasesList, NotesList, QttList,
  ReportsList) — see the per-view docs.
- **Right bar**: the Inspector by default; History / AI / Settings / Creative
  panes are toggled from the top bar (clicking the active button closes the
  pane; opening a file in the coder switches back to the Inspector).
- **Status bar** (h-6): project name · "N files · M codes" (+ cases /
  journals / annotations / memos counts when non-zero) · spacer · app version.
- **Task queue flyout**: opened from the progress chip in the ribbon; lists
  transcribe/autocode jobs with progress bars, pause/resume (pause halts the
  dispatcher and pauses the running transcription job), clear-finished, and
  drag-to-reorder of queued jobs. Also hosts the app-update status row
  (update available → download button, downloading → progress) and the file
  import progress bar. Jobs run strictly sequentially (a dispatcher starts
  queued jobs one at a time; nothing runs in parallel).
- **Coder switcher**: single ribbon button (user icon + coder name + sync
  dot + chevron). Its flyout lists all coders with per-coder coding counts
  and lets you switch coder, add a new coder (inline name input), rename,
  delete (with reassignment prompt when the coder still owns codings), toggle
  a coder's visibility for other sync users, and view per-coder stats
  (per-table counts). The flyout also hosts the collaboration-sync switch:
  enable/disable the background sync cycle, see last-sync time / pending
  changes / errors, run an immediate sync.
- **Inspector** (right-bar default): details of the selected code or file.
  Code details: "Highlight in open file" toggle (dims all other codes'
  segments in the open coder), inline memo editor (opened in edit mode by
  any "Edit memo" action), color swatch, category path, counts, recent
  segment examples (click to jump+flash the segment in the coder), and links
  (incoming/outgoing with jump and delete). File details: type / date /
  owner, memo editor, "Open in coder". Right-clicking the memo label opens
  the Memos tab in Notes. New annotations can be added inline from the
  Inspector (`inspectorNewAnnotation` flag).
- **A11y**: screen-reader mode mounts an aria-live region for task
  announcements and a visible skip link; right-click context menus are
  custom everywhere (browser menu prevented globally).
- **Theme + a11y modes**: persisted in localStorage; dark mode toggled on
  `<html>`; a11y classes (`screenreader`, `high-contrast`, `large-text`,
  `reduced-motion`, `colorblind`).

## API endpoints used

- `/coders` (list/current), `/coders/{name}` (PATCH rename, DELETE with
  optional reassign), `/coders/current` (PUT switch), `/coders/{name}/stats`,
  `/coders/visibility`, `/coders/{name}/visibility` (PUT)
- `/sync/settings` (GET/PUT), `/sync/status`, `/sync/now`
- `/transcribe/jobs/{job_id}` (poll), `/transcribe/jobs/{job_id}/{action}`
  (start/pause/resume), `/autocode/jobs/{job_id}`, `/autocode/jobs/{job_id}/{action}`
- `/health`, `/updates/settings` (GET/PUT)
- Inspector: `/codes/{cid}/details`, `/sources/{source_id}/details`,
  `/annotations` (all), links `/links` (outgoing/incoming), `/bookmarks`

## Screenshot:

(to be inserted)
