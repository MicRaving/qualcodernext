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
import type { MetaDocument, MetaHit, MetaPoolModel } from "@/lib/api/types";
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
  | { kind: "ai" }
  | { kind: "meta" };

/** Which panel the right bar shows. Inspector is the default; AI, Settings,
 *  History, Creative and Help are toggleable panes driven from the top bar. */
export type RightPane = "inspector" | "ai" | "settings" | "history" | "creative" | "help";

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
  /** Meta-analysis workspace state, shared between the study left bar and the
   *  center view (tab = pipeline stage, selectedHit = focused study,
   *  selectedIds = papers ticked for a batch/autocode run, scheme = active
   *  coding scheme, email = Unpaywall contact, importOpen/schemeOpen open the
   *  respective dialogs from the left bar, tick = bumped after mutations so
   *  the left bar reloads). */
  metaUi: {
    tab: MetaTab;
    selectedHit: MetaHit | null;
    /** Hits currently loaded in the left bar (keyboard next/previous). */
    hits: MetaHit[];
    selectedIds: number[];
    scheme: string;
    email: string;
    importOpen: boolean;
    schemeOpen: boolean;
    /** Full text linked to the focused study, shown in the Extract right bar. */
    selectedDocument: MetaDocument | null;
    /** Conflicts tab: whether screening verdicts or extraction cells disagree. */
    agreementScope: MetaAgreementScope;
    /** Conflicts tab: study key filter ("" = every study). */
    agreementStudy: string;
    /** Global coder/owner scope: "" = all coders, else a coder name. */
    coderScope: string;
    /** True once the user picked a coder scope explicitly; while false the
     *  scope tracks the app's current coder (`useCoderStore.coderName`). */
    coderScopeCustom: boolean;
    /** Screening list filter (client-side over the loaded hits). */
    screeningFilter: MetaScreeningFilter;
    /** Screening stage the verdict editor records against. */
    screeningStage: MetaScreeningStage;
    /** Hide AI proposals while screening (blind review). */
    blind: boolean;
    /** Active section of the Analyze tab. */
    analysisSection: MetaAnalysisSection;
    /** Pooled-model switch driven by the Analyze menubar. */
    analysisModel: MetaAnalysisModel;
    /** Frequentist estimator (menubar); drives `POST /meta/analysis/pooled`. */
    poolModel: MetaPoolModel;
    /** Chosen subgroup/moderator field (Analyze menubar); "" = none picked. */
    subgroupBy: string;
    /** Moderator terms in the Analyze regression, primary term first. */
    moderatorTerms: string[];
    /** Moderator interaction pairs (`[a, b]`) in the Analyze regression. */
    moderatorInteractions: [string, string][];
    /** Bayesian µ prior SD: N(0, bayesMuSd²). */
    bayesMuSd: number;
    /** Bayesian τ prior choice, encoded as "family:scale". */
    bayesTauKey: string;
    tick: number;
  };
  setMetaUi: (
    patch: Partial<{
      tab: MetaTab;
      selectedHit: MetaHit | null;
      hits: MetaHit[];
      selectedIds: number[];
      scheme: string;
      email: string;
      importOpen: boolean;
      schemeOpen: boolean;
      selectedDocument: MetaDocument | null;
      agreementScope: MetaAgreementScope;
      agreementStudy: string;
      coderScope: string;
      coderScopeCustom: boolean;
      screeningFilter: MetaScreeningFilter;
      screeningStage: MetaScreeningStage;
      blind: boolean;
      analysisSection: MetaAnalysisSection;
      analysisModel: MetaAnalysisModel;
      poolModel: MetaPoolModel;
      subgroupBy: string;
      moderatorTerms: string[];
      moderatorInteractions: [string, string][];
      bayesMuSd: number;
      bayesTauKey: string;
      tick: number;
    }>,
  ) => void;
}

export type MetaTab = "screen" | "download" | "extract" | "analyze" | "conflicts";
export type MetaScreeningFilter = "all" | "todo" | "screened" | "included" | "excluded";
export type MetaScreeningStage = "abstract" | "fulltext";
/** Conflicts tab scope: screening verdict disagreements vs extraction cell disagreements. */
export type MetaAgreementScope = "screening" | "extraction";
/** Pooled-model switch: classic frequentist pooling vs a Bayesian fit. */
export type MetaAnalysisModel = "frequentist" | "bayes";
export type MetaAnalysisSection =
  | "pooled"
  | "subgroup"
  | "multiverse"
  | "prisma"
  | "audit"
  | "summary"
  | "report";

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
  metaUi: {
    tab: "screen",
    selectedHit: null,
    hits: [],
    selectedIds: [],
    scheme: "",
    email: "",
    importOpen: false,
    schemeOpen: false,
    selectedDocument: null,
    agreementScope: "screening",
    agreementStudy: "",
    coderScope: "default",
    coderScopeCustom: false,
    screeningFilter: "all",
    screeningStage: "abstract",
    blind: false,
    analysisSection: "pooled",
    analysisModel: "frequentist",
    poolModel: "dl",
    subgroupBy: "",
    moderatorTerms: [],
    moderatorInteractions: [],
    bayesMuSd: 1,
    bayesTauKey: "half-normal:0.5",
    tick: 0,
  },
  setMetaUi: (patch) =>
    set((s) => {
      const next = { ...s.metaUi, ...patch };
      // The menubar's "Subgroup by" drives the first/primary moderator term so
      // the quick picker and the Analyze builder stay in sync (moved to the
      // front, never duplicated).
      if ("subgroupBy" in patch) {
        const primary = patch.subgroupBy ?? "";
        const rest = next.moderatorTerms.filter((term) => term !== primary);
        next.moderatorTerms = primary ? [primary, ...rest] : rest;
      }
      return { metaUi: next };
    }),
}));
