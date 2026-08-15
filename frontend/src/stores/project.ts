/**
 * Project + workspace state (Zustand).
 *
 * Owns the open project lifecycle and the current workspace view. UI
 * components call these actions; the store never renders.
 */
import { create } from "zustand";
import {
  api,
  ApiError,
  type Case,
  type CodeDetails,
  type CodeTreeItem,
  type GraphData,
  type ProjectSummary,
  type Source,
  type Journal,
  type SourceDetails,
  type SyncStatus,
} from "@/lib/api";
import type { SortDir, SortKey } from "@/features/manage/files";
import { blankScreenshot, captureAppScreenshot } from "@/features/bugreport/capture";
import { DEFAULT_GITHUB_REPO } from "@/features/bugreport/github";

export type ThemeMode = "light" | "dark";

/** Persist + apply the theme: toggle `.dark` on <html> and store in localStorage. */
function applyThemeMode(mode: ThemeMode) {
  if (typeof document !== "undefined") {
    document.documentElement.classList.toggle("dark", mode === "dark");
  }
  if (typeof window !== "undefined") {
    localStorage.setItem("qc-theme", mode);
  }
}

/** Seed the theme from localStorage; fall back to the OS preference. */
function initialThemeMode(): ThemeMode {
  if (typeof window !== "undefined") {
    const saved = localStorage.getItem("qc-theme");
    if (saved === "dark" || saved === "light") return saved;
    if (
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    ) {
      return "dark";
    }
  }
  return "light";
}

const INITIAL_THEME_MODE = initialThemeMode();
applyThemeMode(INITIAL_THEME_MODE);

/** Accessibility display modes (visual impairments / screen readers). */
export type A11yMode =
  | "off"
  | "screenreader"
  | "high-contrast"
  | "large-text"
  | "reduced-motion"
  | "colorblind";

/** Apply the a11y mode class on <html> and persist it. */
function applyA11yMode(mode: A11yMode) {
  if (typeof document !== "undefined") {
    const root = document.documentElement;
    for (const m of [
      "screenreader",
      "high-contrast",
      "large-text",
      "reduced-motion",
      "colorblind",
    ] as const) {
      root.classList.toggle(`a11y-${m}`, mode === m);
    }
  }
  if (typeof window !== "undefined") {
    localStorage.setItem("qc-a11y", mode);
  }
}

function initialA11yMode(): A11yMode {
  if (typeof window !== "undefined") {
    const saved = localStorage.getItem("qc-a11y");
    if (
      saved === "screenreader" ||
      saved === "high-contrast" ||
      saved === "large-text" ||
      saved === "reduced-motion" ||
      saved === "colorblind"
    ) {
      return saved;
    }
  }
  return "off";
}

const INITIAL_A11Y_MODE = initialA11yMode();
applyA11yMode(INITIAL_A11Y_MODE);

/** UI pref: whether creating a coding auto-selects it in the coder's
 *  segment-details bar (DEFAULT ON). */
function applyAutoShowSegmentDetails(v: boolean) {
  if (typeof window !== "undefined") {
    localStorage.setItem("qc-auto-show-segment-details", v ? "1" : "0");
  }
}

function initialAutoShowSegmentDetails(): boolean {
  if (typeof window !== "undefined") {
    const saved = localStorage.getItem("qc-auto-show-segment-details");
    if (saved === "1") return true;
    if (saved === "0") return false;
  }
  return true;
}

const INITIAL_AUTO_SHOW_SEGMENT_DETAILS = initialAutoShowSegmentDetails();
applyAutoShowSegmentDetails(INITIAL_AUTO_SHOW_SEGMENT_DETAILS);

export type WorkspaceView =
  | { kind: "dashboard" }
  | { kind: "files" }
  | { kind: "coding"; sourceId: number }
  | { kind: "cases" }
  | { kind: "notes" }
  | { kind: "qtt" }
  | { kind: "analyze" }
  | { kind: "graphs" }
  | { kind: "history" }
  | { kind: "settings" }
  | { kind: "ai" };

/** Which panel the right bar shows. Inspector is the default; AI, Settings,
 *  History and Creative are toggleable panes driven from the top bar. */
