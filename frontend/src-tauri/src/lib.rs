//! QualCoder v4 — Tauri 2 desktop shell.
//!
//! Responsibilities:
//! - Create the native window and load the frontend.
//!   `tauri dev` loads `build.devUrl` (Vite dev server, http://localhost:5173);
//!   `tauri build` loads `build.frontendDist` (the built SPA). Tauri 2 picks
//!   this up automatically — no manual URL handling is needed here.
//! - Spawn the Python FastAPI backend (localhost:8765) as a sidecar child
//!   process and kill it on exit.

use std::net::{SocketAddr, TcpStream};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

#[cfg(not(debug_assertions))]
use tauri::Manager;

/// Handle to the spawned backend process, kept alive for the app's lifetime.
/// `const Mutex::new` is stable since Rust 1.63; rust-version is 1.77.
static BACKEND_CHILD: Mutex<Option<Child>> = Mutex::new(None);

/// Returns whether the Python backend answers on 127.0.0.1:8765.
///
/// Placeholder for the tray menu (added later). The frontend already shows
/// backend status, so this command is not wired into the UI yet.
#[tauri::command]
fn backend_health() -> bool {
    let addr: SocketAddr = match "127.0.0.1:8765".parse() {
        Ok(addr) => addr,
        Err(_) => return false,
    };
    TcpStream::connect_timeout(&addr, Duration::from_millis(100)).is_ok()
}

/// Port the spawned backend actually bound (8765 or an ephemeral fallback
/// when a second instance is running). Read from the backend's port file
/// (`%TEMP%\qualcoder-port-<pid>.json`, written early by the backend before
/// its heavy imports). The onedir PyInstaller build runs in-process, so the
/// pid matches the spawned child; fall back to the newest port file in the
/// temp dir as a safety net.
#[tauri::command]
fn backend_port() -> Option<u16> {
    let temp_dir = std::env::temp_dir();
    let parse_port = |text: &str| -> Option<u16> {
        let json: serde_json::Value = serde_json::from_str(text).ok()?;
        json.get("port")?.as_u64().map(|p| p as u16)
    };

    // 1. The port file named after the spawned child pid.
    if let Ok(guard) = BACKEND_CHILD.lock() {
        if let Some(child) = guard.as_ref() {
            let path = temp_dir.join(format!("qualcoder-port-{}.json", child.id()));
            if let Ok(text) = std::fs::read_to_string(path) {
                if let Some(port) = parse_port(&text) {
                    return Some(port);
                }
            }
        }
    }

    // 2. Newest qualcoder-port-*.json in the temp dir.
    let mut newest: Option<(std::time::SystemTime, u16)> = None;
    if let Ok(entries) = std::fs::read_dir(&temp_dir) {
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if !name.starts_with("qualcoder-port-") || !name.ends_with(".json") {
                continue;
            }
            let Ok(meta) = entry.metadata() else { continue };
            let Ok(modified) = meta.modified() else { continue };
            let Ok(text) = std::fs::read_to_string(entry.path()) else { continue };
            if let Some(port) = parse_port(&text) {
                if newest.as_ref().map(|(m, _)| modified > *m).unwrap_or(true) {
                    newest = Some((modified, port));
                }
            }
        }
    }
    newest.map(|(_, port)| port)
}

/// Spawn the Python backend as a sidecar child process.
///
/// Dev: `python -m uvicorn qualcoder_api.main:app --port 8765` using the
/// backend venv interpreter, cwd = backend/ so data files resolve there.
/// The interpreter path is relative to the current working directory
/// (`cargo tauri dev` runs with cwd = src-tauri/, so `../../backend` is the
/// backend dir) and can be overridden with `QUALCODER_PYTHON`.
///
/// Release: runs the PyInstaller ONEDIR backend bundled under
/// `$RESOURCE/backend/` (extracted once by the installer — nothing is
/// unpacked at launch), then falls back to `QUALCODER_BACKEND_EXE` /
/// the dev venv interpreter so the release binary also works on a dev
/// machine.
fn start_backend(app: &tauri::AppHandle) {
    #[cfg(debug_assertions)]
    {
        let _ = app;
        let python = std::env::var("QUALCODER_PYTHON")
            .unwrap_or_else(|_| "../../backend/.venv/Scripts/python.exe".to_string());
        eprintln!("[tauri] spawning dev backend: {python} -m uvicorn qualcoder_api.main:app --port 8765");
        let child = Command::new(&python)
            .args(["-m", "uvicorn", "qualcoder_api.main:app", "--port", "8765"])
            .current_dir("../../backend")
            .spawn();
        store_child(child);
    }

    #[cfg(not(debug_assertions))]
    {
        let spawn_result = spawn_release_backend(app);
        store_child(spawn_result);
    }
}

