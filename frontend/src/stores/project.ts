/**
 * Project lifecycle + background jobs + bug report (Zustand).
 *
 * Owns the open-project lifecycle (open/close/create, summary, sources,
 * code tree, cases, journals), the background task queue, the file search
 * query and the bug-report composer state. Workspace view, coder identity,
 * inspector, graph and preference state live in their own slices — this
 * store re-exports their hooks so `@/stores/project` imports keep working.
 */
import { errorMessage, errorTextOf } from "@/lib/utils";
import { create } from "zustand";
import {
  api,
  type Case,
  type CodeTreeItem,
  type ProjectSummary,
  type Source,
  type Journal,
} from "@/lib/api";
import { blankScreenshot, captureAppScreenshot } from "@/features/bugreport/capture";
import { DEFAULT_GITHUB_REPO } from "@/features/bugreport/github";
import { useCoderStore } from "./coder";
import { useInspectorStore } from "./inspector";
import { usePrefsStore } from "./prefs";
import { useWorkspaceStore, type WorkspaceView } from "./workspace";

// --- Shared task / bug-report types ---------------------------------------

/** A background job as tracked by the UI (transcription, autocode, R or
 *  a local file import). */
export type TaskKind = "transcribe" | "autocode" | "r" | "import";
export type TaskState = "queued" | "running" | "done" | "error";
export interface TaskInfo {
  kind: TaskKind;
  id: string;
  sourceId: number;
  sourceName: string;
  state: TaskState;
  progress: number;
  message: string;
  paused?: boolean;
  transcriptSourceId?: number | null;
  /** Number of codings created by an autocode job (done jobs). */
  resultCount?: number | null;
}

/** The bug-report composer state (screenshot + draft + GitHub config). */
export interface BugReportState {
  open: boolean;
  /** PNG data-URL of the RAW screenshot (without paint marks). */
  rawScreenshot: string | null;
  /** True when the capture failed and the fallback blank canvas was used. */
  captureFailed: boolean;
  /** Last uncaught runtime error ("" / null when none). */
  lastError: string | null;
  /** Last action label (view or newest audit row), shown in the env block. */
  lastAction: string | null;
  title: string;
  body: string;
  labels: string[];
  assignee: string;
  milestone: string;
  /** GitHub integration config read from the app settings on open. */
  githubToken: string;
  githubRepo: string;
}

interface ProjectLifecycleState {
  projectOpen: boolean;
  projectName: string;
  /** Absolute path of the open project ("" when none). Used by the sync
   *  override (per-project decisions) and the shared-folder notice. */
  projectPath: string;
  /** File search query shared by the left sidebar and the center Files
   *  table (the sidebar box filters both). */
  fileQuery: string;
  setFileQuery: (q: string) => void;
  summary: ProjectSummary | null;
  sources: Source[];
  codeTree: CodeTreeItem[];
  cases: Case[];
  journals: Journal[];
  busy: boolean;
  error: string | null;

  /** Another live instance is already open as the current coder (set from
   *  the open-project result). The shell shows a blocking warning; the user
   *  can acknowledge and proceed (offline work is valid). Cleared on
   *  acknowledge or close. */
  duplicateCoder: string;
  acknowledgeDuplicateCoder: () => void;

  /** True while the packaged app is auto-opening the last project. */
  autoOpening: boolean;
  autoOpenStage: "backend" | "open";
  setAutoOpening: (v: boolean) => void;
  setAutoOpenStage: (v: "backend" | "open") => void;

  /** Background tasks (transcription + autocode + R jobs; the shell polls
   *  them and shows a progress chip in the top bar). The queue runs
   *  sequentially: the shell's dispatcher starts queued jobs one after
   *  another. */
  tasks: TaskInfo[];
  tasksPaused: boolean;
  setTasksPaused: (paused: boolean) => void;
  enqueueTranscribe: (job: {
    id: string;
    sourceId: number;
    sourceName: string;
    /** False when the job was created queued (batch mode). */
    start?: boolean;
  }) => void;
  enqueueAutocode: (job: { id: string; sourceId: number; sourceName: string }) => void;
  /** Add an R job. The backend starts it immediately (POST /r/run), so the
   *  task enters the queue as running. No source: `sourceId` stays 0. */
  enqueueRJob: (job: { id: string; sourceName: string }) => void;
  updateTranscribeJob: (id: string, patch: Partial<TaskInfo>) => void;
  updateAutocodeJob: (id: string, patch: Partial<TaskInfo>) => void;
  updateRJob: (id: string, patch: Partial<TaskInfo>) => void;
  /** Remove a task from the queue (also cancels it on the backend). */
  removeTask: (id: string) => void;
  /** Drop queued/running order: move the task with id before targetId. */
  moveTask: (id: string, targetId: string | null) => void;
  clearFinishedTasks: () => void;
  /** Resume the queue: the shell's dispatcher starts queued jobs again. */
  startAllTasks: () => void;
  /** Cancel and remove every background task (queued, running, finished). */
  clearAllTasks: () => void;

