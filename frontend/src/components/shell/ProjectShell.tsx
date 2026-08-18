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
  Bug,
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
  Terminal,
  Trash2,
  Upload,
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
import { BugReportView } from "@/features/bugreport/BugReportView";
import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { useInspectorStore } from "@/stores/inspector";
import { usePrefsStore } from "@/stores/prefs";
import { useWorkspaceStore, type WorkspaceView } from "@/stores/workspace";
import { useProjectStore } from "@/stores/project";
import { A11ySkipLink } from "@/features/accessibility/A11yControls";
import { useUpdatesStore } from "@/stores/updates";
import { Button, Modal } from "@/components/ui/orchestrator";
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
  const annotations = useInspectorStore((s) => s.annotationsAll);
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
  const view = useWorkspaceStore((s) => s.view);
  const setView = useWorkspaceStore((s) => s.setView);
  const analyzeUi = useWorkspaceStore((s) => s.analyzeUi);
  const rightPane = useWorkspaceStore((s) => s.rightPane);
  const setRightPane = useWorkspaceStore((s) => s.setRightPane);
  const projectOpen = useProjectStore((s) => s.projectOpen);
  const tasks = useProjectStore((s) => s.tasks);
  const tasksPaused = useProjectStore((s) => s.tasksPaused);
  const duplicateCoder = useProjectStore((s) => s.duplicateCoder);
  const acknowledgeDuplicateCoder = useProjectStore((s) => s.acknowledgeDuplicateCoder);
  const syncAutoNotice = usePrefsStore((s) => s.syncAutoNotice);
  const [queueOpen, setQueueOpen] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const announceRef = useRef<HTMLDivElement>(null);
  const a11yMode = usePrefsStore((s) => s.a11yMode);

  // Shared-folder notice: shown for 3s after the backend auto-enabled
  // collaboration sync on project open (non-intrusive, self-clearing).
  useEffect(() => {
    if (!syncAutoNotice) return;
    const timer = window.setTimeout(() => {
      usePrefsStore.getState().setSyncAutoNotice(false);
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [syncAutoNotice]);

  // Live coder presence: refresh the list of active instances while a
  // project is open, and report this instance's current file to the others.
  const PRESENCE_POLL_MS = 10_000;
  useEffect(() => {
    if (!projectOpen) return;
    let cancelled = false;
    const refresh = async () => {
      if (cancelled) return;
      await usePrefsStore.getState().refreshPresence();
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), PRESENCE_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [projectOpen]);

  // Report which file this instance is working on whenever the view changes,
  // so other raters see the live "on which file" indicator.
  useEffect(() => {
    if (!projectOpen) return;
    const store = usePrefsStore.getState();
    if (view.kind === "coding" && "sourceId" in view) {
      const source = useProjectStore.getState().sources.find((s) => s.id === view.sourceId);
      store.reportFileActivity(view.sourceId, source?.name ?? String(view.sourceId));
    } else {
      store.reportFileActivity(null, "");
    }
  }, [projectOpen, view]);

  // Announce task completion for screen readers (aria-live region — only
  // mounted in screen-reader mode so the default DOM stays quiet).
  const announce = (text: string) => {
    if (announceRef.current) announceRef.current.textContent = text;
  };

  // Poll running background jobs (transcription + autocode + R); refresh
  // the project when one finishes.
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
          } else if (task.kind === "autocode") {
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
          } else if (task.kind === "r") {
            const j = await api.rJob(task.id);
            const completed = j.state !== "running" && task.state === "running";
            store.updateRJob(task.id, {
              state: j.state as TaskInfo["state"],
              progress: j.progress,
              message: j.message,
            });
            if (completed) {
              if (j.state === "done") {
                void store.refreshProject();
                toast.success(t("r.done"));
                announce(t("r.done"));
              } else if (j.state === "error") {
                toast.error(t("r.error"));
                announce(t("r.error"));
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
    else if (next.kind === "r") store.updateRJob(next.id, { state: "running", progress: 1, message: "starting" });
    else store.updateAutocodeJob(next.id, { state: "running", progress: 1, message: "starting" });
    const start = () =>
      next.kind === "transcribe"
        ? api.transcribeJobControl(next.id, "start")
        : next.kind === "r"
          // R jobs start running at POST /r/run; the queued branch never
          // occurs (enqueueRJob stores them running) — kept for safety.
          ? Promise.resolve({ ok: true })
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
  const showIndicator = tasks.length > 0;
  // Overall progress for the fill circle: active jobs average, or 100 once
  // everything is done (stopped circle).
  const taskProgress =
    activeJobs.length > 0
      ? Math.round(activeJobs.reduce((sum, j) => sum + j.progress, 0) / activeJobs.length)
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
      {syncAutoNotice && (
        <div
          role="status"
          aria-live="polite"
          className="pointer-events-none fixed left-1/2 top-12 z-40 -translate-x-1/2"
        >
          <div className="flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-1.5 text-xs text-text-primary shadow-qc-md">
            <Users size={13} className="shrink-0 text-accent" aria-hidden />
            {t("sync.autoEnabled")}
          </div>
        </div>
      )}
      {duplicateCoder && (
        <Modal
          open
          onClose={acknowledgeDuplicateCoder}
          size="sm"
          title={t("coder.duplicateWarningTitle")}
        >
          <div className="space-y-4 p-4">
            <p className="text-sm leading-relaxed text-text-primary">
              {t("coder.duplicateWarning", { name: duplicateCoder })}
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={acknowledgeDuplicateCoder}>
                {t("coder.duplicateSwitch")}
              </Button>
              <Button variant="primary" onClick={acknowledgeDuplicateCoder}>
                {t("coder.duplicateContinue")}
              </Button>
            </div>
          </div>
        </Modal>
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
                          useWorkspaceStore.getState().setNotesUi({ tab: "journal" });
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
                <Menu
                  position="fixed"
                  role="menu"
                  className="w-80 overflow-y-auto"
                  style={{
                    right: 8,
                    maxHeight: "calc(100dvh - 3.5rem)",
                    maxWidth: "calc(100vw - 16px)",
                  }}
                >
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
                  {tasks.length === 0 && (
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
                      className={`pl-2 pr-1 py-1.5 ${dragId === job.id ? "opacity-50" : ""}`}
                    >
                      <div className="flex items-center gap-2 text-xs">
                        <span
                          className="flex min-w-0 flex-1 items-center gap-1.5"
                          title={
                            job.kind === "transcribe"
                              ? t("tasks.kindTranscribe")
                              : job.kind === "r"
                                ? t("tasks.kindR")
                                : job.kind === "import"
                                  ? t("tasks.kindImport")
                                  : t("tasks.kindAutocode")
                          }
                        >
                          <span className="flex w-4 shrink-0 items-center justify-center" aria-hidden>
                            {job.kind === "transcribe" ? (
                              <AudioLines size={12} aria-hidden />
                            ) : job.kind === "r" ? (
                              <Terminal size={12} aria-hidden />
                            ) : job.kind === "import" ? (
                              <Upload size={12} aria-hidden />
                            ) : (
                              <Sparkles size={12} aria-hidden />
                            )}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-text-primary">
                            {job.kind === "import" ? t("files.importingShort") : job.sourceName}
                          </span>
                        </span>
                        <span className="shrink-0 text-text-secondary">
                          {job.state === "running"
                            ? job.kind === "import"
                              ? job.message // "done/total"
                              : `${Math.round(job.progress)}%`
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
                          className="ml-auto shrink-0 rounded-sm p-0.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
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
        {/* Report a bug: screenshot + GitHub issue composer (works with and
            without a project — same availability as Settings). */}
        <button
          type="button"
          onClick={() => void useProjectStore.getState().openBugReport()}
          aria-label={t("nav.bugReport")}
          title={t("nav.bugReport")}
          className="rounded-sm px-2 py-1 text-text-secondary hover:bg-surface-higher"
        >
          <Bug size={20} aria-hidden />
        </button>
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
      }
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
      <BugReportView />
    </>
  );
}