#[cfg(not(debug_assertions))]
const BACKEND_PYTHON_ARGS: [&str; 5] = ["-m", "uvicorn", "qualcoder_api.main:app", "--port", "8765"];

#[cfg(not(debug_assertions))]
fn spawn_release_backend(app: &tauri::AppHandle) -> std::io::Result<Child> {
    use std::path::{Path, PathBuf};

    /// Spawn `python -m uvicorn ...` with the backend directory (derived
    /// from the interpreter path: .../backend/.venv/Scripts/python.exe)
    /// as the working directory so module/data paths resolve correctly.
    fn spawn_python(python: &Path) -> std::io::Result<Child> {
        let backend_dir = python
            .parent()
            .and_then(Path::parent)
            .and_then(Path::parent)
            .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::NotFound, "bad python path"))?;
        eprintln!("[tauri] spawning backend: {} (cwd {})", python.display(), backend_dir.display());
        Command::new(python)
            .args(BACKEND_PYTHON_ARGS)
            .current_dir(backend_dir)
            .spawn()
    }

    /// Spawn the bundled onedir backend from the resource dir
    /// (`$RESOURCE/backend/qualcoder-backend.exe`).
    fn spawn_resource_backend(app: &tauri::AppHandle) -> std::io::Result<Child> {
        let resource = app
            .path()
            .resolve("backend/qualcoder-backend.exe", tauri::path::BaseDirectory::Resource)
            .map_err(|err| std::io::Error::new(std::io::ErrorKind::NotFound, err.to_string()))?;
        if !resource.exists() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                "bundled backend not found in resources",
            ));
        }
        let dir = resource
            .parent()
            .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::NotFound, "bad resource path"))?;
        eprintln!("[tauri] spawning bundled backend: {} (cwd {})", resource.display(), dir.display());
        Command::new(&resource).current_dir(dir).spawn()
    }

    // 1. Bundled onedir in the resource dir (installed by the installer).
    if let Ok(child) = spawn_resource_backend(app) {
        return Ok(child);
    }

    // 2. Explicit backend executable.
    if let Ok(exe) = std::env::var("QUALCODER_BACKEND_EXE") {
        if !exe.is_empty() {
            eprintln!("[tauri] spawning bundled backend: {exe}");
            return Command::new(&exe).spawn();
        }
    }

    // 3. Explicit python interpreter.
    if let Ok(python) = std::env::var("QUALCODER_PYTHON") {
        if !python.is_empty() {
            return spawn_python(Path::new(&python));
        }
    }

    // 4. Dev venv relative to cwd (run from frontend/ or src-tauri/).
    let cwd_candidates = [
        PathBuf::from("../../backend/.venv/Scripts/python.exe"),
        PathBuf::from("../backend/.venv/Scripts/python.exe"),
    ];
    for candidate in &cwd_candidates {
        if candidate.exists() {
            return spawn_python(candidate);
        }
    }

    // 5. Dev venv relative to the executable's own directory.
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            let candidates = [
                exe_dir.join("backend/.venv/Scripts/python.exe"),
                exe_dir.join("../backend/.venv/Scripts/python.exe"),
            ];
            for candidate in &candidates {
                if candidate.exists() {
                    return spawn_python(candidate);
                }
            }
        }
    }

    Err(std::io::Error::new(
        std::io::ErrorKind::NotFound,
        "no QualCoder backend found (set QUALCODER_BACKEND_EXE or QUALCODER_PYTHON)",
    ))
}

/// Store the spawned child in the static (or log the spawn failure).
fn store_child(spawn_result: std::io::Result<Child>) {
    match spawn_result {
        Ok(child) => {
            let mut guard = match BACKEND_CHILD.lock() {
                Ok(guard) => guard,
                Err(poisoned) => poisoned.into_inner(),
            };
            *guard = Some(child);
        }
        Err(err) => {
            eprintln!("[tauri] failed to spawn backend: {err}");
        }
    }
}

/// Kill the backend child on app exit.
fn kill_backend() {
    let mut guard = match BACKEND_CHILD.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };
    if let Some(child) = guard.take() {
        let pid = child.id();
        #[cfg(windows)]
        {
            let _ = Command::new("taskkill")
                .args(["/T", "/F", "/PID", &pid.to_string()])
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .status();
        }
        #[cfg(not(windows))]
        {
            let mut child = child;
            let _ = child.kill();
            let _ = child.wait();
        }
    }
    drop(guard);
}

/// App entry point: build the Tauri app, then run the event loop so we can
/// observe `RunEvent::ExitRequested` and tear down the backend process.
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![backend_health, backend_port])
        .setup(|app| {
            start_backend(app.handle());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|_app_handle, event| {
        if let tauri::RunEvent::ExitRequested { .. } = event {
            kill_backend();
        }
    });
}



