/**
 * Coder identity + coding visibility (Zustand).
 *
 * Owns the current coder (owner for new codings), the coder list and the
 * coding-visibility state shared across coders (the active sidebar code and
 * the codes whose codings are hidden). UI components call these actions; the
 * store never renders.
 */
import { errorMessage } from "@/lib/utils";
import { create } from "zustand";
import { api } from "@/lib/api";
import { useProjectStore } from "./project";

interface CoderState {
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
}

export const useCoderStore = create<CoderState>((set) => ({
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
      useProjectStore.setState({ error: errorMessage(e, "Could not create coder")});
      return false;
    }
  },
  switchCoder: async (name) => {
    try {
      const res = await api.switchCoder(name);
      set({ coderName: res.current, coders: res.coders });
      return true;
    } catch (e) {
      useProjectStore.setState({ error: errorMessage(e, "Could not switch coder")});
      return false;
    }
  },
  deleteCoder: async (name, reassignTo) => {
    try {
      const res = await api.deleteCoder(name, reassignTo);
      set({ coderName: res.current, coders: res.coders });
      return true;
    } catch (e) {
      useProjectStore.setState({ error: errorMessage(e, "Could not delete coder")});
      return false;
    }
  },
}));
