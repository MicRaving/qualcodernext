# Tauri 2 Desktop Shell — QualCoder v4

**STATUS: VERIFIED (2026-08-05).** Self-contained release exe working:
the Python backend is embedded in the Tauri binary, extracted to a temp
file at startup, spawned, and the whole process tree is killed on app
exit. The full create → close → open → close → open project flow is
verified against the embedded backend.

## What this is

`src-tauri/` is a Tauri 2.x scaffold that:

1. Creates the native window (1280x800, min 1024x700).
2. Spawns the Python FastAPI backend (`qualcoder_api.main:app` on
   `localhost:8765`) as a sidecar child process at app startup.
3. Kills the backend process tree on app exit (`RunEvent::ExitRequested`).
4. Loads the frontend: Vite dev server (`http://localhost:5173`) under
   `tauri dev` (from `build.devUrl`), the built SPA (`../dist`) under
   `tauri build` (from `build.frontendDist`). Tauri 2 handles this switch
   automatically — no URL logic in Rust.

Backend discovery (release builds, in order):

1. **Embedded bytes** — `build.rs` embeds `../../backend/dist/qualcoder-backend.exe`
   (PyInstaller onefile) into the binary via `include_bytes!`. At startup
   `lib.rs` extracts them to `%TEMP%\qualcoder-backend-<pid>.exe`, spawns
   the exe, and removes the temp file on exit. This makes the release exe
   fully self-contained (~67 MB, no Python, no venv, no server install).
2. `QUALCODER_BACKEND_EXE` (explicit backend exe, spawned with no args).
3. `QUALCODER_PYTHON` (interpreter + uvicorn args).
4. The dev venv relative to the current working directory, then relative to
   the executable's own directory. The backend's working directory is
   derived from the found interpreter (`.../backend/.venv/Scripts/python.exe`
   → `.../backend`).

Exposes one command to the frontend: `backend_health() -> bool` (TCP connect
probe to 127.0.0.1:8765, 100ms timeout). Intended for the tray menu later;
the React UI already shows backend status itself.

## Getting it running on this machine (Windows)

1. **Rust**: install via <https://rustup.rs> (default stable toolchain; MSRV
   1.77 declared in `Cargo.toml`).
2. **Visual Studio Build Tools**: install with the "Desktop development with
   C++" workload (MSVC linker needed by the `wry`/`tao` chain).
3. **WebView2 Runtime**: usually preinstalled on Windows 10/11; if not, grab
   it from Microsoft.
4. Frontend deps are already installed (`npm install` done). Build once:
   ```powershell
   npm run build
   ```
5. Dev run — loads the Vite dev server, backend spawns from the backend venv:
   ```powershell
   cd src-tauri
   cargo tauri dev
   ```
   The backend interpreter defaults to `../../backend/.venv/Scripts/python.exe`
   (relative to `src-tauri/`, i.e. the venv created for the FastAPI backend).
   Override with the `QUALCODER_PYTHON` env var.

`cargo tauri dev` will download ~500 crates and take a long time on the first
build.

## Release flow

Use the repo-root `compile.ps1` (or `compile.bat`) — it runs PyInstaller
(backend), `npm run build`, and `npx @tauri-apps/cli build` in the right
order, then reports the artifacts:

```
backend\dist\qualcoder-backend.exe
frontend\src-tauri\target\release\qualcoder-tauri.exe   (self-contained)
frontend\src-tauri\target\release\bundle\nsis\QualCoder_*-setup.exe
frontend\src-tauri\target\release\bundle\msi\QualCoder_*.msi
```

Notes:
- The Tauri build is incremental: after a backend change, rebuild only the
  backend exe (`compile.ps1 -SkipTauri`) — the next `cargo build` re-embeds
  it because `build.rs` declares `cargo:rerun-if-changed` on it. To fully
  refresh the app exe after an embed change, run `compile.ps1 -SkipBackend`
  or a plain `cargo build --release` in `src-tauri/`.
- No auto-updater plugin: the app is distributed as a single self-contained
  executable. `updater.key`/`updater.key.pub` at the repo root are unused
  leftovers from an earlier milestone and can be deleted.

## Files

```
src-tauri/
├── Cargo.toml            # package qualcoder-tauri v0.1.0 (rust-version 1.77)
├── build.rs              # tauri_build::build() + embedded-backend include_bytes!
├── tauri.conf.json       # Tauri 2 config (schema.tauri.app/config/2)
├── capabilities/
│   └── default.json      # core:default + shell:allow-open for window "main"
└── src/
    ├── main.rs           # entry: qualcoder_tauri_lib::run(); hidden console in release
    └── lib.rs            # window + sidecar backend lifecycle + backend_health command
```

## Gotchas

- **`tauri_build::build()` must stay in `build.rs`.** It embeds the Windows
  SxS manifest (comctl32 v6 dependency) — without it the release exe fails
  at load with `0xC0000139` / "Entry Point Not Found: TaskDialogIndirect"
  (the `tray-icon` feature imports comctl32 v6 subclassing functions).
- The PyInstaller onefile backend spawns a child process; `child.kill()` on
  the bootloader leaves the grandchild alive. `kill_backend()` uses
  `taskkill /T /F` to kill the whole tree before deleting the temp exe.
- A crashed/force-killed app leaves `%TEMP%\qualcoder-backend-<pid>.exe`
  behind (normal — it is cleaned on the next graceful exit or manually).
- `src-tauri/` lives outside `src/`, so `npm run build` / `npm test` are
  unaffected by Rust code.
- The shell plugin is registered (`tauri-plugin-shell`) and
  `shell:allow-open` is granted in the capability so the webview can open
  external links. Do not grant `shell:allow-execute` without a security
  review.
- `tauri-plugin-dialog` is registered (`dialog:default` capability) — the
  welcome screen's Browse buttons use the native directory picker via
  `@tauri-apps/plugin-dialog`. In plain-browser dev (no Tauri shell) the
  buttons are hidden and paths are typed into the text inputs.
- Backend CORS already includes `tauri://localhost` (see
  `backend/src/qualcoder_api/main.py`).
