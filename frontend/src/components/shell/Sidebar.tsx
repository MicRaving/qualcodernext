/**
 * Left sidebar — Files / Codes / Cases trees built from the API.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ChevronDown,
  ChevronRight,
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
  Palette,
  Pencil,
  Plus,
  Search,
  StickyNote,
  Trash2,
  Unlink,
  Upload,
  UserRound,
} from "lucide-react";
import { api, type CodeTreeItem, type Source } from "@/lib/api";

import { BarHeader, Button, IconButton, Input, LeftBar, Menu, MenuItem } from "@/components/ui/orchestrator";
import { InlineNameEdit } from "@/components/ui/InlineNameEdit";
import { isPdf } from "@/lib/media";
import { useToast } from "@/lib/toast";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";
import { clampToViewport, matchTargetByName } from "@/features/sidebar/codeActions";

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

export function Sidebar() {
  const { t } = useI18n();
  const toast = useToast();
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [menu, setMenu] = useState<ContextMenu | null>(null);
  const [toolbarError, setToolbarError] = useState<string | null>(null);
  /** Inline name editing (no system prompts): which row is being edited. */
  const [editing, setEditing] = useState<{ kind: "code" | "category" | "file"; id: number } | null>(null);
  // Code search (coding view only); the files search lives in the store so
  // the left bar and the center Files table share it.
  const [query, setQuery] = useState("");
  const fileQuery = useProjectStore((s) => s.fileQuery);
  const setFileQuery = useProjectStore((s) => s.setFileQuery);
  const [colorMenu, setColorMenu] = useState<{ item: CodeTreeItem; x: number; y: number } | null>(null);
  const [palette, setPalette] = useState<string[]>([]);

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

  useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenu(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menu]);

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

  const flatMatches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return codeTree.filter((item) => item.name.toLowerCase().includes(q));
  }, [codeTree, query]);

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

  async function mergeCodeInto(item: CodeTreeItem) {
    const targetName = window.prompt(t("sidebar.mergeCodePrompt", { name: item.name }));
    if (!targetName?.trim()) return;
    setToolbarError(null);
    const targetId = matchTargetByName(codeTree, targetName, "code");
    if (targetId == null) {
      const detail = t("sidebar.noCodeFound", { name: targetName.trim() });
      setToolbarError(detail);
      toast.error(detail);
      return;
    }
    try {
      await api.mergeCode(item.id, targetId);
      await useProjectStore.getState().refreshProject();
      toast.success(t("sidebar.codeMerged", { name: item.name }));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("sidebar.mergeCodeError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  async function mergeCategoryInto(item: CodeTreeItem) {
    const targetName = window.prompt(t("sidebar.mergeCategoryPrompt", { name: item.name }));
    if (!targetName?.trim()) return;
    setToolbarError(null);
    const targetId = matchTargetByName(codeTree, targetName, "category");
    if (targetId == null) {
      const detail = t("sidebar.noCategoryFound", { name: targetName.trim() });
      setToolbarError(detail);
      toast.error(detail);
      return;
    }
    try {
      await api.mergeCategory(item.id, targetId);
      await useProjectStore.getState().refreshProject();
      toast.success(t("sidebar.categoryMerged", { name: item.name }));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("sidebar.mergeCategoryError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  function clearInspectorIfSelected(item: CodeTreeItem) {
    const sel = useProjectStore.getState().inspectorSelection;
    if (sel?.kind === "code" && sel.id === item.id) {
      useProjectStore.getState().clearInspector();
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
      const detail = e instanceof Error ? e.message : t("tree.promoteFail");
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
      const detail = e instanceof Error ? e.message : t("tree.demoteFail");
      setToolbarError(detail);
      toast.error(detail);
    }
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
          run: close(() => void mergeCategoryInto(menu.item)),
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
        {
          label: t("common.delete"),
          icon: <Trash2 size={14} aria-hidden />,
          danger: true,
          run: close(() => void deleteCategoryItem(menu.item)),
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
          label: t("sidebar.menuRename"),
          icon: <Pencil size={14} aria-hidden />,
          run: close(() => void renameCode(menu.item)),
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
          run: close(() => void mergeCodeInto(menu.item)),
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
        {
          label: t("common.delete"),
          icon: <Trash2 size={14} aria-hidden />,
          danger: true,
          run: close(() => void deleteCodeItem(menu.item)),
        },
      );
    }
  }

  let menuStyle: { left: number; top: number } | undefined;
  if (menu) {
    const pos = clampToViewport(menu.x, menu.y, MENU_WIDTH, menuActions.length * 32 + 8);
    menuStyle = { left: pos.x, top: pos.y };
  }

  /* ------------------------------------------------------------------ */
  /* Rendering                                                           */
  /* ------------------------------------------------------------------ */

  const MAX_TREE_DEPTH = 64;

  function renderCodeNode(parent: string, depth: number) {
    const items = treeItems.get(parent) ?? [];
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
        <div key={key}>
          <div className="group flex items-center">
            <button
            type="button"
            onClick={() => {
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
            }`}
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
      <div className="relative shrink-0 border-b border-border px-3 py-1.5">
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
      {view.kind === "coding" && toolbarError && (
        <p className="shrink-0 px-2 pt-1 text-xs text-danger">{toolbarError}</p>
      )}
      <div className={view.kind === "coding" ? "pt-1" : undefined}>
        {view.kind === "coding" ? (
          query.trim() ? (
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
            renderCodeNode("root", 0)
          )
        ) : (
          renderFileGroups()
        )}
      </div>

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
    </LeftBar>
  );
}

