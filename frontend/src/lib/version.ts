/**
 * App version shown in the status bar, dashboard and bug reports.
 *
 * Injected by vite from frontend/package.json at build time (see
 * `define.__APP_VERSION__` in vite.config.ts) — the release flow bumps
 * package.json together with src-tauri/tauri.conf.json, so this always
 * reflects the released version. The locale `app.version` key is
 * intentionally NOT used here — the value is machine/package metadata,
 * not user-facing text.
 */
declare const __APP_VERSION__: string;

export const APP_VERSION: string =
  typeof __APP_VERSION__ === "string" ? __APP_VERSION__ : "0.0.0-dev";