export type RightPane = "inspector" | "ai" | "settings" | "history" | "creative";

/** The report screens of the Analysis area (see analyze/registry.ts). */
export type ReportId =
  | "code-frequencies"
  | "code-segments"
  | "file-code"
  | "code-relations"
  | "interrater"
  | "text-corpus"
  | "codebook"
  | "references"
  | "sql"
  | "graphs"
  | "dictionary"
  | "stats"
  | "summary-table"
  | "sentiment"
  | "doc-compare"
  | "r-console";

export type InspectorSelection = { kind: "code" | "file"; id: number } | null;

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

interface ProjectState {
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
  view: WorkspaceView;
  /** The panel shown in the right bar (Inspector by default). */
  rightPane: RightPane;
  setRightPane: (pane: RightPane) => void;
  busy: boolean;
  error: string | null;

  /** True while the packaged app is auto-opening the last project. */
  autoOpening: boolean;
  autoOpenStage: "backend" | "open";
  setAutoOpening: (v: boolean) => void;
  setAutoOpenStage: (v: "backend" | "open") => void;

  themeMode: ThemeMode;
  setThemeMode: (mode: ThemeMode) => void;

  a11yMode: A11yMode;
  setA11yMode: (mode: A11yMode) => void;

  /** Auto-select a freshly created coding in the segment-details bar. */
  autoShowSegmentDetails: boolean;
  setAutoShowSegmentDetails: (v: boolean) => void;

  /** Code the user picked in the left sidebar; used as the target code for
   *  selections/rects across coders (and highlighted in the sidebar). */
  activeCodeId: number | null;
  setActiveCode: (cid: number | null) => void;

  /** Codes whose codings are HIDDEN in the open coder (click a code label
   *  to hide its codings until clicked again; multiple can be hidden). */
  hiddenCodes: number[];
  toggleHiddenCode: (cid: number) => void;


  /** Current coder identity (owner for new codings). */
  coderName: string;
  coders: { name: string; coding_count: number }[];
  loadCoders: () => Promise<void>;
  createCoder: (name: string) => Promise<boolean>;
  switchCoder: (name: string) => Promise<boolean>;
  deleteCoder: (name: string, reassignTo?: string) => Promise<boolean>;

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

  /** Collaboration sync (Option B: sidecar change files over folder sync). */
  syncStatus: SyncStatus | null;
  setSyncStatus: (v: SyncStatus | null) => void;
  /** Enable/disable the sync cycle. A manual toggle (remember: true) also
   *  writes the per-project override so the decision survives reopens;
   *  the shared-folder auto-enable passes remember: false. */
  setSyncEnabled: (enabled: boolean, opts?: { remember?: boolean }) => Promise<boolean>;
  runSyncNow: () => Promise<boolean>;
  /** Set by the store when the backend reported a shared folder on open;
   *  the shell shows a transient notice and clears it. */
  syncAutoNotice: boolean;
  setSyncAutoNotice: (v: boolean) => void;

  inspectorSelection: InspectorSelection;
  inspectorDetails: CodeDetails | SourceDetails | null;
  inspectorLoading: boolean;
  inspectorError: string | null;
  /** Set by "Edit memo" actions to make the Inspector's memo editor open
   *  directly in edit mode. */
  inspectorMemoEdit: boolean;
  setInspectorMemoEdit: (v: boolean) => void;
  /** Set by "Add annotation" actions to open the Inspector's new-annotation
   *  editor inline. */
  inspectorNewAnnotation: boolean;
  setInspectorNewAnnotation: (v: boolean) => void;

