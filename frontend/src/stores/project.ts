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

export type InspectorSelection = { kind: "code" | "file"; id: number } | null;

/** A background transcription job as tracked by the UI. */
export interface TranscribeJobInfo {
  id: string;
  sourceId: number;
  sourceName: string;
  state: "running" | "done" | "error";
  progress: number;
  message: string;
  transcriptSourceId?: number | null;
}

interface ProjectState {
  projectOpen: boolean;
  projectName: string;
  projectPath: string;
  summary: ProjectSummary | null;
  sources: Source[];
  codeTree: CodeTreeItem[];
  cases: Case[];
  journals: Journal[];
  view: WorkspaceView;
  busy: boolean;
  error: string | null;

  /** True while the packaged app is auto-opening the last project. */
  autoOpening: boolean;
  autoOpenStage: "backend" | "open";
  setAutoOpening: (v: boolean) => void;
  setAutoOpenStage: (v: "backend" | "open") => void;

  themeMode: ThemeMode;
  setThemeMode: (mode: ThemeMode) => void;

  /** Code the user picked in the left sidebar; used as the target code for
   *  selections/rects across coders (and highlighted in the sidebar). */
  activeCodeId: number | null;
  setActiveCode: (cid: number | null) => void;


  /** Current coder identity (owner for new codings). */
  coderName: string;
  coders: { name: string; coding_count: number }[];
  loadCoders: () => Promise<void>;
  createCoder: (name: string) => Promise<boolean>;
  switchCoder: (name: string) => Promise<boolean>;
  deleteCoder: (name: string, reassignTo?: string) => Promise<boolean>;

  /** Background transcription jobs (started from any AV coder; the shell
   *  polls them and shows a progress chip in the top bar). */
  transcribeJobs: TranscribeJobInfo[];
  enqueueTranscribe: (job: Omit<TranscribeJobInfo, "state" | "progress" | "message">) => void;
  updateTranscribeJob: (id: string, patch: Partial<TranscribeJobInfo>) => void;
  clearFinishedTranscribeJobs: () => void;

  /** Background file import progress (shown in the ribbon indicator). */
  importState: { done: number; total: number } | null;
  setImportState: (v: { done: number; total: number } | null) => void;

  /** Collaboration sync (Option B: sidecar change files over folder sync). */
  syncStatus: SyncStatus | null;
  setSyncStatus: (v: SyncStatus | null) => void;
  runSyncNow: () => Promise<boolean>;

  inspectorSelection: InspectorSelection;
  inspectorDetails: CodeDetails | SourceDetails | null;
  inspectorLoading: boolean;
  inspectorError: string | null;

  createProject: (path: string) => Promise<boolean>;
  openProject: (path: string) => Promise<boolean>;
  closeProject: () => Promise<void>;
  refreshProject: () => Promise<void>;
  setView: (view: WorkspaceView) => void;
  clearError: () => void;
  selectCode: (id: number | null) => Promise<void>;
  selectFile: (id: number | null) => Promise<void>;
  clearInspector: () => void;
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  projectOpen: false,
  projectName: "",
  projectPath: "",
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

  activeCodeId: null,
  setActiveCode: (cid) => set({ activeCodeId: cid }),


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

  transcribeJobs: [],
  enqueueTranscribe: (job) =>
    set((s) => ({
      transcribeJobs: [
        ...s.transcribeJobs,
        { ...job, state: "running", progress: 0, message: "queued" },
      ],
    })),
  updateTranscribeJob: (id, patch) =>
    set((s) => ({
      transcribeJobs: s.transcribeJobs.map((j) => (j.id === id ? { ...j, ...patch } : j)),
    })),
  clearFinishedTranscribeJobs: () =>
    set((s) => ({ transcribeJobs: s.transcribeJobs.filter((j) => j.state === "running") })),

  importState: null,
  setImportState: (v) => set({ importState: v }),

  syncStatus: null,
  setSyncStatus: (v) => set({ syncStatus: v }),
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

  createProject: async (path) => {
    set({ busy: true, error: null });
    try {
      const res = await api.createProject(path);
      if (!res.ok) {
        set({ busy: false, error: res.error || "Project creation failed" });
        return false;
      }
      await get().refreshProject();
      set({ projectOpen: true, projectPath: res.project_path, projectName: res.project_name, busy: false });
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
      set({ projectOpen: true, projectPath: res.project_path, projectName: res.project_name, busy: false });
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

  setView: (view) => set({ view }),
  clearError: () => set({ error: null }),

  clearInspector: () =>
    set({
      inspectorSelection: null,
      inspectorDetails: null,
      inspectorLoading: false,
      inspectorError: null,
    }),

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
    try {
      const details = await api.codeDetails(id);
      set({ inspectorDetails: details, inspectorLoading: false });
    } catch (e) {
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
    try {
      const details = await api.sourceDetails(id);
      set({ inspectorDetails: details, inspectorLoading: false });
    } catch (e) {
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
