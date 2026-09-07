import { useEffect, useState } from "react";
import { ProjectShell } from "@/components/shell/ProjectShell";
import { LoadingState } from "@/components/ui/orchestrator";
import { LoginScreen } from "@/features/auth/LoginScreen";
import { api, initApiBase } from "@/lib/api";
import { SERVER_MODE } from "@/lib/config";
import { getToken } from "@/lib/session";
import { I18nProvider } from "@/lib/i18n";
import { ToastProvider } from "@/lib/toast";
import { useProjectStore } from "@/stores/project";
import { checkIntervalMs, updaterAvailable, useUpdatesStore } from "@/stores/updates";

/** Ceiling for the boot gate. `initApiBase()` already caps its own port
 *  poll at 30s before falling back to the dev URL; this race only guards
 *  against a never-settling promise so the UI can never hang. */
const API_BOOT_TIMEOUT_MS = 35_000;

/** App-update scheduling: load the saved preferences, then check now and on
 *  the configured cadence when auto-updates are enabled. An available update
 *  is installed automatically (the setting promises "install automatically");
 *  manual checks in Settings never install on their own. Runs only in the
 *  packaged (Tauri) app — plain-browser dev has no updater.
 *  Deferred until the browser is idle (or 30s after boot): the check does
 *  DNS/TLS to GitHub and must never compete with first paint + project open. */
const UPDATES_DEFER_MS = 30_000;
function scheduleUpdates(): () => void {
  if (!updaterAvailable()) return () => {};
  let timer: number | null = null;
  let cancelled = false;
  const store = useUpdatesStore.getState();
  const checkAndInstall = () => {
    if (cancelled) return;
    void useUpdatesStore.getState().checkNow().then(() => {
      if (cancelled) return;
      const s = useUpdatesStore.getState();
      if (s.status === "available" && s.settings?.auto_update) void s.install();
    });
  };
  void store
    .loadSettings()
    // Hotpatch/overlay/native state feeds version comparison in checkNow —
    // without it an applied nightly would be re-offered on every check.
    .then(() => store.loadHotpatch())
    .then(() => {
    if (cancelled) return;
    const settings = useUpdatesStore.getState().settings;
    if (!settings?.auto_update) return;
    checkAndInstall();
    const ms = checkIntervalMs(settings.check_interval);
    if (ms != null) {
      timer = window.setInterval(() => {
        const current = useUpdatesStore.getState().settings;
        if (current?.auto_update) {
          checkAndInstall();
        } else if (timer != null) {
          window.clearInterval(timer);
          timer = null;
        }
      }, ms);
    }
  });
  return () => {
    cancelled = true;
    if (timer != null) window.clearInterval(timer);
  };
}

/** Boot-gate note: after 10s of blank loading, say so with a live count.
 *  Rendered outside i18n like the gate itself (which hardcodes the brand).
 *  Neutral wording — slow spawns are usually AV/first-run scanning. */
function BootSlowNote() {
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setSecs((s) => s + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);
  if (secs < 10) return null;
  return <p className="text-xs">Still starting the backend ({secs}s)…</p>;
}

