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

1. **Welcome screen + theme toggle** — health pill shows "Backend ok", the
   theme button flips the `dark` class on `<html>`.
2. **Create project** — welcome form → project shell (toolbar, sidebar nav).
3. **Import + code** — import `interview.txt`, open it in the text coder,
   autocode the word "the" into a new code named `E2E`, verify the success
   message.
4. **Report** — Code frequencies shows `E2E` with count ≥ 1; close project
   and verify it appears in "Recent projects".
5. **Settings + AI** — reopen the project, check the Appearance and
   AI assistant sections render.

Tests run serially (single worker) because the backend keeps one project
open at a time and shares `~/.qualcoder/settings.json` (which the setup and
teardown delete so runs start clean).

## Notes

- Test projects are created under `%TEMP%\qc-e2e` and removed by the
  global teardown.
- The suite intentionally leaves `npm test` / `npm run build` untouched —
  the E2E files live in `tests-e2e/` outside the app `tsconfig` include.
