/**
 * App-update state — check/download/install via the Tauri updater plugin,
 * plus the `nightly` channel for `X.Y.Z_NNN` delta patches.
 *
 * Channels (`Settings → Updates`, opt-in/out):
 * - `stable` (default): full Tauri releases from `qcnext-latest.json` only.
 * - `nightly`: additionally offers signed delta patches from
 *   `qcnext-nightly.json`. A nightly is NEWER than the stable of the same
 *   base (`0.1.13_001 > 0.1.13`): nightlies are post-release patches, so a
 *   client on the stable must be offered them. A nightly is offered ONLY on
 *   its own base (`manifest.base` must equal the app's base) — any other
 *   base is offered the newer stable full update instead. Cross-base delta
 *   application is never attempted (backend sources + native files would
 *   mismatch the running tree).
 *
 * After a frontend patch activates, the window navigates to the
 * backend-served SPA: Tauri loads the frozen bundle (`frontendDist`), so a
 * bare reload would re-render the STALE bundle — only the boot gate
 * reroutes, and only installs navigate.
 *
 * Version ordering mirrors `backend/.../services/versioning.py` — keep the
 * two in sync. `tauri.conf.json`/`Cargo.toml`/`package.json` always carry
 * the BASE semver; only `APP_VERSION` and the nightly manifest carry `_NNN`.
 *
 * The check hits the configured GitHub release manifests; in a plain browser
 * (dev server / vitest) the Tauri internals are absent, so checks report a
 * friendly "desktop only" error instead of crashing.
 */
import { errorMessage } from "@/lib/utils";
import { create } from "zustand";
import {
  ApiError,
  api,
  apiBaseSync,
  initApiBase,
  invalidateApiBase,
  type BackendPatchRef,
  type HotpatchVersion,
  type NativePatchRef,
  type NativeVersion,
  type NightlyManifest,
  type OverlayVersion,
  type UpdatesSettings,
} from "@/lib/api";
import { APP_VERSION } from "@/lib/version";

/** Refuse native deltas above this (ship a full release instead).
 *  Mirrored in `backend/.../services/native.py` — keep in sync. */
export const NATIVE_DELTA_MAX_BYTES = 60 * 1024 * 1024;

/** Human download size ("1.4 MB", "900 KB", "12 B"). */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Total known download bytes across an update's sections (0 if unknown). */
export function updateDownloadSize(info: UpdateInfo): number {
  if (info.kind === "full") return Number.POSITIVE_INFINITY;
  return (
    (info.size ?? 0) + (info.backend?.size ?? 0) + (info.native?.size ?? 0)
  );
}

export type UpdateStatus =
  | "idle"
  | "checking"
  | "available"
  | "up-to-date"
  | "downloading"
  | "patching"
  | "error";

export type UpdateKind = "full" | "nightly";

export interface UpdateInfo {
  version: string;
  body?: string;
  date?: string;
  kind: UpdateKind;
  /** Frontend section download bytes (kind === "nightly" only, when known). */
  size?: number;
  /** Nightly frontend patch (kind === "nightly" only, when shipped). */
  url?: string;
  /** Expected SHA-256 + minisign signature (kind === "nightly" only). */
  sha256?: string;
  signature?: string;
  /** Nightly backend-source patch (kind === "nightly" only, when shipped). */
  backend?: BackendPatchRef;
  /** Nightly native-file delta (kind === "nightly" only, when shipped). */
  native?: NativePatchRef;
}

/** Nightly patch manifest shape — the canonical type lives in `@/lib/api`
 *  (re-exported here so existing imports keep working). */
export type { NightlyManifest } from "@/lib/api";

/** Whether a manifest backend/native section is complete + installable. */
export function patchRefUsable(
  ref: Partial<BackendPatchRef> | undefined,
): ref is BackendPatchRef {
  return !!ref && !!ref.url && !!ref.sha256 && !!ref.signature;
}

