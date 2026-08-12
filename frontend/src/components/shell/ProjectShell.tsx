/**
 * Project shell — toolbar, sidebar, workspace, status bar.
 * Always rendered: with a project open it shows the full workspace; without
 * one the dashboard empty state provides New/Open project (the app always
 * starts on the dashboard).
 */
import { useEffect, useState } from "react";
import {
  BarChart3,
  Download,
  Files,
  History,
  LayoutDashboard,
  Network,
  NotebookPen,
  Settings,
  Sparkles,
  Users,
} from "lucide-react";
import { Sidebar } from "@/components/shell/Sidebar";
import { Inspector } from "@/components/shell/Inspector";
import { CoderSwitcher } from "@/components/shell/CoderSwitcher";
import { WorkspaceLayout } from "@/components/shell/WorkspaceLayout";
import { DashboardView } from "@/features/dashboard/DashboardView";
import { CodingWorkspace } from "@/features/coding/CodingWorkspace";
import { FileManager } from "@/features/manage/FileManager";
import { CaseDetails, CasesList } from "@/features/cases/CasesView";
import { NotesEditor, NotesList } from "@/features/notes/NotesView";
import { AnalyzeView } from "@/features/analyze/AnalyzeView";
import { ReportsList } from "@/features/analyze/ReportsList";
import { GraphsInspector, GraphsList, GraphsView } from "@/features/graphs/GraphsView";
import { HistoryView } from "@/features/history/HistoryView";
import { SettingsView } from "@/features/settings/SettingsView";
import { AiView } from "@/features/ai/AiView";
import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { useProjectStore, type WorkspaceView } from "@/stores/project";
import { useUpdatesStore } from "@/stores/updates";
import { Button } from "@/components/ui/orchestrator";
import { cls } from "@/components/ui/tokens";
import { Menu, MenuItem } from "@/components/ui/orchestrator";

/** Circular progress indicator (same size as the ribbon icon buttons). */
function TaskIndicator({ progress }: { progress: number }) {
  const r = 7;
  const c = 2 * Math.PI * r;
  const filled = Math.max(0, Math.min(100, progress));
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 18 18"
      className="-rotate-90"
      aria-hidden
    >
      <circle cx="9" cy="9" r={r} fill="none" stroke="var(--qc-border)" strokeWidth="2.5" />
      <circle
        cx="9"
        cy="9"
        r={r}
        fill="none"
        stroke="var(--qc-accent)"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeDasharray={`${(filled / 100) * c} ${c}`}
      />
    </svg>
  );
}

/**
 * Update status inside the background-tasks flyout: only rendered while an
 * update is available or being downloaded (quiet otherwise).
 */
function UpdateStatusRow() {
  const { t } = useI18n();
  const status = useUpdatesStore((s) => s.status);
  const info = useUpdatesStore((s) => s.info);
  const progress = useUpdatesStore((s) => s.progress);
  if (status === "available" && info) {
    return (
      <div className="flex items-center gap-2 border-b border-border px-2 py-1.5">
        <span className="min-w-0 flex-1 truncate text-xs text-text-primary">
          {t("settings.updatesAvailable", { version: info.version })}
        </span>
        <Button
          variant="primary"
          icon={<Download size={11} aria-hidden />}
          onClick={() => void useUpdatesStore.getState().install()}
        >
          {t("settings.updatesInstall")}
        </Button>
      </div>
    );
  }
  if (status === "downloading") {
    return (
      <div className="border-b border-border px-2 py-1.5">
        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="text-text-primary">{t("settings.updatesDownloading", { pct: String(progress) })}</span>
          <span className="text-text-secondary">{t("settings.updatesInstall")}</span>
        </div>
        <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-border">
          <div
            className="h-full rounded-full bg-accent transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
    );
  }
  return null;
}

