/**
 * Left sidebar — Files / Codes / Cases trees built from the API.
 */
import { useEffect, useMemo, useRef, useState, type DragEvent as ReactDragEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  FileAudio,
  FileImage,
  FileText,
  Folder,
  FolderOpen,
  FolderPlus,
  GitMerge,
  IndentDecrease,
  IndentIncrease,
  Info,
  LoaderCircle,
  Palette,
  Pencil,
  Plus,
  Search,
  SlidersHorizontal,
  StickyNote,
  Trash2,
  Unlink,
  Upload,
  UserRound,
  X,
} from "lucide-react";
import { api, ApiError, type CodeTreeItem, type Source } from "@/lib/api";
import {
  addCodeSetMembers,
  createCodeSet,
  deleteCodeSet,
  getCodeSet,
  listCodeSets,
  removeCodeSetMembers,
  renameCodeSet,
  type CodeSetSummary,
} from "@/lib/codeSetsApi";

import {
  BarHeader,
  Button,
  IconButton,
  Input,
  LeftBar,
  Menu,
  MenuItem,
  Modal,
  Select,
} from "@/components/ui/orchestrator";
import { InlineNameEdit } from "@/components/ui/InlineNameEdit";
import { isPdf } from "@/lib/media";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";
import { clampToViewport } from "@/features/sidebar/codeActions";

type ContextMenu =
  | { kind: "code"; x: number; y: number; item: CodeTreeItem }
  | { kind: "file"; x: number; y: number; source: Source };

interface MenuAction {
  label: string;
  icon: ReactNode;
  danger?: boolean;
  run: () => void;
}

const MENU_WIDTH = 176;

/** Payload of the in-flight HTML5 drag. Module-level so it survives
 *  re-renders; ``subtree`` is the dragged node's descendant keys, computed
 *  once at dragstart and reused for every cycle guard (the tree cannot
 *  change while a drag is in flight). */
interface DragNode {
  kind: "code" | "category";
  id: number;
  subtree: Set<string>;
}

let dragNode: DragNode | null = null;

/** The current drop affordance on the hovered row (``key`` = kind:id). */
type DropZone =
  | { mode: "before"; key: string }
  | { mode: "after"; key: string }
  | { mode: "into"; key: string }
  | { mode: "merge"; key: string };

/** Body shapes of the backend move endpoints (only set fields are sent;
 *  an explicit null means "move to the root / clear the parent"). */
type CodeMoveOpts = {
  parent_catid?: number | null;
  supercid?: number | null;
  after_cid?: number | null;
  before_cid?: number | null;
};
type CategoryMoveOpts = {
  supercatid?: number | null;
  after_catid?: number | null;
  before_catid?: number | null;
};

