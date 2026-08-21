# E2E tests (Playwright)

End-to-end tests that drive the REAL application — the FastAPI backend and
the Vite frontend — through the core workflows, using the UI only (no direct
API calls). `COVERAGE.md` maps every documented user operation (`docs/*.md`)
to the spec that covers it.

## Run

```powershell
# one-time setup: install the browser binary (~170 MB)
npx playwright install chromium

# run the suite (starts both servers automatically) — from frontend/
npm run test:e2e
```

NOTE: the Playwright config lives in `frontend/playwright.config.ts`, and
Playwright only loads a config from the current working directory — running
`npx playwright test` inside `tests-e2e/` silently runs with DEFAULT settings
(no global setup, no base URL, many workers) and every test fails. Always run
from `frontend/`.

The Playwright config (`playwright.config.ts`) uses a `globalSetup` that
spawns both servers and waits for them to respond, then **pre-warms vite's
transform cache** (fetches `/src/main.tsx`, halving the first test's cold-app
cost), and a `globalTeardown` that kills the process trees and cleans up test
artifacts:

- backend: `backend\.venv\Scripts\python.exe -m uvicorn qualcoder_api.main:app --port 8765`
- frontend: `npm run dev -- --port 5173 --strictPort`

Logs land in `tests-e2e/server-backend.log` and `tests-e2e/server-frontend.log`
if a server fails to start.

## Requirements

- Node.js + npm (Playwright CLI)
- The backend virtualenv at `backend\.venv` (with uvicorn + fastapi installed)
- Ports 5173 (frontend) and 8765 (backend) free

## What it covers

The specs run alphabetically in one serial worker (see "Why serial" below):

1. **Advanced** (`advanced.spec.ts`) — PDF region coding, plain-text mode for
   PDFs, duplicate-import skip banner, theme persistence, recent-projects
   persistence and the nonexistent-project error path.
2. **App shell** (`app.spec.ts`) — dashboard without a project, create project,
   import + autocode + code-frequencies report, recent projects, settings +
   AI sections.
3. **Coding flows** (`coding-flows.spec.ts`) — graph create/delete, PDF text
   marking with the plain-text/PDF toggles, and the multi-code autocode dialog.
   Shares ONE project across its three tests.
4. **Coverage gaps** (`coverage-gaps.spec.ts`) — segment link copy/paste +
   jump, bookmarks, dictionary autocode, send-to-QTT from the coder, and the
   Publish dialog with a real .docx export.
5. **Features** (`features.spec.ts`) — image region coding, sidebar-code
   clicking, history view + filter, autocode + SQL report, cases + attributes,
   REFI-QDA interchange export/import, a11y smoke (accessible names).
6. **Inspector** (`inspector-annotation.spec.ts`) — file-inspector annotation.
7. **Media** (`media.spec.ts`) — AV coding on a generated WAV: timeline
   segments, delete, play/pause, the manual-transcription mode toggle, and a
   whisper transcription run (skipped when no spoken fixture exists).
8. **Roadmap** (`roadmap.spec.ts`) — later-round features: code promote/demote
   via the sidebar context menu, the reports registry (dictionary / statistics /
   summary table / sentiment / document comparison), QTT worksheet creation +
   note entry, the creative scratchpad, and value-labels selects in the
   attribute editor. Shares ONE project across its five tests.
9. **Smoke** (`smoke-features.spec.ts`) — reports menu bar, graphs under
   reports, journal ribbon.
10. **Sync** (`sync.spec.ts`) — collaboration sync end to end: the coder-flyout
    sync switch + status + "Sync now", the shared-folder auto-detect notice
    (project under a "OneDrive" path), and live coder presence (active-coder
    indicator + current file) via a simulated peer presence file.
11. **Tasks + a11y** (`tasks-a11y.spec.ts`) — batch autocode with eligible
    counts on the batch buttons, the background-tasks queue flyout (pause/
    resume/delete/clear), the coder flyout (viewport bounds, per-coder
    trashcan incl. the reassignment prompt, background-tasks section), sidebar
    drag-hide, display-mode a11y classes, and the PDF coder's plain-text pane
    (PDF + text side by side). Shares ONE project across its first four tests.
12. **Coverage wave** (`coverage-wave.spec.ts`) — History per-row undo/redo of
    a coding, Notes journal entry + code memo via the memos tab, the Files row
    context menu (rename/delete, Assign-to-case/Replace presence), the
    Sentiment lexicon report, the Statistics crosstab (chi-square) and the
    Summary-table file×code grid with a cell memo edit. Shares ONE project
    across its seven tests.

Flaky media-dependent flows (whisper transcription without a spoken fixture,
headless autoplay) carry explicit skip/fallback annotations instead of
weakening the assertions.

## Why serial (one worker)

`workers: 1` is intentional and must stay:

- The backend keeps ONE project open at a time (server-side singleton state)
  and specs rely on a defined file order (e.g. `app.spec.ts` wipes
  `%TEMP%\qc-e2e` in its `beforeAll`, which would delete another worker's
  project mid-run).
- The `about`-marker quirk (`features.spec.ts`) lets a project be opened only
  once per backend session, so parallel workers would collide on the same
  project files and lock files.
- `~/.qualcoder/settings.json` (recent projects, coders) is shared and wiped
  by setup/teardown.

## Speedups applied (2026-08)

Before: **37 tests, 1.9 m wall** (104 s of test time; the first test paid a
32.3 s cold-vite transform). After (current): **53 tests, ~4 m wall** across
12 specs — the growth is new specs (sync, tasks+a11y, coverage-wave), not
slower tests.

- **Vite prewarm in `global-setup.ts`** — fetches `/src/main.tsx` once the
  dev server is up; vite transforms the whole static module graph
  recursively. First test: 32.3 s → 16.1 s.
- **Shared project per spec file** (`coding-flows`, `roadmap`, `tasks-a11y`,
  `coverage-gaps`) — the first test creates the project, the rest re-open it
  from the recent list with the lock-file + `about`-marker repair, instead of
  creating a fresh project per test.
- **No fixed waits left** — all `waitForTimeout` calls replaced with
  `expect.poll(...)` on the canvas bounding box / element state.
- **Animations disabled** — `tests-e2e/helpers.ts` injects
  `*{animation:none!important;transition:none!important}` via
  `addInitScript` on every page (same effect as the app's reduced-motion
  a11y mode); Playwright's actionability waits no longer stall on
  transitioning elements.
- `contextOptions.reducedMotion: "reduce"` in the config as a second layer.

## Notes

- Test projects are created under `%TEMP%\qc-e2e` (plus `qc-tabtest`,
  `qc-roadmap`, `qc-tasks`, `qc-gaps` for the per-file projects) and removed
  by the global teardown / the next run's `beforeAll`.
- The suite intentionally leaves `npm test` / `npm run build` untouched —
  the E2E files live in `tests-e2e/` outside the app `tsconfig` include.