function StatusBar() {
  const { t } = useI18n();
  const summary = useProjectStore((s) => s.summary);
  const projectName = useProjectStore((s) => s.projectName);
  const cases = useProjectStore((s) => s.cases);
  const journals = useProjectStore((s) => s.journals);
  const annotations = useProjectStore((s) => s.annotationsAll);
  const sources = useProjectStore((s) => s.sources);
  const codeTree = useProjectStore((s) => s.codeTree);
  const memoCount =
    sources.filter((s) => (s.memo ?? "").trim() !== "").length +
    codeTree.filter((c) => (c.memo ?? "").trim() !== "").length;
  return (
    <footer className="flex h-6 shrink-0 items-center gap-4 border-t border-border bg-surface px-3 text-xs text-text-secondary">
      <span className="font-medium text-text-primary">{projectName}</span>
      <span>
        {summary
          ? `${summary.files_count} ${t("status.files")} · ${summary.codes_count} ${t("status.codes")}`
          : ""}
      </span>
      {cases.length > 0 && <span>{cases.length} {t("status.cases")}</span>}
      {journals.length > 0 && <span>{journals.length} {t("status.journals")}</span>}
      {annotations.length > 0 && <span>{annotations.length} {t("status.annotations")}</span>}
      {memoCount > 0 && <span>{memoCount} {t("status.memos")}</span>}
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
];

const RIGHT_ICON_BUTTONS: { pane: "history" | "ai"; labelKey: string; icon: typeof Files }[] = [
  { pane: "history", labelKey: "nav.history", icon: History },
  { pane: "ai", labelKey: "nav.ai", icon: Sparkles },
];

export function ProjectShell() {
  const { t } = useI18n();
  const toast = useToast();
  const view = useProjectStore((s) => s.view);
  const setView = useProjectStore((s) => s.setView);
  const rightPane = useProjectStore((s) => s.rightPane);
  const setRightPane = useProjectStore((s) => s.setRightPane);
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
            // Clean the top-bar indicator: finished jobs auto-remove shortly
            // after completion instead of lingering as a stopped queue.
            window.setTimeout(() => {
              useProjectStore.getState().clearFinishedTranscribeJobs();
            }, 6000);
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
  const showIndicator = transcribeJobs.length > 0 || importState !== null;
  // Overall progress for the fill circle: active jobs average, import %, or
  // 100 once everything is done (stopped circle).
  const taskProgress =
    activeJobs.length > 0
      ? Math.round(activeJobs.reduce((sum, j) => sum + j.progress, 0) / activeJobs.length)
      : importState !== null
        ? Math.round((importState.done / importState.total) * 100)
        : 100;

  return (
    <WorkspaceLayout
      ribbon={
        <header className="flex h-11 shrink-0 items-center gap-0.5 border-b border-border bg-surface px-3">
          {NAV_BUTTONS.map(({ kind, labelKey, icon: Icon }) => {
            const label = t(labelKey);
            return (
              <button
                key={kind}
                type="button"
                onClick={projectOpen ? () => setView({ kind } as WorkspaceView) : undefined}
                disabled={!projectOpen}
                aria-label={label}
                title={projectOpen ? label : t("shell.navDisabled")}
                className={`flex items-center gap-1.5 rounded-sm px-2 py-1 ${
                  !projectOpen
                    ? "cursor-not-allowed text-text-secondary/40"
                    : `hover:bg-surface-higher ${
                        view.kind === kind ? "bg-surface-higher text-accent" : "text-text-secondary"
                      }`
                }`}
              >
                <Icon size={20} aria-hidden />
                <span className="text-xs font-medium">{label}</span>
              </button>
            );
          })}
          <div className="h-5 w-px bg-border" aria-hidden />
          <div className="flex-1" />
          {projectOpen && showIndicator && (
            <div className="relative">
              <button
                type="button"
                onClick={() => setQueueOpen((o) => !o)}
                aria-expanded={queueOpen}
                aria-label={t("transcribe.queue")}
                title={t("transcribe.queue")}
                className={cls.secondary}
              >
                <TaskIndicator progress={taskProgress} />
                {activeJobs.length > 0 ? String(activeJobs.length) : ""}
              </button>
              {queueOpen && (
                <Menu className="right-0 w-72">
                  <div className="border-b border-border px-2 py-1 text-xs font-medium text-text-secondary">
                    {t("transcribe.queue")}
                  </div>
                  {/* App-update info rides in the same background-tasks
                      flyout: available → download button, downloading →
                      progress. */}
                  <UpdateStatusRow />
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
                    <MenuItem
                      className="text-xs text-text-secondary"
                      onClick={() => useProjectStore.getState().clearFinishedTranscribeJobs()}
                    >
                      {t("transcribe.clearFinished")}
                    </MenuItem>
                  )}
                </Menu>
              )}
            </div>
          )}
          {projectOpen && <CoderSwitcher />}
          {projectOpen && (
            <>
              {RIGHT_ICON_BUTTONS.map(({ pane, labelKey, icon: Icon }) => {
              const label = t(labelKey);
              const active = rightPane === pane;
              return (
                <button
                  key={pane}
                  type="button"
                  onClick={() => setRightPane(active ? "inspector" : pane)}
                  aria-label={label}
                  title={label}
                  aria-pressed={active}
                  className={`rounded-sm px-2 py-1 hover:bg-surface-higher ${
                    active ? "bg-surface-higher text-accent" : "text-text-secondary"
                  }`}
                >
                  <Icon size={20} aria-hidden />
                </button>
              );
            })}
          </>
        )}
        {/* Settings is available without a project (theme, AI and
            transcription options are machine-level). */}
        <button
          type="button"
          onClick={() => setRightPane(rightPane === "settings" ? "inspector" : "settings")}
          aria-label={t("nav.settings")}
          title={t("nav.settings")}
          aria-pressed={rightPane === "settings"}
          className={`rounded-sm px-2 py-1 hover:bg-surface-higher ${
            rightPane === "settings" ? "bg-surface-higher text-accent" : "text-text-secondary"
          }`}
        >
          <Settings size={20} aria-hidden />
        </button>
      </header>
      }      menuBar={undefined}
      leftBar={
        view.kind === "cases" ? (
          <CasesList />
        ) : view.kind === "notes" ? (
          <NotesList />
        ) : view.kind === "graphs" ? (
          <GraphsList />
        ) : view.kind === "analyze" ? (
          // The reports list replaces the standard file-groups sidebar
          // while the Analysis area is active.
          <ReportsList />
        ) : (
          <Sidebar />
        )
      }
      rightBar={
        rightPane === "ai" ? (
          <AiView />
        ) : rightPane === "settings" ? (
          <SettingsView />
        ) : rightPane === "history" ? (
          <HistoryView />
        ) : view.kind === "graphs" ? (
          // The graph details inspector opens automatically; closing the
          // AI/Settings/History panes returns here.
          <GraphsInspector />
        ) : (
          <Inspector />
        )
      }
      statusBar={<StatusBar />}
    >
      {projectOpen ? (
        view.kind === "coding" ? (
          <CodingWorkspace sourceId={view.sourceId} />
        ) : view.kind === "files" ? (
          <FileManager />
        ) : view.kind === "cases" ? (
          <CaseDetails />
        ) : view.kind === "notes" ? (
          <NotesEditor />
        ) :         view.kind === "analyze" ? (
          <AnalyzeView />
        ) : view.kind === "graphs" ? (
          <GraphsView />
        ) : (
          <DashboardView />
        )
      ) : (
        <DashboardView />
      )}
    </WorkspaceLayout>
  );
}
