# E2E tests (Playwright)

End-to-end tests that drive the REAL application — the FastAPI backend and
the Vite frontend — through the core workflows, using the UI only (no direct
API calls).

## Run

```powershell
# one-time setup: install the browser binary (~170 MB)
npx playwright install chromium

# run the suite (starts both servers automatically)
npm run test:e2e
```

The Playwright config (`playwright.config.ts`) uses a `globalSetup` that
spawns both servers and waits for them to respond, and a `globalTeardown`
that kills the process trees and cleans up test artifacts:

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
4. **Features** (`features.spec.ts`) — image region coding, sidebar-code
   clicking, history view + filter, autocode + SQL report, cases + attributes,
   REFI-QDA interchange export/import, a11y smoke (accessible names).
5. **Inspector** (`inspector-annotation.spec.ts`) — file-inspector annotation.
6. **Media** (`media.spec.ts`) — AV coding on a generated WAV: timeline
   segments, delete, play/pause, the manual-transcription mode toggle, and a
   whisper transcription run (skipped when no spoken fixture exists).
7. **Roadmap** (`roadmap.spec.ts`) — v0.2.0 features: code promote/demote via
   the sidebar context menu, the reports registry (dictionary / statistics /
   summary table / sentiment / document comparison), QTT worksheet creation +
   note entry, the creative scratchpad, and value-labels selects in the
   attribute editor.
8. **Smoke** (`smoke-features.spec.ts`) — reports menu bar, graphs under
   reports, journal ribbon.
9. **Tasks + a11y** (`tasks-a11y.spec.ts`) — batch autocode with eligible
   counts on the batch buttons, the background-tasks queue flyout (pause/
   resume/delete/clear), the coder flyout (viewport bounds, per-coder
   trashcan, background-tasks section), sidebar drag-hide, display-mode a11y
   classes, and the PDF coder's plain-text pane (PDF + text side by side).

Flaky media-dependent flows (whisper transcription without a spoken fixture,
headless autoplay) carry explicit skip/fallback annotations instead of
weakening the assertions.

Tests run serially (single worker) because the backend keeps one project
open at a time and shares `~/.qualcoder/settings.json` (which the setup and
teardown delete so runs start clean).

## Notes

- Test projects are created under `%TEMP%\qc-e2e` and removed by the
  global teardown.
- The suite intentionally leaves `npm test` / `npm run build` untouched —
  the E2E files live in `tests-e2e/` outside the app `tsconfig` include.