export function nativeRefUsable(
  ref: Partial<NativePatchRef> | undefined,
): ref is NativePatchRef {
  // Independent of patchRefUsable (a guard would narrow `ref` away here).
  return (
    !!ref &&
    !!ref.url &&
    !!ref.sha256 &&
    !!ref.signature &&
    typeof ref.from === "string" &&
    typeof ref.to === "string" &&
    typeof ref.size === "number"
  );
}

/** Whether a manifest carries at least one complete, installable section. */
export function nightlyManifestUsable(manifest: Partial<NightlyManifest>): manifest is NightlyManifest {
  if (typeof manifest.version !== "string" || !parseNightlyVersion(manifest.version)) return false;
  const frontendOk = !!manifest.url && !!manifest.sha256 && !!manifest.signature;
  return frontendOk || patchRefUsable(manifest.backend) || nativeRefUsable(manifest.native);
}

/** Rolling nightly release holding the latest delta patch + manifest. */
export const NIGHTLY_MANIFEST_URL =
  "https://github.com/MicRaving/qualcodernext/releases/download/nightly/qcnext-nightly.json";

/** Reload seam (tests replace these with mocks — jsdom has no navigation). */
export const patchHooks = {
  reload: () => window.location.reload(),
  /**
   * Show the freshly activated frontend: navigate to the backend-served
   * SPA when the window still shows the frozen bundle, else reload in
   * place. A bare `reload()` here would re-render the STALE bundle and
   * the patch would look like it never applied (visible only after a
   * full app restart via the boot gate).
   */
  showPatchedFrontend: (origin: string) => {
    if (origin && !window.location.href.startsWith(origin)) {
      window.location.replace(`${origin}/`);
    } else {
      window.location.reload();
    }
  },
};

interface UpdatesState {
  status: UpdateStatus;
  info: UpdateInfo | null;
  /** Download progress 0–100 (only while downloading). */
  progress: number;
  error: string | null;
  lastCheckedAt: number | null;
  settings: UpdatesSettings | null;
  hotpatch: HotpatchVersion | null;
  overlay: OverlayVersion | null;
  native: NativeVersion | null;
  /** Non-null when the backend runs an older base than the app build. */
  backendBaseMismatch: BackendBaseMismatch | null;
  loadSettings: () => Promise<void>;
  saveSettings: (settings: UpdatesSettings) => Promise<void>;
  loadHotpatch: () => Promise<void>;
  checkNow: () => Promise<void>;
  install: () => Promise<void>;
  rollback: () => Promise<void>;
}