  /** Per-view workspace UI state (left bar / center coordination). */
  casesUi: { selectedId: number | null; query: string; tick: number };
  setCasesUi: (patch: Partial<{ selectedId: number | null; query: string; tick: number }>) => void;
  /** Files view workspace UI state: the table's sort column/direction and
   *  the active saved filter. Session-only: survives view remounts (and
   *  view switches) but is never persisted to disk. The search query is
   *  already session-stable via `fileQuery`. */
  filesUi: { sortKey: SortKey; sortDir: SortDir; activeFilter: number | "" };
  setFilesUi: (
    patch: Partial<{ sortKey: SortKey; sortDir: SortDir; activeFilter: number | "" }>,
  ) => void;
  /** QTT workspace state: the selected worksheet + reload tick. */
  qttUi: { selectedId: number | null; tick: number };
  setQttUi: (patch: Partial<{ selectedId: number | null; tick: number }>) => void;
  notesUi: {
    tab: "journal" | "annotations" | "memos";
    query: string;
    selectedId: number | null;
    selectedKind: "code" | "file" | null;
    /** Set by "add annotation" so the center editor opens in edit mode. */
    newAnnotation: boolean;
    tick: number;
  };
  setNotesUi: (
    patch: Partial<{
      tab: "journal" | "annotations" | "memos";
      query: string;
      selectedId: number | null;
      selectedKind: "code" | "file" | null;
      newAnnotation: boolean;
      tick: number;
    }>,
  ) => void;
  /** Analysis area UI state (reports left bar / center coordination). */
  analyzeUi: { selectedId: ReportId | null };
  setAnalyzeUi: (patch: Partial<{ selectedId: ReportId | null }>) => void;
  annotationsAll: {
    anid: number;
    fid: number;
    file_name: string;
    memo: string;
    pos0: number;
    pos1: number;
    date: string;
    owner: string;
  }[];

  /** Graph workspace state (shared between the left list, the canvas and
   *  the details inspector). */  graphsUi: {
    grid: number | null;
    list: { grid: number; name: string }[];
    tick: number;
    selectedNode: string | null;
    selectedLine: string | null;
    connectFrom: string | null;
    zoom: number;
    /** Which modal the graph chrome opens (owned by the center toolbar). */
    dialog: null | "name" | "models" | "delete";
    error: string | null;
  };
  setGraphsUi: (
    patch: Partial<{
      grid: number | null;
      list: { grid: number; name: string }[];
      tick: number;
      selectedNode: string | null;
      selectedLine: string | null;
      connectFrom: string | null;
      zoom: number;
      dialog: null | "name" | "models" | "delete";
      error: string | null;
    }>,
  ) => void;

  /** Graph canvas data + actions (shared by the center canvas and the
   *  details inspector in the right bar). */
  graphsData: GraphData | null;
  graphsLoading: boolean;
  loadGraphData: (grid: number) => Promise<void>;
  graphPatchNode: (kind: string, id: number, body: Record<string, unknown>) => Promise<void>;
  graphDeleteNode: (kind: string, id: number) => Promise<void>;
  graphPatchLine: (kind: string, id: number, body: Record<string, unknown>) => Promise<void>;
  graphDeleteLine: (kind: string, id: number) => Promise<void>;
  graphConnect: (
    from: { kind: string; id: number },
    to: { kind: string; id: number },
  ) => Promise<void>;

  createProject: (path: string) => Promise<boolean>;
  openProject: (path: string) => Promise<boolean>;
  closeProject: () => Promise<void>;
  refreshProject: () => Promise<void>;
  setView: (view: WorkspaceView) => void;
  selectCode: (id: number | null) => Promise<void>;
  selectFile: (id: number | null) => Promise<void>;
  clearInspector: () => void;

