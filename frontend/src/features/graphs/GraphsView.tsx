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
  BookMarked,
  CaseSensitive,
  FileText,
  FolderPlus,
  Link2,
  LoaderCircle,
  Map as MapIcon,
  Network,
  Pencil,
  Save,
  Sparkles,
  Trash2,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { api, GRAPH_MODELS, type GraphData } from "@/lib/api";

import { useI18n } from "@/lib/i18n";
import { Button, ErrorBanner, Field, IconButton, Input, LeftBar, BarHeader, Menu, MenuItem, Modal, Select } from "@/components/ui/orchestrator";
import { InlineNameEdit } from "@/components/ui/InlineNameEdit";

import { RowContextMenu } from "@/features/shell/RowContextMenu";
import { cls } from "@/components/ui/tokens";

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

/** In-app dialog for naming a new graph (no system prompt). */
function GraphNameDialog({
  open,
  onClose,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (name: string) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  useEffect(() => {
    if (open) setName("");
  }, [open]);
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      title={t("graphs.newGraph")}
      ariaLabel={t("graphs.newGraph")}
    >
      <div className="p-3">
        <Field label={t("graphs.graphName")}>
          <Input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && name.trim()) onSubmit(name.trim());
            }}
            placeholder={t("graphs.graphNamePlaceholder")}
            className="w-full"
          />
        </Field>
        <div className="mt-3 flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" disabled={!name.trim()} onClick={() => onSubmit(name.trim())}>
            {t("graphs.newGraph")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/** In-app confirmation dialog (no system confirm). */
function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  onClose,
  onConfirm,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  return (
    <Modal open={open} onClose={onClose} size="sm" title={title} ariaLabel={title}>
      <div className="p-3">
        <p className="text-sm text-text-primary">{message}</p>
        <div className="mt-3 flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="danger" onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/** The center-contained graph toolbar: title + zoom/connect on the right.
 *  Graph picking lives in the left bar; the modals are owned here (opened
 *  from the left bar via the store dialog flag). */
export function GraphsMenuBar({ actions }: { actions?: ReactNode }) {
  const { t } = useI18n();
  const graphsUi = useProjectStore((s) => s.graphsUi);
  const setGraphsUi = useProjectStore((s) => s.setGraphsUi);
  const dialog = graphsUi.dialog;

  async function loadGraphs() {
    try {
      const res = await api.graphs();
      setGraphsUi({
        list: res.graphs.map((g) => ({ grid: g.grid, name: g.name })),
        grid: graphsUi.grid ?? (res.graphs.length > 0 ? res.graphs[0].grid : null),
        tick: graphsUi.tick + 1,
      });
    } catch {
      /* the picker shows whatever is cached */
    }
  }

  async function createGraph(name: string) {
    setGraphsUi({ dialog: null });
    try {
      const graph = await api.createGraph(name);
      await loadGraphs();
      setGraphsUi({ grid: graph.grid, tick: graphsUi.tick + 1 });
    } catch {
      /* keep the picker state */
    }
  }

  async function deleteGraph() {
    const grid = graphsUi.grid;
    if (grid == null) return;
    setGraphsUi({ dialog: null });
    try {
      await api.deleteGraph(grid);
      setGraphsUi({ grid: null, tick: graphsUi.tick + 1 });
      await loadGraphs();
    } catch {
      /* keep the picker state */
    }
  }

  const deleteName = graphsUi.list.find((g) => g.grid === graphsUi.grid)?.name ?? "";

  return (
    <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border bg-surface px-3">
      <h1 className="text-sm font-semibold text-text-primary">{t("graphs.title")}</h1>
      <div className="flex-1" />
      {actions}
      {graphsUi.grid != null && (
        <Button
          variant="danger"
          icon={<Trash2 size={12} aria-hidden />}
          onClick={() => setGraphsUi({ dialog: "delete" })}
        >
          {t("common.delete")}
        </Button>
      )}
      <GraphNameDialog
        open={dialog === "name"}
        onClose={() => setGraphsUi({ dialog: null })}
        onSubmit={(n) => void createGraph(n)}
      />
      <ConfirmDialog
        open={dialog === "delete"}
        title={t("graphs.deleteTitle")}
        message={t("graphs.deleteConfirm", { name: deleteName })}
        confirmLabel={t("common.delete")}
        onClose={() => setGraphsUi({ dialog: null })}
        onConfirm={() => void deleteGraph()}
      />
      {dialog === "models" && (
        <ModelDialog
          onClose={() => setGraphsUi({ dialog: null })}
          onCreated={(g) => {
            setGraphsUi({ dialog: null, grid: g, tick: graphsUi.tick + 1 });
            void loadGraphs();
          }}
          setError={(msg) => setGraphsUi({ error: msg })}
        />
      )}
    </div>
  );
}

export function GraphsView() {
  const { t } = useI18n();
  const graphsUi = useProjectStore((s) => s.graphsUi);
  const setGraphsUi = useProjectStore((s) => s.setGraphsUi);
  const data = useProjectStore((s) => s.graphsData);
  const loading = useProjectStore((s) => s.graphsLoading);
  const loadGraphData = useProjectStore((s) => s.loadGraphData);
  const graphConnect = useProjectStore((s) => s.graphConnect);
  const graphs = graphsUi.list;
  const grid = graphsUi.grid;
  const selectedNode = graphsUi.selectedNode;
  const connectFrom = graphsUi.connectFrom;
  const zoom = graphsUi.zoom;
  const error = graphsUi.error;

  // viewport transform (canvas-local)
  const [pan, setPan] = useState({ x: 40, y: 40 });
  const panRef = useRef(pan);
  panRef.current = pan;
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;

  // interactions
  const [drag, setDrag] = useState<{ node: string; startX: number; startY: number; origX: number; origY: number } | null>(null);
  const [panDrag, setPanDrag] = useState<{ x: number; y: number; startX: number; startY: number } | null>(null);
  const [addMenu, setAddMenu] = useState<{ x: number; y: number } | null>(null);
  const [pickAdd, setPickAdd] = useState<{
    kind: "category" | "code" | "case" | "file" | "free" | "memo";
    options: { id: number; name: string }[];
  } | null>(null);
  const [saving, setSaving] = useState(false);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const nodes = useMemo(() => (data ? buildNodes(data) : []), [data]);
  const lines = useMemo(() => (data ? buildLines(data, nodes) : []), [data, nodes]);
  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  const loadGraphs = useCallback(async () => {
    try {
      const res = await api.graphs();
      setGraphsUi({
        list: res.graphs.map((g) => ({ grid: g.grid, name: g.name })),
        grid:
          graphsUi.grid ??
          (res.graphs.length > 0 ? res.graphs[0].grid : null),
        tick: graphsUi.tick + 1,
      });
    } catch (e) {
      setGraphsUi({ error: e instanceof Error ? e.message : "Failed to load graphs" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void loadGraphs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (grid != null) void loadGraphData(grid);
  }, [grid, loadGraphData]);

  async function createGraph(name: string) {
    setGraphsUi({ dialog: null });
    try {
      const graph = await api.createGraph(name);
      setGraphsUi({ grid: graph.grid, tick: graphsUi.tick + 1 });
    } catch (e) {
      setGraphsUi({ error: e instanceof Error ? e.message : "Could not create graph" });
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
    setGraphsUi({ selectedNode: node.id, selectedLine: null });
    if (connectFrom) {
      // connecting two nodes
      if (connectFrom !== node.id) {
        const [fk, fid] = connectFrom.split(":");
        const [tk, tid] = node.id.split(":");
        void graphConnect({ kind: fk, id: Number(fid) }, { kind: tk, id: Number(tid) });
      }
      setGraphsUi({ connectFrom: null });
      return;
    }
    setDrag({ node: node.id, startX: e.clientX, startY: e.clientY, origX: node.x, origY: node.y });
  }

  /* ------------------------------------------------------ add node menu */

  /** Open the in-app picker for adding a node of the given kind. */
  function openAddPicker(
    kind: "category" | "code" | "case" | "file" | "free" | "memo",
  ) {
    if (!data) return;
    let options: { id: number; name: string }[] = [];
    if (kind === "category") options = data.categories.map((c) => ({ id: c.catid, name: c.name }));
    else if (kind === "code") options = data.codes.map((c) => ({ id: c.cid, name: c.name }));
    else if (kind === "case") options = data.cases.map((c) => ({ id: c.caseid, name: c.name }));
    else if (kind === "file") options = data.sources.map((s) => ({ id: s.id, name: s.name }));
    else if (kind === "memo") options = data.codes.filter((c) => c.memo && c.memo.trim()).map((c) => ({ id: c.cid, name: c.name }));
    if (options.length === 0 && kind !== "free") {
      setGraphsUi({ error: "No items to add yet" });
      return;
    }
    setAddMenu(null);
    setPickAdd({ kind, options });
  }

  async function doAddNode(kind: "category" | "code" | "case" | "file" | "free" | "memo", id: number, name: string) {
    if (!data || !addMenu) return;
    setPickAdd(null);
    try {
      if (kind === "category" || kind === "code") {
        await api.graphAddCdctItem(data.graph.grid, { kind, ref_id: id, x: addMenu.x, y: addMenu.y });
      } else if (kind === "case") {
        await api.graphAddCaseItem(data.graph.grid, { caseid: id, x: addMenu.x, y: addMenu.y });
      } else if (kind === "file") {
        await api.graphAddFileItem(data.graph.grid, { fid: id, x: addMenu.x, y: addMenu.y });
      } else if (kind === "free") {
        await api.graphAddFreeItem(data.graph.grid, { x: addMenu.x, y: addMenu.y, free_text: name.trim() });
      } else {
        await api.graphAddMemoItem(data.graph.grid, {
          memo_source_type: "code",
          memo_source_id: id,
          x: addMenu.x,
          y: addMenu.y,
        });
      }
      await loadGraphData(data.graph.grid);
    } catch (e) {
      setGraphsUi({ error: e instanceof Error ? e.message : "Could not add node" });
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
        setGraphsUi({ tick: graphsUi.tick + 1 });
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
    setGraphsUi({ selectedNode: null });
    setGraphsUi({ selectedLine: null });
    setGraphsUi({ connectFrom: null });
    setPanDrag({ x: pan.x, y: pan.y, startX: e.clientX, startY: e.clientY });
  }

  function onWheel(e: React.WheelEvent) {
    const factor = e.deltaY > 0 ? 0.9 : 1.1;
    const next = Math.min(2.5, Math.max(0.25, zoom * factor));
    setGraphsUi({ zoom: next });
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

  return (
    <div className="flex h-full flex-col bg-bg">
      <GraphsMenuBar
        actions={
          <>
            <IconButton label="Zoom in" onClick={() => setGraphsUi({ zoom: Math.min(2.5, +(graphsUi.zoom * 1.2).toFixed(2)) })}>
              <ZoomIn size={16} aria-hidden />
            </IconButton>
            <span className="w-10 text-center text-xs text-text-secondary">
              {Math.round(zoom * 100)}%
            </span>
            <IconButton label="Zoom out" onClick={() => setGraphsUi({ zoom: Math.max(0.25, +(graphsUi.zoom / 1.2).toFixed(2)) })}>
              <ZoomOut size={16} aria-hidden />
            </IconButton>
            <IconButton
              label={t("graphs.connect")}
              title={t("graphs.connect")}
              onClick={() => {
                if (selectedNode) setGraphsUi({ connectFrom: selectedNode });
              }}
              disabled={!selectedNode}
              className={connectFrom ? "bg-accent/20 text-accent" : ""}
            >
              <Link2 size={16} aria-hidden />
            </IconButton>
          </>
        }
      />
      {error && <ErrorBanner onClose={() => setGraphsUi({ error: null })}>{error}</ErrorBanner>}

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
            <Button variant="primary" onClick={() => setGraphsUi({ dialog: "name" })}>
              {t("graphs.newGraph")}
            </Button>
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
                        setGraphsUi({ selectedLine: line.id });
                        setGraphsUi({ selectedNode: null });
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
          </div>
        )}
      </div>

      {/* Add-node context menu */}
      {addMenu && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setAddMenu(null)} aria-hidden />
          <Menu
            position="fixed"
            className="min-w-40"
            style={{ left: addMenu.x, top: addMenu.y }}
            role="menu"
          >
            {(
              [
                ["Code…", () => openAddPicker("code"), <Network key="i" size={14} aria-hidden />],
                ["Category…", () => openAddPicker("category"), <FolderPlus key="i" size={14} aria-hidden />],
                ["Case…", () => openAddPicker("case"), <BookMarked key="i" size={14} aria-hidden />],
                ["File…", () => openAddPicker("file"), <FileText key="i" size={14} aria-hidden />],
                ["Free text…", () => openAddPicker("free"), <CaseSensitive key="i" size={14} aria-hidden />],
                ["Memo…", () => openAddPicker("memo"), <Pencil key="i" size={14} aria-hidden />],
              ] as [string, () => void, ReactNode][]
            ).map(([label, run, icon]) => (
              <MenuItem
                key={label}
                role="menuitem"
                onClick={() => {
                  setAddMenu(null);
                  run();
                }}
              >
                {icon}
                {label}
              </MenuItem>
            ))}
          </Menu>
        </>
      )}

      {saving && (
        <div className={`pointer-events-none ${cls.modalOverlay}`}>
          <LoaderCircle size={18} className="animate-spin text-text-secondary" aria-hidden />
        </div>
      )}
      {pickAdd && (
        <PickNodeDialog
          kind={pickAdd.kind}
          options={pickAdd.options}
          onClose={() => setPickAdd(null)}
          onAdd={(id, name) => void doAddNode(pickAdd.kind, id, name)}
        />
      )}
      <GraphNameDialog
        open={graphsUi.dialog === "name"}
        onClose={() => setGraphsUi({ dialog: null })}
        onSubmit={(n) => void createGraph(n)}
      />
    </div>
  );
}

/** In-app picker for adding a node to the canvas (no system prompt). */
function PickNodeDialog({
  kind,
  options,
  onClose,
  onAdd,
}: {
  kind: string;
  options: { id: number; name: string }[];
  onClose: () => void;
  onAdd: (id: number, name: string) => void;
}) {
  const { t } = useI18n();
  const [value, setValue] = useState("");
  const isFree = kind === "free";
  return (
    <Modal open onClose={onClose} size="sm" title={`Add ${kind} node`} ariaLabel={`Add ${kind} node`}>
      <div className="p-3">
        {isFree ? (
          <Field label="Free text">
            <Input
              autoFocus
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && value.trim()) onAdd(-1, value);
              }}
              placeholder="Free text"
              className="w-full"
            />
          </Field>
        ) : (
          <Field label={`${kind} name`}>
            <Select
              autoFocus
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="w-full"
            >
              <option value="">—</option>
              {options.map((o) => (
                <option key={o.id} value={o.name}>
                  {o.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <div className="mt-3 flex items-center justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="primary"
            disabled={!value.trim()}
            onClick={() => {
              const option = options.find((o) => o.name === value);
              onAdd(option ? option.id : -1, value);
            }}
          >
            {t("interchange.import")}
          </Button>
        </div>
      </div>
    </Modal>
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
    <Field label="Comma-separated ids">
      <Input
        value={values.join(",")}
        onChange={(e) =>
          set(
            e.target.value
              .split(",")
              .map((v) => Number(v.trim()))
              .filter((v) => Number.isFinite(v) && v > 0),
          )
        }
        className="w-full"
      />
    </Field>
  );

  return (
    <Modal
      open
      onClose={onClose}
      title={t("graphs.models")}
      panelClassName="w-full max-w-md"
      ariaLabel="Generate graph model"
    >
      <div className="space-y-3 p-4">
        <Field label="Model">
          <Select
            value={model}
            onChange={(e) => setModel(e.target.value as (typeof GRAPH_MODELS)[number])}
            className="w-full"
          >
            {GRAPH_MODELS.map((m) => (
              <option key={m} value={m}>
                {m.replace(/-/g, " ")}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Graph name">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. My model"
            className="w-full"
          />
        </Field>
        {(model === "file-comparison" || model === "file-hierarchy") &&
          multi(fileIds, setFileIds)}
        {(model === "case-comparison" || model === "case-hierarchy") &&
          multi(caseIds, setCaseIds)}
        <p className="text-[11px] leading-relaxed text-text-secondary">
          {sources.length} files · {cases.length} cases in the project.
        </p>
      </div>
      <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-2.5">
        <Button variant="secondary" onClick={onClose}>
          {t("common.cancel")}
        </Button>
        <Button
          variant="primary"
          onClick={() => void generate()}
          disabled={busy || !name.trim()}
          icon={
            busy ? (
              <LoaderCircle size={12} className="animate-spin" aria-hidden />
            ) : (
              <Save size={12} aria-hidden />
            )
          }
        >
          Generate
        </Button>
      </div>
    </Modal>
  );
}
/** Left bar for the graphs view: the graph list + New graph / Models. */
export function GraphsList() {
  const { t } = useI18n();
  const graphsUi = useProjectStore((s) => s.graphsUi);
  const setGraphsUi = useProjectStore((s) => s.setGraphsUi);
  const [rowMenu, setRowMenu] = useState<{ x: number; y: number; grid: number; name: string } | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);

  async function reloadList() {
    try {
      const res = await api.graphs();
      setGraphsUi({
        list: res.graphs.map((g) => ({ grid: g.grid, name: g.name })),
        tick: graphsUi.tick + 1,
      });
    } catch {
      /* keep the cached list */
    }
  }

  async function createGraph(name: string) {
    try {
      const graph = await api.createGraph(name);
      setGraphsUi({ grid: graph.grid, tick: graphsUi.tick + 1 });
      await reloadList();
      return graph.grid;
    } catch {
      return null;
    }
  }

  async function renameGraphInline(grid: number, name: string) {
    // Close the editor synchronously so Tab can move it to the next row.
    setEditingId(null);
    try {
      await api.updateGraph(grid, { name });
      await reloadList();
    } catch {
      /* keep the picker state */
    }
  }

  async function deleteGraphRow(grid: number, name: string) {
    if (!window.confirm(t("graphs.deleteConfirm", { name }))) return;
    try {
      await api.deleteGraph(grid);
      setGraphsUi({ grid: null, tick: graphsUi.tick + 1 });
      await reloadList();
    } catch {
      /* keep the picker state */
    }
  }

  return (
    <LeftBar
      header={
        <BarHeader
          title={t("graphs.title")}
          actions={
            <>
              <Button
                variant="secondary"
                icon={<Sparkles size={12} aria-hidden />}
                onClick={() => setGraphsUi({ dialog: "models" })}
              >
                {t("graphs.models")}
              </Button>
              <Button
                variant="primary"
                icon={<Network size={12} aria-hidden />}
                onClick={() => {
                  void createGraph(t("graphs.untitled")).then((grid) => {
                    if (grid != null) setEditingId(grid);
                  });
                }}
              >
                {t("common.add")}
              </Button>
            </>
          }
        />
      }
      
    >
      {graphsUi.list.length === 0 ? (
        <p className="px-3 py-6 text-center text-sm text-text-secondary">
          {t("graphs.noGraphs")}
        </p>
      ) : (
        <div className="divide-y divide-border">
          {graphsUi.list.map((g) =>
            editingId === g.grid ? (
              <div key={g.grid} className="flex w-full items-center gap-2 px-3 py-2">
                <Network size={14} className="shrink-0 text-text-secondary" aria-hidden />
                <InlineNameEdit
                  value={g.name}
                  placeholder={t("graphs.graphNamePlaceholder")}
                  onSave={(name) => void renameGraphInline(g.grid, name)}
                  onCancel={() => setEditingId(null)}
                  onTab={() => {
                    const idx = graphsUi.list.findIndex((x) => x.grid === g.grid);
                    const next = graphsUi.list[idx + 1];
                    setEditingId(next ? next.grid : null);
                  }}
                />
              </div>
            ) : (
              <div key={g.grid} className="group">
                <button
                  type="button"
                  onClick={() => setGraphsUi({ grid: g.grid, tick: graphsUi.tick + 1 })}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    setRowMenu({ x: e.clientX, y: e.clientY, grid: g.grid, name: g.name });
                  }}
                  className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-higher ${
                    graphsUi.grid === g.grid ? "bg-accent/10 text-accent" : "text-text-primary"
                  }`}
                >
                  <Network size={14} className="shrink-0 text-text-secondary" aria-hidden />
                  <span className="min-w-0 flex-1 truncate">{g.name}</span>
                  <span className="ml-auto flex shrink-0 gap-0.5 opacity-0 group-hover:opacity-100">
                    <IconButton
                      label={t("graphs.renameFor", { name: g.name })}
                      title={t("graphs.renameFor", { name: g.name })}
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditingId(g.grid);
                      }}
                    >
                      <Pencil size={13} aria-hidden />
                    </IconButton>
                    <IconButton
                      label={t("graphs.deleteFor", { name: g.name })}
                      title={t("graphs.deleteFor", { name: g.name })}
                      size="sm"
                      className="hover:text-danger"
                      onClick={(e) => {
                        e.stopPropagation();
                        setGraphsUi({ grid: g.grid, dialog: "delete", tick: graphsUi.tick + 1 });
                      }}
                    >
                      <Trash2 size={13} aria-hidden />
                    </IconButton>
                  </span>
                </button>
              </div>
            ),
          )}
        </div>
      )}
      {rowMenu && (
        <RowContextMenu
          x={rowMenu.x}
          y={rowMenu.y}
          onClose={() => setRowMenu(null)}
          items={[
            {
              label: t("common.rename"),
              icon: <Pencil size={14} aria-hidden />,
              run: () => {
                setRowMenu(null);
                setEditingId(rowMenu.grid);
              },
            },
            {
              label: t("common.delete"),
              icon: <Trash2 size={14} aria-hidden />,
              danger: true,
              run: () => void deleteGraphRow(rowMenu.grid, rowMenu.name),
            },
          ]}
        />
      )}
    </LeftBar>
  );
}

/** Right-bar inspector for the graphs view (opens automatically): the
 *  selected node/line editor. */
export function GraphsInspector() {
  const { t } = useI18n();
  const graphsUi = useProjectStore((s) => s.graphsUi);
  const data = useProjectStore((s) => s.graphsData);
  const graphPatchNode = useProjectStore((s) => s.graphPatchNode);
  const graphDeleteNode = useProjectStore((s) => s.graphDeleteNode);
  const graphPatchLine = useProjectStore((s) => s.graphPatchLine);
  const graphDeleteLine = useProjectStore((s) => s.graphDeleteLine);

  const nodes = useMemo(() => (data ? buildNodes(data) : []), [data]);
  const lines = useMemo(() => (data ? buildLines(data, nodes) : []), [data, nodes]);
  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const lineById = useMemo(() => new Map(lines.map((l) => [l.id, l])), [lines]);

  const selected = graphsUi.selectedNode ? nodeById.get(graphsUi.selectedNode) : undefined;
  const selectedL = graphsUi.selectedLine ? lineById.get(graphsUi.selectedLine) : undefined;

  async function deleteNode(kind: string, id: number, label: string) {
    if (kind === "memo") return;
    if (!window.confirm(`Delete node "${label}"?`)) return;
    await graphDeleteNode(kind, id);
  }

  async function deleteLine(kind: string, id: number) {
    if (!window.confirm("Delete this line?")) return;
    await graphDeleteLine(kind, id);
  }

  return (
    <LeftBar
      borderSide="l"
      header={<BarHeader title={t("graphs.title")} />}
    >
      {selected ? (
        <div className="space-y-2 p-2">
          <p className="text-sm font-medium">{selected.label}</p>
          <p className="text-xs text-text-secondary">
            {selected.kind} · ({Math.round(selected.x)}, {Math.round(selected.y)})
          </p>
          <label className="block">
            <span className="mb-0.5 block text-xs text-text-secondary">Label</span>
            <Input
              key={selected.id}
              defaultValue={selected.label}
              onBlur={(e) => {
                const v = e.target.value.trim();
                if (v && v !== selected.label) {
                  const [, id] = selected.id.split(":");
                  void graphPatchNode(selected.kind, Number(id), { displaytext: v });
                }
              }}
              className="w-full"
            />
          </label>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                const [, id] = selected.id.split(":");
                void graphPatchNode(selected.kind, Number(id), { bold: selected.bold ? 0 : 1 });
              }}
            >
              {selected.bold ? "Bold ✓" : "Bold"}
            </Button>
            {selected.kind !== "memo" && (
              <Button
                variant="secondary"
                onClick={() => {
                  const [, id] = selected.id.split(":");
                  void graphPatchNode(selected.kind, Number(id), { font_size: selected.fontSize + 1 });
                }}
              >
                Font +
              </Button>
            )}
          </div>
          <Button
            variant="danger"
            className="w-full"
            onClick={() => {
              const [, id] = selected.id.split(":");
              void deleteNode(selected.kind, Number(id), selected.label);
            }}
          >
            <Trash2 size={12} aria-hidden />
            {t("common.delete")}
          </Button>
        </div>
      ) : selectedL ? (
        <div className="space-y-2 p-2">
          <p className="text-sm font-medium">Line</p>
          <label className="block">
            <span className="mb-0.5 block text-xs text-text-secondary">Label (relation)</span>
            <Input
              key={selectedL.id}
              defaultValue={selectedL.label}
              onBlur={(e) => {
                const [, id] = selectedL.id.split(":");
                void graphPatchLine(selectedL.kind, Number(id), { label: e.target.value });
              }}
              className="w-full"
            />
          </label>
          <label className="block">
            <span className="mb-0.5 block text-xs text-text-secondary">Style</span>
            <Select
              value={selectedL.arrow_mode}
              onChange={(e) => {
                const [, id] = selectedL.id.split(":");
                void graphPatchLine(selectedL.kind, Number(id), { arrow_mode: e.target.value });
              }}
              className="w-full"
            >
              {ARROW_MODES.map((m) => (
                <option key={m} value={m}>
                  {m.replace(/_/g, " ")}
                </option>
              ))}
            </Select>
          </label>
          <Button
            variant="danger"
            className="w-full"
            onClick={() => {
              const [, id] = selectedL.id.split(":");
              void deleteLine(selectedL.kind, Number(id));
            }}
          >
            <Trash2 size={12} aria-hidden />
            {t("common.delete")}
          </Button>
        </div>
      ) : (
        <div className="space-y-1.5 p-3 text-xs text-text-secondary">
          <p>Double-click the canvas to add a node.</p>
          <p>Drag nodes to move them (positions save automatically).</p>
          <p>Select a node, press the link button, then click a second node to draw a relation line.</p>
          <p>Select a line to label it or change its arrow style.</p>
        </div>
      )}
      {graphsUi.error && (
        <div className="border-t border-border p-2">
          <p className="text-xs text-danger">{graphsUi.error}</p>
        </div>
      )}
    </LeftBar>
  );
}