  /** Background file-import progress. Kept as a task entry (kind "import",
   *  id "import") in `tasks` — the queue flyout renders it like any other
   *  background job. FileManager calls this to report done/total; null
   *  marks the task finished. */
  setImportState: (v: { done: number; total: number } | null) => void;

  /** Import-request tick: the left bar's Import button asks the FileManager
   *  to open its file picker (FileManager watches the tick). */
  importTick: number;
  requestImport: () => void;

  createProject: (path: string) => Promise<boolean>;
  openProject: (path: string) => Promise<boolean>;
  closeProject: () => Promise<void>;
  refreshProject: () => Promise<void>;

  // --- Bug report (screenshot + GitHub issue composer) ----------------

  bugReport: BugReportState;
  /** Open the composer: gathers the last action (newest audit row + current
   *  view), the last error, the GitHub config and the screenshot, then shows
   *  the modal. The screenshot is captured BEFORE the modal opens so the
   *  composer never appears in its own picture. */
  openBugReport: () => Promise<void>;
  closeBugReport: () => void;
  updateBugReport: (patch: Partial<BugReportState>) => void;
  /** Lightweight in-session recorder for the last user action (view
   *  changes); the newest audit row is fetched when the report opens. */
  recordLastAction: (action: string) => void;
  /** Last uncaught error (window error / unhandledrejection listeners
   *  installed below feed this). */
  setLastError: (error: string | null) => void;
}

/** Human-readable label of the current view (last-action recorder). */
function viewLabelOf(view: WorkspaceView): string {
  switch (view.kind) {
    case "coding":
      return `View: coding (source ${view.sourceId})`;
    case "dashboard":
      return "View: dashboard";
    default:
      return `View: ${view.kind}`;
  }
}

// In-session last-error recorder: uncaught errors and rejected promises feed
// the bug report so the composer can show what actually went wrong.
if (typeof window !== "undefined") {
  window.addEventListener("error", (e) => {
    useProjectStore.getState().setLastError(errorTextOf(e.error) || e.message || "Runtime error");
  });
  window.addEventListener("unhandledrejection", (e) => {
    useProjectStore.getState().setLastError(errorTextOf(e.reason));
  });
}

