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

export type WorkspaceView =
  | { kind: "dashboard" }
  | { kind: "files" }
  | { kind: "coding"; sourceId: number }
  | { kind: "cases" }
  | { kind: "notes" }
  | { kind: "analyze" }
  | { kind: "graphs" }
  | { kind: "history" }
  | { kind: "settings" }
  | { kind: "ai" };

/** Which panel the right bar shows. Inspector is the default; AI, Settings
 *  and History are toggleable panes driven from the top bar. */
export type RightPane = "inspector" | "ai" | "settings" | "history";

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
  | "graphs";

export type InspectorSelection = { kind: "code" | "file"; id: number } | null;

/** A background job as tracked by the UI (transcription or autocode). */
export type TaskKind = "transcribe" | "autocode";
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

  /** Background tasks (transcription + autocode jobs; the shell polls them
   *  and shows a progress chip in the top bar). The queue runs sequentially:
   *  the shell's dispatcher starts queued jobs one after another. */
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
  updateTranscribeJob: (id: string, patch: Partial<TaskInfo>) => void;
  updateAutocodeJob: (id: string, patch: Partial<TaskInfo>) => void;
  /** Remove a task from the queue (also cancels it on the backend). */
  removeTask: (id: string) => void;
  /** Drop queued/running order: move the task with id before targetId. */
  moveTask: (id: string, targetId: string | null) => void;
  clearFinishedTasks: () => void;
  /** Resume the queue: the shell's dispatcher starts queued jobs again. */
  startAllTasks: () => void;
  /** Cancel and remove every background task (queued, running, finished). */
  clearAllTasks: () => void;

  /** Background file import progress (shown in the ribbon indicator). */
  importState: { done: number; total: number } | null;
  setImportState: (v: { done: number; total: number } | null) => void;

  /** Import-request tick: the left bar's Import button asks the FileManager
   *  to open its file picker (FileManager watches the tick). */
  importTick: number;
  requestImport: () => void;

  /** Collaboration sync (Option B: sidecar change files over folder sync). */
  syncStatus: SyncStatus | null;
  setSyncStatus: (v: SyncStatus | null) => void;
  setSyncEnabled: (enabled: boolean) => Promise<boolean>;
  runSyncNow: () => Promise<boolean>;

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
}

/** Monotonic guard for the inspector detail fetches (only the LATEST
 *  selection may write the result — see selectCode/selectFile). */
let inspectorSelectSeq = 0;

export const useProjectStore = create<ProjectState>((set, get) => ({
  projectOpen: false,
  projectName: "",
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
  removeTask: (id) => {
    const task = useProjectStore.getState().tasks.find((j) => j.id === id);
    if (!task) return;
    if (task.kind === "transcribe") void api.transcribeJobDelete(id);
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
      if (job.kind === "transcribe") void api.transcribeJobDelete(job.id);
      else void api.autocodeJobDelete(job.id);
    }
    set({ tasks: [] });
  },

  importState: null,
  setImportState: (v) => set({ importState: v }),
  importTick: 0,
  requestImport: () => set((s) => ({ importTick: s.importTick + 1 })),

  syncStatus: null,
  setSyncStatus: (v) => set({ syncStatus: v }),
  setSyncEnabled: async (enabled) => {
    try {
      await api.setSyncEnabled(enabled);
      const status = await api.syncStatus();
      set({ syncStatus: status });
      return true;
    } catch {
      return false;
    }
  },
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
      set({ projectOpen: true, projectName: res.project_name, busy: false });
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
      set({ projectOpen: true, projectName: res.project_name, busy: false });
      void get().loadCoders();
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
}));