  /** Pending "show this segment in the coder" request (set by the code
   *  inspector's recent-segment click; consumed by the TextCoder once the
   *  segment's codings are loaded). */
  gotoSegment: { ctid: number | null; pos0: number | null; pos1: number | null } | null;
  setGotoSegment: (goto: { ctid: number | null; pos0: number | null; pos1: number | null } | null) => void;

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

/** Monotonic guard for the inspector detail fetches (only the LATEST
 *  selection may write the result — see selectCode/selectFile). */
let inspectorSelectSeq = 0;

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

/** Normalize an uncaught error (event reason, Error, string…) to text. */
function errorTextOf(e: unknown): string {
  if (e instanceof Error) return e.message || e.name;
  if (typeof e === "string") return e;
  if (e && typeof e === "object" && "message" in e && typeof e.message === "string") {
    return e.message;
  }
  try {
    return JSON.stringify(e);
  } catch {
    return String(e);
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

export const useProjectStore = create<ProjectState>((set, get) => ({
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
  view: { kind: "dashboard" },
  busy: false,
  error: null,
  autoOpening: false,
  autoOpenStage: "backend",
  setAutoOpening: (v) => set({ autoOpening: v }),
  setAutoOpenStage: (v) => set({ autoOpenStage: v }),

  themeMode: INITIAL_THEME_MODE,
  setThemeMode: (mode) => {
    applyThemeMode(mode);
    set({ themeMode: mode });
  },

  a11yMode: INITIAL_A11Y_MODE,
  setA11yMode: (mode) => {
    applyA11yMode(mode);
    set({ a11yMode: mode });
  },

  autoShowSegmentDetails: INITIAL_AUTO_SHOW_SEGMENT_DETAILS,
  setAutoShowSegmentDetails: (v) => {
    applyAutoShowSegmentDetails(v);
    set({ autoShowSegmentDetails: v });
  },

  activeCodeId: null,
  setActiveCode: (cid) => set({ activeCodeId: cid }),

  hiddenCodes: [],
  toggleHiddenCode: (cid) =>
    set((s) => ({
      hiddenCodes: s.hiddenCodes.includes(cid)
        ? s.hiddenCodes.filter((c) => c !== cid)
        : [...s.hiddenCodes, cid],
    })),


  coderName: "default",
  coders: [],
  loadCoders: async () => {
    try {
      const res = await api.coders();
      set({ coderName: res.current, coders: res.coders });
    } catch {
      /* backend may be unavailable; keep the current state */
    }
  },
  createCoder: async (name) => {
    try {
      const res = await api.createCoder(name);
      set({ coderName: res.current, coders: res.coders });
      return true;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "Could not create coder" });
      return false;
    }
  },
  switchCoder: async (name) => {
    try {
      const res = await api.switchCoder(name);
      set({ coderName: res.current, coders: res.coders });
      return true;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "Could not switch coder" });
      return false;
    }
  },
  deleteCoder: async (name, reassignTo) => {
    try {
      const res = await api.deleteCoder(name, reassignTo);
      set({ coderName: res.current, coders: res.coders });
      return true;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "Could not delete coder" });
      return false;
    }
  },

  tasks: [],
  tasksPaused: false,
  setTasksPaused: (paused) => set({ tasksPaused: paused }),
  rightPane: "inspector",
  setRightPane: (pane) => set({ rightPane: pane }),
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

  syncStatus: null,
  setSyncStatus: (v) => set({ syncStatus: v }),
  setSyncEnabled: async (enabled, opts) => {
    try {
      await api.setSyncEnabled(enabled);
      // A manual toggle (the coder flyout) becomes the remembered
      // per-project override; the shared-folder auto-enable must NOT
      // write it, so the next open re-detects.
      if (opts?.remember !== false) {
        const path = useProjectStore.getState().projectPath;
        if (path) {
          void api.syncSetOverride(path, enabled ? "on" : "off").catch(() => {});
        }
      }
      const status = await api.syncStatus();
      set({ syncStatus: status });
      return true;
    } catch {
      return false;
    }
  },
  syncAutoNotice: false,
  setSyncAutoNotice: (v) => set({ syncAutoNotice: v }),
  runSyncNow: async () => {
    try {
      const res = await api.syncNow();
      if (!res.ok) return false;
      const status = await api.syncStatus();
      set({ syncStatus: status });
      return true;
    } catch {
      return false;
    }
  },

  inspectorSelection: null,
  inspectorDetails: null,
  inspectorLoading: false,
  inspectorError: null,
  inspectorMemoEdit: false,
  setInspectorMemoEdit: (v) => set({ inspectorMemoEdit: v }),
  inspectorNewAnnotation: false,
  setInspectorNewAnnotation: (v) => set({ inspectorNewAnnotation: v }),

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
      void get().loadCoders();
      return true;
    } catch (e) {
      set({ busy: false, error: e instanceof Error ? e.message : "Project creation failed" });
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
        busy: false,
      });
      void get().loadCoders();
      if (res.sync_auto_enabled) {
        // Shared folder: enable the collaboration sync cycle and let the
        // shell show the transient notice. The override is NOT written —
        // the decision stays "auto" so the next open re-detects.
        set({ syncAutoNotice: true });
        void get().setSyncEnabled(true, { remember: false });
      }
      return true;
    } catch (e) {
      set({ busy: false, error: e instanceof Error ? e.message : "Could not open project" });
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
      view: { kind: "dashboard" },
      error: null,
      inspectorSelection: null,
      inspectorDetails: null,
      inspectorLoading: false,
      inspectorError: null,
      activeCodeId: null,
      syncAutoNotice: false,
    });
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
      set({ error: e instanceof Error ? e.message : "Failed to load project data" });
    }
  },

  setView: (view) => {
    set({ view });
    // Opening a file in the coder shows its details in the right bar.
    if (view.kind === "coding" && "sourceId" in view) {
      set({ rightPane: "inspector" });
      void get().selectFile(view.sourceId);
    }
  },

  casesUi: { selectedId: null, query: "", tick: 0 },
  setCasesUi: (patch) => set((s) => ({ casesUi: { ...s.casesUi, ...patch } })),
  filesUi: { sortKey: "name", sortDir: "asc", activeFilter: "" },
  setFilesUi: (patch) => set((s) => ({ filesUi: { ...s.filesUi, ...patch } })),
  qttUi: { selectedId: null, tick: 0 },
  setQttUi: (patch) => set((s) => ({ qttUi: { ...s.qttUi, ...patch } })),
  notesUi: { tab: "journal", query: "", selectedId: null, selectedKind: null, newAnnotation: false, tick: 0 },
  setNotesUi: (patch) => set((s) => ({ notesUi: { ...s.notesUi, ...patch } })),
  analyzeUi: { selectedId: "code-frequencies" },
  setAnalyzeUi: (patch) => set((s) => ({ analyzeUi: { ...s.analyzeUi, ...patch } })),
  annotationsAll: [],
  graphsUi: {
    grid: null,
    list: [],
    tick: 0,
    selectedNode: null,
    selectedLine: null,
    connectFrom: null,
    zoom: 1,
    dialog: null,
    error: null,
  },
  setGraphsUi: (patch) => set((s) => ({ graphsUi: { ...s.graphsUi, ...patch } })),

  graphsData: null,
  graphsLoading: false,
  loadGraphData: async (grid) => {
    set({ graphsLoading: true, graphsUi: { ...get().graphsUi, error: null } });
    try {
      set({ graphsData: await api.graphData(grid) });
    } catch (e) {
      set({
        graphsUi: {
          ...get().graphsUi,
          error: e instanceof Error ? e.message : "Failed to load graph",
        },
      });
    } finally {
      set({ graphsLoading: false });
    }
  },
  graphPatchNode: async (kind, id, body) => {
    const grid = get().graphsUi.grid;
    if (grid == null) return;
    const url =
      kind === "category" || kind === "code"
        ? `/graphs/${grid}/cdct/entity/${id}`
        : kind === "case"
          ? `/graphs/${grid}/cases/entity/${id}`
          : kind === "file"
            ? `/graphs/${grid}/files/entity/${id}`
            : kind === "free"
              ? `/graphs/${grid}/free/entity/${id}`
              : `/graphs/${grid}/memos/entity/${id}`;
    try {
      await api.patchPath(url, body);
    } catch {
      /* keep local state; the next save retries */
    }
  },
  graphDeleteNode: async (kind, id) => {
    const grid = get().graphsUi.grid;
    if (grid == null) return;
    try {
      if (kind === "category" || kind === "code") await api.graphDeleteCdctItem(grid, id);
      else if (kind === "case") await api.graphDeleteCaseItem(grid, id);
      else if (kind === "file") await api.graphDeleteFileItem(grid, id);
      else if (kind === "free") await api.graphDeleteFreeItem(grid, id);
      set({ graphsUi: { ...get().graphsUi, selectedNode: null } });
      await get().loadGraphData(grid);
    } catch (e) {
      set({
        graphsUi: {
          ...get().graphsUi,
          error: e instanceof Error ? e.message : "Could not delete node",
        },
      });
    }
  },
  graphPatchLine: async (kind, id, body) => {
    const grid = get().graphsUi.grid;
    if (grid == null) return;
    const url =
      kind === "cdct"
        ? `/graphs/${grid}/lines/cdct/${id}`
        : `/graphs/${grid}/lines/entity/${id}`;
    try {
      await api.patchPath(url, body);
      await get().loadGraphData(grid);
    } catch (e) {
      set({
        graphsUi: {
          ...get().graphsUi,
          error: e instanceof Error ? e.message : "Could not update line",
        },
      });
    }
  },
  graphDeleteLine: async (kind, id) => {
    const grid = get().graphsUi.grid;
    if (grid == null) return;
    try {
      if (kind === "cdct") await api.graphDeleteCdctLine(grid, id);
      else await api.graphDeleteEntityLine(grid, id);
      set({ graphsUi: { ...get().graphsUi, selectedLine: null } });
      await get().loadGraphData(grid);
    } catch (e) {
      set({
        graphsUi: {
          ...get().graphsUi,
          error: e instanceof Error ? e.message : "Could not delete line",
        },
      });
    }
  },
  graphConnect: async (from, to) => {
    const grid = get().graphsUi.grid;
    if (grid == null) return;
    try {
      if (from.kind === "code" || from.kind === "category") {
        if (to.kind === "code" || to.kind === "category") {
          await api.graphAddCdctLine(grid, { from_node: from.id, to_node: to.id });
        } else {
          await api.graphAddEntityLine(grid, {
            from_kind: from.kind,
            from_id: from.id,
            to_kind: to.kind,
            to_id: to.id,
          });
        }
      } else {
        await api.graphAddEntityLine(grid, {
          from_kind: from.kind,
          from_id: from.id,
          to_kind: to.kind,
          to_id: to.id,
        });
      }
      set({ graphsUi: { ...get().graphsUi, connectFrom: null } });
      await get().loadGraphData(grid);
    } catch (e) {
      set({
        graphsUi: {
          ...get().graphsUi,
          error: e instanceof Error ? e.message : "Could not connect nodes",
        },
      });
    }
  },

  clearInspector: () =>
    set({
      inspectorSelection: null,
      inspectorDetails: null,
      inspectorLoading: false,
      inspectorError: null,
    }),

  gotoSegment: null,
  setGotoSegment: (goto) => set({ gotoSegment: goto }),

  selectCode: async (id) => {
    if (id == null) {
      set({
        inspectorSelection: null,
        inspectorDetails: null,
        inspectorLoading: false,
        inspectorError: null,
      });
      return;
    }
    set({ inspectorSelection: { kind: "code", id }, inspectorLoading: true, inspectorError: null });
    // Sequence-guard: only the LATEST selection may write the details —
    // otherwise a slow response for item A overwrites the details of the
    // item B the user switched to.
    const seq = ++inspectorSelectSeq;
    try {
      const details = await api.codeDetails(id);
      if (seq === inspectorSelectSeq) {
        set({ inspectorDetails: details, inspectorLoading: false });
      }
    } catch (e) {
      if (seq !== inspectorSelectSeq) return;
      if (e instanceof ApiError && e.status === 404) {
        set({
          inspectorSelection: null,
          inspectorDetails: null,
          inspectorLoading: false,
          inspectorError: null,
        });
        return;
      }
      set({
        inspectorLoading: false,
        inspectorError: e instanceof Error ? e.message : "Failed to load code details",
      });
    }
  },

  selectFile: async (id) => {
    if (id == null) {
      set({
        inspectorSelection: null,
        inspectorDetails: null,
        inspectorLoading: false,
        inspectorError: null,
      });
      return;
    }
    set({ inspectorSelection: { kind: "file", id }, inspectorLoading: true, inspectorError: null });
    const seq = ++inspectorSelectSeq;
    try {
      const details = await api.sourceDetails(id);
      if (seq === inspectorSelectSeq) {
        set({ inspectorDetails: details, inspectorLoading: false });
      }
    } catch (e) {
      if (seq !== inspectorSelectSeq) return;
      if (e instanceof ApiError && e.status === 404) {
        set({
          inspectorSelection: null,
          inspectorDetails: null,
          inspectorLoading: false,
          inspectorError: null,
        });
        return;
      }
      set({
        inspectorLoading: false,
        inspectorError: e instanceof Error ? e.message : "Failed to load file details",
      });
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
    let lastAction = viewLabelOf(store.view);
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