export const useProjectStore = create<ProjectLifecycleState>((set, get) => ({
  projectOpen: false,
  projectName: "",
  projectPath: "",
  fileQuery: "",
  setFileQuery: (q) => set({ fileQuery: q }),
  summary: null,
  sources: [],
  codeTree: [],
  cases: [],
  journals: [],
  busy: false,
  error: null,
  duplicateCoder: "",
  acknowledgeDuplicateCoder: () => set({ duplicateCoder: "" }),
  autoOpening: false,
  autoOpenStage: "backend",
  setAutoOpening: (v) => set({ autoOpening: v }),
  setAutoOpenStage: (v) => set({ autoOpenStage: v }),

  tasks: [],
  tasksPaused: false,
  setTasksPaused: (paused) => set({ tasksPaused: paused }),
  enqueueTranscribe: (job) =>
    set((s) => ({
      tasks: [
        ...s.tasks,
        {
          kind: "transcribe",
          id: job.id,
          sourceId: job.sourceId,
          sourceName: job.sourceName,
          state: job.start === false ? "queued" : "running",
          progress: 0,
          message: job.start === false ? "queued" : "loading model",
        },
      ],
    })),
  enqueueAutocode: (job) =>
    set((s) => ({
      tasks: [
        ...s.tasks,
        {
          kind: "autocode",
          id: job.id,
          sourceId: job.sourceId,
          sourceName: job.sourceName,
          state: "queued",
          progress: 0,
          message: "queued",
        },
      ],
    })),
  updateTranscribeJob: (id, patch) =>
    set((s) => ({
      tasks: s.tasks.map((j) => (j.kind === "transcribe" && j.id === id ? { ...j, ...patch } : j)),
    })),
  updateAutocodeJob: (id, patch) =>
    set((s) => ({
      tasks: s.tasks.map((j) => (j.kind === "autocode" && j.id === id ? { ...j, ...patch } : j)),
    })),
  enqueueRJob: (job) =>
    set((s) => ({
      tasks: [
        ...s.tasks,
        {
          kind: "r",
          id: job.id,
          sourceId: 0,
          sourceName: job.sourceName,
          state: "running",
          progress: 0,
          message: "starting",
        },
      ],
    })),
  updateRJob: (id, patch) =>
    set((s) => ({
      tasks: s.tasks.map((j) => (j.kind === "r" && j.id === id ? { ...j, ...patch } : j)),
    })),
  removeTask: (id) => {
    const task = useProjectStore.getState().tasks.find((j) => j.id === id);
    if (!task) return;
    if (task.kind === "import") {
      // Local-only task: nothing to cancel on the backend.
      set((s) => ({ tasks: s.tasks.filter((j) => j.id !== id) }));
      return;
    }
    if (task.kind === "transcribe") void api.transcribeJobDelete(id);
    else if (task.kind === "r") void api.rJobDelete(id);
    else void api.autocodeJobDelete(id);
    set((s) => ({ tasks: s.tasks.filter((j) => j.id !== id) }));
  },
  moveTask: (id, targetId) =>
    set((s) => {
      const from = s.tasks.findIndex((j) => j.id === id);
      if (from < 0) return {};
      const tasks = s.tasks.filter((j) => j.id !== id);
      if (targetId === null) return { tasks: [...tasks, s.tasks[from]] };
      const to = tasks.findIndex((j) => j.id === targetId);
      if (to < 0) return {};
      tasks.splice(to, 0, s.tasks[from]);
      return { tasks };
    }),
  clearFinishedTasks: () =>
    set((s) => ({
      tasks: s.tasks.filter((j) => j.state === "queued" || j.state === "running"),
    })),
  startAllTasks: () => set({ tasksPaused: false }),
  clearAllTasks: () => {
    for (const job of useProjectStore.getState().tasks) {
      if (job.kind === "import") continue; // local-only task
      if (job.kind === "transcribe") void api.transcribeJobDelete(job.id);
      else if (job.kind === "r") void api.rJobDelete(job.id);
      else void api.autocodeJobDelete(job.id);
    }
    set({ tasks: [] });
  },

  importTick: 0,
  requestImport: () => set((s) => ({ importTick: s.importTick + 1 })),

  setImportState: (v) => {
    const existing = useProjectStore.getState().tasks.find((j) => j.kind === "import");
    if (v === null) {
      // Finished: the task stays in the queue (done) so the user sees the
      // completed import until they clear finished tasks.
      if (!existing) return;
      set((s) => ({
        tasks: s.tasks.map((j) =>
          j.kind === "import" && j.state === "running"
            ? { ...j, state: "done", progress: 100, message: "done" }
            : j,
        ),
      }));
      return;
    }
    const progress = v.total > 0 ? (v.done / v.total) * 100 : 0;
    if (existing) {
      set((s) => ({
        tasks: s.tasks.map((j) =>
          j.kind === "import"
            ? { ...j, state: "running", progress, message: `${v.done}/${v.total}` }
            : j,
        ),
      }));
    } else {
      set((s) => ({
        tasks: [
          ...s.tasks,
          {
            kind: "import",
            id: "import",
            sourceId: 0,
            sourceName: "",
            state: "running",
            progress,
            message: `${v.done}/${v.total}`,
          },
        ],
      }));
    }
  },

  createProject: async (path) => {
    set({ busy: true, error: null });
    try {
      const res = await api.createProject(path);
      if (!res.ok) {
        set({ busy: false, error: res.error || "Project creation failed" });
        return false;
      }
      await get().refreshProject();
      set({
        projectOpen: true,
        projectName: res.project_name,
        projectPath: res.project_path,
        busy: false,
      });
      void useCoderStore.getState().loadCoders();
      return true;
    } catch (e) {
      set({ busy: false, error: errorMessage(e, "Project creation failed")});
      return false;
    }
  },

  openProject: async (path) => {
    set({ busy: true, error: null });
    try {
      const res = await api.openProject(path);
      if (!res.ok) {
        set({ busy: false, error: res.lock_user ? `Project is in use by ${res.lock_user}` : res.error });
        return false;
      }
      await get().refreshProject();
      set({
        projectOpen: true,
        projectName: res.project_name,
        projectPath: res.project_path,
        duplicateCoder: res.duplicate_coder ?? "",
        busy: false,
      });
      void useCoderStore.getState().loadCoders();
      if (res.sync_auto_enabled) {
        // Shared folder: enable the collaboration sync cycle and let the
        // shell show the transient notice. The override is NOT written —
        // the decision stays "auto" so the next open re-detects.
        usePrefsStore.setState({ syncAutoNotice: true });
        void usePrefsStore.getState().setSyncEnabled(true, { remember: false });
      }
      return true;
    } catch (e) {
      set({ busy: false, error: errorMessage(e, "Could not open project")});
      return false;
    }
  },

  closeProject: async () => {
    try {
      await api.closeProject();
    } catch {
      /* backend may be gone; still reset local state */
    }
    set({
      projectOpen: false,
      projectName: "",
      projectPath: "",
      summary: null,
      sources: [],
      codeTree: [],
      error: null,
    });
    useWorkspaceStore.setState({ view: { kind: "dashboard" } });
    useInspectorStore.setState({
      inspectorSelection: null,
      inspectorDetails: null,
      inspectorLoading: false,
      inspectorError: null,
    });
    useCoderStore.setState({ activeCodeId: null });
    usePrefsStore.setState({ syncAutoNotice: false, presence: [] });
  },

  refreshProject: async () => {
    try {
      const [summary, sources, codeTree, cases, journals] = await Promise.all([
        api.projectSummary(),
        api.sources(),
        api.codeTree(),
        api.cases(),
        api.journals(),
      ]);
      set({ summary: summary.summary, sources, codeTree, cases, journals });
    } catch (e) {
      set({ error: errorMessage(e, "Failed to load project data")});
    }
  },

  bugReport: {
    open: false,
    rawScreenshot: null,
    captureFailed: false,
    lastError: null,
    lastAction: null,
    title: "",
    body: "",
    labels: ["bug"],
    assignee: "",
    milestone: "",
    githubToken: "",
    githubRepo: DEFAULT_GITHUB_REPO,
  },
  closeBugReport: () => set((s) => ({ bugReport: { ...s.bugReport, open: false } })),
  updateBugReport: (patch) => set((s) => ({ bugReport: { ...s.bugReport, ...patch } })),
  recordLastAction: (action) => {
    if (!action) return;
    set((s) => ({ bugReport: { ...s.bugReport, lastAction: action } }));
  },
  setLastError: (error) => set((s) => ({ bugReport: { ...s.bugReport, lastError: error } })),
  openBugReport: async () => {
    const store = useProjectStore.getState();
    // 1. Last action: the current view, upgraded to the newest audit row
    //    when one exists (that is the last thing the app persisted).
    let lastAction = viewLabelOf(useWorkspaceStore.getState().view);
    try {
      const { rows } = await api.audit({ limit: 1 });
      const row = rows[0];
      if (row) {
        lastAction = row.action + (row.entity ? ` (${row.entity})` : "");
      }
    } catch {
      /* backend unreachable — the view label stays */
    }
    // 2. Last error: the in-session uncaught error, else the store's error
    //    slot (set by failed actions).
    const lastError = store.bugReport.lastError ?? store.error;
    // 3. GitHub config from the app settings.
    let githubToken = store.bugReport.githubToken;
    let githubRepo = store.bugReport.githubRepo;
    try {
      const s = await api.appSettings();
      githubToken = s.github_token ?? "";
      githubRepo =
        s.github_repo && s.github_repo.trim().includes("/")
          ? s.github_repo.trim()
          : DEFAULT_GITHUB_REPO;
    } catch {
      /* keep the stored defaults */
    }
    // 4. Screenshot of the app view (BEFORE the modal opens — the composer
    //    must never appear in its own picture). A failed capture (tainted
    //    canvas, html2canvas crash) falls back to a blank canvas with a note.
    let rawScreenshot: string | null = null;
    let captureFailed = false;
    try {
      const shot = await captureAppScreenshot();
      rawScreenshot = shot.dataUrl;
    } catch (e) {
      console.warn("bugreport capture failed:", e instanceof Error ? `${e.message}\n${e.stack}` : e);
      captureFailed = true;
      try {
        const shot = await blankScreenshot("Screenshot unavailable");
        rawScreenshot = shot.dataUrl;
      } catch {
        rawScreenshot = null;
      }
    }
    set({
      bugReport: {
        ...store.bugReport,
        open: true,
        rawScreenshot,
        captureFailed,
        lastAction,
        lastError,
        githubToken,
        githubRepo,
      },
    });
  },
}));
