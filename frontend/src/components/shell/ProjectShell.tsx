/**
 * Project shell — toolbar, sidebar, workspace, status bar.
 * Always rendered: with a project open it shows the full workspace; without
 * one the dashboard empty state provides New/Open project (the app always
 * starts on the dashboard).
 */
import { useEffect, useRef, useState } from "react";
import {
  AudioLines,
  BarChart3,
  Download,
  Files,
  History,
  LayoutDashboard,
  Lightbulb,
  NotebookPen,
  Pause,
  Play,
  ScrollText,
  Settings,
  Sparkles,
  Trash2,
  Users,
} from "lucide-react";
import type { TaskInfo } from "@/stores/project";
import { Sidebar } from "@/components/shell/Sidebar";
import { Inspector } from "@/components/shell/Inspector";
import { CoderSwitcher } from "@/components/shell/CoderSwitcher";
import { WorkspaceLayout } from "@/components/shell/WorkspaceLayout";
import { DashboardView } from "@/features/dashboard/DashboardView";
import { CodingWorkspace } from "@/features/coding/CodingWorkspace";
import { FileManager } from "@/features/manage/FileManager";
import { CaseDetails, CasesList } from "@/features/cases/CasesView";
import { NotesEditor, NotesList } from "@/features/notes/NotesView";
import { QttList, QttView } from "@/features/qtt/QttView";
import { AnalyzeView } from "@/features/analyze/AnalyzeView";
import { ReportsList } from "@/features/analyze/ReportsList";
import { GraphsInspector, GraphsView } from "@/features/graphs/GraphsView";
import { HistoryView } from "@/features/history/HistoryView";
import { CreativePanel } from "@/features/creative/CreativePanel";
import { SettingsView } from "@/features/settings/SettingsView";
import { AiView } from "@/features/ai/AiView";
import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { useProjectStore, type WorkspaceView } from "@/stores/project";
import { A11ySkipLink } from "@/features/accessibility/A11yControls";
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
  { kind: "qtt", labelKey: "nav.qtt", icon: ScrollText },
  { kind: "analyze", labelKey: "nav.analyze", icon: BarChart3 },
];

const RIGHT_ICON_BUTTONS: { pane: "history" | "ai" | "creative"; labelKey: string; icon: typeof Files }[] = [
  { pane: "history", labelKey: "nav.history", icon: History },
  { pane: "ai", labelKey: "nav.ai", icon: Sparkles },
  { pane: "creative", labelKey: "nav.creative", icon: Lightbulb },
];

