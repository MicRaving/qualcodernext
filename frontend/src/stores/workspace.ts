/**
 * Workspace view + per-view UI state (Zustand).
 *
 * Owns the current view (dashboard/files/coding/…), the right-bar panel
 * selection and the per-view workspace UI state (cases/files/qtt/notes/
 * analyze coordination). UI components call these actions; the store never
 * renders.
 */
import { create } from "zustand";
import type { SortDir, SortKey } from "@/features/manage/files";
import { useInspectorStore } from "./inspector";

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

interface WorkspaceState {
  view: WorkspaceView;
  /** The panel shown in the right bar (Inspector by default). */
  rightPane: RightPane;
  setRightPane: (pane: RightPane) => void;
  setView: (view: WorkspaceView) => void;

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
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  view: { kind: "dashboard" },
  rightPane: "inspector",
  setRightPane: (pane) => set({ rightPane: pane }),

  setView: (view) => {
    set({ view });
    // Opening a file in the coder shows its details in the right bar.
    if (view.kind === "coding" && "sourceId" in view) {
      set({ rightPane: "inspector" });
      void useInspectorStore.getState().selectFile(view.sourceId);
    }
  },

  casesUi: { selectedId: null, query: "", tick: 0 },
  setCasesUi: (patch) => set((s) => ({ casesUi: { ...s.casesUi, ...patch } })),
  filesUi: { sortKey: "name", sortDir: "asc", activeFilter: "" },
  setFilesUi: (patch) => set((s) => ({ filesUi: { ...s.filesUi, ...patch } })),
  qttUi: { selectedId: null, tick: 0 },
  setQttUi: (patch) => set((s) => ({ qttUi: { ...s.qttUi, ...patch } })),
  notesUi: {
    tab: "journal",
    query: "",
    selectedId: null,
    selectedKind: null,
    newAnnotation: false,
    tick: 0,
  },
  setNotesUi: (patch) => set((s) => ({ notesUi: { ...s.notesUi, ...patch } })),
  analyzeUi: { selectedId: "code-frequencies" },
  setAnalyzeUi: (patch) => set((s) => ({ analyzeUi: { ...s.analyzeUi, ...patch } })),
}));