export function Sidebar() {
  const { t } = useI18n();
  const toast = useToast();
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [menu, setMenu] = useState<ContextMenu | null>(null);
  const [toolbarError, setToolbarError] = useState<string | null>(null);
  /** Pointer-drag state (refs — the drag must survive re-renders). */
  const pointerDownRef = useRef<{ item: CodeTreeItem; x: number; y: number } | null>(null);
  const dragStartedRef = useRef(false);
  const suppressClickRef = useRef(false);
  const treeContainerRef = useRef<HTMLDivElement | null>(null);
  /** Drop indicator while a code/category is dragged over the tree. */
  const [dropZone, setDropZone] = useState<DropZone | null>(null);
  /** Key of the row currently being dragged (dimmed during the drag). */
  const [draggingKey, setDraggingKey] = useState<string | null>(null);
  /** OS file drag hovering the files leftbar (import affordance). */
  const [fileDropActive, setFileDropActive] = useState(false);
  /** Inline name editing (no system prompts): which row is being edited. */
  const [editing, setEditing] = useState<{ kind: "code" | "category" | "file"; id: number } | null>(null);
  // Code search (coding view only); the files search lives in the store so
  // the left bar and the center Files table share it.
  const [query, setQuery] = useState("");
  const fileQuery = useProjectStore((s) => s.fileQuery);
  const setFileQuery = useProjectStore((s) => s.setFileQuery);
  const [colorMenu, setColorMenu] = useState<{ item: CodeTreeItem; x: number; y: number } | null>(null);
  const [palette, setPalette] = useState<string[]>([]);
  /** "Merge into…" submenu opened from a context menu. */
  const [mergeMenu, setMergeMenu] = useState<{
    kind: "code" | "category";
    item: CodeTreeItem;
    x: number;
    y: number;
    search: string;
  } | null>(null);
  // Code sets (MAXQDA-style named subsets of codes): the set list, the
  // select's active entry, the APPLIED filter (client-side tree visibility)
  // and the manage/membership-editor popups.
  const [codeSets, setCodeSets] = useState<CodeSetSummary[]>([]);
  const [activeSetId, setActiveSetId] = useState<number | null>(null);
  const [appliedSet, setAppliedSet] = useState<{ id: number; name: string; cids: Set<number> } | null>(null);
  const [manageMenu, setManageMenu] = useState<{ x: number; y: number } | null>(null);
  const [membersEditor, setMembersEditor] = useState<{ set: CodeSetSummary; members: Set<number> } | null>(null);

  const sources = useProjectStore((s) => s.sources);
  const codeTree = useProjectStore((s) => s.codeTree);
  const projectOpen = useProjectStore((s) => s.projectOpen);
  
  const setView = useProjectStore((s) => s.setView);
  const selectCode = useProjectStore((s) => s.selectCode);
  const selectFile = useProjectStore((s) => s.selectFile);
  const activeCodeId = useProjectStore((s) => s.activeCodeId);
  const setActiveCode = useProjectStore((s) => s.setActiveCode);
  const hiddenCodes = useProjectStore((s) => s.hiddenCodes);
  const toggleHiddenCode = useProjectStore((s) => s.toggleHiddenCode);
  const view = useProjectStore((s) => s.view);

  // Refresh the set list whenever a project opens/closes. The applied
  // filter is a client-side snapshot and is dropped on close.
  useEffect(() => {
    if (!projectOpen) {
      setCodeSets([]);
      setActiveSetId(null);
      setAppliedSet(null);
      return;
    }
    listCodeSets()
      .then((sets) => {
        setCodeSets(sets);
        setActiveSetId((prev) =>
          prev != null && sets.some((s) => s.id === prev) ? prev : (sets[0]?.id ?? null),
        );
      })
      .catch((e) => {
        const detail = e instanceof Error ? e.message : t("codeSets.loadError");
        setToolbarError(detail);
      });
  }, [projectOpen, t]);

  useEffect(() => {
    if (!menu && !mergeMenu && !colorMenu && !manageMenu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenu(null);
        setMergeMenu(null);
        setColorMenu(null);
        setManageMenu(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menu, mergeMenu, colorMenu, manageMenu]);

  const groups = useMemo(() => {
    const g: Record<string, Source[]> = {
      "Text documents": [],
      "PDF documents": [],
      Images: [],
      Audio: [],
      Video: [],
    };
    for (const s of sources) {
      const key = isPdf(s.name)
        ? "PDF documents"
        : s.media_type === "text"
          ? "Text documents"
          : s.media_type === "image"
            ? "Images"
            : s.media_type === "audio"
              ? "Audio"
              : "Video";
      g[key].push(s);
    }
    return g;
  }, [sources]);

  const treeItems = useMemo(() => {
    const byParent = new Map<string, CodeTreeItem[]>();
    for (const item of codeTree) {
      const parentKey =
        item.parent_id == null
          ? "root"
          : item.kind === "category" || !item.subcode
            ? `cat:${item.parent_id}`
            : `code:${item.parent_id}`;
      const list = byParent.get(parentKey) ?? [];
      list.push(item);
      byParent.set(parentKey, list);
    }
    return byParent;
  }, [codeTree]);

  /** When a code set is applied: the tree keys (``kind:id``) that stay
   *  visible. Codes outside the set are pruned; categories survive only
   *  when at least one visible code lives in their subtree. Purely a
   *  client-side view state — nothing is deleted. */
  const filteredKeys = useMemo(() => {
    if (!appliedSet) return null;
    const visible = new Set<string>();
    const walk = (parentKey: string): boolean => {
      let anyVisible = false;
      for (const item of treeItems.get(parentKey) ?? []) {
        if (item.kind === "category") {
          if (walk(`cat:${item.id}`)) {
            visible.add(`cat:${item.id}`);
            anyVisible = true;
          }
        } else if (appliedSet.cids.has(item.id)) {
          visible.add(`code:${item.id}`);
          anyVisible = true;
        }
      }
      return anyVisible;
    };
    walk("root");
    return visible;
  }, [treeItems, appliedSet]);

  const flatMatches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return codeTree.filter(
      (item) =>
        item.name.toLowerCase().includes(q) &&
        (!filteredKeys || filteredKeys.has(`${item.kind}:${item.id}`)),
    );
  }, [codeTree, query, filteredKeys]);

  /** Depth-first flattened tree order (used for Tab-cycling the editor). */
  const flatTree = useMemo(() => {
    const out: CodeTreeItem[] = [];
    const walk = (parentKey: string) => {
      for (const item of treeItems.get(parentKey) ?? []) {
        out.push(item);
        const childKey = item.kind === "category" ? `cat:${item.id}` : `code:${item.id}`;
        walk(childKey);
      }
    };
    walk("root");
    return out;
  }, [treeItems]);

  /** Move the inline editor to the next row of the same list (Tab key).
   *  The tree is namespace-aware: in legacy projects category and code ids
   *  can collide, so a bare id lookup could land on the wrong row. */
  function editNext(kind: "code" | "category" | "file", currentId: number) {
    const list = kind === "file" ? sources : flatTree;
    const idx = list.findIndex(
      (x) => x.id === currentId && (kind === "file" || (x as CodeTreeItem).kind === kind),
    );
    if (idx < 0 || idx + 1 >= list.length) {
      setEditing(null);
      return;
    }
    const next = list[idx + 1];
    if (kind === "file") {
      setEditing({ kind: "file", id: next.id });
      return;
    }
    // Expand every ancestor of the next row so the editor is actually
    // visible (Tab must never vanish into a collapsed subtree).
    const ancestors: string[] = [];
    const walk = (parentKey: string, depth: number): boolean => {
      if (depth > MAX_TREE_DEPTH) return false;
      for (const item of treeItems.get(parentKey) ?? []) {
        if (item.id === next.id && (item as CodeTreeItem).kind === kind) return true;
        const childKey =
          (item as CodeTreeItem).kind === "category" ? `cat:${item.id}` : `code:${item.id}`;
        if (walk(childKey, depth + 1)) {
          if (parentKey !== "root") ancestors.push(parentKey);
          return true;
        }
      }
      return false;
    };
    walk("root", 0);
    if (ancestors.length > 0) {
      setCollapsed((c) => {
        const copy = { ...c };
        for (const key of ancestors) delete copy[key];
        return copy;
      });
    }
    setEditing({
      kind: (next as CodeTreeItem).kind === "category" ? "category" : "code",
      id: next.id,
    });
  }

  /* ------------------------------------------------------------------ */
  /* CRUD actions                                                        */
  /* ------------------------------------------------------------------ */

  async function createCode(catid: number | null, supercid: number | null = null) {
    setToolbarError(null);
    try {
      // Create immediately with a placeholder name and hand over to the
      // inline editor — no system prompt.
      const res = await api.createCode(t("sidebar.untitled"), { catid, supercid });
      await useProjectStore.getState().refreshProject();
      await selectCode(res.cid);
      setEditing({ kind: "code", id: res.cid });
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("codePicker.createError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  async function createCategory(supercatid: number | null) {
    setToolbarError(null);
    try {
      const res = await api.createCategory(t("sidebar.untitled"), { supercatid });
      await useProjectStore.getState().refreshProject();
      setEditing({ kind: "category", id: res.catid });
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("sidebar.createCategoryError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  /** Persist an inline-edit rename (codes, categories or files). The editor
   *  closes synchronously so the Tab flow can move it to the next row. */
  async function saveRename(
    kind: "code" | "category" | "file",
    id: number,
    name: string,
  ) {
    setEditing(null);
    setToolbarError(null);
    try {
      if (kind === "file") {
        await api.patchSource(id, { name });
        await useProjectStore.getState().refreshProject();
        toast.success(t("files.renamed", { name }));
      } else if (kind === "code") {
        await api.patchCode(id, { name });
        await useProjectStore.getState().refreshProject();
        toast.success(t("sidebar.codeRenamed", { name }));
      } else {
        await api.patchCategory(id, { name });
        await useProjectStore.getState().refreshProject();
        toast.success(t("sidebar.categoryRenamed", { name }));
      }
    } catch (e) {
      const detail =
        kind === "file"
          ? e instanceof Error
            ? e.message
            : t("files.renameError")
          : e instanceof Error
            ? e.message
            : t("sidebar.renameCodeError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  /** Enter inline edit mode for a row (also used by the context menu). */
  function startEdit(item: CodeTreeItem | Source, kind: "code" | "category" | "file") {
    if (query.trim()) setQuery(""); // ensure the row is visible in the tree
    setEditing({ kind, id: item.id });
  }

  /** Assign a palette colour to a code (right-click → Colour). */
  async function patchCodeColor(item: CodeTreeItem, color: string) {
    setToolbarError(null);
    try {
      await api.patchCode(item.id, { color });
      await useProjectStore.getState().refreshProject();
      toast.success(t("sidebar.codeColourSet"));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("sidebar.colourError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  /** Enter inline edit mode for a code row (no system prompt). */
  function renameCode(item: CodeTreeItem) {
    startEdit(item, "code");
  }

  async function editCodeMemo(item: CodeTreeItem) {
    // The details panel (right bar) hosts the inline memo editor; open it
    // straight in edit mode.
    useProjectStore.getState().setInspectorMemoEdit(true);
    void selectCode(item.id);
  }

  /** Add an annotation to the given file: opens the Inspector's inline
   *  new-annotation editor (no system prompt). */
  function addAnnotation(fid: number) {
    useProjectStore.getState().setInspectorNewAnnotation(true);
    void selectFile(fid);
  }

  /** Merge ``source`` into ``target`` after a confirm dialog (drop-onto and
   *  the "Merge into…" submenu share this path). */
  async function confirmAndMerge(source: CodeTreeItem, target: CodeTreeItem) {
    if (!window.confirm(t("tree.mergeConfirm", { name: source.name, target: target.name }))) return;
    setToolbarError(null);
    try {
      if (source.kind === "category") {
        await api.mergeCategory(source.id, target.id);
        clearInspectorIfSelected(source);
        await useProjectStore.getState().refreshProject();
        toast.success(t("sidebar.categoryMerged", { name: source.name }));
      } else {
        await api.mergeCode(source.id, target.id);
        clearInspectorIfSelected(source);
        await useProjectStore.getState().refreshProject();
        toast.success(t("sidebar.codeMerged", { name: source.name }));
      }
    } catch (e) {
      const detail =
        e instanceof Error
          ? friendlyTreeError(t, e.message)
          : source.kind === "category"
            ? t("sidebar.mergeCategoryError")
            : t("sidebar.mergeCodeError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  /** Open the "Merge into…" submenu listing every other node of the same
   *  kind (closes the context menu it was opened from). */
  function openMergeMenu(item: CodeTreeItem, kind: "code" | "category", x: number, y: number) {
    setMenu(null);
    setMergeMenu({ kind, item, x, y, search: "" });
  }

  function clearInspectorIfSelected(item: CodeTreeItem) {
    const sel = useProjectStore.getState().inspectorSelection;
    if (sel?.kind === "code" && sel.id === item.id) {
      useProjectStore.getState().clearInspector();
    }
  }

  /** Turn a backend tree-mutation error into a human-friendly line. Known
   *  details (matched on the raw detail, so older backends still map) become
   *  i18n messages; everything else drops the "API error <status> on <path>:"
   *  prefix and shows the backend's own detail text. */
  function friendlyTreeError(translator: (key: string) => string, message: string): string {
    const detail = message.replace(/^API error \d+ on [^:]+: /, "");
    switch (detail) {
      case "code is already at the top level":
      case "category is already at the top level":
        return translator("tree.promoteTopLevel");
      case "no previous sibling to demote under":
        return translator("tree.demoteNoSibling");
      default:
        return detail;
    }
  }

  /** Enter inline edit mode for a file row (no system prompt). */
  function renameFile(source: Source) {
    startEdit(source, "file");
  }

  async function editFileMemo(source: Source) {
    // The details panel (right bar) hosts the inline memo editor; open it
    // straight in edit mode.
    useProjectStore.getState().setInspectorMemoEdit(true);
    void selectFile(source.id);
  }

  async function deleteFile(source: Source) {
    if (!window.confirm(t("files.deleteConfirm", { name: source.name }))) return;
    setToolbarError(null);
    try {
      await api.deleteSource(source.id);
      await useProjectStore.getState().refreshProject();
      toast.success(t("files.deleted", { name: source.name }));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("files.deleteError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  async function assignFileToCase(source: Source) {
    const name = window.prompt(t("files.assignCasePrompt", { name: source.name }));
    if (name === null) return;
    const trimmed = name.trim();
    if (!trimmed) return;
    setToolbarError(null);
    try {
      const casesList = await api.cases();
      const match = casesList.find((c) => c.name === trimmed);
      if (!match) {
        const detail = t("files.assignCaseNotFound", { name: trimmed });
        setToolbarError(detail);
        toast.error(detail);
        return;
      }
      await api.linkFileToCase(match.caseid, source.id);
      toast.success(t("files.assignCaseDone", { file: source.name, case: match.name }));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("files.assignCaseError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  async function deleteCodeItem(item: CodeTreeItem) {
    if (!window.confirm(t("sidebar.deleteCodeConfirm", { name: item.name }))) return;
    setToolbarError(null);
    try {
      await api.deleteCode(item.id);
      clearInspectorIfSelected(item);
      await useProjectStore.getState().refreshProject();
      toast.success(t("sidebar.codeDeleted", { name: item.name }));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("sidebar.deleteCodeError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  async function deleteCategoryItem(item: CodeTreeItem) {
    if (!window.confirm(t("sidebar.deleteCategoryConfirm", { name: item.name }))) return;
    setToolbarError(null);
    try {
      await api.deleteCategory(item.id);
      clearInspectorIfSelected(item);
      await useProjectStore.getState().refreshProject();
      toast.success(t("sidebar.categoryDeleted", { name: item.name }));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("sidebar.deleteCategoryError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  async function removeSubcode(item: CodeTreeItem) {
    setToolbarError(null);
    try {
      await api.patchCode(item.id, { supercid: null });
      await useProjectStore.getState().refreshProject();
      toast.success(t("sidebar.subcodeRemoved"));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("sidebar.subcodeRemovalError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  /** Move a code/category one level UP (Word-list style). */
  async function promoteItem(item: CodeTreeItem) {
    setToolbarError(null);
    try {
      if (item.kind === "category") await api.promoteCategory(item.id);
      else await api.promoteCode(item.id);
      await useProjectStore.getState().refreshProject();
    } catch (e) {
      const detail = e instanceof Error ? friendlyTreeError(t, e.message) : t("tree.promoteFail");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  /** Move a code/category one level DOWN (Word-list style). */
  async function demoteItem(item: CodeTreeItem) {
    setToolbarError(null);
    try {
      if (item.kind === "category") await api.demoteCategory(item.id);
      else await api.demoteCode(item.id);
      await useProjectStore.getState().refreshProject();
    } catch (e) {
      const detail = e instanceof Error ? friendlyTreeError(t, e.message) : t("tree.demoteFail");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  /* ------------------------------------------------------------------ */
  /* Drag & drop rearranging                                             */
  /* ------------------------------------------------------------------ */

  /** Move a dragged node through the backend, then refresh the tree. */
  async function moveDragged(drag: DragNode, opts: CodeMoveOpts | CategoryMoveOpts) {
    setToolbarError(null);
    try {
      if (drag.kind === "category") await api.moveCategory(drag.id, opts as CategoryMoveOpts);
      else await api.moveCode(drag.id, opts as CodeMoveOpts);
      await useProjectStore.getState().refreshProject();
    } catch (e) {
      const detail = e instanceof Error ? friendlyTreeError(t, e.message) : t("tree.moveFail");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  /** A category can only nest in categories; a code nests in a category or
   *  as a sub-code — never under its own descendant (cycle guard). */
  function canDropInto(drag: DragNode, target: CodeTreeItem): boolean {
    if (drag.kind === "category" && target.kind !== "category") return false;
    return !drag.subtree.has(`${target.kind}:${target.id}`);
  }

  /** before/after land in the target's sibling group — only same-kind rows
   *  can anchor a sibling slot, and never inside the dragged node's own
   *  subtree (the backend would reject that cycle anyway). */
  function canOrderSibling(drag: DragNode, target: CodeTreeItem): boolean {
    if (drag.kind !== target.kind) return false;
    return !drag.subtree.has(`${target.kind}:${target.id}`);
  }

  /** Merge-onto needs a same-kind target outside the dragged subtree. */
  function canDropMerge(drag: DragNode, target: CodeTreeItem): boolean {
    if (drag.kind !== target.kind) return false;
    return !drag.subtree.has(`${target.kind}:${target.id}`);
  }

  /** Resolve the drop zone from the pointer position: the top/bottom bands
   *  give the before/after insertion lines, the left indent gutter gives
   *  the "into" (make child) zone, the row body gives the merge target.
   *  Must run inside the event handler itself: React nulls the synthetic
   *  event's ``currentTarget`` once the handler returns, so calling this
   *  from a state-updater callback (which runs at render time) would read
   *  a null rect and crash the tree. */
  function computeDropZone(
    rect: DOMRect,
    clientX: number,
    clientY: number,
    item: CodeTreeItem,
    depth: number,
    drag: DragNode,
  ): DropZone | null {
    if (drag.kind === item.kind && drag.id === item.id) return null;
    const y = (clientY - rect.top) / Math.max(1, rect.height);
    const x = clientX - rect.left;
    const key = `${item.kind}:${item.id}`;
    if (y < 0.25) return canOrderSibling(drag, item) ? { mode: "before", key } : null;
    if (y > 0.75) return canOrderSibling(drag, item) ? { mode: "after", key } : null;
    if (x < 8 + depth * 16 + 28) {
      return canDropInto(drag, item) ? { mode: "into", key } : null;
    }
    return canDropMerge(drag, item) ? { mode: "merge", key } : null;
  }

  /* --- Pointer-based tree drag ------------------------------------------
     HTML5 drag & drop repeatedly failed to deliver drops in the packaged
     WebView2 (drag events cancelled, empty dataTransfer types, render-phase
     event nulling). Pointer events behave identically in every engine and on
     touch: pointerdown on a row arms the drag, a 6px movement starts it, the
     zone is recomputed from elementFromPoint on every move, pointerup
     commits. The OS-file drop on the files leftbar stays HTML5 (only a
     native file drag can provide dataTransfer.files). */

  function handleRowPointerDown(e: ReactPointerEvent<HTMLDivElement>, item: CodeTreeItem) {
    if (e.button !== 0 || (e.pointerType === "mouse" && e.ctrlKey)) return;
    // Only editable elements opt out — the row body IS a button (the code
    // name), so rejecting buttons here would make the drag unarmable.
    // The click that follows a completed drag is suppressed separately.
    if ((e.target as HTMLElement).closest("input, select, textarea")) return;
    pointerDownRef.current = { item, x: e.clientX, y: e.clientY };
    dragStartedRef.current = false;
  }

  function handleTreePointerMove(e: ReactPointerEvent<HTMLDivElement>) {
    const down = pointerDownRef.current;
    if (!down) return;
    if (!dragStartedRef.current) {
      const dx = e.clientX - down.x;
      const dy = e.clientY - down.y;
      if (dx * dx + dy * dy < 36) return; // 6px threshold — below it it's a click
      dragStartedRef.current = true;
      suppressClickRef.current = true;
      dragNode = { kind: down.item.kind, id: down.item.id, subtree: subtreeKeysOf(down.item) };
      setDraggingKey(`${down.item.kind}:${down.item.id}`);
      try {
        treeContainerRef.current?.setPointerCapture(e.pointerId);
      } catch {
        /* capture is best-effort */
      }
      document.body.style.userSelect = "none";
    }
    const el = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null;
    const row = el?.closest?.("[data-tree-row]") as HTMLElement | null;
    if (!row || !dragNode) {
      setDropZone(null);
      return;
    }
    const key = row.dataset.treeRow ?? "";
    const depth = Number(row.dataset.treeDepth ?? 0);
    const item = codeTree.find((i) => `${i.kind}:${i.id}` === key);
    const rect = row.getBoundingClientRect();
    const next =
      item && rect ? computeDropZone(rect, e.clientX, e.clientY, item, depth, dragNode) : null;
    setDropZone((prev) => (prev?.mode === next?.mode && prev?.key === next?.key ? prev : next));
  }

  function handleTreePointerUp(e: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragNode;
    const started = dragStartedRef.current;
    pointerDownRef.current = null;
    dragStartedRef.current = false;
    if (drag && started) {
      const el = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null;
      const row = el?.closest?.("[data-tree-row]") as HTMLElement | null;
      let zone: DropZone | null = null;
      if (row) {
        const key = row.dataset.treeRow ?? "";
        const depth = Number(row.dataset.treeDepth ?? 0);
        const item = codeTree.find((i) => `${i.kind}:${i.id}` === key);
        const rect = row.getBoundingClientRect();
        zone = item && rect ? computeDropZone(rect, e.clientX, e.clientY, item, depth, drag) : null;
      }
      finishDrop(drag, zone);
    }
    try {
      treeContainerRef.current?.releasePointerCapture(e.pointerId);
    } catch {
      /* noop */
    }
    document.body.style.userSelect = "";
  }

  function handleTreePointerCancel() {
    pointerDownRef.current = null;
    dragStartedRef.current = false;
    dragNode = null;
    setDraggingKey(null);
    setDropZone(null);
    document.body.style.userSelect = "";
  }

  /** Consume the click that follows a completed drag (row onClick fires
   *  after pointerup; a drag must not toggle the active code). */
  function consumeDragClick(): boolean {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return true;
    }
    return false;
  }

  /** Commit a resolved drop (move or merge); clears the drag state. */
  function finishDrop(drag: DragNode, zone: DropZone | null) {
    dragNode = null;
    setDraggingKey(null);
    setDropZone(null);
    if (!zone) return;
    const item = codeTree.find((i) => `${i.kind}:${i.id}` === zone.key);
    if (!item) return;
    if (zone.mode === "before" || zone.mode === "after") {
      const before = zone.mode === "before";
      if (drag.kind === "category") {
        void moveDragged(drag, before ? { before_catid: item.id } : { after_catid: item.id });
      } else {
        void moveDragged(drag, before ? { before_cid: item.id } : { after_cid: item.id });
      }
    } else if (zone.mode === "into") {
      if (drag.kind === "category") void moveDragged(drag, { supercatid: item.id });
      else if (item.kind === "category") void moveDragged(drag, { parent_catid: item.id });
      else void moveDragged(drag, { supercid: item.id });
    } else {
      // Merge-on-drop: dropped onto the row body of a same-kind node.
      const source = codeTree.find((i) => i.kind === drag.kind && i.id === drag.id);
      const target = codeTree.find((i) => i.kind === item.kind && i.id === item.id);
      if (source && target) void confirmAndMerge(source, target);
    }
  }

  /* ------------------------------------------------------------------ */
  /* OS file drop on the files leftbar (same import path as FileManager) */
  /* ------------------------------------------------------------------ */

  /** Import dropped OS files one by one through the API (409 = duplicate). */
  async function importDroppedFiles(files: File[]) {
    if (files.length === 0) return;
    setToolbarError(null);
    useProjectStore.getState().setImportState({ done: 0, total: files.length });
    const dupes: string[] = [];
    let failed: string | null = null;
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      try {
        await api.importSource(file);
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          dupes.push(file.name);
        } else {
          failed = e instanceof Error ? e.message : t("files.importFailed", { name: file.name });
        }
      }
      useProjectStore.getState().setImportState({ done: i + 1, total: files.length });
    }
    useProjectStore.getState().setImportState(null);
    if (dupes.length > 0) {
      toast.error(
        t("files.skipped", { names: dupes.map((n) => t("files.duplicate", { name: n })).join(", ") }),
      );
    }
    if (failed) toast.error(failed);
    await useProjectStore.getState().refreshProject();
  }

  /** The files leftbar is a drop target for OS files (documents, PDFs,
   *  images, audio, video) — everything goes through api.importSource. */
  function handleFileDragOver(e: ReactDragEvent<HTMLDivElement>) {
    if (e.dataTransfer.types.includes("Files")) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      setFileDropActive(true);
    }
  }

  function handleFileDragLeave(e: ReactDragEvent<HTMLDivElement>) {
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFileDropActive(false);
  }

  function handleFileDrop(e: ReactDragEvent<HTMLDivElement>) {
    e.preventDefault();
    setFileDropActive(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) void importDroppedFiles(files);
  }

  /** All ``kind:id`` keys of the subtree rooted at ``item`` (inclusive) —
   *  the cycle-guard lookup for drop zones. */
  function subtreeKeysOf(item: CodeTreeItem): Set<string> {
    const keys = new Set<string>();
    const stack: CodeTreeItem[] = [item];
    let depth = 0;
    while (stack.length > 0 && depth <= MAX_TREE_DEPTH) {
      depth += 1;
      const cur = stack.pop()!;
      keys.add(`${cur.kind}:${cur.id}`);
      const childKey = cur.kind === "category" ? `cat:${cur.id}` : `code:${cur.id}`;
      for (const child of treeItems.get(childKey) ?? []) stack.push(child);
    }
    return keys;
  }

  /* ------------------------------------------------------------------ */
  /* Code sets                                                           */
  /* ------------------------------------------------------------------ */

  /** Apply the active set: snapshot its members and filter the tree. */
  async function applyCodeSet() {
    if (activeSetId == null) return;
    setToolbarError(null);
    try {
      const detail = await getCodeSet(activeSetId);
      const set = codeSets.find((s) => s.id === activeSetId);
      const name = set?.name ?? `${activeSetId}`;
      setAppliedSet({ id: activeSetId, name, cids: new Set(detail.members.map((m) => m.cid)) });
      toast.success(t("codeSets.applied", { name }));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("codeSets.applyError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  async function createSet() {
    const name = window.prompt(t("codeSets.createPrompt"));
    if (name == null) return;
    const trimmed = name.trim();
    if (!trimmed) return;
    setToolbarError(null);
    try {
      const created = await createCodeSet(trimmed);
      setCodeSets((prev) => [...prev, created]);
      setActiveSetId(created.id);
      toast.success(t("codeSets.created", { name: trimmed }));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("codeSets.createError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  async function renameActiveSet() {
    const set = codeSets.find((s) => s.id === activeSetId);
    if (!set) return;
    const name = window.prompt(t("codeSets.renamePrompt", { name: set.name }), set.name);
    if (name == null) return;
    const trimmed = name.trim();
    if (!trimmed || trimmed === set.name) return;
    setToolbarError(null);
    try {
      const updated = await renameCodeSet(set.id, trimmed);
      setCodeSets((prev) => prev.map((s) => (s.id === set.id ? { ...s, name: updated.name } : s)));
      if (appliedSet?.id === set.id) setAppliedSet({ ...appliedSet, name: updated.name });
      toast.success(t("codeSets.renamed", { name: trimmed }));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("codeSets.renameError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  async function deleteActiveSet() {
    const set = codeSets.find((s) => s.id === activeSetId);
    if (!set) return;
    if (!window.confirm(t("codeSets.deleteConfirm", { name: set.name }))) return;
    setToolbarError(null);
    try {
      await deleteCodeSet(set.id);
      setCodeSets((prev) => prev.filter((s) => s.id !== set.id));
      if (appliedSet?.id === set.id) setAppliedSet(null);
      setActiveSetId(null);
      toast.success(t("codeSets.deleted", { name: set.name }));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("codeSets.deleteError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  /** Open the membership editor for the active set (fetches its members). */
  async function openMembersEditor() {
    const set = codeSets.find((s) => s.id === activeSetId);
    if (!set) return;
    setToolbarError(null);
    try {
      const detail = await getCodeSet(set.id);
      setMembersEditor({ set, members: new Set(detail.members.map((m) => m.cid)) });
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("codeSets.loadError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  /** Sync the editor's checked codes: add/remove the diff, refresh counts,
   *  and re-snapshot the filter when the applied set was edited. */
  async function saveMembers(cids: number[]) {
    if (!membersEditor) return;
    const { set, members } = membersEditor;
    const toAdd = cids.filter((c) => !members.has(c));
    const toRemove = [...members].filter((c) => !cids.includes(c));
    if (toAdd.length > 0) await addCodeSetMembers(set.id, toAdd);
    if (toRemove.length > 0) await removeCodeSetMembers(set.id, toRemove);
    const updated = await listCodeSets();
    setCodeSets(updated);
    if (appliedSet?.id === set.id) {
      const detail = await getCodeSet(set.id);
      setAppliedSet({
        id: set.id,
        name: set.name,
        cids: new Set(detail.members.map((m) => m.cid)),
      });
    }
    setMembersEditor(null);
    toast.success(t("codeSets.membersSaved"));
  }

  /* ------------------------------------------------------------------ */
  /* Context menu                                                        */
  /* ------------------------------------------------------------------ */

  const menuActions: MenuAction[] = [];
  if (menu) {
    const close = (fn: () => void) => () => {
      setMenu(null);
      fn();
    };
    if (menu.kind === "file") {
      menuActions.push(
        {
          label: t("sidebar.menuDetails"),
          icon: <Info size={14} aria-hidden />,
          run: close(() => void selectFile(menu.source.id)),
        },
        {
          label: t("sidebar.menuAddAnnotation"),
          icon: <StickyNote size={14} aria-hidden />,
          run: close(() => void addAnnotation(menu.source.id)),
        },
        {
          label: t("files.menuRename"),
          icon: <Pencil size={14} aria-hidden />,
          run: close(() => void renameFile(menu.source)),
        },
        {
          label: t("files.menuEditMemo"),
          icon: <StickyNote size={14} aria-hidden />,
          run: close(() => void editFileMemo(menu.source)),
        },
        {
          label: t("files.menuAssignCase"),
          icon: <UserRound size={14} aria-hidden />,
          run: close(() => void assignFileToCase(menu.source)),
        },
        {
          label: t("common.delete"),
          icon: <Trash2 size={14} aria-hidden />,
          danger: true,
          run: close(() => void deleteFile(menu.source)),
        },
      );
    } else if (menu.item.kind === "category") {
      menuActions.push(
        {
          label: t("sidebar.menuAddCode"),
          icon: <Plus size={14} aria-hidden />,
          run: close(() => void createCode(menu.item.id)),
        },
        {
          label: t("sidebar.menuAddSubcategory"),
          icon: <FolderPlus size={14} aria-hidden />,
          run: close(() => void createCategory(menu.item.id)),
        },
        {
          label: t("sidebar.menuMergeInto"),
          icon: <GitMerge size={14} aria-hidden />,
          run: close(() => openMergeMenu(menu.item, "category", menu.x, menu.y)),
        },
        {
          label: t("tree.promote"),
          icon: <IndentDecrease size={14} aria-hidden />,
          run: close(() => void promoteItem(menu.item)),
        },
        {
          label: t("tree.demote"),
          icon: <IndentIncrease size={14} aria-hidden />,
          run: close(() => void demoteItem(menu.item)),
        },
      );
    } else {
      menuActions.push(
        {
          label: t("sidebar.menuDetails"),
          icon: <Info size={14} aria-hidden />,
          run: close(() => void selectCode(menu.item.id)),
        },
        {
          label: t("sidebar.menuAddCodeHere"),
          icon: <Plus size={14} aria-hidden />,
          run: close(() => void createCode(menu.item.parent_id)),
        },
        {
          label: t("sidebar.menuAddSubcode"),
          icon: <Plus size={14} aria-hidden />,
          run: close(() => void createCode(null, menu.item.id)),
        },
        {
          label: t("sidebar.menuColour"),
          icon: <Palette size={14} aria-hidden />,
          run: () => {
            void api
              .colorScheme()
              .then((s) => setPalette(s.colors))
              .catch(() => setPalette([]));
            setColorMenu({ item: menu.item, x: menu.x, y: menu.y });
          },
        },
        {
          label: t("sidebar.menuMemo"),
          icon: <StickyNote size={14} aria-hidden />,
          run: close(() => void editCodeMemo(menu.item)),
        },
        {
          label: t("sidebar.menuMergeInto"),
          icon: <GitMerge size={14} aria-hidden />,
          run: close(() => openMergeMenu(menu.item, "code", menu.x, menu.y)),
        },
        ...(menu.item.subcode
          ? [
              {
                label: t("sidebar.menuRemoveFromParent"),
                icon: <Unlink size={14} aria-hidden />,
                run: close(() => void removeSubcode(menu.item)),
              },
            ]
          : []),
        {
          label: t("tree.promote"),
          icon: <IndentDecrease size={14} aria-hidden />,
          run: close(() => void promoteItem(menu.item)),
        },
        {
          label: t("tree.demote"),
          icon: <IndentIncrease size={14} aria-hidden />,
          run: close(() => void demoteItem(menu.item)),
        },
      );
    }
  }

  let menuStyle: { left: number; top: number } | undefined;
  if (menu) {
    const pos = clampToViewport(menu.x, menu.y, MENU_WIDTH, menuActions.length * 32 + 8);
    menuStyle = { left: pos.x, top: pos.y };
  }

  /** Flat code list for the membership editor: every code with its
   *  category/sub-code path label (``A / B / Code``), sorted by label.
   *  Cycle-guarded like the backend tree (legacy projects can have
   *  self-references). */
  const codeSetOptions = useMemo(() => {
    const cats = new Map<number, CodeTreeItem>();
    const codes = new Map<number, CodeTreeItem>();
    for (const item of codeTree) {
      if (item.kind === "category") cats.set(item.id, item);
      else codes.set(item.id, item);
    }
    const pathOf = (item: CodeTreeItem): string => {
      const parts: string[] = [];
      const seen = new Set<string>();
      let cur: CodeTreeItem | undefined = item;
      while (cur && !seen.has(`${cur.kind}:${cur.id}`)) {
        seen.add(`${cur.kind}:${cur.id}`);
        parts.push(cur.name);
        if (cur.kind === "category" || !cur.subcode) {
          cur = cur.parent_id != null ? cats.get(cur.parent_id) : undefined;
        } else {
          cur = cur.parent_id != null ? codes.get(cur.parent_id) : undefined;
        }
      }
      parts.reverse();
      return parts.join(" / ");
    };
    return codeTree
      .filter((item) => item.kind === "code")
      .map((item) => ({ cid: item.id, label: pathOf(item), color: item.color }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [codeTree]);

  /** Candidates for the "Merge into…" submenu: every other node of the same
   *  kind as the source, optionally filtered by the search box. */
  const mergeCandidates = mergeMenu
    ? codeTree.filter((i) => i.kind === mergeMenu.kind && i.id !== mergeMenu.item.id)
    : [];
  const mergeFiltered = (() => {
    const q = mergeMenu?.search.trim().toLowerCase();
    if (!q) return mergeCandidates;
    return mergeCandidates.filter((c) => c.name.toLowerCase().includes(q));
  })();

  /* ------------------------------------------------------------------ */
  /* Rendering                                                           */
  /* ------------------------------------------------------------------ */

  const MAX_TREE_DEPTH = 64;

  function renderCodeNode(parent: string, depth: number) {
    const items = (treeItems.get(parent) ?? []).filter(
      (item) => !filteredKeys || filteredKeys.has(`${item.kind}:${item.id}`),
    );
    return items.map((item) => {
      const key = `${item.kind}:${item.id}`;
      const isCollapsed = collapsed[key] ?? false;
      const childrenKey = item.kind === "category" ? `cat:${item.id}` : `code:${item.id}`;
      const hasChildren = (treeItems.get(childrenKey)?.length ?? 0) > 0;
      const editingThis =
        editing !== null && editing.id === item.id && editing.kind === item.kind;
      const rowStyle = { paddingLeft: `${8 + depth * 16}px` };
      if (editingThis) {
        return (
          <div key={key} style={rowStyle} className="flex w-full items-center gap-1 px-2 py-0.5">
            <InlineNameEdit
              value={item.name}
              placeholder={t("sidebar.renamePrompt", { name: item.name })}
              onSave={(name) => {
                void saveRename(editing.kind as "code" | "category", item.id, name);
              }}
              onCancel={() => setEditing(null)}
              onTab={() => editNext(editing.kind as "code" | "category", item.id)}
            />
          </div>
        );
      }
      return (
        <div key={key} className="relative">
          {/* Insertion lines (before/after drop zones) */}
          {dropZone?.mode === "before" && dropZone.key === key && (
            <div
              className="pointer-events-none absolute inset-x-1 top-0 z-10 h-0.5 rounded-full bg-accent"
              aria-hidden
            />
          )}
          {dropZone?.mode === "after" && dropZone.key === key && (
            <div
              className="pointer-events-none absolute inset-x-1 bottom-0 z-10 h-0.5 rounded-full bg-accent"
              aria-hidden
            />
          )}
          {/* The row box is the pointer-drag source (the whole row incl. its
              edges arms the drag; interactive children — buttons, inputs —
              never start one). The drop indicator + merge highlight render
              above, driven by the pointer-move zone computation. */}
          <div
            className="group flex items-center"
            data-tree-row={key}
            data-tree-depth={depth}
            onPointerDown={(e) => handleRowPointerDown(e, item)}
          >
            <button
            type="button"
            onClick={() => {
              if (consumeDragClick()) return;
              if (item.kind === "category") {
                if (hasChildren) setCollapsed((c) => ({ ...c, [key]: !isCollapsed }));
              } else {
                // Clicking a code makes it the ACTIVE code (any pending
                // selection in the open coder is coded with it immediately),
                // shows its details, AND toggles hiding its codings in the
                // open coder (click again to show them).
                setActiveCode(item.id);
                void selectCode(item.id);
                window.dispatchEvent(
                  new CustomEvent("qc:assign-code", { detail: { cid: item.id } }),
                );
                if (hasChildren) setCollapsed((c) => ({ ...c, [key]: !isCollapsed }));
              }
            }}
            onContextMenu={(e) => {
              e.preventDefault();
              setMenu({ kind: "code", x: e.clientX, y: e.clientY, item });
            }}
            className={`flex min-w-0 flex-1 items-center gap-1.5 rounded-sm px-2 py-1 text-left text-sm hover:bg-surface-higher ${
              item.kind === "code" && activeCodeId === item.id
                ? "bg-accent/15 text-accent"
                : ""
            } ${
              item.kind === "code" && hiddenCodes.includes(item.id)
                ? "opacity-40"
                : ""
            } ${
              dropZone?.key === key && dropZone.mode === "merge"
                ? "ring-2 ring-accent"
                : dropZone?.key === key && dropZone.mode === "into"
                  ? "bg-accent/10 ring-1 ring-accent"
                  : ""
            } ${draggingKey === key ? "opacity-50" : ""}`}
            style={rowStyle}
          >
            {item.kind === "category" ? (
              <>
                {hasChildren ? (
                  <FolderOpen size={14} className="shrink-0 text-text-secondary" aria-hidden />
                ) : (
                  <Folder size={14} className="shrink-0 text-text-secondary" aria-hidden />
                )}
              </>
            ) : (
              <>
                {hasChildren ? (
                  isCollapsed ? (
                    <ChevronRight size={14} className="shrink-0 text-text-secondary" aria-hidden />
                  ) : (
                    <ChevronDown size={14} className="shrink-0 text-text-secondary" aria-hidden />
                  )
                ) : (
                  <span className="inline-block w-3.5 shrink-0" aria-hidden />
                )}
                <span
                  className="inline-block h-3 w-3 shrink-0 rounded-sm border border-border hover:ring-1 hover:ring-accent"
                  style={{ backgroundColor: item.color ?? "#ccc" }}
                  onClick={(e) => {
                    // Clicking exactly the color rectangle toggles hiding
                    // this code's codings in the open coder.
                    e.stopPropagation();
                    toggleHiddenCode(item.id);
                  }}
                  title={t("sidebar.highlightCode")}
                  aria-hidden
                />
              </>
            )}
            <span className="truncate">{item.name}</span>
            {dropZone?.key === key && dropZone.mode === "into" && (
              <span className="ml-auto flex shrink-0 items-center gap-1 rounded-sm bg-accent px-1.5 py-0.5 text-[10px] font-medium text-[var(--qc-bg)]">
                <Plus size={10} aria-hidden />
                {t("tree.dropInto")}
              </span>
            )}
            {dropZone?.key === key && dropZone.mode === "merge" && (
              <span className="ml-auto flex shrink-0 items-center gap-1 rounded-sm bg-accent px-1.5 py-0.5 text-[10px] font-medium text-[var(--qc-bg)]">
                <GitMerge size={10} aria-hidden />
                {t("tree.dropMerge")}
              </span>
            )}
          </button>
          <span className="flex shrink-0 items-center gap-0.5 pr-1 opacity-0 transition-opacity group-hover:opacity-100 hover:opacity-100">
            <IconButton
              label={t("sidebar.renameFor", { name: item.name })}
              title={t("sidebar.renameFor", { name: item.name })}
              size="row"
              onClick={() => renameCode(item)}
            >
              <Pencil size={12} aria-hidden />
            </IconButton>
            <IconButton
              label={t("sidebar.deleteFor", { name: item.name })}
              title={t("common.delete")}
              size="row"
              className="hover:text-danger"
              onClick={() => {
                if (item.kind === "category") void deleteCategoryItem(item);
                else void deleteCodeItem(item);
              }}
            >
              <Trash2 size={12} aria-hidden />
            </IconButton>
          </span>
          </div>
          {hasChildren && !isCollapsed && depth < MAX_TREE_DEPTH && renderCodeNode(childrenKey, depth + 1)}
        </div>
      );
    });
  }

  const fileIcon = (mediaType: string) =>
    mediaType === "image" ? (
      <FileImage size={14} className="shrink-0 text-text-secondary" aria-hidden />
    ) : mediaType === "audio" || mediaType === "video" ? (
      <FileAudio size={14} className="shrink-0 text-text-secondary" aria-hidden />
    ) : (
      <FileText size={14} className="shrink-0 text-text-secondary" aria-hidden />
    );

  const groupLabels: Record<string, string> = {
    "Text documents": t("sidebar.groupText"),
    "PDF documents": t("sidebar.groupPdf"),
    Images: t("sidebar.groupImages"),
    Audio: t("sidebar.groupAudio"),
    Video: t("sidebar.groupVideo"),
  };

  function renderFileGroups() {
    const q = fileQuery.trim().toLowerCase();
    return (
      <>
        {Object.entries(groups).map(([group, items]) => {
          const visible = q ? items.filter((s) => s.name.toLowerCase().includes(q)) : items;
          if (visible.length === 0) return null;
          return (
            <div key={group}>
              <div className="px-2 py-1 text-xs font-medium text-text-secondary">
                {groupLabels[group] ?? group}
              </div>
              {visible.map((s) => {
                const editingThis = editing !== null && editing.kind === "file" && editing.id === s.id;
                if (editingThis) {
                  return (
                    <div key={s.id} className="flex w-full items-center gap-1 px-2 py-0.5">
                      <InlineNameEdit
                        value={s.name}
                        placeholder={t("files.renamePrompt", { name: s.name })}
                        onSave={(name) => void saveRename("file", s.id, name)}
                        onCancel={() => setEditing(null)}
                        onTab={() => editNext("file", s.id)}
                      />
                    </div>
                  );
                }
                return (
                  <div key={s.id}>
                    <div className="group flex items-center">
                      <button
                        type="button"
                        onClick={() => setView({ kind: "coding", sourceId: s.id })}
                        onContextMenu={(e) => {
                          e.preventDefault();
                          setMenu({ kind: "file", x: e.clientX, y: e.clientY, source: s });
                        }}
                        className="flex min-w-0 flex-1 items-center gap-1.5 rounded-sm px-2 py-1 text-left text-sm hover:bg-surface-higher"
                        title={s.memo || s.name}
                      >
                        {fileIcon(s.media_type)}
                        <span className="truncate">{s.name}</span>
                      </button>
                      <span className="flex shrink-0 items-center gap-0.5 pr-1 opacity-0 transition-opacity group-hover:opacity-100 hover:opacity-100">
                        <IconButton
                          label={t("sidebar.renameFor", { name: s.name })}
                          title={t("sidebar.renameFor", { name: s.name })}
                          size="row"
                          onClick={() => renameFile(s)}
                        >
                          <Pencil size={12} aria-hidden />
                        </IconButton>
                        <IconButton
                          label={t("sidebar.deleteFor", { name: s.name })}
                          title={t("common.delete")}
                          size="row"
                          className="hover:text-danger"
                          onClick={() => void deleteFile(s)}
                        >
                          <Trash2 size={12} aria-hidden />
                        </IconButton>
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          );
        })}
      </>
    );
  }

  return (
    <LeftBar
      width="md"
      className="h-full min-h-0 overflow-y-auto"
      header={
        view.kind !== "coding" ? (
          <BarHeader
            title={t("nav.files")}
            actions={
              <Button
                variant="primary"
                icon={<Upload size={12} aria-hidden />}
                disabled={!projectOpen}
                onClick={() => {
                  setView({ kind: "files" });
                  useProjectStore.getState().requestImport();
                }}
              >
                {t("files.import")}
              </Button>
            }
          />
        ) : (
          <BarHeader
            title={t("nav.codes")}
            actions={
              <>
                <Button
                  variant="primary"
                  icon={<Plus size={12} aria-hidden />}
                  onClick={() => void createCode(null)}
                >
                  {t("sidebar.addCode")}
                </Button>
                <Button
                  variant="primary"
                  icon={<FolderPlus size={12} aria-hidden />}
                  onClick={() => void createCategory(null)}
                >
                  {t("sidebar.addCategory")}
                </Button>
              </>
            }
          />
        )
      }
    >
      <div
        className="relative shrink-0 border-b border-border px-3 py-1.5"
        onDragOver={(e) => {
          // Chrome above the tree: never a drop target — clear any leftover
          // indicator while the pointer is over the search box.
          if (dragNode && e.target === e.currentTarget) setDropZone(null);
        }}
      >
        <Search
          size={14}
          className="pointer-events-none absolute left-5 top-1/2 -translate-y-1/2 text-text-secondary"
          aria-hidden
        />
        <Input
          value={view.kind === "coding" ? query : fileQuery}
          onChange={(e) => {
            if (view.kind === "coding") setQuery(e.target.value);
            else setFileQuery(e.target.value);
          }}
          placeholder={view.kind === "coding" ? t("sidebar.searchCodes") : t("sidebar.searchFiles")}
          aria-label={view.kind === "coding" ? t("sidebar.searchCodes") : t("sidebar.searchFiles")}
          className="w-full pl-7!"
        />
      </div>
      {view.kind === "coding" && (
        <div
          className="flex shrink-0 items-center gap-1 border-b border-border px-2 py-1"
          onDragOver={(e) => {
            // Code-set toolbar is never a drop target either.
            if (dragNode && e.target === e.currentTarget) setDropZone(null);
          }}
        >
          <Select
            value={activeSetId ?? ""}
            onChange={(e) => setActiveSetId(e.target.value ? Number(e.target.value) : null)}
            aria-label={t("codeSets.selectAria")}
            className={`min-w-0 flex-1 ${
              appliedSet ? "border-accent text-accent" : ""
            }`}
          >
            {codeSets.length === 0 ? (
              <option value="">{t("codeSets.none")}</option>
            ) : (
              codeSets.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.member_count})
                </option>
              ))
            )}
          </Select>
          {appliedSet && (
            <IconButton
              label={t("codeSets.clearFilter")}
              title={t("codeSets.clearFilter")}
              size="sm"
              onClick={() => setAppliedSet(null)}
            >
              <X size={14} aria-hidden />
            </IconButton>
          )}
          <Button
            variant={appliedSet ? "primaryCompact" : "secondary"}
            className="shrink-0 px-2 text-xs"
            disabled={activeSetId == null}
            onClick={() => void applyCodeSet()}
          >
            {t("codeSets.apply")}
          </Button>
          <IconButton
            label={t("codeSets.manage")}
            title={t("codeSets.manage")}
            size="sm"
            onClick={(e) => setManageMenu({ x: e.clientX, y: e.clientY })}
          >
            <SlidersHorizontal size={14} aria-hidden />
          </IconButton>
        </div>
      )}
      {view.kind === "coding" && toolbarError && (
        <p
          role="alert"
          className="flex shrink-0 items-center gap-1.5 px-2 pt-1 text-xs text-danger"
        >
          <CircleAlert size={12} className="shrink-0" aria-hidden />
          <span className="min-w-0 truncate">{toolbarError}</span>
        </p>
      )}
      {view.kind === "coding" ? (
        <div
          className="pt-1"
          onDragOver={(e) => {
            // Dropping on empty tree space cancels the drag (no zone).
            if (dragNode && e.target === e.currentTarget) {
              e.preventDefault();
              setDropZone(null);
            }
          }}
        >
          {query.trim() ? (
            <div className="pb-2">
              {flatMatches.length === 0 ? (
                <p className="px-2 py-3 text-center text-sm text-text-secondary">
                  {t("sidebar.noMatches")}
                </p>
              ) : (
                flatMatches.map((item) => (
                  <button
                    key={`${item.kind}:${item.id}`}
                    type="button"
                    onClick={() => {
                      if (item.kind !== "category") {
                        setActiveCode(item.id);
                        void selectCode(item.id);
                        window.dispatchEvent(
                          new CustomEvent("qc:assign-code", { detail: { cid: item.id } }),
                        );
                      }
                    }}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      setMenu({ kind: "code", x: e.clientX, y: e.clientY, item });
                    }}
                    className={`flex w-full items-center gap-1.5 rounded-sm px-2 py-1 text-left text-sm hover:bg-surface-higher ${
                      item.kind === "code" && activeCodeId === item.id ? "bg-accent/15 text-accent" : ""
                    } ${
                      item.kind === "code" &&
                      hiddenCodes.includes(item.id)
                        ? "opacity-40"
                        : ""
                    }`}
                  >
                    {item.kind === "category" ? (
                      <FolderOpen size={14} className="shrink-0 text-text-secondary" aria-hidden />
                    ) : (
                      <>
                        <span className="inline-block w-3.5 shrink-0" aria-hidden />
                        <span
                          className="inline-block h-3 w-3 shrink-0 rounded-sm border border-border hover:ring-1 hover:ring-accent"
                          style={{ backgroundColor: item.color ?? "#ccc" }}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleHiddenCode(item.id);
                          }}
                          title={t("sidebar.highlightCode")}
                          aria-hidden
                        />
                      </>
                    )}
                    <span className="truncate">{item.name}</span>
                  </button>
                ))
              )}
            </div>
          ) : (
            <div
              ref={treeContainerRef}
              onPointerMove={handleTreePointerMove}
              onPointerUp={handleTreePointerUp}
              onPointerCancel={handleTreePointerCancel}
            >
              {renderCodeNode("root", 0)}
            </div>
          )}
        </div>
      ) : (
        /* Files view: the whole group area accepts OS file drops. */
        <div
          className="relative"
          onDragOver={handleFileDragOver}
          onDragLeave={handleFileDragLeave}
          onDrop={handleFileDrop}
        >
          {fileDropActive && (
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0 z-20 flex flex-col items-center justify-center gap-1.5 border-2 border-dashed border-accent bg-accent/10"
            >
              <Upload size={22} className="text-accent" aria-hidden />
              <p className="text-sm font-medium text-accent">{t("files.dropImport")}</p>
              <p className="text-xs text-text-secondary">{t("files.dropImportHint")}</p>
            </div>
          )}
          {renderFileGroups()}
        </div>
      )}

      {/* Context menu */}
      {menu && menuStyle && (
        <>
          <div
            className="fixed inset-0 z-30"
            onClick={() => setMenu(null)}
            onContextMenu={(e) => {
              e.preventDefault();
              setMenu(null);
            }}
            aria-hidden
          />
          <Menu
            position="fixed"
            className="min-w-44"
            style={menuStyle}
            role="menu"
            aria-label={t("sidebar.contextMenuAria")}
          >
            {menuActions.map((a) => (
              <MenuItem
                key={a.label}
                role="menuitem"
                className={a.danger ? "text-danger" : ""}
                onClick={a.run}
              >
                {a.icon}
                {a.label}
              </MenuItem>
            ))}
          </Menu>
        </>
      )}
      {/* Colour palette (right-click a code → Colour) */}
      {colorMenu && (
        <>
          <div
            className="fixed inset-0 z-30"
            onClick={() => setColorMenu(null)}
            onContextMenu={(e) => {
              e.preventDefault();
              setColorMenu(null);
            }}
            aria-hidden
          />
          <Menu
            position="fixed"
            className="min-w-40 p-2"
            style={{
              left: Math.min(colorMenu.x, window.innerWidth - 180),
              top: Math.min(colorMenu.y, window.innerHeight - 140),
            }}
            role="menu"
            aria-label={t("sidebar.menuColour")}
          >
            <p className="mb-1.5 truncate px-0.5 text-[10px] text-text-secondary">
              {colorMenu.item.name}
            </p>
            <div className="grid grid-cols-8 gap-1">
              {palette.map((color) => (
                <button
                  key={color}
                  type="button"
                  onClick={() => {
                    setColorMenu(null);
                    void patchCodeColor(colorMenu.item, color);
                  }}
                  className="h-4 w-4 rounded-sm border border-border hover:ring-1 hover:ring-accent"
                  style={{ backgroundColor: color }}
                  aria-label={color}
                />
              ))}
            </div>
          </Menu>
        </>
      )}
      {/* "Merge into…" submenu (context menu → Merge into…) */}
      {mergeMenu && (
        <>
          <div
            className="fixed inset-0 z-30"
            onClick={() => setMergeMenu(null)}
            onContextMenu={(e) => {
              e.preventDefault();
              setMergeMenu(null);
            }}
            aria-hidden
          />
          <Menu
            position="fixed"
            className="min-w-56 p-1.5"
            style={{
              left: Math.min(mergeMenu.x + MENU_WIDTH - 8, window.innerWidth - 240),
              top: Math.min(mergeMenu.y, window.innerHeight - 360),
            }}
            role="menu"
            aria-label={t("tree.mergeInto")}
          >
            <p className="mb-1 truncate px-1 pt-0.5 text-[10px] text-text-secondary">
              {t("tree.mergeInto")} — {mergeMenu.item.name}
            </p>
            {mergeCandidates.length > 10 && (
              <div className="relative mb-1">
                <Search
                  size={12}
                  className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-text-secondary"
                  aria-hidden
                />
                <Input
                  value={mergeMenu.search}
                  onChange={(e) => setMergeMenu({ ...mergeMenu, search: e.target.value })}
                  placeholder={t("tree.mergeSearch")}
                  className="w-full pl-6!"
                />
              </div>
            )}
            <div className="qc-scroll max-h-72 overflow-y-auto">
              {mergeFiltered.length === 0 ? (
                <p className="px-2 py-2 text-xs text-text-secondary">{t("tree.mergeEmpty")}</p>
              ) : (
                mergeFiltered.map((c) => (
                  <MenuItem
                    key={`${c.kind}:${c.id}`}
                    role="menuitem"
                    onClick={() => {
                      setMergeMenu(null);
                      void confirmAndMerge(mergeMenu.item, c);
                    }}
                  >
                    {c.kind === "code" && (
                      <span
                        className="inline-block h-3 w-3 shrink-0 rounded-sm border border-border"
                        style={{ backgroundColor: c.color ?? "#ccc" }}
                        aria-hidden
                      />
                    )}
                    <span className="min-w-0 truncate">{c.name}</span>
                  </MenuItem>
                ))
              )}
            </div>
          </Menu>
        </>
      )}
      {/* Code-set actions (create / edit members / rename / delete) */}
      {manageMenu && (
        <>
          <div
            className="fixed inset-0 z-30"
            onClick={() => setManageMenu(null)}
            onContextMenu={(e) => {
              e.preventDefault();
              setManageMenu(null);
            }}
            aria-hidden
          />
          <Menu
            position="fixed"
            className="min-w-44"
            style={{
              left: Math.min(manageMenu.x, window.innerWidth - 190),
              top: Math.min(manageMenu.y, window.innerHeight - 200),
            }}
            role="menu"
            aria-label={t("codeSets.manageMenuAria")}
          >
            <MenuItem
              role="menuitem"
              onClick={() => {
                setManageMenu(null);
                void createSet();
              }}
            >
              <Plus size={14} aria-hidden />
              {t("codeSets.create")}
            </MenuItem>
            <MenuItem
              role="menuitem"
              disabled={activeSetId == null}
              onClick={() => {
                setManageMenu(null);
                void openMembersEditor();
              }}
            >
              <SlidersHorizontal size={14} aria-hidden />
              {t("codeSets.editMembers")}
            </MenuItem>
            <MenuItem
              role="menuitem"
              disabled={activeSetId == null}
              onClick={() => {
                setManageMenu(null);
                void renameActiveSet();
              }}
            >
              <Pencil size={14} aria-hidden />
              {t("codeSets.rename")}
            </MenuItem>
            <MenuItem
              role="menuitem"
              disabled={activeSetId == null}
              className="text-danger"
              onClick={() => {
                setManageMenu(null);
                void deleteActiveSet();
              }}
            >
              <Trash2 size={14} aria-hidden />
              {t("codeSets.delete")}
            </MenuItem>
          </Menu>
        </>
      )}
      {/* Code-set membership editor */}
      <CodeSetMembersModal
        open={membersEditor != null}
        set={membersEditor?.set ?? null}
        members={membersEditor?.members ?? null}
        codes={codeSetOptions}
        onClose={() => setMembersEditor(null)}
        onSave={(cids) => saveMembers(cids)}
        t={t}
      />
    </LeftBar>
  );
}

interface CodeSetOption {
  cid: number;
  label: string;
  color: string | null;
}

/** Membership editor: every code of the project with a checkbox for the
 *  active set. Saving syncs the diff (add + remove) through the API. */
function CodeSetMembersModal({
  open,
  set,
  members,
  codes,
  onClose,
  onSave,
  t,
}: {
  open: boolean;
  set: CodeSetSummary | null;
  members: Set<number> | null;
  codes: CodeSetOption[];
  onClose: () => void;
  onSave: (cids: number[]) => Promise<void>;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const [draft, setDraft] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open && members) setDraft(new Set(members));
  }, [open, members]);

  const toggle = (cid: number) => {
    setDraft((prev) => {
      const next = new Set(prev);
      if (next.has(cid)) next.delete(cid);
      else next.add(cid);
      return next;
    });
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSave([...draft]);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("codeSets.membersSaveError"));
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={busy ? undefined : onClose}
      title={set ? t("codeSets.membersTitle", { name: set.name }) : undefined}
      icon={<SlidersHorizontal size={14} aria-hidden />}
      size="lg"
      panelClassName="w-[32rem] max-w-[92vw]"
    >
      <div className="flex max-h-[65vh] flex-col">
        <div className="qc-scroll min-h-0 flex-1 overflow-y-auto px-2 py-1">
          {codes.length === 0 ? (
            <p className="px-2 py-3 text-center text-sm text-text-secondary">
              {t("codeSets.noCodes")}
            </p>
          ) : (
            codes.map((code) => (
              <label
                key={code.cid}
                className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1 text-sm hover:bg-surface-higher"
              >
                <input
                  type="checkbox"
                  checked={draft.has(code.cid)}
                  onChange={() => toggle(code.cid)}
                  className="shrink-0 accent-accent"
                />
                <span
                  className="inline-block h-3 w-3 shrink-0 rounded-sm border border-border"
                  style={{ backgroundColor: code.color ?? "#ccc" }}
                  aria-hidden
                />
                <span className="min-w-0 truncate" title={code.label}>
                  {code.label}
                </span>
              </label>
            ))
          )}
        </div>
        {error && (
          <p
            role="alert"
            className="flex shrink-0 items-center gap-1.5 px-3 pt-2 text-xs text-danger"
          >
            <CircleAlert size={12} className="shrink-0" aria-hidden />
            <span className="min-w-0 truncate">{error}</span>
          </p>
        )}
        <div className="flex items-center justify-end gap-2 px-3 py-2">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="primary"
            icon={
              busy ? (
                <LoaderCircle size={12} className="animate-spin" aria-hidden />
              ) : (
                <Check size={12} aria-hidden />
              )
            }
            disabled={busy}
            onClick={() => void save()}
          >
            {t("codeSets.membersSave")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