export function ProjectShell() {
  const { t } = useI18n();
  const toast = useToast();
  const view = useProjectStore((s) => s.view);
  const setView = useProjectStore((s) => s.setView);
  const analyzeUi = useProjectStore((s) => s.analyzeUi);
  const rightPane = useProjectStore((s) => s.rightPane);
  const setRightPane = useProjectStore((s) => s.setRightPane);
  const projectOpen = useProjectStore((s) => s.projectOpen);
  const tasks = useProjectStore((s) => s.tasks);
  const tasksPaused = useProjectStore((s) => s.tasksPaused);
  const importState = useProjectStore((s) => s.importState);
  const [queueOpen, setQueueOpen] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const announceRef = useRef<HTMLDivElement>(null);
  const a11yMode = useProjectStore((s) => s.a11yMode);

  // Announce task completion for screen readers (aria-live region — only
  // mounted in screen-reader mode so the default DOM stays quiet).
  const announce = (text: string) => {
    if (announceRef.current) announceRef.current.textContent = text;
  };

  // Poll running background jobs (transcription + autocode); refresh the
  // project when one finishes.
  useEffect(() => {
    if (tasks.length === 0) return;
    const poll = async () => {
      const store = useProjectStore.getState();
      for (const task of store.tasks) {
        if (task.state !== "running") continue;
        try {
          if (task.kind === "transcribe") {
            const j = await api.transcribeJob(task.id);
            const completed = j.state !== "running" && task.state === "running";
            store.updateTranscribeJob(task.id, {
              state: j.state as TaskInfo["state"],
              progress: j.progress,
              message: j.message,
              paused: j.paused,
              transcriptSourceId: j.transcript_source_id ?? null,
            });
            if (completed && j.state === "done") {
              void store.refreshProject();
              toast.success(t("transcribe.done", { id: j.transcript_source_id ?? 0 }));
              announce(t("transcribe.done", { id: j.transcript_source_id ?? 0 }));
            }
          } else {
            const j = await api.autocodeJob(task.id);
            const completed = j.state !== "running" && task.state === "running";
            store.updateAutocodeJob(task.id, {
              state: j.state as TaskInfo["state"],
              progress: j.progress,
              message: j.message,
              paused: j.paused,
              resultCount: j.result?.count ?? null,
            });
            if (completed) {
              if (j.state === "done") {
                void store.refreshProject();
                toast.success(t("tasks.autocoded", { count: j.result?.count ?? 0 }));
                announce(t("tasks.autocoded", { count: j.result?.count ?? 0 }));
              } else if (j.state === "error") {
                toast.error(t("tasks.autocodeFailed"));
              }
            }
          }
        } catch {
          /* transient — the next poll retries */
        }
      }
    };
    const timer = setInterval(() => void poll(), 1500);
    return () => clearInterval(timer);
  }, [tasks.length, t, toast]);

  // Sequential queue dispatcher: while not paused, start queued jobs one at
  // a time (nothing may run in parallel with the current job). The task is
  // marked running IN THE STORE before the request fires so the effect never
  // re-starts the same job (and the poll loop picks it up).
  useEffect(() => {
    if (tasksPaused) return;
    const store = useProjectStore.getState();
    if (store.tasks.some((j) => j.state === "running")) return;
    const next = store.tasks.find((j) => j.state === "queued");
    if (!next) return;
    if (next.kind === "transcribe") store.updateTranscribeJob(next.id, { state: "running" });
    else store.updateAutocodeJob(next.id, { state: "running", progress: 1, message: "starting" });
    const start = () =>
      next.kind === "transcribe"
        ? api.transcribeJobControl(next.id, "start")
        : api.autocodeJobControl(next.id, "start");
    start().catch(() => {
      /* retried on the next state change */
    });
  }, [tasks, tasksPaused]);

  // Pause/resume: pause halts the dispatcher and pauses the running
  // transcription job (autocode jobs finish their file, then wait).
  useEffect(() => {
    const store = useProjectStore.getState();
    for (const task of store.tasks) {
      if (task.state !== "running") continue;
      if (task.kind !== "transcribe") continue;
      const action = tasksPaused ? "pause" : "resume";
      api.transcribeJobControl(task.id, action).catch(() => {});
      store.updateTranscribeJob(task.id, { paused: tasksPaused });
    }
  }, [tasksPaused]);

  const activeJobs = tasks.filter((j) => j.state === "running");
  const finishedJobs = tasks.filter((j) => j.state === "done" || j.state === "error");
  const showIndicator = tasks.length > 0 || importState !== null;
  // Overall progress for the fill circle: active jobs average, import %, or
  // 100 once everything is done (stopped circle).
  const taskProgress =
    activeJobs.length > 0
      ? Math.round(activeJobs.reduce((sum, j) => sum + j.progress, 0) / activeJobs.length)
      : importState !== null
        ? Math.round((importState.done / importState.total) * 100)
        : 100;

  return (
    <>
      <A11ySkipLink />
      {a11yMode === "screenreader" && (
        <div
          ref={announceRef}
          role="status"
          aria-live="polite"
          className="sr-only"
        />
      )}
      <WorkspaceLayout
      ribbon={
        <header className="flex h-11 shrink-0 items-center gap-0.5 border-b border-border bg-surface px-3">
          {NAV_BUTTONS.map(({ kind, labelKey, icon: Icon }) => {
            const label = t(labelKey);
            return (
              <button
                key={kind}
                type="button"
                onClick={
                  projectOpen
                    ? () => {
                        setView({ kind } as WorkspaceView);
                        // The ribbon entry is "Journal": coming back from an
                        // annotations/memos view (opened via the file
                        // inspector) always resets to the journal tab.
                        if (kind === "notes") {
                          useProjectStore.getState().setNotesUi({ tab: "journal" });
                        }
                      }
                    : undefined
                }
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
                aria-label={t("tasks.title")}
                title={t("tasks.title")}
                className={cls.secondary}
              >
                <TaskIndicator progress={taskProgress} />
                {activeJobs.length > 0 ? String(activeJobs.length) : ""}
              </button>
              {queueOpen && (
                <Menu role="menu" className="right-0 w-80">
                  <div className="flex items-center gap-1 border-b border-border px-2 py-1">
                    <span className="min-w-0 flex-1 text-xs font-medium text-text-secondary">
                      {t("tasks.title")}
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        const paused = !useProjectStore.getState().tasksPaused;
                        useProjectStore.getState().setTasksPaused(paused);
                      }}
                      aria-pressed={tasksPaused}
                      title={tasksPaused ? t("tasks.resume") : t("tasks.pause")}
                      className="rounded-sm p-1 hover:bg-surface-higher"
                    >
                      {tasksPaused ? (
                        <Play size={13} aria-hidden />
                      ) : (
                        <Pause size={13} aria-hidden />
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        useProjectStore.getState().clearFinishedTasks();
                      }}
                      title={t("tasks.clear")}
                      className="rounded-sm p-1 hover:bg-surface-higher"
                    >
                      <Trash2 size={13} aria-hidden />
                    </button>
                  </div>
                  {/* App-update info rides in the same background-tasks
                      flyout: available → download button, downloading →
                      progress. */}
                  <UpdateStatusRow />
                  {tasksPaused && (
                    <div className="border-b border-border px-2 py-1 text-xs text-text-secondary">
                      {t("tasks.pausedHint")}
                    </div>
                  )}
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
                  {tasks.length === 0 && importState === null && (
                    <div className="px-2 py-3 text-center text-xs text-text-secondary">
                      {t("tasks.empty")}
                    </div>
                  )}
                  {tasks.map((job) => (
                    <div
                      key={job.id}
                      draggable
                      onDragStart={(e) => {
                        setDragId(job.id);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      onDragOver={(e) => {
                        if (dragId && dragId !== job.id) e.preventDefault();
                      }}
                      onDrop={(e) => {
                        e.preventDefault();
                        if (dragId && dragId !== job.id) {
                          useProjectStore.getState().moveTask(dragId, job.id);
                        }
                        setDragId(null);
                      }}
                      onDragEnd={() => setDragId(null)}
                      className={`px-2 py-1.5 ${dragId === job.id ? "opacity-50" : ""}`}
                    >
                      <div className="flex items-center gap-2 text-xs">
                        <span
                          className="flex items-center gap-1.5"
                          title={job.kind === "transcribe" ? t("tasks.kindTranscribe") : t("tasks.kindAutocode")}
                        >
                          {job.kind === "transcribe" ? (
                            <AudioLines size={12} aria-hidden />
                          ) : (
                            <Sparkles size={12} aria-hidden />
                          )}
                          <span className="min-w-0 flex-1 truncate text-text-primary">
                            {job.sourceName}
                          </span>
                        </span>
                        <span className="shrink-0 text-text-secondary">
                          {job.state === "running"
                            ? `${Math.round(job.progress)}%`
                            : job.state === "queued"
                              ? t("tasks.queued")
                              : job.state === "done"
                                ? "✓"
                                : "✗"}
                        </span>
                        <button
                          type="button"
                          onClick={() => useProjectStore.getState().removeTask(job.id)}
                          aria-label={t("tasks.delete", { name: job.sourceName })}
                          title={t("tasks.delete", { name: job.sourceName })}
                          className="shrink-0 rounded-sm p-0.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
                        >
                          <Trash2 size={12} aria-hidden />
                        </button>
                      </div>
                      <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-border">
                        <div
                          className={`h-full rounded-full transition-all ${
                            job.state === "error" ? "bg-danger" : "bg-accent"
                          }`}
                          style={{
                            width:
                              job.state === "running" || job.state === "done"
                                ? `${Math.round(job.progress)}%`
                                : job.state === "error"
                                  ? "100%"
                                  : "0%",
                          }}
                        />
                      </div>
                    </div>
                  ))}
                  {finishedJobs.length > 0 && (
                    <MenuItem
                      className="text-xs text-text-secondary"
                      onClick={() => useProjectStore.getState().clearFinishedTasks()}
                    >
                      {t("tasks.clearFinished")}
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
        ) : view.kind === "qtt" ? (
          <QttList />
        ) : view.kind === "analyze" ? (
          // The reports list replaces the standard file-groups sidebar
          // while the Analysis area is active (graphs live under it too).
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
        ) : rightPane === "creative" ? (
          <CreativePanel />
        ) : view.kind === "analyze" && analyzeUi.selectedId === "graphs" ? (
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
        ) : view.kind === "qtt" ? (
          <QttView />
        ) :         view.kind === "analyze" ? (
          analyzeUi.selectedId === "graphs" ? (
            <GraphsView />
          ) : (
            <AnalyzeView />
          )
        ) : (
          <DashboardView />
        )
      ) : (
        <DashboardView />
      )}
      </WorkspaceLayout>
    </>
  );
}