/** Whether the Tauri updater plugin is reachable (desktop app only). */
export function updaterAvailable(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/**
 * Sentinel stored in `error` when the update check fails because the
 * release manifest is missing on the remote (no `qcnext-latest.json`
 * asset on the latest GitHub release — e.g. the release was published
 * without signing, so no updater artifacts exist). The Settings tab
 * renders a dedicated, non-alarming message for it instead of the raw
 * plugin error ("Could not fetch a valid release JSON from the remote").
 */
export const NO_UPDATE_MANIFEST = "no-manifest";

/**
 * Map a raw update-check failure to the missing-manifest sentinel when
 * the Tauri updater plugin reports that the remote release JSON is
 * absent or invalid. Returns null for every other failure (the raw
 * message is shown then).
 */
export function classifyUpdateCheckError(raw: unknown): typeof NO_UPDATE_MANIFEST | null {
  const msg = errorMessage(raw, String(raw));
  return /valid release JSON/i.test(msg) ? NO_UPDATE_MANIFEST : null;
}

const NIGHTLY_RE = /^(\d+)\.(\d+)\.(\d+)(?:_(\d{1,5}))?$/;

export function parseNightlyVersion(version: string): [number, number, number, number | null] | null {
  const match = NIGHTLY_RE.exec((version ?? "").trim());
  if (!match) return null;
  return [Number(match[1]), Number(match[2]), Number(match[3]), match[4] === undefined ? null : Number(match[4])];
}

/** -1 / 0 / +1. Same base: any nightly sorts AFTER the stable. */
export function compareNightlyVersions(left: string, right: string): number {
  const l = parseNightlyVersion(left);
  const r = parseNightlyVersion(right);
  if (!l || !r) return 0;
  for (let i = 0; i < 3; i++) {
    if (l[i] !== r[i]) return l[i]! < r[i]! ? -1 : 1;
  }
  if (l[3] === r[3]) return 0;
  if (l[3] === null) return -1;
  if (r[3] === null) return 1;
  return l[3] < r[3] ? -1 : 1;
}

/** Whether `candidate` should be offered on `channel` over `current`. */
export function nightlyVisibleOnChannel(candidate: string, current: string, channel: string): boolean {
  if (!parseNightlyVersion(candidate) || !parseNightlyVersion(current)) return false;
  if (channel !== "nightly" && parseNightlyVersion(candidate)?.[3] !== null) return false;
  return compareNightlyVersions(candidate, current) > 0;
}

/**
 * Whether a nightly manifest applies to THIS app: its `base` must equal the
 * app's own base (stable or already-patched nightly). Anything else means
 * the client belongs on the newer stable full update, never on this delta.
 */
export function nightlyBaseMatches(manifest: Partial<NightlyManifest>, current: string): boolean {
  return (
    typeof manifest.base === "string" &&
    baseOfVersion(current) !== null &&
    manifest.base === baseOfVersion(current)
  );
}

/** Origin (`scheme://host:port`) serving the backend API — and the patched SPA. */
export function backendOrigin(): string {
  try {
    return new URL(apiBaseSync()).origin;
  } catch {
    return "";
  }
}

/** A backend running an older base than the app (mixed/stale install). */
export interface BackendBaseMismatch {
  app: string;
  backend: string;
}

/** `X.Y.Z` base of a version, or null when unparseable. */
export function baseOfVersion(version: string): string | null {
  const parts = parseNightlyVersion(version);
  if (!parts) return null;
  return `${parts[0]}.${parts[1]}.${parts[2]}`;
}

/**
 * Detect a stale backend: its reported base is strictly older than the
 * app's own build version (e.g. new frontend talking to a backend process
 * that survived an update). A backend AHEAD of the app is legitimate
 * (backend-overlay nightlies move it forward) and never flagged.
 */
export function staleBackend(hotpatch: HotpatchVersion | null): BackendBaseMismatch | null {
  const appBase = baseOfVersion(APP_VERSION);
  const backendBase = hotpatch?.app_version ? baseOfVersion(hotpatch.app_version) : null;
  if (!appBase || !backendBase) return null;
  if (compareNightlyVersions(backendBase, appBase) >= 0) return null;
  return { app: APP_VERSION, backend: hotpatch?.app_version ?? "?" };
}

/** Effective running version: the newest of build / hotpatch / native delta.
 *  Comparing against the max (not just the build) keeps applied nightlies
 *  from being re-offered on the next check. */
export function effectiveVersion(
  hotpatch: HotpatchVersion | null,
  native: NativeVersion | null = null,
): string {
  let best = hotpatch?.frontend_version ?? hotpatch?.app_version ?? APP_VERSION;
  const nativeTo = native?.applied_to;
  if (nativeTo && compareNightlyVersions(nativeTo, best) > 0) best = nativeTo;
  return best;
}

async function fetchNightlyManifest(): Promise<NightlyManifest | null> {
  // Primary: the backend proxy. GitHub release assets send no CORS headers,
  // so a direct webview fetch always fails the CORS check — the backend
  // (no CORS outbound) fetches it instead.
  try {
    const data = await api.nightlyManifest();
    if (nightlyManifestUsable(data)) return data;
  } catch {
    /* old backend (404) or proxy unreachable — try direct fetch below */
  }
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), 30_000);
  try {
    const res = await fetch(NIGHTLY_MANIFEST_URL, {
      signal: ctrl.signal,
      // The manifest URL is stable across nightlies — never serve it stale.
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = (await res.json()) as Partial<NightlyManifest>;
    if (!nightlyManifestUsable(data)) return null;
    return data;
  } catch {
    return null;
  } finally {
    window.clearTimeout(timer);
  }
}

/**
 * Stage a backend-source patch and restart into it. The open project is
 * captured first: the restart shuts the backend down cleanly (project
 * closed), so the frontend reopens it once the new process answers.
 * Afterwards the transport re-resolves the API base (the port may have
 * changed) — subsequent calls self-heal the same way on retry.
 */
async function applyBackendPatch(version: string, backend: BackendPatchRef): Promise<void> {
  const { useProjectStore } = await import("@/stores/project");
  const projectPath = useProjectStore.getState().projectPath || null;
  await api.applyOverlay({ version, ...backend });
  const core = await import("@tauri-apps/api/core");
  await core.invoke<number>("restart_backend");
  invalidateApiBase();
  await initApiBase();
  if (projectPath) {
    await useProjectStore.getState().openProject(projectPath);
  }
}

export const useUpdatesStore = create<UpdatesState>((set, get) => ({
  status: "idle",
  info: null,
  progress: 0,
  error: null,
  lastCheckedAt: null,
  settings: null,
  hotpatch: null,
  overlay: null,
  native: null,
  backendBaseMismatch: null,

  loadSettings: async () => {
    try {
      const settings = await api.updatesSettings();
      set({ settings });
    } catch {
      /* settings stay null — the UI falls back to defaults */
    }
  },

  saveSettings: async (settings: UpdatesSettings) => {
    const saved = await api.setUpdatesSettings(settings);
    set({ settings: saved });
  },

  loadHotpatch: async () => {
    try {
      const [hotpatch, overlay, native] = await Promise.all([
        api.hotpatchVersion(),
        api.patchesVersion(),
        api.nativeVersion(),
      ]);
      set({ hotpatch, overlay, native, backendBaseMismatch: staleBackend(hotpatch) });
    } catch {
      /* backend unreachable at boot — the UI falls back to APP_VERSION */
    }
  },

  checkNow: async () => {
    if (!updaterAvailable()) {
      set({
        status: "error",
        error: "desktop only",
        info: null,
        lastCheckedAt: Date.now(),
      });
      return;
    }
    set({ status: "checking", error: null });
    try {
      // Settings are loaded by the app boot (`scheduleUpdates`) and the
      // Settings tab before any check runs; a missing value means "stable".
      // (Deliberately no `loadSettings()` here: it hits the network and
      // must never stall a manual check.)
      const channel = get().settings?.channel ?? "stable";
      const current = effectiveVersion(get().hotpatch, get().native);

      const { check } = await import("@tauri-apps/plugin-updater");
      const update = await check({ timeout: 30_000 });
      let best: UpdateInfo | null = update
        ? {
            version: update.version,
            body: update.body ?? undefined,
            date: update.date ? new Date(update.date).toISOString() : undefined,
            kind: "full",
          }
        : null;

      if (channel === "nightly") {
        const nightly = await fetchNightlyManifest();
        // Same-base only: a foreign-base nightly is never offered (the
        // newer stable full update in `best` stands), so a delta can never
        // be applied onto a tree it wasn't built for.
        if (
          nightly &&
          nightlyBaseMatches(nightly, current) &&
          nightlyVisibleOnChannel(nightly.version, current, channel)
        ) {
          const { url, sha256, signature, backend, native } = nightly;
          // Sections are offered independently: a manifest is usable when at
          // least one section is complete AND applicable here. Native deltas
          // chain exactly (from == our pointer) and respect the size ceiling;
          // the pointer comes from loadHotpatch (boot + Settings tab), so a
          // never-loaded state simply skips the native section this round.
          const pointer = get().native?.pointer;
          const nativeOffer =
            nativeRefUsable(native) &&
            pointer !== undefined &&
            native.from === pointer &&
            native.size <= NATIVE_DELTA_MAX_BYTES
              ? native
              : undefined;
          if (
            (url && sha256 && signature) ||
            patchRefUsable(backend) ||
            nativeOffer
          ) {
            if (!best || compareNightlyVersions(nightly.version, best.version) > 0) {
              const { url, sha256, signature, size, backend } = nightly;
              best = {
                version: nightly.version,
                body: nightly.notes ?? undefined,
                date: nightly.pub_date ?? undefined,
                kind: "nightly",
                ...(url && sha256 && signature
                  ? { url, sha256, signature, ...(typeof size === "number" ? { size } : {}) }
                  : {}),
                ...(patchRefUsable(backend) ? { backend } : {}),
                ...(nativeOffer ? { native: nativeOffer } : {}),
              };
            }
          }
        }
      }

      if (!best) {
        set({ status: "up-to-date", info: null, lastCheckedAt: Date.now() });
        return;
      }
      set({
        status: "available",
        info: best,
        lastCheckedAt: Date.now(),
      });
    } catch (e) {
      set({
        status: "error",
        error: classifyUpdateCheckError(e) ?? errorMessage(e, String(e)),
        lastCheckedAt: Date.now(),
      });
    }
  },

  install: async () => {
    const info = get().info;
    if (!info || !updaterAvailable()) return;
    if (info.kind === "nightly") {
      // Delta patch, applied bottom-up so one relaunch activates everything:
      // backend-source overlay (staged), frontend files (staged), native
      // files (staged + boot plan). Without a native section there is no
      // app restart — a backend restart (overlay) or WebView reload
      // (frontend-only) suffices.
      const hasFrontend = !!(info.url && info.sha256 && info.signature);
      if (!info.backend && !hasFrontend && !info.native) {
        set({ status: "error", error: "nightly patch has no usable sections" });
        return;
      }
      set({ status: "patching", progress: 0, error: null });
      try {
        if (info.backend && !info.native) {
          // No relaunch coming: restart the backend now to activate.
          await applyBackendPatch(info.version, info.backend);
        } else if (info.backend) {
          await api.applyOverlay({ version: info.version, ...info.backend });
        }
        let hotpatch = get().hotpatch;
        if (hasFrontend) {
          hotpatch = await api.applyHotpatch({
            version: info.version,
            url: info.url as string,
            sha256: info.sha256 as string,
            signature: info.signature as string,
          });
        }
        let overlay = get().overlay;
        let nativeState = get().native;
        if (info.backend) {
          try {
            overlay = await api.patchesVersion();
          } catch {
            /* restart already proved the backend is up; keep prior state */
          }
        }
        if (info.native) {
          await api.applyNative({
            version: info.native.to,
            from_version: info.native.from,
            url: info.native.url,
            sha256: info.native.sha256,
            signature: info.native.signature,
            size: info.native.size,
          });
          try {
            nativeState = await api.nativeVersion();
          } catch {
            /* staged state is known; keep prior state */
          }
        }
        set({
          hotpatch,
          overlay,
          native: nativeState,
          status: "up-to-date",
          info: null,
          lastCheckedAt: Date.now(),
        });
        if (info.native) {
          // The relaunching instance executes the staged plan at boot
          // (activating all three layers); this process exits instead of
          // reloading, and the boot gate reopens the recent project.
          const core = await import("@tauri-apps/api/core");
          await core.invoke<string>("apply_native_plan_and_relaunch");
          return;
        }
        // Navigate only when patched frontend files exist behind the backend
        // URL: a backend-only install over a bundle window has no SPA there
        // (the backend answers 404) — a plain reload is correct instead.
        if (get().hotpatch?.frontend_version) {
          patchHooks.showPatchedFrontend(backendOrigin());
        } else {
          patchHooks.reload();
        }
      } catch (e) {
        set({ status: "error", error: errorMessage(e, String(e)) });
      }
      return;
    }
    set({ status: "downloading", progress: 0, error: null });
    try {
      const { check } = await import("@tauri-apps/plugin-updater");
      const update = await check({ timeout: 30_000 });
      if (!update || update.version !== info.version) {
        await get().checkNow();
        return;
      }
      let contentLength = 0;
      let downloaded = 0;
      await update.downloadAndInstall((event) => {
        if (event.event === "Started") {
          contentLength = event.data.contentLength ?? 0;
        } else if (event.event === "Progress") {
          downloaded += event.data.chunkLength;
          if (contentLength > 0) {
            set({ progress: Math.min(99, Math.round((downloaded / contentLength) * 100)) });
          }
        }
      });
      set({ status: "up-to-date", progress: 100 });
      // On Windows the install step already exited the app; elsewhere the
      // user restarts manually.
    } catch (e) {
      set({
        status: "error",
        error: errorMessage(e, String(e)),
      });
    }
  },

  rollback: async () => {
    if (!updaterAvailable()) return;
    set({ status: "patching", error: null });
    try {
      // Roll back every layer that keeps a previous copy (404 = none kept).
      // A native restore needs an app relaunch and covers the other layers
      // too (boot re-applies their restored state); otherwise a backend
      // rollback restarts just the backend, and a frontend-only rollback
      // just reloads the WebView.
      let rolledBack = false;
      let needRelaunch = false;
      let overlayRolledBack = false;
      try {
        const nativeState = await api.rollbackNative();
        set({ native: nativeState });
        rolledBack = true;
        needRelaunch = true;
      } catch (e) {
        if (!(e instanceof ApiError) || e.status !== 404) throw e;
      }
      try {
        const overlay = await api.rollbackOverlay();
        set({ overlay });
        rolledBack = true;
        overlayRolledBack = true;
      } catch (e) {
        if (!(e instanceof ApiError) || e.status !== 404) throw e;
      }
      try {
        const hotpatch = await api.rollbackHotpatch();
        set({ hotpatch });
        rolledBack = true;
      } catch (e) {
        if (!(e instanceof ApiError) || e.status !== 404) throw e;
      }
      if (!rolledBack) {
        set({ status: "error", error: "nothing to roll back" });
        return;
      }
      if (needRelaunch) {
        const core = await import("@tauri-apps/api/core");
        await core.invoke<string>("apply_native_plan_and_relaunch");
        return;
      }
      // A backend rollback only takes effect after a restart; a
      // frontend-only rollback just needs the reload below.
      if (overlayRolledBack) {
        const { useProjectStore } = await import("@/stores/project");
        const projectPath = useProjectStore.getState().projectPath || null;
        const core = await import("@tauri-apps/api/core");
        await core.invoke<number>("restart_backend");
        invalidateApiBase();
        await initApiBase();
        if (projectPath) {
          await useProjectStore.getState().openProject(projectPath);
        }
        // Re-read post-restart truth (the overlay is active now).
        const [hotpatch, overlay] = await Promise.all([
          api.hotpatchVersion(),
          api.patchesVersion(),
        ]);
        set({ hotpatch, overlay });
      }
      set({ status: "up-to-date", info: null, lastCheckedAt: Date.now() });
      // A restored frontend lives behind the backend URL too — but only
      // when files are actually there (rolling back the last frontend
      // patch leaves no SPA behind the backend URL: reload the bundle).
      if (get().hotpatch?.frontend_version) {
        patchHooks.showPatchedFrontend(backendOrigin());
      } else {
        patchHooks.reload();
      }
    } catch (e) {
      set({ status: "error", error: errorMessage(e, String(e)) });
    }
  },
}));

/** Interval between automatic checks, from the saved cadence. */
export function checkIntervalMs(interval: UpdatesSettings["check_interval"] | undefined): number | null {
  switch (interval) {
    case "daily":
      return 24 * 60 * 60 * 1000;
    case "weekly":
      return 7 * 24 * 60 * 60 * 1000;
    default:
      return null;
  }
}
