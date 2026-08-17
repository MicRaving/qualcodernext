# Status & Tasks — background jobs, the queue, and collaboration sync

QCnext runs long work in the **background**: transcription, autocode, R runs,
and file imports. A single **sequential queue** guarantees nothing runs in
parallel with the current job. The same flyout also carries the app-update
status. This page also explains the **collaboration sync** mechanism that lets
several coders work on the same project simultaneously.

## How to reach it

- **Task queue**: the circular-progress chip in the ribbon (visible whenever
  tasks exist or an import is running) → the "Tasks" flyout.
- **Coder flyout + sync**: the coder switcher button (person icon + coder name
  + sync dot) → its flyout.

## Background jobs

- **Kinds**: `transcribe` (Whisper transcription), `autocode` (AI/dictionary
  autocode), `r` (R script runs), `import` (file imports). Each job tracks
  state (queued / running / done / error), progress %, a message, and pause
  state.
- **Sequential queue**: a dispatcher starts queued jobs **one at a time** —
  nothing runs in parallel. Pausing halts the dispatcher and pauses the
  running transcription job (an in-flight autocode finishes its file, then
  waits).
- **The flyout**: per-job rows (kind icon, source name, state: percent /
  queued / ✓ / ✗, a progress bar, remove button), **drag-to-reorder** queued
  jobs, a pause/resume button, and clear-finished. The **file-import
  progress** row (done/total) and the **app-update** row (available →
  download, downloading → progress) ride in the same flyout.
- **Completion**: the shell polls running jobs every 1.5 s; a finished job
  refreshes the project and shows a toast (announced in screen-reader mode).

## Collaboration sync

QCnext supports several coders working on **separate copies of the same
project folder**, shared through any folder-sync tool (Nextcloud, ownCloud,
Sync&Share, Syncthing, Dropbox, …). The SQLite database is **never merged by
the sync tool** (that corrupts projects). Instead:

1. Every mutation is captured into a `sync_log` with full row snapshots.
2. Every 60 seconds (or via **Sync now**) the app appends your local changes
   to `changes/<your-coder-name>/changes.jsonl` inside the project folder —
   the sync tool carries those files.
3. Every 60 seconds the app imports your collaborators' sidecar files and
   **replays** them: INSERT/UPDATE/DELETE by primary key, last-write-wins per
   row, with automatic primary-key remapping when two coders' autoincrement
   counters collide. Replay never re-exports (no ping-pong).
4. The toolbar sync chip shows pending changes and collaborators' last-sync
   times.

### Using sync

- Enable/disable the cycle from the coder switcher flyout; the status shows
  last-sync time, pending changes and the last error (polled every 30 s while
  the flyout is open or sync is on); **Sync now** runs an immediate cycle.
- The sync dot is **green** when syncing healthily, **red** on error, **grey**
  when off.
- **Per-coder visibility**: hide a coder's codings from other users' views
  (useful for blind reliability checks).

### Rules of thumb

- Give every rater a **unique coder name** (never share one coder across
  machines).
- Do not sync per-machine artifacts: `project_in_use.lock`,
  `ai_index.sqlite3`, `backups/` (sync state lives in `~/.qualcoder/sync/`).

## Project lock

Opening a project that another live instance holds reports the **locking
user** — so two people editing the same copy at the same time are warned, and
the sync workflow (separate copies) stays the supported way to collaborate.

## High-level logic

The whole design is "Option B": **change logs carried by the folder-sync
tool**, never the live database. Because each rater's changes are journaled
with row snapshots, the app can merge them deterministically (per-row
last-write-wins, natural-key fallback for codings, PK remapping on counter
collisions) without any central server — QCnext projects remain fully offline
and local.
