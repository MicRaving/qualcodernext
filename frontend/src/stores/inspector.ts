/**
 * Inspector details + notes/annotation/goto coordination (Zustand).
 *
 * Owns what the right-bar Inspector shows (code/file details), the Notes
 * view's annotation list, the memo/annotation edit-mode flags and the
 * pending "show this segment in the coder" request. UI components call these
 * actions; the store never renders.
 */
import { errorMessage } from "@/lib/utils";
import { create } from "zustand";
import { api, ApiError, type CodeDetails, type SourceDetails } from "@/lib/api";

/** The item the right bar's Inspector shows. */
export type InspectorSelection = { kind: "code" | "file"; id: number } | null;

/** A list-row of the Notes view's annotations tab. */
export interface AnnotationRow {
  anid: number;
  fid: number;
  file_name: string;
  memo: string;
  pos0: number;
  pos1: number;
  date: string;
  owner: string;
}

interface InspectorState {
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
  annotationsAll: AnnotationRow[];
  /** Pending "show this segment in the coder" request (set by the code
   *  inspector's recent-segment click; consumed by the TextCoder once the
   *  segment's codings are loaded). */
  gotoSegment: { ctid: number | null; pos0: number | null; pos1: number | null } | null;
  setGotoSegment: (goto: { ctid: number | null; pos0: number | null; pos1: number | null } | null) => void;
  selectCode: (id: number | null) => Promise<void>;
  selectFile: (id: number | null) => Promise<void>;
  clearInspector: () => void;
}

/** Monotonic guard for the inspector detail fetches (only the LATEST
 *  selection may write the result — see selectCode/selectFile). */
let inspectorSelectSeq = 0;

export const useInspectorStore = create<InspectorState>((set) => ({
  inspectorSelection: null,
  inspectorDetails: null,
  inspectorLoading: false,
  inspectorError: null,
  inspectorMemoEdit: false,
  setInspectorMemoEdit: (v) => set({ inspectorMemoEdit: v }),
  inspectorNewAnnotation: false,
  setInspectorNewAnnotation: (v) => set({ inspectorNewAnnotation: v }),
  annotationsAll: [],
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
        inspectorError: errorMessage(e, "Failed to load code details"),
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
        inspectorError: errorMessage(e, "Failed to load file details"),
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
}));
