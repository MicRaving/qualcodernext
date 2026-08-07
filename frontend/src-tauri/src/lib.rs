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
use std::path::PathBuf;
#[cfg(not(debug_assertions))]
use tauri::Manager;

/// Handle to the spawned backend process, kept alive for the app's lifetime.
/// `const Mutex::new` is stable since Rust 1.63; rust-version is 1.77.
static BACKEND_CHILD: Mutex<Option<Child>> = Mutex::new(None);

/// Temp file the embedded backend was extracted to (cleaned up on exit).
#[cfg(not(debug_assertions))]
static BACKEND_TEMP_FILE: Mutex<Option<PathBuf>> = Mutex::new(None);

// Embedded backend bytes (set by build.rs from backend/dist/qualcoder-backend.exe).
#[cfg(not(debug_assertions))]
include!(concat!(env!("OUT_DIR"), "/backend_embedded.rs"));

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
/// when a second instance is running). Read from the backend's port file.
#[tauri::command]
fn backend_port() -> Option<u16> {
    let pid = BACKEND_CHILD.lock().ok()?.as_ref()?.id().to_string();
    let path = std::env::temp_dir().join(format!("qualcoder-port-{pid}.json"));
    let text = std::fs::read_to_string(path).ok()?;
    let json: serde_json::Value = serde_json::from_str(&text).ok()?;
    json.get("port")?.as_u64().map(|p| p as u16)
}

/// Spawn the Python backend as a sidecar child process.
///
/// Dev: `python -m uvicorn qualcoder_api.main:app --port 8765` using the
/// backend venv interpreter, cwd = backend/ so data files resolve there.
/// The interpreter path is relative to the current working directory
/// (`cargo tauri dev` runs with cwd = src-tauri/, so `../../backend` is the
/// backend dir) and can be overridden with `QUALCODER_PYTHON`.
///
/// Release: prefers the embedded PyInstaller-bundled `qualcoder-backend`
/// executable (single-file extraction), then falls back to
/// `QUALCODER_BACKEND_EXE` / the dev venv interpreter so the release binary
/// also works on a dev machine.
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

    /// Spawn the embedded backend: extract the bytes to a unique temp file
    /// and run it. The path is remembered so it can be removed on exit.
    fn spawn_embedded() -> std::io::Result<Child> {
        if BACKEND_EXE.is_empty() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                "no embedded backend (build without backend/dist)",
            ));
        }
        let temp_path = std::env::temp_dir().join(format!("qualcoder-backend-{}.exe", std::process::id()));
        std::fs::write(&temp_path, BACKEND_EXE)?;
        eprintln!("[tauri] spawning embedded backend: {}", temp_path.display());
        let child = Command::new(&temp_path).spawn();
        match &child {
            Ok(_) => {
                if let Ok(mut guard) = BACKEND_TEMP_FILE.lock() {
                    *guard = Some(temp_path);
                }
            }
            Err(_) => {
                let _ = std::fs::remove_file(&temp_path);
            }
        }
        child
    }

    // 1. Explicit backend executable (PyInstaller onefile, no args).
    if let Ok(exe) = std::env::var("QUALCODER_BACKEND_EXE") {
        if !exe.is_empty() {
            eprintln!("[tauri] spawning bundled backend: {exe}");
            return Command::new(&exe).spawn();
        }
    }

    // 2. Embedded bytes (release builds compiled via compile.ps1).
    if let Ok(child) = spawn_embedded() {
        return Ok(child);
    }

    // 3. Bundled resource (`bundle.resources` → resource dir).
    if let Ok(resource) = app
        .path()
        .resolve("qualcoder-backend.exe", tauri::path::BaseDirectory::Resource)
    {
        if resource.exists() {
            eprintln!("[tauri] spawning bundled backend resource: {}", resource.display());
            return Command::new(&resource).spawn();
        }
    }

    // 4. Explicit python interpreter.
    if let Ok(python) = std::env::var("QUALCODER_PYTHON") {
        if !python.is_empty() {
            return spawn_python(Path::new(&python));
        }
    }

    // 5. Dev venv relative to cwd (run from frontend/ or src-tauri/).
    let cwd_candidates = [
        PathBuf::from("../../backend/.venv/Scripts/python.exe"),
        PathBuf::from("../backend/.venv/Scripts/python.exe"),
    ];
    for candidate in &cwd_candidates {
        if candidate.exists() {
            return spawn_python(candidate);
        }
    }

    // 6. Dev venv relative to the executable's own directory.
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
///
/// On Windows the direct `kill()` only terminates the PyInstaller bootloader,
/// leaving its onefile child alive — so the whole process tree is killed.
/// (Backup: taskkill /T /F /PID <pid>.)
fn kill_backend() {
    let mut guard = match BACKEND_CHILD.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };
    if let Some(mut child) = guard.take() {
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
            let _ = child.kill();
            let _ = child.wait();
        }
    }
    drop(guard);

    // Remove the extracted embedded backend from the temp dir. The process
    // tree has just been killed but Windows may still hold a transient
    // handle on the exe (AV scan etc.) — retry briefly.
    #[cfg(not(debug_assertions))]
    {
        let mut temp_guard = match BACKEND_TEMP_FILE.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        };
        if let Some(path) = temp_guard.take() {
            for _ in 0..25 {
                match std::fs::remove_file(&path) {
                    Ok(()) => break,
                    Err(_) => std::thread::sleep(Duration::from_millis(250)),
                }
            }
        }
    }
}

/// App entry point: build the Tauri app, then run the event loop so we can
/// observe `RunEvent::ExitRequested` and tear down the backend process.
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
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


