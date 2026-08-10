/**
 * Project shell — toolbar, sidebar, workspace, status bar.
 * Always rendered: with a project open it shows the full workspace; without
 * one the dashboard empty state provides New/Open project (the app always
 * starts on the dashboard).
 */
import { useEffect, useState } from "react";
import {
  BarChart3,
  Files,
  History,
  LayoutDashboard,
  LoaderCircle,
  Network,
  NotebookPen,
  Settings,
  Sparkles,
  Users,
} from "lucide-react";
import { Sidebar } from "@/components/shell/Sidebar";
import { Inspector } from "@/components/shell/Inspector";
import { CoderSwitcher } from "@/components/shell/CoderSwitcher";
import { DashboardView } from "@/features/dashboard/DashboardView";
import { CodingWorkspace } from "@/features/coding/CodingWorkspace";
import { FileManager } from "@/features/manage/FileManager";
import { CasesView } from "@/features/cases/CasesView";
import { NotesView } from "@/features/notes/NotesView";
import { AnalyzeView } from "@/features/analyze/AnalyzeView";
import { GraphsView } from "@/features/graphs/GraphsView";
import { HistoryView } from "@/features/history/HistoryView";
import { SettingsView } from "@/features/settings/SettingsView";
import { AiView } from "@/features/ai/AiView";
import { api, type HealthStatus } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { useProjectStore, type WorkspaceView } from "@/stores/project";

function BackendStatus() {
  const { t } = useI18n();
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .health()
      .then((h) => {
        if (!cancelled) setHealth(h);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "backend unreachable");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <span className="flex items-center gap-1.5 text-warning" role="status">
        <span className="h-2 w-2 rounded-full bg-warning" aria-hidden />
        {t("backend.offline")}
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 text-text-secondary" role="status">
      <span className="h-2 w-2 rounded-full bg-success" aria-hidden />
      {health ? t("backend.ok", { status: health.status }) : t("backend.connecting")}
    </span>
  );
}

function ThemeToggle() {
  const { t } = useI18n();
  const mode = useProjectStore((s) => s.themeMode);
  const setThemeMode = useProjectStore((s) => s.setThemeMode);
  return (
    <button
      type="button"
      onClick={() => setThemeMode(mode === "dark" ? "light" : "dark")}
      className="rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher"
      aria-label={t("theme.switchLabel", { theme: mode === "dark" ? "light" : "dark" })}
    >
      {mode === "dark" ? t("theme.light") : t("theme.dark")}
    </button>
  );
}

function StatusBar() {
  const { t } = useI18n();
  const summary = useProjectStore((s) => s.summary);
  const projectName = useProjectStore((s) => s.projectName);
  return (
    <footer className="flex h-6 shrink-0 items-center gap-4 border-t border-border bg-surface px-3 text-xs text-text-secondary">
      <span className="font-medium text-text-primary">{projectName}</span>
      <span>
        {summary
          ? t("status.summary", { files: summary.files_count, codes: summary.codes_count })
          : ""}
      </span>
      <span className="flex-1" />
      <span>{t("app.version")}</span>
    </footer>
  );
}

const NAV_BUTTONS: { kind: WorkspaceView["kind"]; labelKey: string; icon: typeof Files }[] = [
  { kind: "dashboard", labelKey: "nav.dashboard", icon: LayoutDashboard },
  { kind: "files", labelKey: "nav.files", icon: Files },
  { kind: "cases", labelKey: "nav.cases", icon: Users },
  { kind: "notes", labelKey: "nav.notes", icon: NotebookPen },
  { kind: "analyze", labelKey: "nav.analyze", icon: BarChart3 },
  { kind: "graphs", labelKey: "nav.graphs", icon: Network },
  { kind: "history", labelKey: "nav.history", icon: History },
  { kind: "ai", labelKey: "nav.ai", icon: Sparkles },
];

