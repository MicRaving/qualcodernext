//! Build script — required for the standard Tauri resource embedding
//! (Windows manifest, icon, config resources — without this the exe fails
//! at load with "TaskDialogIndirect entry point not found").
//!
//! The backend is NOT embedded here anymore: it ships as a PyInstaller
//! onedir under `src-tauri/resources/backend/` (copied there by
//! `release.ps1 -Compile` and bundled via `bundle.resources`), so nothing
//! needs to be extracted at launch.

use std::env;

fn main() {
    tauri_build::build();

    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=tauri.conf.json");
    println!("cargo:rerun-if-changed=resources/backend/qualcoder-backend.exe");
    let _ = env::var("CARGO_MANIFEST_DIR");
}
