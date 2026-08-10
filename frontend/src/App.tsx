import { useEffect } from "react";
import { ProjectShell } from "@/components/shell/ProjectShell";
import { api, initApiBase } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n";
import { ToastProvider } from "@/lib/toast";
import { useProjectStore } from "@/stores/project";

function App() {
  useEffect(() => {
    // No default browser context menu anywhere — only the app's custom ones.
    const preventContextMenu = (e: MouseEvent) => e.preventDefault();
    window.addEventListener("contextmenu", preventContextMenu);
    return () => window.removeEventListener("contextmenu", preventContextMenu);
  }, []);

  useEffect(() => {
    // Resolve the backend base URL early (packaged app: the backend may be
    // on an ephemeral port when a second instance is running).
    void initApiBase().then(() => {
      // In the packaged app, jump straight to the dashboard: auto-open the
      // most recent project. The embedded backend takes ~10s to start, so
      // retry until it answers. Plain-browser dev keeps the empty dashboard
      // so the E2E suite can exercise the create/open flows deterministically.
      if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
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
              const ok = await useProjectStore.getState().openProject(path);
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
