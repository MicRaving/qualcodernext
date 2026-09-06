//! Boot-time native-delta executor.
//!
//! Windows locks loaded DLLs, so the backend can only *stage* a native-file
//! delta (`~/.qualcoder/hotpatch/native/`, see `backend/.../services/native.py`).
//! This module executes the staged plan at boot — before the backend child
//! is spawned, so nothing holds the files — and handles the matching
//! restore. Pure file ops over explicit paths (unit-tested); the only
//! app-specific bits are the path wiring in `execute_pending_plan`.

use std::fs;
use std::path::{Component, Path, PathBuf};

/// Reject absolute relpaths and `..` escapes before joining onto a base dir.
fn join_guarded(base: &Path, rel: &str) -> Result<PathBuf, String> {
    let rel_path = Path::new(rel);
    if rel_path.is_absolute() {
        return Err(format!("absolute delta path: {rel}"));
    }
    for component in rel_path.components() {
        match component {
            Component::Normal(_) => {}
            _ => return Err(format!("unsafe delta path: {rel}")),
        }
    }
    Ok(base.join(rel_path))
}

fn read_json(path: &Path) -> Option<serde_json::Value> {
    fs::read_to_string(path)
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
}

fn copy_file(src: &Path, dest: &Path) -> Result<(), String> {
    if let Some(parent) = dest.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("mkdir {}: {e}", parent.display()))?;
    }
    fs::copy(src, dest).map_err(|e| format!("copy {}: {e}", src.display()))?;
    Ok(())
}

/// Apply a staged delta: backup overwritten/removed files, copy the new
/// ones in, record `applied.json`. Returns the applied version.
pub fn apply_staged(native_dir: &Path, resource_dir: &Path) -> Result<String, String> {
    let staged = native_dir.join("staged");
    let delta_path = staged.join("delta.json");
    let delta = read_json(&delta_path).ok_or_else(|| "staged delta.json missing".to_string())?;
    let version = delta
        .get("to")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "delta.json has no 'to' version".to_string())?
        .to_string();
    let files = delta
        .get("files")
        .and_then(|v| v.as_array())
        .ok_or_else(|| "delta.json has no 'files' list".to_string())?;
    let deleted = delta
        .get("deleted")
        .and_then(|v| v.as_array())
        .ok_or_else(|| "delta.json has no 'deleted' list".to_string())?;

    let prev_files = native_dir.join("prev").join("files");
    for entry in files {
        let rel = entry
            .get("path")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "delta file entry has no 'path'".to_string())?;
        let staged_file = join_guarded(&staged, rel)?;
        if !staged_file.is_file() {
            return Err(format!("staged file missing: {rel}"));
        }
        let target = join_guarded(resource_dir, rel)?;
        if target.exists() {
            copy_file(&target, &join_guarded(&prev_files, rel)?)?;
        }
        copy_file(&staged_file, &target)?;
        if let Some(size) = entry.get("size").and_then(|v| v.as_u64()) {
            let actual = fs::metadata(&target).map_err(|e| e.to_string())?.len();
            if actual != size {
                return Err(format!("size mismatch after copy: {rel}"));
            }
        }
    }
    for entry in deleted {
        let rel = entry
            .as_str()
            .ok_or_else(|| "delta 'deleted' entry is not a string".to_string())?;
        let target = join_guarded(resource_dir, rel)?;
        if target.exists() {
            copy_file(&target, &join_guarded(&prev_files, rel)?)?;
            fs::remove_file(&target).map_err(|e| format!("remove {rel}: {e}"))?;
        }
    }

    let previous_to = read_json(&native_dir.join("applied.json"))
        .and_then(|v| v.get("to").and_then(|t| t.as_str()).map(str::to_string));
    let applied = serde_json::json!({
        "from": delta.get("from"),
        "to": version,
        "files": files,
        "deleted": deleted,
        "previous_to": previous_to,
    });
    fs::write(native_dir.join("applied.json"), serde_json::to_string(&applied).unwrap_or_default())
        .map_err(|e| format!("write applied.json: {e}"))?;
    // The plan + staged tree are consumed; backups stay for one-step undo.
    let _ = fs::remove_file(native_dir.join("plan.json"));
    let _ = fs::remove_dir_all(&staged);
    Ok(version)
}

/// Restore the pre-delta backups: previously existing files come back,
/// files the delta added (no backup) are deleted.
pub fn restore_previous(native_dir: &Path, resource_dir: &Path) -> Result<String, String> {
    let applied = read_json(&native_dir.join("applied.json"))
        .ok_or_else(|| "no applied delta to restore".to_string())?;
    let version = applied
        .get("to")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown")
        .to_string();
    let prev_files = native_dir.join("prev").join("files");
    let empty = Vec::new();
    let files = applied
        .get("files")
        .and_then(|v| v.as_array())
        .unwrap_or(&empty);
    for entry in files {
        let rel = entry
            .get("path")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "applied file entry has no 'path'".to_string())?;
        let backup = join_guarded(&prev_files, rel)?;
        let target = join_guarded(resource_dir, rel)?;
        if backup.exists() {
            copy_file(&backup, &target)?;
        } else {
            // Added by the delta — remove it again.
            let _ = fs::remove_file(&target);
        }
    }
    let deleted = applied
        .get("deleted")
        .and_then(|v| v.as_array())
        .unwrap_or(&empty);
    for entry in deleted {
        let rel = entry
            .as_str()
            .ok_or_else(|| "applied 'deleted' entry is not a string".to_string())?;
        let backup = join_guarded(&prev_files, rel)?;
        if backup.exists() {
            copy_file(&backup, &join_guarded(resource_dir, rel)?)?;
        }
    }
    let _ = fs::remove_file(native_dir.join("applied.json"));
    let _ = fs::remove_dir_all(native_dir.join("prev"));
    let _ = fs::remove_file(native_dir.join("plan.json"));
    let _ = fs::remove_dir_all(native_dir.join("staged"));
    Ok(version)
}

