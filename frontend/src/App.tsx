import { useEffect } from "react";
import { ProjectShell } from "@/components/shell/ProjectShell";
import { api, initApiBase } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n";
import { ToastProvider } from "@/lib/toast";
import { useProjectStore } from "@/stores/project";
import { checkIntervalMs, updaterAvailable, useUpdatesStore } from "@/stores/updates";

/** App-update scheduling: load the saved preferences, then check now and on
 *  the configured cadence when auto-updates are enabled. An available update
 *  is installed automatically (the setting promises "install automatically");
 *  manual checks in Settings never install on their own. Runs only in the
 *  packaged (Tauri) app — plain-browser dev has no updater. */
function scheduleUpdates() {
  if (!updaterAvailable()) return;
  const store = useUpdatesStore.getState();
  const checkAndInstall = () => {
    void useUpdatesStore.getState().checkNow().then(() => {
      const s = useUpdatesStore.getState();
      if (s.status === "available" && s.settings?.auto_update) void s.install();
    });
  };
  void store.loadSettings().then(() => {
    const settings = useUpdatesStore.getState().settings;
    if (!settings?.auto_update) return;
    checkAndInstall();
    const ms = checkIntervalMs(settings.check_interval);
    if (ms != null) {
      const timer = setInterval(() => {
        const current = useUpdatesStore.getState().settings;
        if (current?.auto_update) {
          checkAndInstall();
        } else {
          clearInterval(timer);
        }
      }, ms);
    }
  });
}

function App() {
  useEffect(() => {
    // No default browser context menu anywhere — only the app's custom ones.
    const preventContextMenu = (e: MouseEvent) => e.preventDefault();
    window.addEventListener("contextmenu", preventContextMenu);
    return () => window.removeEventListener("contextmenu", preventContextMenu);
  }, []);

  useEffect(() => {
    scheduleUpdates();
  }, []);

  useEffect(() => {
    // Resolve the backend base URL early (packaged app: the backend may be
    // on an ephemeral port when a second instance is running).
    void initApiBase().then(async () => {
      // In the packaged app, jump straight to the dashboard: auto-open the
      // most recent project (gated by the "auto-load project" setting —
      // default on). The embedded backend takes ~10s to start, so retry
      // until it answers. Plain-browser dev keeps the empty dashboard so
      // the E2E suite can exercise the create/open flows deterministically.
      if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
        try {
          const appSettings = await api.appSettings();
          if (!appSettings.auto_open_project) return;
        } catch {
          /* settings unreachable at boot — keep the default (auto-open) */
        }
        const store = useProjectStore.getState();
        store.setAutoOpening(true);
        store.setAutoOpenStage("backend");
        const tryAutoOpen = async (attempt: number) => {
          try {
            // Short timeout: when the backend is still booting this fails
            // fast and the tight retry cadence opens the project the moment
            // the backend answers (no welcome screen flash).
            const { recent } = await api.recentProjects(3_000);
            useProjectStore.getState().setAutoOpenStage("open");
            for (const path of recent.slice(0, 3)) {
              // A hanging open (e.g. a large project while the backend is
              // still warming up) must never freeze the dashboard — give up
              // after 30s and let the user open it manually.
              const ok = await Promise.race([
                useProjectStore.getState().openProject(path),
                new Promise<boolean>((resolve) => setTimeout(() => resolve(false), 30_000)),
              ]);
              if (ok) {
                useProjectStore.getState().setAutoOpening(false);
                return;
              }
            }
          } catch {
            if (attempt < 120) {
              setTimeout(() => void tryAutoOpen(attempt + 1), 250);
              return;
            }
          }
          useProjectStore.getState().setAutoOpening(false);
        };
        void tryAutoOpen(0);
      }
    });
  }, []);

  return (
    <I18nProvider>
      <ToastProvider>
        <div className="flex h-full flex-col">
          <ProjectShell />
        </div>
      </ToastProvider>
    </I18nProvider>
  );
}

export default App;
