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
  Info,
  Pencil,
  Plus,
  StickyNote,
  Trash2,
  Unlink,
  UserRound,
} from "lucide-react";
import { api, type CodeTreeItem, type Source } from "@/lib/api";
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

  const sources = useProjectStore((s) => s.sources);
  const codeTree = useProjectStore((s) => s.codeTree);
  const setView = useProjectStore((s) => s.setView);
  const selectCode = useProjectStore((s) => s.selectCode);
  const selectFile = useProjectStore((s) => s.selectFile);
  const activeCodeId = useProjectStore((s) => s.activeCodeId);
  const setActiveCode = useProjectStore((s) => s.setActiveCode);
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

  /* ------------------------------------------------------------------ */
  /* CRUD actions                                                        */
  /* ------------------------------------------------------------------ */

  async function createCode(catid: number | null, supercid: number | null = null) {
    const name = window.prompt(t("sidebar.newCodeName"));
    if (!name?.trim()) return;
    setToolbarError(null);
    try {
      const res = await api.createCode(name.trim(), { catid, supercid });
      await useProjectStore.getState().refreshProject();
      await selectCode(res.cid);
      toast.success(t("sidebar.codeAdded", { name: name.trim() }));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("codePicker.createError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  async function createCategory(supercatid: number | null) {
    const name = window.prompt(t("sidebar.newCategoryName"));
    if (!name?.trim()) return;
    setToolbarError(null);
    try {
      await api.createCategory(name.trim(), { supercatid });
      await useProjectStore.getState().refreshProject();
      toast.success(t("sidebar.categoryAdded", { name: name.trim() }));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("sidebar.createCategoryError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  async function renameCode(item: CodeTreeItem) {
    const next = window.prompt(t("sidebar.renamePrompt", { name: item.name }), item.name);
    if (next === null) return;
    const name = next.trim();
    if (!name || name === item.name) return;
    setToolbarError(null);
    try {
      await api.patchCode(item.id, { name });
      await useProjectStore.getState().refreshProject();
      toast.success(t("sidebar.codeRenamed", { name }));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("sidebar.renameCodeError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  async function editCodeMemo(item: CodeTreeItem) {
    const next = window.prompt(t("sidebar.memoPrompt", { name: item.name }), item.memo ?? "");
    if (next === null) return;
    setToolbarError(null);
    try {
      await api.patchCode(item.id, { memo: next });
      await useProjectStore.getState().refreshProject();
      toast.success(t("sidebar.memoSaved"));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("sidebar.memoError");
      setToolbarError(detail);
      toast.error(detail);
    }
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

  async function renameFile(source: Source) {
    const next = window.prompt(t("files.renamePrompt", { name: source.name }), source.name);
    if (next === null) return;
    const name = next.trim();
    if (!name || name === source.name) return;
    setToolbarError(null);
    try {
      await api.patchSource(source.id, { name });
      await useProjectStore.getState().refreshProject();
      toast.success(t("files.renamed", { name }));
    } catch (e) {
      const detail = e instanceof Error ? e.message : t("files.renameError");
      setToolbarError(detail);
      toast.error(detail);
    }
  }

  async function editFileMemo(source: Source) {
    // The details panel (right bar) hosts the inline memo editor.
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
      return (
        <div key={key}>
          <button
            type="button"
            onClick={() => {
              if (item.kind === "category") {
                if (hasChildren) setCollapsed((c) => ({ ...c, [key]: !isCollapsed }));
              } else {
                // Clicking a code makes it the ACTIVE code (any pending
                // selection in the open coder is coded with it immediately)
                // and shows its details in the right-hand inspector. Codes
                // that are parents of sub-codes also toggle their children.
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
            className={`flex w-full items-center gap-1.5 rounded-sm px-2 py-1 text-left text-sm hover:bg-surface-higher ${
              item.kind === "code" && activeCodeId === item.id
                ? "bg-accent/15 text-accent"
                : ""
            }`}
            style={{ paddingLeft: `${8 + depth * 16}px` }}
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
                  className="inline-block h-3 w-3 shrink-0 rounded-sm border border-border"
                  style={{ backgroundColor: item.color ?? "#ccc" }}
                  aria-hidden
                />
              </>
            )}
            <span className="truncate">{item.name}</span>
          </button>
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

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-border bg-surface">
      <div className="min-h-0 flex-1 overflow-y-auto p-1">
        {view.kind === "coding" ? (
          <div className="flex flex-col">
            <div className="flex shrink-0 items-center gap-1 border-b border-border px-1.5 py-1.5">
              <button
                type="button"
                onClick={() => void createCode(null)}
                className="flex items-center gap-1 rounded-sm border border-border bg-bg px-2 py-0.5 text-xs text-text-secondary hover:bg-surface-higher hover:text-text-primary"
              >
                <Plus size={12} aria-hidden />
                {t("sidebar.addCode")}
              </button>
              <button
                type="button"
                onClick={() => void createCategory(null)}
                className="flex items-center gap-1 rounded-sm border border-border bg-bg px-2 py-0.5 text-xs text-text-secondary hover:bg-surface-higher hover:text-text-primary"
              >
                <FolderPlus size={12} aria-hidden />
                {t("sidebar.addCategory")}
              </button>
            </div>
            {toolbarError && (
              <p className="shrink-0 px-2 pt-1 text-xs text-danger">{toolbarError}</p>
            )}
            <div className="pt-1">{renderCodeNode("root", 0)}</div>
          </div>
        ) : (
          Object.entries(groups).map(([group, items]) =>
            items.length === 0 ? null : (
              <div key={group}>
                <div className="px-2 py-1 text-xs font-medium text-text-secondary">
                  {groupLabels[group] ?? group}
                </div>
                {items.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => setView({ kind: "coding", sourceId: s.id })}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      setMenu({ kind: "file", x: e.clientX, y: e.clientY, source: s });
                    }}
                    className="flex w-full items-center gap-1.5 rounded-sm px-2 py-1 text-left text-sm hover:bg-surface-higher"
                    title={s.memo || s.name}
                  >
                    {fileIcon(s.media_type)}
                    <span className="truncate">{s.name}</span>
                  </button>
                ))}
              </div>
            ),
          )
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
          <div
            className="fixed z-40 min-w-44 rounded-md border border-border bg-surface py-1 shadow-lg"
            style={menuStyle}
            role="menu"
            aria-label={t("sidebar.contextMenuAria")}
          >
            {menuActions.map((a) => (
              <button
                key={a.label}
                type="button"
                role="menuitem"
                onClick={a.run}
                className={`flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher ${
                  a.danger ? "text-danger" : ""
                }`}
              >
                {a.icon}
                {a.label}
              </button>
            ))}
          </div>
        </>
      )}
    </aside>
  );
}
