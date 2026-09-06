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

mod native_plan;

/// Windows: spawn helper processes (python, the PyInstaller backend,
/// taskkill) WITHOUT a flashing console window. taskkill.exe is a console
/// program — invoked plainly at app exit it briefly popped a terminal.
#[cfg(windows)]
fn hide_console(mut cmd: Command) -> Command {
    use std::os::windows::process::CommandExt;

    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    cmd.creation_flags(CREATE_NO_WINDOW);
    cmd
}

/// No-op on platforms without console windows.
#[cfg(not(windows))]
fn hide_console(cmd: Command) -> Command {
    cmd
}

#[cfg(not(debug_assertions))]
use tauri::Manager;

/// Handle to the spawned backend process, kept alive for the app's lifetime.
/// `const Mutex::new` is stable since Rust 1.63; rust-version is 1.77.
static BACKEND_CHILD: Mutex<Option<Child>> = Mutex::new(None);

#[cfg(windows)]
static BACKEND_JOB: Mutex<Option<windows::Win32::Foundation::HANDLE>> = Mutex::new(None);

#[cfg(windows)]
fn ensure_backend_job() -> Option<windows::Win32::Foundation::HANDLE> {
    let mut guard = match BACKEND_JOB.lock() {
        Ok(g) => g,
        Err(p) => p.into_inner(),
    };
    if let Some(handle) = *guard {
        if !handle.is_invalid() {
            return Some(handle);
        }
    }
    unsafe {
        use windows::Win32::System::JobObjects::{
            CreateJobObjectW, JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JobObjectExtendedLimitInformation,
            SetInformationJobObject, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        };
        let handle = match CreateJobObjectW(None, windows::core::PCWSTR::null()) {
            Ok(h) => h,
            Err(_) => return None,
        };
        if handle.is_invalid() {
            return None;
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if SetInformationJobObject(
            handle,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const std::ffi::c_void,
            std::mem::size_of_val(&info) as u32,
        )
        .is_err()
        {
            let _ = windows::Win32::Foundation::CloseHandle(handle);
            return None;
        }
        *guard = Some(handle);
        Some(handle)
    }
}

#[cfg(windows)]
fn assign_child_to_job(child: &Child) {
    let Some(job) = ensure_backend_job() else { return };
    unsafe {
        use windows::Win32::System::JobObjects::AssignProcessToJobObject;
        use windows::Win32::System::Threading::{OpenProcess, PROCESS_SET_QUOTA, PROCESS_TERMINATE};
        let pid = child.id();
        let proc_handle = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, false, pid);
        if let Ok(handle) = proc_handle {
            let _ = AssignProcessToJobObject(job, handle);
            let _ = windows::Win32::Foundation::CloseHandle(handle);
        }
        let _ = std::mem::ManuallyDrop::new(job);
    }
}

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
        let child = hide_console(Command::new(&python))
            .args(["-m", "uvicorn", "qualcoder_api.main:app", "--port", "8765", "--loop", "asyncio", "--http", "httptools"])
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
const BACKEND_PYTHON_ARGS: [&str; 9] = ["-m", "uvicorn", "qualcoder_api.main:app", "--port", "8765", "--loop", "asyncio", "--http", "httptools"];

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
        hide_console(Command::new(python))
            .args(BACKEND_PYTHON_ARGS)
            .current_dir(backend_dir)
            .spawn()
    }

    /// Spawn the bundled onedir backend from the resource dir
    /// (`$RESOURCE/backend/qualcoder-backend[.exe]` — PyInstaller names the
    /// binary without an extension on Linux/macOS).
    fn spawn_resource_backend(app: &tauri::AppHandle) -> std::io::Result<Child> {
        #[cfg(windows)]
        let backend_name = "backend/qualcoder-backend.exe";
        #[cfg(not(windows))]
        let backend_name = "backend/qualcoder-backend";
        let resource = app
            .path()
            .resolve(backend_name, tauri::path::BaseDirectory::Resource)
            .map_err(|err| std::io::Error::new(std::io::ErrorKind::NotFound, err.to_string()))?;
        if !resource.exists() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                format!("bundled backend not found in resources ({backend_name})"),
            ));
        }
        let dir = resource
            .parent()
            .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::NotFound, "bad resource path"))?;
        eprintln!("[tauri] spawning bundled backend: {} (cwd {})", resource.display(), dir.display());
        hide_console(Command::new(&resource)).current_dir(dir).spawn()
    }

    // 1. Bundled onedir in the resource dir (installed by the installer).
    if let Ok(child) = spawn_resource_backend(app) {
        return Ok(child);
    }

    // 2. Explicit backend executable.
    if let Ok(exe) = std::env::var("QUALCODER_BACKEND_EXE") {
        if !exe.is_empty() {
            eprintln!("[tauri] spawning bundled backend: {exe}");
            return hide_console(Command::new(&exe)).spawn();
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
            #[cfg(windows)]
            assign_child_to_job(&child);
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

/// Restart the backend child process (e.g. after staging a backend-source
/// overlay) and return the new backend's port once it answers.
///
/// The old child is terminated the same way as on app exit; the new child
/// is spawned with the same resolution order (bundled onedir first). The
/// caller re-resolves its API base (the port may change) and reopens its
/// project — the backend shuts down cleanly (open project closed) before
/// the old process exits.
#[tauri::command]
fn restart_backend(app: tauri::AppHandle) -> Result<u16, String> {
    kill_backend();
    // Give the OS a beat to release the port and remove the old port file
    // (taskkill is asynchronous; the old backend deletes its own file on
    // exit, which races us here).
    std::thread::sleep(Duration::from_millis(1000));
    start_backend(&app);

    // The new child's pid identifies its port file
    // (`qualcoder-port-<pid>.json`), so a lingering file from the killed
    // backend can never be mistaken for the new one.
    let child_pid = BACKEND_CHILD
        .lock()
        .map(|guard| guard.as_ref().map(|child| child.id()))
        .unwrap_or(None);
    let pid = child_pid.ok_or_else(|| "backend did not start".to_string())?;
    let port_file = std::env::temp_dir().join(format!("qualcoder-port-{pid}.json"));
    for _ in 0..150 {
        if let Ok(text) = std::fs::read_to_string(&port_file) {
            if let Ok(json) = serde_json::from_str::<serde_json::Value>(&text) {
                if let Some(port) = json.get("port").and_then(|p| p.as_u64()) {
                    return Ok(port as u16);
                }
            }
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    Err("backend did not come back after restart".to_string())
}

/// Kill the backend child on app exit.
fn kill_backend() {
    let mut guard = match BACKEND_CHILD.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };
    if let Some(child) = guard.take() {
        #[cfg(windows)]
        {
            let pid = child.id();
            let _ = hide_console(Command::new("taskkill"))
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
    #[cfg(windows)]
    {
        let mut job_guard = match BACKEND_JOB.lock() {
            Ok(g) => g,
            Err(p) => p.into_inner(),
        };
        if let Some(handle) = job_guard.take() {
            unsafe {
                let _ = windows::Win32::Foundation::CloseHandle(handle);
            }
        }
    }
}

/// If a frontend delta patch is installed (``~/.qualcoder/hotpatch/
/// frontend/current/``), navigate the main window to the backend-served
/// SPA so the patch applies with a WebView reload — no installer, no app
/// restart (decision 1: backend-served SPA). No-op when no hotpatch is
/// active: the window keeps showing its embedded assets.
///
/// Release only: `tauri dev` loads the Vite server (HMR) and must never
/// be rerouted. Uses a plain `TcpStream` HTTP probe (no new deps) and
/// `eval(location.replace)` (no `url` crate dep).
#[cfg(not(debug_assertions))]
fn maybe_navigate_to_hotpatch(app: &tauri::AppHandle) {
    use std::io::{Read, Write};

    // 1. Wait for the backend port (the backend writes its port file
    //    before its heavy imports, so this resolves while it boots).
    let mut port: Option<u16> = None;
    for _ in 0..150 {
        port = backend_port();
        if port.is_some() {
            break;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    let port = match port {
        Some(p) => p,
        None => return,
    };

    // 2. Poll the version endpoint until the backend answers, then check
    //    for an active hotpatch. A reachable backend WITHOUT a hotpatch
    //    (`"frontend_version":null`) returns immediately — no polling.
    let mut hotpatched = false;
    for _ in 0..150 {
        let addr: SocketAddr = match format!("127.0.0.1:{port}").parse() {
            Ok(addr) => addr,
            Err(_) => return,
        };
        let probe = TcpStream::connect_timeout(&addr, Duration::from_millis(500))
            .and_then(|mut stream| {
                stream.set_read_timeout(Some(Duration::from_secs(2)))?;
                stream.write_all(
                    b"GET /api/v1/hotpatch/version HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n",
                )?;
                let mut body = String::new();
                stream.read_to_string(&mut body)?;
                Ok(body)
            });
        match probe {
            Err(_) => {
                // Backend not up yet — keep waiting.
                std::thread::sleep(Duration::from_millis(200));
                continue;
            }
            Ok(body) => {
                if let Some(idx) = body.find("\"frontend_version\"") {
                    // Byte-safe: a truncated body yields None, never a panic.
                    if let Some(tail) = body.get(idx + 19..) {
                        let tail = tail.trim_start_matches([':', ' ', '\t', '\r', '\n']);
                        // Non-null means `"0.1.13_001"` (a quoted version);
                        // `null` means no hotpatch is installed.
                        hotpatched = tail.starts_with('"');
                    }
                }
                break;
            }
        }
    }
    if !hotpatched {
        return;
    }

    // 3. Reroute the window. `replace` keeps the embedded page out of the
    //    history stack, so Back never returns to the stale bundle.
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.eval(&format!("window.location.replace('http://127.0.0.1:{port}/')"));
    }
}

/// Relaunch the app so a staged native plan executes at boot.
///
/// The backend already staged verified files + `plan.json` (nothing locked
/// in user-data). The backend child is killed first so no DLL is held when
/// the new instance copies files; the new instance then exits this one by
/// taking over (single app window either way after old exit).
#[tauri::command]
fn apply_native_plan_and_relaunch(app: tauri::AppHandle) -> Result<String, String> {
    kill_backend();
    std::thread::sleep(Duration::from_millis(500));
    let exe = std::env::current_exe().map_err(|e| format!("own executable: {e}"))?;
    hide_console(Command::new(&exe))
        .spawn()
        .map_err(|e| format!("relaunch: {e}"))?;
    app.exit(0);
    Ok("relaunching for native update".to_string())
}

/// App entry point: build the Tauri app, then run the event loop so we can
/// observe `RunEvent::ExitRequested` and tear down the backend process.
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            backend_health,
            backend_port,
            restart_backend,
            apply_native_plan_and_relaunch
        ])
        .setup(|app| {
            // Boot-time native delta (release only): the backend is not
            // spawned yet, so no installed file is locked. Dev builds have
            // no bundled backend to patch.
            #[cfg(not(debug_assertions))]
            if let Some(home) = native_plan::qualcoder_home() {
                let native_dir = home.join("hotpatch").join("native");
                match app
                    .path()
                    .resolve("backend", tauri::path::BaseDirectory::Resource)
                {
                    Ok(resource_backend) => eprintln!(
                        "[tauri] {}",
                        native_plan::execute_pending_plan(&native_dir, &resource_backend)
                    ),
                    Err(err) => eprintln!("[tauri] native plan skipped: {err}"),
                }
            }
            start_backend(app.handle());
            #[cfg(not(debug_assertions))]
            {
                let handle = app.handle().clone();
                std::thread::spawn(move || maybe_navigate_to_hotpatch(&handle));
            }
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



