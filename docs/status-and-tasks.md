# Status & tasks — background jobs, queue, collaboration sync

Everything that runs in the background: transcription and autocode jobs with
a sequential queue, file import progress, and the folder-sync collaboration
mechanism. UI lives in the ribbon (progress chip + flyout) and the coder
switcher flyout.

## How to reach it

- Task queue: the circular-progress chip in the ribbon (visible whenever
  tasks exist or an import is running) → the "Tasks" flyout.
- Coder flyout + sync: the coder switcher button (user icon + name + sync
  dot) → its flyout.

## Layout slots used

Ribbon slot (chip, flyout) and the coder switcher flyout; no center view.

## Features

- **Job kinds**: `transcribe` (background Whisper transcription) and
  `autocode` (background AI/dictionary autocode). Each job tracks state
  (queued / running / done / error), progress %, a message, and pause state.
- **Sequential queue**: the shell's dispatcher starts queued jobs one at a
  time — nothing runs in parallel with the current job. Pausing halts the
  dispatcher and pauses the running transcription job (autocode finishes
  its file, then waits).
- **Flyout**: per-job rows (kind icon, source name, state: percent /
  queued / ✓ / ✗, progress bar, remove button), drag-to-reorder queued jobs,
  pause/resume button, clear finished, "clear finished" menu item, and the
  import progress row (done/total). The app-update row (available →
  download, downloading → progress) rides in the same flyout.
- **Completion**: the shell polls running jobs (1.5 s); a finished job
  refreshes the project and toasts (and, in screen-reader mode, announces).
- **Import progress**: `importState {done,total}` drives the ribbon chip's
  fill and the flyout row while files import sequentially.
- **Collaboration sync** (Option B: sidecar change files over folder sync):
  - Enable/disable the background sync cycle from the coder switcher flyout.
  - Status: last-sync time, pending changes, last error; polled while the
    flyout is open or sync is on (30 s); "Sync now" button.
  - The coder switcher's sync dot is green when syncing (red on error,
    grey when off); a title tooltip shows "last sync <n>m" or the error.
  - Per-coder visibility: hide a coder's codings from other users' views.
- **Project lock**: opening a project in use by another user reports the
  locking user.

## API endpoints used

- `GET /transcribe/jobs/{id}`, `POST /transcribe/jobs/{id}/{action}`,
  `DELETE /transcribe/jobs/{id}` (cancel)
- `GET /codings/autocode/jobs/{id}`, `POST /codings/autocode/jobs/{id}/{action}`,
  `DELETE /codings/autocode/jobs/{id}`
- `POST /transcribe` / `POST /codings/autocode/batch` (job creation,
  `start:false` for queued)
- `GET /sync/settings`, `PUT /sync/settings`, `GET /sync/status`,
  `POST /sync/now`
- `GET /coders/visibility`, `PUT /coders/{name}/visibility`
- `GET /updates/settings`, `PUT /updates/settings` (update status row)

## Screenshot:

(to be inserted)