export function ProjectShell() {
  const { t } = useI18n();
  const toast = useToast();
  const view = useProjectStore((s) => s.view);
  const setView = useProjectStore((s) => s.setView);
  const projectOpen = useProjectStore((s) => s.projectOpen);
  const transcribeJobs = useProjectStore((s) => s.transcribeJobs);
  const importState = useProjectStore((s) => s.importState);
  const [queueOpen, setQueueOpen] = useState(false);

  // Poll running transcription jobs; refresh the project when one finishes.
  useEffect(() => {
    if (transcribeJobs.length === 0) return;
    const poll = async () => {
      const store = useProjectStore.getState();
      for (const job of store.transcribeJobs) {
        if (job.state !== "running") continue;
        try {
          const j = await api.transcribeJob(job.id);
          const completed = j.state !== "running" && job.state === "running";
          store.updateTranscribeJob(job.id, {
            state: j.state,
            progress: j.progress,
            message: j.message,
            transcriptSourceId: j.transcript_source_id ?? null,
          });
          if (completed && j.state === "done") {
            void store.refreshProject();
            toast.success(t("transcribe.done", { id: j.transcript_source_id ?? 0 }));
          }
        } catch {
          /* transient — the next poll retries */
        }
      }
    };
    const timer = setInterval(() => void poll(), 1500);
    return () => clearInterval(timer);
  }, [transcribeJobs.length, t, toast]);

  const activeJobs = transcribeJobs.filter((j) => j.state === "running");
  const finishedJobs = transcribeJobs.filter((j) => j.state !== "running");
  const avgProgress =
    activeJobs.length > 0
      ? Math.round(activeJobs.reduce((sum, j) => sum + j.progress, 0) / activeJobs.length)
      : 100;
  const hasBackground = transcribeJobs.length > 0 || importState !== null;

  return (
    <div className="flex h-full flex-col bg-bg text-text-primary">
      {/* Toolbar */}
      <header className="flex h-11 shrink-0 items-center gap-0.5 border-b border-border bg-surface px-3">
        {projectOpen ? (
          <>
            {NAV_BUTTONS.map(({ kind, labelKey, icon: Icon }) => {
              const label = t(labelKey);
              return (
                <button
                  key={kind}
                  type="button"
                  onClick={() => setView({ kind } as WorkspaceView)}
                  aria-label={label}
                  title={label}
                  className={`flex items-center gap-1.5 rounded-sm px-2 py-1 hover:bg-surface-higher ${
                    view.kind === kind ? "bg-surface-higher text-accent" : "text-text-secondary"
                  }`}
                >
                  <Icon size={20} aria-hidden />
                  <span className="text-xs font-medium">{label}</span>
                </button>
              );
            })}
            <div className="h-5 w-px bg-border" aria-hidden />
          </>
        ) : (
          <>
            <span className="font-heading">{t("app.name")}</span>
            <span className="text-xs text-text-secondary">{t("app.version")}</span>
          </>
        )}
        <div className="flex-1" />
        <CoderSwitcher />
        {projectOpen ? (
          <>
            {hasBackground && (
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setQueueOpen((o) => !o)}
                  aria-expanded={queueOpen}
                  className="flex items-center gap-1.5 rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher"
                >
                  <LoaderCircle size={12} className="animate-spin" aria-hidden />
                  {activeJobs.length > 0
                    ? `${t("transcribe.running")} ${avgProgress}%`
                    : importState !== null
                      ? `${t("files.importingShort")} ${Math.round((importState.done / importState.total) * 100)}%`
                      : `${finishedJobs.length} ${t("transcribe.finished")}`}
                </button>
                {queueOpen && (
                  <div className="absolute right-0 top-full z-50 mt-1 w-72 rounded-md border border-border bg-surface py-1 shadow-lg">
                    <div className="border-b border-border px-2 py-1 text-xs font-medium text-text-secondary">
                      {t("transcribe.queue")}
                    </div>
                    {importState !== null && (
                      <div className="px-2 py-1.5">
                        <div className="flex items-center gap-2 text-xs">
                          <span className="min-w-0 flex-1 truncate text-text-primary">
                            {t("files.importingShort")}
                          </span>
                          <span className="text-text-secondary">
                            {importState.done}/{importState.total}
                          </span>
                        </div>
                        <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-border">
                          <div
                            className="h-full rounded-full bg-accent transition-all"
                            style={{
                              width: `${Math.round((importState.done / importState.total) * 100)}%`,
                            }}
                          />
                        </div>
                      </div>
                    )}
                    {transcribeJobs.map((job) => (
                      <div key={job.id} className="px-2 py-1.5">
                        <div className="flex items-center gap-2 text-xs">
                          <span className="min-w-0 flex-1 truncate text-text-primary">
                            {job.sourceName}
                          </span>
                          <span className="text-text-secondary">
                            {job.state === "running"
                              ? `${Math.round(job.progress)}%`
                              : job.state === "done"
                                ? "✓"
                                : "✗"}
                          </span>
                        </div>
                        <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-border">
                          <div
                            className="h-full rounded-full bg-accent transition-all"
                            style={{ width: `${Math.round(job.progress)}%` }}
                          />
                        </div>
                      </div>
                    ))}
                    {finishedJobs.length > 0 && (
                      <button
                        type="button"
                        onClick={() => useProjectStore.getState().clearFinishedTranscribeJobs()}
                        className="w-full px-2 py-1.5 text-left text-xs text-text-secondary hover:bg-surface-higher"
                      >
                        {t("transcribe.clearFinished")}
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
            <button
              type="button"
              onClick={() => setView({ kind: "settings" })}
              aria-label={t("nav.settings")}
              title={t("nav.settings")}
              className={`rounded-sm px-2 py-1 hover:bg-surface-higher ${
                view.kind === "settings" ? "bg-surface-higher text-accent" : "text-text-secondary"
              }`}
            >
              <Settings size={20} aria-hidden />
            </button>
          </>
        ) : (
          <>
            <BackendStatus />
            <ThemeToggle />
          </>
        )}
      </header>

      {/* Body: sidebar | workspace | inspector (only with an open project).
          Cases/journals have their own function bars — hide the sidebar. */}
      {projectOpen ? (
        <div className="flex min-h-0 flex-1">
          {view.kind !== "cases" && view.kind !== "notes" && <Sidebar />}
          <main className="min-w-0 flex-1 overflow-hidden">
            {view.kind === "coding" ? (
              <CodingWorkspace sourceId={view.sourceId} />
            ) : view.kind === "files" ? (
              <FileManager />
            ) : view.kind === "cases" ? (
              <CasesView />
            ) : view.kind === "notes" ? (
              <NotesView />
            ) : view.kind === "analyze" ? (
              <AnalyzeView />
            ) : view.kind === "graphs" ? (
              <GraphsView />
            ) : view.kind === "history" ? (
              <HistoryView />
            ) : view.kind === "ai" ? (
              <AiView />
            ) : view.kind === "settings" ? (
              <SettingsView />
            ) : (
              <DashboardView />
            )}
          </main>
          <Inspector />
        </div>
      ) : (
        <main className="min-h-0 flex-1 overflow-hidden">
          <DashboardView />
        </main>
      )}

      {projectOpen && <StatusBar />}
    </div>
  );
}