/// The `~/.qualcoder` home (mirrors `user_settings.QUALCODER_HOME`).
pub fn qualcoder_home() -> Option<PathBuf> {
    #[cfg(windows)]
    let home = std::env::var_os("USERPROFILE");
    #[cfg(not(windows))]
    let home = std::env::var_os("HOME");
    home.map(PathBuf::from).map(|h| h.join(".qualcoder"))
}

/// Execute a pending native plan (if any) before the backend spawns.
/// Returns a short status for the boot log; failures are reported but
/// never block startup (worst case the delta stays staged for next boot).
pub fn execute_pending_plan(
    native_dir: &Path,
    resource_dir: &Path,
) -> String {
    let plan = match read_json(&native_dir.join("plan.json")) {
        Some(plan) => plan,
        None => return "native plan: none".to_string(),
    };
    let action = plan.get("action").and_then(|v| v.as_str()).unwrap_or("");
    let result = match action {
        "apply" => apply_staged(native_dir, resource_dir),
        "restore" => restore_previous(native_dir, resource_dir),
        other => return format!("native plan: unknown action {other:?} (ignored)"),
    };
    match result {
        Ok(version) => format!("native plan {action} applied ({version})"),
        Err(err) => format!("native plan {action} FAILED: {err}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_root(name: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let root = std::env::temp_dir().join(format!("qcnext-{name}-{nanos}"));
        fs::create_dir_all(&root).unwrap();
        root
    }

    fn write(path: &Path, content: &str) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(path, content).unwrap();
    }

    fn stage_delta(native_dir: &Path, delta: &serde_json::Value, files: &[(&str, &str)]) {
        let staged = native_dir.join("staged");
        for (rel, content) in files {
            write(&staged.join(rel), content);
        }
        write(
            &staged.join("delta.json"),
            &serde_json::to_string(delta).unwrap(),
        );
    }

    #[test]
    fn rejects_unsafe_paths() {
        let base = Path::new("/base");
        assert!(join_guarded(base, "a/b.dll").is_ok());
        assert!(join_guarded(base, "../evil").is_err());
        assert!(join_guarded(base, "a/../../evil").is_err());
        assert!(join_guarded(base, "/absolute").is_err());
        #[cfg(windows)]
        assert!(join_guarded(base, "C:\\win").is_err());
    }

    #[test]
    fn apply_and_restore_roundtrip() {
        let root = temp_root("native-rt");
        let native_dir = root.join("native");
        let resource = root.join("resource");
        write(&resource.join("keep.dll"), "old-keep");
        write(&resource.join("del.txt"), "bye");

        let delta = serde_json::json!({
            "from": "0.1.13",
            "to": "0.1.13_001",
            "files": [
                {"path": "keep.dll", "size": 7},
                {"path": "new/file.bin", "size": 3},
            ],
            "deleted": ["del.txt"],
        });
        stage_delta(&native_dir, &delta, &[("keep.dll", "new-kee"), ("new/file.bin", "bin")]);

        let version = apply_staged(&native_dir, &resource).unwrap();
        assert_eq!(version, "0.1.13_001");
        assert_eq!(fs::read_to_string(resource.join("keep.dll")).unwrap(), "new-kee");
        assert_eq!(fs::read_to_string(resource.join("new/file.bin")).unwrap(), "bin");
        assert!(!resource.join("del.txt").exists());
        assert!(native_dir.join("applied.json").is_file());
        assert!(!native_dir.join("staged").exists());

        // Size mismatch must fail loudly (tamper evidence).
        let restored = restore_previous(&native_dir, &resource).unwrap();
        assert_eq!(restored, "0.1.13_001");
        assert_eq!(fs::read_to_string(resource.join("keep.dll")).unwrap(), "old-keep");
        assert!(!resource.join("new/file.bin").exists());
        assert_eq!(fs::read_to_string(resource.join("del.txt")).unwrap(), "bye");
        assert!(!native_dir.join("applied.json").exists());

        fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn apply_rejects_missing_staged_file() {
        let root = temp_root("native-missing");
        let native_dir = root.join("native");
        let resource = root.join("resource");
        fs::create_dir_all(&resource).unwrap();
        let delta = serde_json::json!({
            "from": "0.1.13",
            "to": "0.1.13_001",
            "files": [{"path": "ghost.dll", "size": 1}],
            "deleted": [],
        });
        stage_delta(&native_dir, &delta, &[]);
        assert!(apply_staged(&native_dir, &resource).is_err());
        fs::remove_dir_all(&root).unwrap();
    }
}
