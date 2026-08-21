/**
 * App version shown in the status bar, dashboard and bug reports.
 *
 * Kept in sync with the desktop bundle version (package.json, Cargo.toml,
 * tauri.conf.json). The locale `app.version` key is intentionally NOT used
 * here — the value is machine/package metadata, not user-facing text.
 */
export const APP_VERSION = "0.1.0";
