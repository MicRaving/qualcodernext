# Dashboard — start screen

The app's home: project statistics with a project open; New/Open project and
recent projects without one. The app always starts on the dashboard.

## How to reach it

Ribbon → Dashboard, or the initial state of the app (with or without an open
project). Also the implicit empty state when no project is open.

## Layout slots used

Center only (`ViewHeader` + scrollable body). Ribbon shows (nav disabled
without a project); left/right bars and status bar are present with a
project, absent without one. The A11y controls and project dialogs live in
the center.

## Features

- **Stat cards**: Files, Codes, Code categories, Cases, Attribute types,
  Journal entries (read "—" without a project).
- **Header**: back-less ViewHeader with the project name + "Database version
  X · created Y" meta (or app name/version without a project).
- **New project**: opens the ProjectFormDialog (path input; in the Tauri
  shell a native folder picker pre-fills `<dir>\NewProject.qda`).
- **Open project**: in the Tauri shell the native folder picker IS the
  action — picking a folder opens the project immediately, no second click.
  In the plain browser a dialog with a path input is used.
- **Recent projects**: list of previously opened project paths from the
  backend; one click re-opens.
- **Auto-open progress**: while the packaged app starts its backend and
  auto-opens the last project, a spinner with the stage ("starting backend"
  / "opening recent") sits next to the Open button.
- **Accessibility controls**: the a11y mode dropdown (off / screenreader /
  high-contrast / large-text / reduced-motion / colorblind) with hint text.
- **Error banner** for failed create/open (e.g. "Project is in use by …").
- Opening a locked project reports the locking user.

## API endpoints used

- `POST /projects` (create), `POST /projects/open`, `GET /projects` (recent)
- `GET /projects/current/summary` (stats)

## Screenshot:

(to be inserted)
