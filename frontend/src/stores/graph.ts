/**
 * Graph workspace state + canvas data (Zustand).
 *
 * Owns the graph list/grid selection (shared between the left list, the
 * canvas and the details inspector) and the graph canvas data with
 * node/line CRUD. UI components call these actions; the store never renders.
 */
import { errorMessage } from "@/lib/utils";
import { create } from "zustand";
import { api, type GraphData } from "@/lib/api";

/** Graph workspace state shared between the left list, the canvas and the
 *  details inspector. */
export interface GraphsUi {
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
}

interface GraphState {
  graphsUi: GraphsUi;
  setGraphsUi: (patch: Partial<GraphsUi>) => void;

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
}

export const useGraphStore = create<GraphState>((set, get) => ({
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
          error: errorMessage(e, "Failed to load graph"),
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
        ? `/graphs/${grid}/items/cdct/${id}`
        : kind === "case"
          ? `/graphs/${grid}/items/case/${id}`
          : kind === "file"
            ? `/graphs/${grid}/items/file/${id}`
            : kind === "free"
              ? `/graphs/${grid}/items/free/${id}`
              : `/graphs/${grid}/items/memo/${id}`;
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
          error: errorMessage(e, "Could not delete node"),
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
          error: errorMessage(e, "Could not update line"),
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
          error: errorMessage(e, "Could not delete line"),
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
          error: errorMessage(e, "Could not connect nodes"),
        },
      });
    }
  },
}));
