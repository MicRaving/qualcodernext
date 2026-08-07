/**
 * GraphsView — the code-map editor (upstream view_graph / graph models).
 *
 * SVG canvas with pan/zoom; draggable nodes (categories, codes, cases,
 * files, free text, memos); relation lines with labels and arrow modes;
 * and the six analytical model generators.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import {
  ArrowLeft,
  BookMarked,
  CaseSensitive,
  FileText,
  FolderPlus,
  Link2,
  LoaderCircle,
  Map as MapIcon,
  Network,
  Pencil,
  Plus,
  Save,
  Sparkles,
  Trash2,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  api,
  GRAPH_MODELS,
  type GraphData,
  type GraphSummary,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";

const NODE_W = 150;
const NODE_H = 30;

interface NodeView {
  id: string; // "cdct:<gtextid>" | "case:<gcaseid>" | "file:<gfileid>" | "free:<gfreeid>" | "memo:<gmemoid>"
  kind: "category" | "code" | "case" | "file" | "free" | "memo";
  entityId: number; // catid/cid/caseid/fid/freetextid/memo_source_id
  label: string;
  color: string;
  x: number;
  y: number;
  bold: boolean;
  fontSize: number;
  patchUrl?: string;
}

interface LineView {
  id: string;
  kind: "cdct" | "entity";
  fromNode?: string; // resolved node id (undefined when target absent)
  toNode?: string;
  fromEntity?: { kind: string; id: number };
  toEntity?: { kind: string; id: number };
  color: string;
  linewidth: number;
  linetype: string;
  label: string;
  arrow_mode: string;
  patchUrl?: string;
  deleteUrl?: string;
}

const ENTITY_LINE_COLS: { kind: string; col: string }[] = [
  { kind: "free", col: "freetextid" },
  { kind: "code", col: "cid" },
  { kind: "category", col: "catid" },
  { kind: "case", col: "caseid" },
  { kind: "file", col: "fileid" },
  { kind: "imid", col: "imid" },
  { kind: "avid", col: "avid" },
];

const KIND_COLOR: Record<NodeView["kind"], string> = {
  category: "#8a8fa3",
  code: "#7d26cd",
  case: "#5882fa",
  file: "#6b6bda",
  free: "#1d1d23",
  memo: "#c8c8c8",
};

function buildNodes(data: GraphData): NodeView[] {
  const nodes: NodeView[] = [];
  for (const item of data.cdct_items) {
    const isCat = item.cid == null;
    const code = data.codes.find((c) => c.cid === item.cid);
    const cat = data.categories.find((c) => c.catid === item.catid);
    nodes.push({
      id: `cdct:${item.gtextid}`,
      kind: isCat ? "category" : "code",
      entityId: isCat ? (item.catid ?? 0) : (item.cid ?? 0),
      label: item.displaytext || (isCat ? cat?.name ?? "Category" : code?.name ?? "Code"),
      color: isCat ? KIND_COLOR.category : (code?.color ?? KIND_COLOR.code),
      x: item.x,
      y: item.y,
      bold: item.bold === 1,
      fontSize: item.font_size || 12,
      patchUrl: `/graphs/${data.graph.grid}/items/cdct/${item.gtextid}`,
    });
  }
  for (const item of data.case_items) {
    const caseInfo = data.cases.find((c) => c.caseid === item.caseid);
    nodes.push({
      id: `case:${item.gcaseid}`,
      kind: "case",
      entityId: item.caseid,
      label: item.displaytext || (caseInfo?.name ?? "Case"),
      color: item.color || KIND_COLOR.case,
      x: item.x,
      y: item.y,
      bold: item.bold === 1,
      fontSize: item.font_size || 12,
      patchUrl: `/graphs/${data.graph.grid}/items/case/${item.gcaseid}`,
    });
  }
  for (const item of data.file_items) {
    const file = data.sources.find((s) => s.id === item.fid);
    nodes.push({
      id: `file:${item.gfileid}`,
      kind: "file",
      entityId: item.fid,
      label: item.displaytext || (file?.name ?? "File"),
      color: item.color || KIND_COLOR.file,
      x: item.x,
      y: item.y,
      bold: item.bold === 1,
      fontSize: item.font_size || 12,
      patchUrl: `/graphs/${data.graph.grid}/items/file/${item.gfileid}`,
    });
  }
  for (const item of data.free_items) {
    nodes.push({
      id: `free:${item.gfreeid}`,
      kind: "free",
      entityId: item.freetextid,
      label: item.free_text,
      color: item.color || KIND_COLOR.free,
      x: item.x,
      y: item.y,
      bold: item.bold === 1,
      fontSize: item.font_size || 12,
      patchUrl: `/graphs/${data.graph.grid}/items/free/${item.gfreeid}`,
    });
  }
  for (const item of data.memo_items) {
    nodes.push({
      id: `memo:${item.gmemoid}`,
      kind: "memo",
      entityId: item.memo_source_id,
      label: "Memo",
      color: item.color || KIND_COLOR.memo,
      x: item.x,
      y: item.y,
      bold: false,
      fontSize: item.font_size || 11,
    });
  }
  return nodes;
}

function nodeByEntity(nodes: NodeView[], kind: string, id: number | null): NodeView | undefined {
  if (id == null) return undefined;
  return nodes.find((n) => n.kind === kind && n.entityId === id);
}

function buildLines(data: GraphData, nodes: NodeView[]): LineView[] {
  const lines: LineView[] = [];
  for (const line of data.cdct_lines) {
    const from =
      nodeByEntity(nodes, "code", line.fromcid) ??
      nodeByEntity(nodes, "category", line.fromcatid);
    const to =
      nodeByEntity(nodes, "code", line.tocid) ??
      nodeByEntity(nodes, "category", line.tocatid);
    lines.push({
      id: `cdct:${line.glineid}`,
      kind: "cdct",
      fromNode: from?.id,
      toNode: to?.id,
      color: line.color || "#888888",
      linewidth: line.linewidth || 1,
      linetype: line.linetype || "solid",
      label: line.label || "",
      arrow_mode: line.arrow_mode || "solid_with_arrow",
      patchUrl: `/graphs/${data.graph.grid}/lines/cdct/${line.glineid}`,
      deleteUrl: `/graphs/${data.graph.grid}/lines/cdct/${line.glineid}`,
    });
  }
  for (const line of data.free_lines) {
    const fromCol = ENTITY_LINE_COLS.find((c) => (line as unknown as Record<string, unknown>)[`from${c.col}`] != null);
    const toCol = ENTITY_LINE_COLS.find((c) => (line as unknown as Record<string, unknown>)[`to${c.col}`] != null);
    const from = fromCol
      ? nodeByEntity(nodes, fromCol.kind, (line as unknown as Record<string, number>)[`from${fromCol.col}`] ?? null)
      : undefined;
    const to = toCol
      ? nodeByEntity(nodes, toCol.kind, (line as unknown as Record<string, number>)[`to${toCol.col}`] ?? null)
      : undefined;
    lines.push({
      id: `entity:${line.gflineid}`,
      kind: "entity",
      fromNode: from?.id,
      toNode: to?.id,
      color: line.color || "#888888",
      linewidth: line.linewidth || 1,
      linetype: line.linetype || "solid",
      label: line.label || "",
      arrow_mode: line.arrow_mode || "solid_with_arrow",
      patchUrl: `/graphs/${data.graph.grid}/lines/entity/${line.gflineid}`,
      deleteUrl: `/graphs/${data.graph.grid}/lines/entity/${line.gflineid}`,
    });
  }
  return lines;
}

const ARROW_MODES = ["solid_with_arrow", "solid_without_arrow", "dotted_with_arrow", "dotted_without_arrow"];

export function GraphsView() {
  const { t } = useI18n();
  const setView = useProjectStore((s) => s.setView);
  const [graphs, setGraphs] = useState<GraphSummary[]>([]);
  const [grid, setGrid] = useState<number | null>(null);
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // viewport transform
  const [pan, setPan] = useState({ x: 40, y: 40 });
  const [zoom, setZoom] = useState(1);
  const panRef = useRef(pan);
  panRef.current = pan;
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;

  // interactions
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [selectedLine, setSelectedLine] = useState<string | null>(null);
  const [connectFrom, setConnectFrom] = useState<string | null>(null);
  const [drag, setDrag] = useState<{ node: string; startX: number; startY: number; origX: number; origY: number } | null>(null);
  const [panDrag, setPanDrag] = useState<{ x: number; y: number; startX: number; startY: number } | null>(null);
  const [addMenu, setAddMenu] = useState<{ x: number; y: number } | null>(null);
  const [modelOpen, setModelOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const nodes = useMemo(() => (data ? buildNodes(data) : []), [data]);
  const lines = useMemo(() => (data ? buildLines(data, nodes) : []), [data, nodes]);
  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const lineById = useMemo(() => new Map(lines.map((l) => [l.id, l])), [lines]);

  const loadGraphs = useCallback(async () => {
    try {
      const res = await api.graphs();
      setGraphs(res.graphs);
      if (grid == null && res.graphs.length > 0) {
        setGrid(res.graphs[0].grid);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load graphs");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadGraph = useCallback(async (g: number) => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.graphData(g));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load graph");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadGraphs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (grid != null) void loadGraph(grid);
  }, [grid, loadGraph]);

  async function createGraph() {
    const name = window.prompt("Graph name:");
    if (!name?.trim()) return;
    try {
      const graph = await api.createGraph(name.trim());
      await loadGraphs();
      setGrid(graph.grid);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create graph");
    }
  }

  async function deleteGraph() {
    if (grid == null) return;
    if (!window.confirm(`Delete graph "${graphs.find((g) => g.grid === grid)?.name}"?`)) return;
    try {
      await api.deleteGraph(grid);
      setGrid(null);
      setData(null);
      await loadGraphs();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete graph");
    }
  }

  /* ------------------------------------------------------------- nodes */

  async function patchNode(node: NodeView, body: Record<string, unknown>) {
    if (!node.patchUrl || saving) return;
    setSaving(true);
    try {
      await api.patchPath(node.patchUrl, body);
    } catch {
      /* keep local position; next save retries */
    } finally {
      setSaving(false);
    }
  }

  function onNodeMouseDown(e: ReactMouseEvent, node: NodeView) {
    e.stopPropagation();
    setSelectedNode(node.id);
    setSelectedLine(null);
    if (connectFrom) {
      // connecting two nodes
      if (connectFrom !== node.id) {
        void connectNodes(connectFrom, node.id);
      }
      setConnectFrom(null);
      return;
    }
    setDrag({ node: node.id, startX: e.clientX, startY: e.clientY, origX: node.x, origY: node.y });
  }

  async function connectNodes(a: string, b: string) {
    if (!data) return;
    const na = nodeById.get(a);
    const nb = nodeById.get(b);
    if (!na || !nb) return;
    try {
      if (na.kind === "code" || na.kind === "category") {
        if (nb.kind === "code" || nb.kind === "category") {
          await api.graphAddCdctLine(data.graph.grid, {
            from_node: Number(a.split(":")[1]),
            to_node: Number(b.split(":")[1]),
          });
        } else {
          await api.graphAddEntityLine(data.graph.grid, {
            from_kind: na.kind,
            from_id: na.entityId,
            to_kind: nb.kind,
            to_id: nb.entityId,
          });
        }
      } else {
        await api.graphAddEntityLine(data.graph.grid, {
          from_kind: na.kind,
          from_id: na.entityId,
          to_kind: nb.kind,
          to_id: nb.entityId,
        });
      }
      await loadGraph(data.graph.grid);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not connect nodes");
    }
  }

  async function deleteNode() {
    if (!data || !selectedNode) return;
    const node = nodeById.get(selectedNode);
    if (!node || node.kind === "memo") return;
    if (!window.confirm(`Delete node "${node.label}"?`)) return;
    try {
      const id = Number(selectedNode.split(":")[1]);
      if (node.kind === "category" || node.kind === "code") {
        await api.graphDeleteCdctItem(data.graph.grid, id);
      } else if (node.kind === "case") {
        await api.graphDeleteCaseItem(data.graph.grid, id);
      } else if (node.kind === "file") {
        await api.graphDeleteFileItem(data.graph.grid, id);
      } else if (node.kind === "free") {
        await api.graphDeleteFreeItem(data.graph.grid, id);
      }
      setSelectedNode(null);
      await loadGraph(data.graph.grid);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete node");
    }
  }

  /* ------------------------------------------------------------- lines */

  async function deleteLine() {
    if (!data || !selectedLine) return;
    const line = lineById.get(selectedLine);
    if (!line || !line.deleteUrl) return;
    if (!window.confirm("Delete this line?")) return;
    try {
      const id = Number(selectedLine.split(":")[1]);
      if (line.kind === "cdct") {
        await api.graphDeleteCdctLine(data.graph.grid, id);
      } else {
        await api.graphDeleteEntityLine(data.graph.grid, id);
      }
      setSelectedLine(null);
      await loadGraph(data.graph.grid);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete line");
    }
  }

  async function patchLine(body: Record<string, unknown>) {
    if (!data || !selectedLine) return;
    const line = lineById.get(selectedLine);
    if (!line || !line.patchUrl) return;
    try {
      await api.patchPath(line.patchUrl, body);
      await loadGraph(data.graph.grid);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update line");
    }
  }

  /* ------------------------------------------------------ add node menu */

  async function addCdct(kind: "category" | "code") {
    if (!data || !addMenu) return;
    const options =
      kind === "category"
        ? data.categories.map((c) => ({ id: c.catid, name: c.name }))
        : data.codes.map((c) => ({ id: c.cid, name: c.name }));
    if (options.length === 0) {
      setError(kind === "category" ? "No categories yet" : "No codes yet");
      return;
    }
    const list = options.map((o) => `${o.name}`).join("\n");
    const pick = window.prompt(`${kind === "category" ? "Category" : "Code"} name:`, options[0].name);
    const option = options.find((o) => o.name === pick);
    if (!option) return;
    try {
      await api.graphAddCdctItem(data.graph.grid, {
        kind,
        ref_id: option.id,
        x: addMenu.x,
        y: addMenu.y,
      });
      setAddMenu(null);
      await loadGraph(data.graph.grid);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add node");
    }
    void list;
  }

  async function addCase() {
    if (!data || !addMenu) return;
    const pick = window.prompt("Case name:", data.cases[0]?.name ?? "");
    const option = data.cases.find((c) => c.name === pick);
    if (!option) return;
    try {
      await api.graphAddCaseItem(data.graph.grid, {
        caseid: option.caseid,
        x: addMenu.x,
        y: addMenu.y,
      });
      setAddMenu(null);
      await loadGraph(data.graph.grid);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add node");
    }
  }

  async function addFile() {
    if (!data || !addMenu) return;
    const pick = window.prompt("File name:", data.sources[0]?.name ?? "");
    const option = data.sources.find((s) => s.name === pick);
    if (!option) return;
    try {
      await api.graphAddFileItem(data.graph.grid, {
        fid: option.id,
        x: addMenu.x,
        y: addMenu.y,
      });
      setAddMenu(null);
      await loadGraph(data.graph.grid);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add node");
    }
  }

  async function addFree() {
    if (!data || !addMenu) return;
    const text = window.prompt("Free text:");
    if (!text?.trim()) return;
    try {
      await api.graphAddFreeItem(data.graph.grid, {
        x: addMenu.x,
        y: addMenu.y,
        free_text: text.trim(),
      });
      setAddMenu(null);
      await loadGraph(data.graph.grid);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add node");
    }
  }

  async function addMemo() {
    if (!data || !addMenu) return;
    const codesWithMemo = data.codes.filter((c) => c.memo && c.memo.trim());
    const pick = window.prompt(
      "Code with a memo:",
      codesWithMemo[0]?.name ?? "",
    );
    const code = codesWithMemo.find((c) => c.name === pick);
    if (!code) return;
    try {
      await api.graphAddMemoItem(data.graph.grid, {
        memo_source_type: "code",
        memo_source_id: code.cid,
        x: addMenu.x,
        y: addMenu.y,
      });
      setAddMenu(null);
      await loadGraph(data.graph.grid);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add memo node");
    }
  }

  /* -------------------------------------------------- viewport & events */

  useEffect(() => {
    const onMove = (e: globalThis.MouseEvent) => {
      if (drag) {
        const node = nodeById.get(drag.node);
        if (!node) return;
        node.x = drag.origX + (e.clientX - drag.startX) / zoomRef.current;
        node.y = drag.origY + (e.clientY - drag.startY) / zoomRef.current;
        setData((d) => (d ? { ...d } : d));
        return;
      }
      if (panDrag) {
        setPan({
          x: panDrag.x + (e.clientX - panDrag.startX),
          y: panDrag.y + (e.clientY - panDrag.startY),
        });
      }
    };
    const onUp = () => {
      if (drag) {
        const node = nodeById.get(drag.node);
        if (node && node.patchUrl) {
          void patchNode(node, { x: Math.round(node.x), y: Math.round(node.y) });
        }
        setDrag(null);
      }
      setPanDrag(null);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag, panDrag]);

  const svgToWorld = (clientX: number, clientY: number) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return {
      x: (clientX - rect.left - pan.x) / zoom,
      y: (clientY - rect.top - pan.y) / zoom,
    };
  };

  function onSvgMouseDown(e: ReactMouseEvent) {
    if (e.button !== 0) return;
    setSelectedNode(null);
    setSelectedLine(null);
    setConnectFrom(null);
    setPanDrag({ x: pan.x, y: pan.y, startX: e.clientX, startY: e.clientY });
  }

  function onWheel(e: React.WheelEvent) {
    const factor = e.deltaY > 0 ? 0.9 : 1.1;
    const next = Math.min(2.5, Math.max(0.25, zoom * factor));
    setZoom(next);
    setPan({
      x: e.clientX - (e.clientX - pan.x) * (next / zoom),
      y: e.clientY - (e.clientY - pan.y) * (next / zoom),
    });
  }

  const linePath = (line: LineView) => {
    const from = line.fromNode ? nodeById.get(line.fromNode) : undefined;
    const to = line.toNode ? nodeById.get(line.toNode) : undefined;
    if (!from || !to) return null;
    const x1 = from.x + NODE_W / 2;
    const y1 = from.y + NODE_H / 2;
    const x2 = to.x + NODE_W / 2;
    const y2 = to.y + NODE_H / 2;
    return { x1, y1, x2, y2 };
  };

  const arrowMarker = (id: string, color: string) => (
    <marker id={id} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
      <path d="M0,0 L8,4 L0,8 z" fill={color} />
    </marker>
  );

  /* --------------------------------------------------------------- ui */

  const selected = selectedNode ? nodeById.get(selectedNode) : undefined;
  const selectedL = selectedLine ? lineById.get(selectedLine) : undefined;

  return (
    <div className="flex h-full flex-col bg-bg">
      <header className="flex h-10 shrink-0 items-center gap-2 border-b border-border bg-surface px-3">
        <h1 className="text-sm font-semibold text-text-primary">{t("graphs.title")}</h1>
        <select
          value={grid ?? ""}
          onChange={(e) => setGrid(e.target.value === "" ? null : Number(e.target.value))}
          className="h-7 rounded-sm border border-border bg-bg px-1.5 text-xs outline-none focus:border-accent"
          aria-label="Graph"
        >
          <option value="">—</option>
          {graphs.map((g) => (
            <option key={g.grid} value={g.grid}>
              {g.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void createGraph()}
          className="flex items-center gap-1 rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher"
        >
          <Plus size={12} aria-hidden />
          {t("graphs.newGraph")}
        </button>
        <button
          type="button"
          onClick={() => setModelOpen(true)}
          className="flex items-center gap-1 rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher"
        >
          <Sparkles size={12} aria-hidden />
          {t("graphs.models")}
        </button>
        <div className="flex-1" />
        {grid != null && (
          <button
            type="button"
            onClick={() => void deleteGraph()}
            className="flex items-center gap-1 rounded-sm border border-danger/50 px-2 py-1 text-xs text-danger hover:bg-danger/10"
          >
            <Trash2 size={12} aria-hidden />
            {t("common.delete")}
          </button>
        )}
        <button
          type="button"
          onClick={() => setView({ kind: "dashboard" })}
          className="rounded-sm p-1.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
          aria-label={t("common.close")}
        >
          <ArrowLeft size={16} aria-hidden />
        </button>
      </header>

      {error && (
        <div className="flex shrink-0 items-center gap-2 border-b border-danger bg-danger/10 px-3 py-1.5 text-sm text-danger">
          <span className="min-w-0 flex-1 truncate">{error}</span>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-hidden">
        {loading && !data ? (
          <div className="flex h-full items-center justify-center gap-2 text-text-secondary">
            <LoaderCircle size={16} className="animate-spin" aria-hidden />
            Loading…
          </div>
        ) : !data ? (
          <div className="flex h-full flex-col items-center justify-center gap-3">
            <MapIcon size={32} className="text-text-secondary" aria-hidden />
            <p className="text-sm text-text-secondary">
              {graphs.length === 0 ? "No graphs yet — create one or generate a model." : "Select a graph."}
            </p>
            <button
              type="button"
              onClick={() => void createGraph()}
              className="rounded-sm bg-accent px-3 py-1.5 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover"
            >
              {t("graphs.newGraph")}
            </button>
          </div>
        ) : (
          <div className="flex h-full">
            <svg
              ref={svgRef}
              className="min-w-0 flex-1 cursor-grab active:cursor-grabbing"
              onMouseDown={onSvgMouseDown}
              onWheel={onWheel}
            >
              <defs>
                {arrowMarker("arrow-cdct", "#888888")}
                {arrowMarker("arrow-entity", "#888888")}
              </defs>
              {/* grid dots */}
              <pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse">
                <circle cx="1" cy="1" r="1" fill="#d9d9dc" />
              </pattern>
              <rect
                x={pan.x}
                y={pan.y}
                width={data.graph.scene_width * zoom}
                height={data.graph.scene_height * zoom}
                fill="url(#dots)"
                stroke="#d9d9dc"
                strokeWidth={1 / zoom}
                onContextMenu={(e) => e.preventDefault()}
                onDoubleClick={(e) => {
                  const world = svgToWorld(e.clientX, e.clientY);
                  setAddMenu({ x: Math.round(world.x), y: Math.round(world.y) });
                }}
              />
              <g transform={`translate(${pan.x},${pan.y}) scale(${zoom})`}>
                {lines.map((line) => {
                  const path = linePath(line);
                  if (!path) return null;
                  const dashed = line.linetype === "dotted" || line.arrow_mode.startsWith("dotted");
                  const withArrow = line.arrow_mode.endsWith("_arrow");
                  const color = line.color || "#888888";
                  return (
                    <g
                      key={line.id}
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedLine(line.id);
                        setSelectedNode(null);
                      }}
                      className="cursor-pointer"
                    >
                      <line
                        x1={path.x1}
                        y1={path.y1}
                        x2={path.x2}
                        y2={path.y2}
                        stroke={color}
                        strokeWidth={(line.linewidth || 1) * 1.5 + 6}
                        strokeOpacity={0}
                        strokeLinecap="round"
                        onDoubleClick={(e) => e.stopPropagation()}
                      />
                      <line
                        x1={path.x1}
                        y1={path.y1}
                        x2={path.x2}
                        y2={path.y2}
                        stroke={color}
                        strokeWidth={(line.linewidth || 1) * 1.5}
                        strokeDasharray={dashed ? "6 4" : undefined}
                        markerEnd={withArrow ? (line.kind === "cdct" ? "url(#arrow-cdct)" : "url(#arrow-entity)") : undefined}
                      />
                      {line.label && (
                        <text
                          x={(path.x1 + path.x2) / 2}
                          y={(path.y1 + path.y2) / 2 - 4}
                          fontSize={11}
                          fill="#6b6b76"
                          textAnchor="middle"
                        >
                          {line.label}
                        </text>
                      )}
                    </g>
                  );
                })}
                {nodes.map((node) => (
                  <g
                    key={node.id}
                    transform={`translate(${node.x},${node.y})`}
                    onMouseDown={(e) => onNodeMouseDown(e, node)}
                    className="cursor-move"
                  >
                    <rect
                      width={NODE_W}
                      height={NODE_H}
                      rx={5}
                      fill={node.color}
                      fillOpacity={connectFrom && connectFrom !== node.id ? 0.7 : 0.92}
                      stroke={selectedNode === node.id ? "#111" : node.color}
                      strokeWidth={selectedNode === node.id ? 2 : 1}
                    />
                    <text
                      x={8}
                      y={NODE_H / 2 + 4}
                      fontSize={node.fontSize}
                      fontWeight={node.bold ? 700 : 400}
                      fill="#111"
                      className="pointer-events-none select-none"
                    >
                      {node.label.length > 26 ? `${node.label.slice(0, 25)}…` : node.label}
                    </text>
                    {connectFrom === node.id && (
                      <circle cx={NODE_W} cy={NODE_H / 2} r={8} fill="#ff6f00" />
                    )}
                  </g>
                ))}
                {connectFrom && (
                  <text x={10} y={-8} fontSize={12} fill="#ff6f00">
                    Click a second node to connect…
                  </text>
                )}
              </g>
            </svg>

            {/* Inspector */}
            <div className="flex w-64 shrink-0 flex-col border-l border-border bg-surface">
              <div className="flex items-center gap-1 border-b border-border px-2 py-1.5">
                <button
                  type="button"
                  onClick={() => setZoom((z) => Math.min(2.5, +(z * 1.2).toFixed(2)))}
                  className="rounded-sm p-1 text-text-secondary hover:bg-surface-higher"
                  aria-label="Zoom in"
                >
                  <ZoomIn size={14} aria-hidden />
                </button>
                <button
                  type="button"
                  onClick={() => setZoom((z) => Math.max(0.25, +(z / 1.2).toFixed(2)))}
                  className="rounded-sm p-1 text-text-secondary hover:bg-surface-higher"
                  aria-label="Zoom out"
                >
                  <ZoomOut size={14} aria-hidden />
                </button>
                <span className="px-1 text-xs text-text-secondary">{Math.round(zoom * 100)}%</span>
                <div className="flex-1" />
                <button
                  type="button"
                  onClick={() => {
                    if (selectedNode) {
                      setConnectFrom(selectedNode);
                    }
                  }}
                  disabled={!selectedNode}
                  title="Connect this node to another (then click the second node)"
                  className={cn(
                    "rounded-sm p-1 hover:bg-surface-higher",
                    connectFrom ? "bg-accent/20 text-accent" : "text-text-secondary",
                  )}
                >
                  <Link2 size={14} aria-hidden />
                </button>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto p-2">
                {selected ? (
                  <div className="space-y-2">
                    <p className="text-sm font-medium">{selected.label}</p>
                    <p className="text-xs text-text-secondary">
                      {selected.kind} · ({Math.round(selected.x)}, {Math.round(selected.y)})
                    </p>
                    <label className="block">
                      <span className="mb-0.5 block text-xs text-text-secondary">Label</span>
                      <input
                        defaultValue={selected.label}
                        onBlur={(e) => {
                          const v = e.target.value.trim();
                          if (v && v !== selected.label) void patchNode(selected, { displaytext: v });
                        }}
                        className="h-7 w-full rounded-sm border border-border bg-bg px-1.5 text-xs outline-none focus:border-accent"
                      />
                    </label>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => void patchNode(selected, { bold: selected.bold ? 0 : 1 })}
                        className="rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher"
                      >
                        {selected.bold ? "Bold ✓" : "Bold"}
                      </button>
                      {selected.kind !== "memo" && (
                        <button
                          type="button"
                          onClick={() => void patchNode(selected, { font_size: selected.fontSize + 1 })}
                          className="rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher"
                        >
                          Font +
                        </button>
                      )}
                      {selected.kind === "free" && (
                        <button
                          type="button"
                          onClick={() => {
                            const text = window.prompt("Free text:", selected.label);
                            if (text?.trim()) void patchNode(selected, { free_text: text.trim() });
                          }}
                          className="rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher"
                        >
                          <CaseSensitive size={12} aria-hidden />
                        </button>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => void deleteNode()}
                      className="flex items-center gap-1 rounded-sm border border-danger/50 px-2 py-1 text-xs text-danger hover:bg-danger/10"
                    >
                      <Trash2 size={12} aria-hidden />
                      Delete node
                    </button>
                  </div>
                ) : selectedL ? (
                  <div className="space-y-2">
                    <p className="text-sm font-medium">Line</p>
                    <label className="block">
                      <span className="mb-0.5 block text-xs text-text-secondary">Label (relation)</span>
                      <input
                        defaultValue={selectedL.label}
                        onBlur={(e) => void patchLine({ label: e.target.value })}
                        className="h-7 w-full rounded-sm border border-border bg-bg px-1.5 text-xs outline-none focus:border-accent"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-0.5 block text-xs text-text-secondary">Style</span>
                      <select
                        value={selectedL.arrow_mode}
                        onChange={(e) => void patchLine({ arrow_mode: e.target.value })}
                        className="h-7 w-full rounded-sm border border-border bg-bg px-1.5 text-xs outline-none focus:border-accent"
                      >
                        {ARROW_MODES.map((m) => (
                          <option key={m} value={m}>
                            {m.replace(/_/g, " ")}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      type="button"
                      onClick={() => void deleteLine()}
                      className="flex items-center gap-1 rounded-sm border border-danger/50 px-2 py-1 text-xs text-danger hover:bg-danger/10"
                    >
                      <Trash2 size={12} aria-hidden />
                      Delete line
                    </button>
                  </div>
                ) : (
                  <div className="space-y-1.5 text-xs text-text-secondary">
                    <p>Double-click the canvas to add a node.</p>
                    <p>Drag nodes to move them (positions save automatically).</p>
                    <p>Select a node, press the link button, then click a second node to draw a relation line.</p>
                    <p>Select a line to label it or change its arrow style.</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Add-node context menu */}
      {addMenu && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setAddMenu(null)} aria-hidden />
          <div
            className="fixed z-40 min-w-40 rounded-md border border-border bg-surface py-1 shadow-lg"
            style={{ left: addMenu.x, top: addMenu.y }}
            role="menu"
          >
            {(
              [
                ["Code…", () => void addCdct("code"), <Network key="i" size={14} aria-hidden />],
                ["Category…", () => void addCdct("category"), <FolderPlus key="i" size={14} aria-hidden />],
                ["Case…", () => void addCase(), <BookMarked key="i" size={14} aria-hidden />],
                ["File…", () => void addFile(), <FileText key="i" size={14} aria-hidden />],
                ["Free text…", () => void addFree(), <CaseSensitive key="i" size={14} aria-hidden />],
                ["Memo…", () => void addMemo(), <Pencil key="i" size={14} aria-hidden />],
              ] as [string, () => void, ReactNode][]
            ).map(([label, run, icon]) => (
              <button
                key={label}
                type="button"
                role="menuitem"
                onClick={() => {
                  setAddMenu(null);
                  run();
                }}
                className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher"
              >
                {icon}
                {label}
              </button>
            ))}
          </div>
        </>
      )}

      {/* Model generator dialog */}
      {modelOpen && (
        <ModelDialog
          onClose={() => setModelOpen(false)}
          onCreated={(g) => {
            setModelOpen(false);
            void loadGraphs();
            setGrid(g);
          }}
          setError={setError}
        />
      )}
      {saving && (
        <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center">
          <LoaderCircle size={18} className="animate-spin text-text-secondary" aria-hidden />
        </div>
      )}
    </div>
  );
}

function ModelDialog({
  onClose,
  onCreated,
  setError,
}: {
  onClose: () => void;
  onCreated: (grid: number) => void;
  setError: (msg: string | null) => void;
}) {
  const { t } = useI18n();
  const sources = useProjectStore((s) => s.sources);
  const cases = useProjectStore((s) => s.cases);
  const [model, setModel] = useState<(typeof GRAPH_MODELS)[number]>("category-hierarchy");
  const [name, setName] = useState("");
  const [fileIds, setFileIds] = useState<number[]>([]);
  const [caseIds, setCaseIds] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);

  async function generate() {
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      const res = await api.graphGenerateModel(
        model,
        name.trim(),
        fileIds.length > 0 ? fileIds : undefined,
        caseIds.length > 0 ? caseIds : undefined,
      );
      onCreated(res.grid);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not generate model");
    } finally {
      setBusy(false);
    }
  }

  const multi = (values: number[], set: (v: number[]) => void) => (
    <label className="block">
      <span className="mb-0.5 block text-xs text-text-secondary">Comma-separated ids</span>
      <input
        value={values.join(",")}
        onChange={(e) =>
          set(
            e.target.value
              .split(",")
              .map((v) => Number(v.trim()))
              .filter((v) => Number.isFinite(v) && v > 0),
          )
        }
        className="h-7 w-full rounded-sm border border-border bg-bg px-1.5 text-xs outline-none focus:border-accent"
      />
    </label>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-lg border border-border bg-surface p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Generate graph model"
      >
        <h2 className="text-sm font-semibold text-text-primary">{t("graphs.models")}</h2>
        <div className="mt-3 space-y-3">
          <label className="block">
            <span className="mb-0.5 block text-xs text-text-secondary">Model</span>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value as (typeof GRAPH_MODELS)[number])}
              className="h-7 w-full rounded-sm border border-border bg-bg px-1.5 text-xs outline-none focus:border-accent"
            >
              {GRAPH_MODELS.map((m) => (
                <option key={m} value={m}>
                  {m.replace(/-/g, " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-0.5 block text-xs text-text-secondary">Graph name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. My model"
              className="h-7 w-full rounded-sm border border-border bg-bg px-1.5 text-xs outline-none focus:border-accent"
            />
          </label>
          {(model === "file-comparison" || model === "file-hierarchy") &&
            multi(fileIds, setFileIds)}
          {(model === "case-comparison" || model === "case-hierarchy") &&
            multi(caseIds, setCaseIds)}
          <p className="text-[11px] leading-relaxed text-text-secondary">
            {sources.length} files · {cases.length} cases in the project.
          </p>
        </div>
        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-sm border border-border bg-bg px-3 py-1 text-xs hover:bg-surface-higher"
          >
            {t("common.cancel")}
          </button>
          <button
            type="button"
            onClick={() => void generate()}
            disabled={busy || !name.trim()}
            className="flex items-center gap-1.5 rounded-sm bg-accent px-3 py-1 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50"
          >
            {busy ? <LoaderCircle size={12} className="animate-spin" aria-hidden /> : <Save size={12} aria-hidden />}
            Generate
          </button>
        </div>
      </div>
    </div>
  );
}