function App() {
  const [baseReady, setBaseReady] = useState(false);
  // Re-render after a server-mode login stores a token.
  const [, setAuthTick] = useState(0);

  useEffect(() => {
    // App custom context menus replace the native one — except inside text
    // inputs/textareas/contentEditable where users (and screen readers) need
    // cut/copy/paste/spellcheck.
    const preventContextMenu = (e: MouseEvent) => {
      const t = e.target as HTMLElement | null;
      if (t?.closest?.("input, textarea, [contenteditable='true'], [contenteditable='']")) return;
      e.preventDefault();
    };
    window.addEventListener("contextmenu", preventContextMenu);
    return () => window.removeEventListener("contextmenu", preventContextMenu);
  }, []);

  useEffect(() => {
    // Deferred (see UPDATES_DEFER_MS): never on the boot critical path.
    let cleanup: (() => void) | null = null;
    let timer: number | null = window.setTimeout(() => {
      timer = null;
      cleanup = scheduleUpdates();
    }, UPDATES_DEFER_MS);
    // requestIdleCallback fires earlier on an idle machine; the timeout
    // above is the backstop for browsers without it or a busy main thread.
    let idle: number | null = null;
    const w = window as Window & { requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number; cancelIdleCallback?: (id: number) => void };
    if (typeof w.requestIdleCallback === "function") {
      idle = w.requestIdleCallback(() => {
        if (timer != null) {
          window.clearTimeout(timer);
          timer = null;
        }
        cleanup = scheduleUpdates();
      }, { timeout: UPDATES_DEFER_MS });
    }
    return () => {
      if (timer != null) window.clearTimeout(timer);
      if (idle != null) w.cancelIdleCallback?.(idle);
      cleanup?.();
    };
  }, []);

  // Boot gate: hold the whole UI until the backend base URL is resolved.
  // Views build raw file URLs from apiBaseSync(), which is the DEV fallback
  // until initApiBase() settles — in the packaged app the backend may boot
  // slowly or fall back to an ephemeral port (a second instance holds 8765),
  // so mounting views early makes their file fetches hit the wrong port and
  // fail with "Failed to fetch". The timeout falls back to the dev URL in
  // plain-browser dev (no backend_port command — resolves instantly) so the
  // gate can never hang the app. After this, apiBaseSync() is stable for the
  // whole session unless the backend restarts (handled by the retry helpers).
  useEffect(() => {
    let active = true;
    void Promise.race([
      initApiBase(),
      new Promise((resolve) => setTimeout(resolve, API_BOOT_TIMEOUT_MS)),
    ]).then(() => {
      if (active) {
        setBaseReady(true);
        try {
          performance.mark("qc:base-resolved");
        } catch {
          /* performance API unavailable (older webviews) */
        }
      }
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: number | null = null;
    // Resolve the backend base URL early (packaged app: the backend may be
    // on an ephemeral port when a second instance is running).
    void initApiBase().then(async () => {
      if (cancelled) return;
      // In the packaged app, jump straight to the dashboard: auto-open the
      // most recent project (gated by the "auto-load project" setting —
      // default on). The embedded backend takes ~10s to start, so retry
      // until it answers. Plain-browser dev keeps the empty dashboard so
      // the E2E suite can exercise the create/open flows deterministically.
      if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
        // appSettings and recentProjects are independent — fetch them in
        // parallel instead of serially.  A settings failure keeps the
        // default (auto-open); a recent failure enters the retry loop below.
        const [settingsRes, recentRes] = await Promise.allSettled([
          api.appSettings(),
          api.recentProjects(3_000),
        ]);
        if (cancelled) return;
        if (settingsRes.status === "fulfilled" && !settingsRes.value.auto_open_project) return;
        try {
          performance.mark("qc:auto-open-start");
        } catch {
          /* performance API unavailable (older webviews) */
        }
        const store = useProjectStore.getState();
        store.setAutoOpening(true);
        store.setAutoOpenStage("backend");
        const openFromRecent = async (recent: string[]) => {
          if (cancelled) return false;
          useProjectStore.getState().setAutoOpenStage("open");
          for (const path of recent.slice(0, 3)) {
            if (cancelled) return false;
            // A hanging open must never freeze the dashboard — but the cap
            // must exceed PROJECT_OPEN_TIMEOUT_MS (120s): large/shared
            // projects legitimately take that long, and cutting them off
            // early just restarts the same slow open on every retry.
            const ok = await Promise.race([
              useProjectStore.getState().openProject(path),
              new Promise<boolean>((resolve) => setTimeout(() => resolve(false), 150_000)),
            ]);
            if (cancelled) return false;
            if (ok) return true;
          }
          return false;
        };
        const tryAutoOpen = async (attempt: number, firstRecent?: string[]) => {
          if (cancelled) return;
          try {
            // Short timeout: when the backend is still booting this fails
            // fast and the retry cadence opens the project the moment
            // the backend answers (no welcome screen flash).
            const recent = firstRecent ?? (await api.recentProjects(3_000)).recent;
            if (cancelled) return;
            if (await openFromRecent(recent)) {
              if (!cancelled) {
                useProjectStore.getState().setAutoOpening(false);
                try {
                  performance.mark("qc:auto-open-done");
                } catch {
                  /* performance API unavailable (older webviews) */
                }
              }
              return;
            }
          } catch {
            if (!cancelled && attempt < 120) {
              // Exponential backoff (250ms → 5s cap): fast when the backend
              // is just about to answer, quiet once it is clearly still down.
              const delay = Math.min(250 * 2 ** attempt, 5_000);
              retryTimer = window.setTimeout(() => void tryAutoOpen(attempt + 1), delay);
              return;
            }
          }
          if (!cancelled) useProjectStore.getState().setAutoOpening(false);
        };
        void tryAutoOpen(
          0,
          recentRes.status === "fulfilled" ? recentRes.value.recent : undefined,
        );
      }
    });
    return () => {
      cancelled = true;
      if (retryTimer != null) window.clearTimeout(retryTimer);
    };
  }, []);

  if (!baseReady) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 bg-bg text-text-secondary">
        <LoadingState>QualCoder</LoadingState>
        <BootSlowNote />
      </div>
    );
  }

  return (
    <I18nProvider>
      <ToastProvider>
        {SERVER_MODE && !getToken() ? (
          // Server mode auth gate (SERVER_PLAN.md §6.7): no token, no app.
          <LoginScreen onAuthed={() => setAuthTick((n) => n + 1)} />
        ) : (
          <div className="flex h-full flex-col">
            <ProjectShell />
          </div>
        )}
      </ToastProvider>
    </I18nProvider>
  );
}

export default App;
