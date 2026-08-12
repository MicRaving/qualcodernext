/**
 * Notes workspace — split into the shell's left bar (NotesList) and center
 * (NotesEditor). A dropdown in the left bar's header picks the note type;
 * the per-type list and editor fill the left/center slots.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  FolderOpen,
  Hash,
  Info,
  LoaderCircle,
  NotebookPen,
  Pencil,
  Save,
  Search,
  StickyNote,
  Trash2,
} from "lucide-react";
import { api, type Source } from "@/lib/api";
import {
  BarHeader,
  Button,
  IconButton,
  LeftBar,
  Select,
  ViewHeader,
} from "@/components/ui/orchestrator";

import { RowContextMenu } from "@/features/shell/RowContextMenu";
import { InlineNameEdit } from "@/components/ui/InlineNameEdit";
import { JournalEditor, JournalList } from "@/features/journals/JournalView";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";

const MAX_TREE_DEPTH = 64;

/** Left bar: the journal list by default. Annotations and memos have no tab
 *  switcher anymore — those views are opened from the file inspector's
 *  right-click (their lists fill this bar while active). */
export function NotesList() {
  const { t } = useI18n();
  const notesUi = useProjectStore((s) => s.notesUi);
  const setNotesUi = useProjectStore((s) => s.setNotesUi);

  const loadAnnotations = useCallback(async () => {
    try {
      useProjectStore.setState({ annotationsAll: await api.annotationsAll() });
    } catch {
      /* the list shows whatever is cached */
    }
  }, []);

  useEffect(() => {
    if (notesUi.tab === "annotations") void loadAnnotations();
  }, [notesUi.tab, notesUi.tick, loadAnnotations]);

  async function newEntry() {
    try {
      const created = await api.createJournal(t("journal.untitled"), "");
      setNotesUi({ selectedId: created.jid, tick: notesUi.tick + 1 });
    } catch {
      /* surface via the list's own error on reload */
    }
  }

  /** Add an annotation at the very start of the first source; the center
   *  editor opens in edit mode (newAnnotation flag). */
  async function newAnnotation() {
    const first = useProjectStore.getState().sources[0];
    if (!first) return;
    try {
      const created = await api.createAnnotation({ fid: first.id, pos0: 0, pos1: 1, memo: "" });
      useProjectStore.setState({ annotationsAll: await api.annotationsAll() });
      setNotesUi({
        tab: "annotations",
        selectedId: created.anid,
        selectedKind: null,
        newAnnotation: true,
        tick: notesUi.tick + 1,
      });
    } catch {
      /* surface via the list's own error on reload */
    }
  }

  /** Add a memo: keep the current selection, else jump to the first code
   *  without a memo (the center editor is always in edit mode). */
  function newMemo() {
    if (notesUi.selectedId != null && notesUi.selectedKind != null) {
      setNotesUi({
        selectedId: notesUi.selectedId,
        selectedKind: notesUi.selectedKind,
        tick: notesUi.tick + 1,
      });
      return;
    }
    const first = useProjectStore
      .getState()
      .codeTree.find((c) => c.kind === "code" && (c.memo ?? "").trim() === "");
    if (!first) return;
    setNotesUi({ selectedId: first.id, selectedKind: "code", tick: notesUi.tick + 1 });
  }

  return (
    <LeftBar
      header={
        <BarHeader
          title={
            notesUi.tab === "journal"
              ? t("nav.notes")
              : t(`notes.tab.${notesUi.tab}`)
          }
          actions={
            <>
              {notesUi.tab === "journal" && (
                <Button
                  variant="primary"
                  icon={<NotebookPen size={12} aria-hidden />}
                  aria-label={t("common.add")}
                  title={t("common.add")}
                  onClick={() => void newEntry()}
                >
                  {t("common.add")}
                </Button>
              )}
              {notesUi.tab === "annotations" && (
                <Button
                  variant="primary"
                  icon={<StickyNote size={12} aria-hidden />}
                  aria-label={t("common.add")}
                  title={t("common.add")}
                  onClick={() => void newAnnotation()}
                >
                  {t("common.add")}
                </Button>
              )}
              {notesUi.tab === "memos" && (
                <Button
                  variant="primary"
                  icon={<Hash size={12} aria-hidden />}
                  aria-label={t("common.add")}
                  title={t("common.add")}
                  onClick={() => void newMemo()}
                >
                  {t("common.add")}
                </Button>
              )}
            </>
          }
        />
      }
    >
      <div className="relative shrink-0 px-3 py-2">
        <Search
          size={14}
          className="pointer-events-none absolute left-5 top-1/2 -translate-y-1/2 text-text-secondary"
          aria-hidden
        />
        <input
          value={notesUi.query}
          onChange={(e) => setNotesUi({ query: e.target.value })}
          placeholder={t("notes.searchPlaceholder")}
          aria-label={t("notes.searchAria")}
          className="h-7 w-full rounded-sm border border-border bg-bg pl-7 pr-2 text-sm outline-none focus:border-accent"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {notesUi.tab === "journal" ? (
          <JournalList />
        ) : notesUi.tab === "annotations" ? (
          <AnnotationItems />
        ) : (
          <MemoItems />
        )}
      </div>
    </LeftBar>
  );
}

/** Center: the per-tab editor (journal entry / annotation / memo). */
export function NotesEditor() {
  const tab = useProjectStore((s) => s.notesUi.tab);
  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1">
        {tab === "journal" ? (
          <JournalEditor />
        ) : tab === "annotations" ? (
          <AnnotationDetails />
        ) : (
          <MemoEditor />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Annotations
// ---------------------------------------------------------------------------

function AnnotationItems() {
  const { t } = useI18n();
  const annotations = useProjectStore((s) => s.annotationsAll);
  const notesUi = useProjectStore((s) => s.notesUi);
  const setNotesUi = useProjectStore((s) => s.setNotesUi);
  const setView = useProjectStore((s) => s.setView);
  const [rowMenu, setRowMenu] = useState<{ x: number; y: number; a: (typeof annotations)[number] } | null>(null);
  /** Inline memo editing (journal-style): which row is being edited. */
  const [editingId, setEditingId] = useState<number | null>(null);

  const q = notesUi.query.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      annotations.filter(
        (a) =>
          !q ||
          a.file_name.toLowerCase().includes(q) ||
          (a.memo ?? "").toLowerCase().includes(q),
      ),
    [annotations, q],
  );

  /** The row after the given annotation in the visible list (Tab cycles). */
  function nextEditingId(anid: number): number | null {
    const idx = filtered.findIndex((a) => a.anid === anid);
    const next = idx >= 0 ? filtered[idx + 1] : undefined;
    return next ? next.anid : null;
  }

  async function renameAnnotation(a: (typeof annotations)[number], memo: string) {
    // Close the editor synchronously so Tab can move it to the next row.
    setEditingId(null);
    if (!memo || memo === a.memo) return;
    try {
      await api.updateAnnotation(a.anid, memo);
      useProjectStore.setState({ annotationsAll: await api.annotationsAll() });
    } catch {
      /* surface via the editor's error state */
    }
  }

  async function deleteAnnotation(a: (typeof annotations)[number]) {
    if (!window.confirm(t("coder.deleteAnnotation"))) return;
    try {
      await api.deleteAnnotation(a.anid);
      useProjectStore.setState({ annotationsAll: await api.annotationsAll() });
      if (notesUi.selectedId === a.anid) setNotesUi({ selectedId: null });
    } catch {
      /* surface via the editor's error state */
    }
  }

  if (annotations.length === 0) {
    return (
      <p className="px-3 py-6 text-center text-sm text-text-secondary">
        {t("notes.annotationsEmpty")}
      </p>
    );
  }
  if (filtered.length === 0) {
    return (
      <p className="px-3 py-6 text-center text-sm text-text-secondary">
        {t("notes.noMatch", { query: notesUi.query })}
      </p>
    );
  }
  return (
    <div className="divide-y divide-border">
      {filtered.map((a) => {
        if (editingId === a.anid) {
          return (
            <div key={a.anid} className="px-3 py-2">
              <InlineNameEdit
                value={a.memo ?? ""}
                placeholder={t("coder.annotationMemoPlaceholder")}
                onSave={(memo) => void renameAnnotation(a, memo)}
                onCancel={() => setEditingId(null)}
                onTab={() => setEditingId(nextEditingId(a.anid))}
              />
            </div>
          );
        }
        return (
        <div key={a.anid} className="group">
          <button
            type="button"
            onClick={() => setNotesUi({ selectedId: a.anid })}
            onContextMenu={(e) => {
              e.preventDefault();
              setRowMenu({ x: e.clientX, y: e.clientY, a });
            }}
            className={`flex w-full items-center gap-1.5 px-3 py-2 text-left hover:bg-surface-higher ${
              notesUi.selectedId === a.anid ? "bg-accent/10" : ""
            }`}
          >
            <span className="min-w-0 flex-1">
              {(a.memo ?? "").trim() ? (
                <span className="line-clamp-2 block text-sm text-text-primary">{a.memo}</span>
              ) : (
                <span className="block text-sm italic text-text-secondary">{t("common.noMemo")}</span>
              )}
              <span className="mt-0.5 flex items-center gap-1.5 text-xs text-text-secondary">
                <FileText size={11} className="shrink-0" aria-hidden />
                <span className="min-w-0 flex-1 truncate">{a.file_name}</span>
                <span className="shrink-0">
                  {a.pos0}–{a.pos1} · {a.date}
                </span>
              </span>
            </span>
            <span className="ml-auto flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 hover:opacity-100">
              <IconButton
                label={t("notes.renameFor", { name: a.file_name })}
                title={t("notes.renameFor", { name: a.file_name })}
                size="row"
                onClick={(e) => {
                  e.stopPropagation();
                  setEditingId(a.anid);
                }}
              >
                <Pencil size={12} aria-hidden />
              </IconButton>
              <IconButton
                label={t("notes.deleteFor", { name: a.file_name })}
                title={t("common.delete")}
                size="row"
                className="hover:text-danger"
                onClick={(e) => {
                  e.stopPropagation();
                  void deleteAnnotation(a);
                }}
              >
                <Trash2 size={12} aria-hidden />
              </IconButton>
            </span>
          </button>
        </div>
        );
      })}
      {rowMenu && (
        <RowContextMenu
          x={rowMenu.x}
          y={rowMenu.y}
          onClose={() => setRowMenu(null)}
          items={[
            {
              label: t("sidebar.menuDetails"),
              icon: <Info size={14} aria-hidden />,
              run: () => setNotesUi({ selectedId: rowMenu.a.anid }),
            },
            {
              label: t("notes.openFile"),
              icon: <FileText size={14} aria-hidden />,
              run: () => setView({ kind: "coding", sourceId: rowMenu.a.fid }),
            },
            {
              label: t("common.rename"),
              icon: <Pencil size={14} aria-hidden />,
              run: () => setEditingId(rowMenu.a.anid),
            },
            {
              label: t("common.delete"),
              icon: <Trash2 size={14} aria-hidden />,
              danger: true,
              run: () => void deleteAnnotation(rowMenu.a),
            },
          ]}
        />
      )}
    </div>
  );
}

function AnnotationDetails() {
  const { t } = useI18n();
  const setView = useProjectStore((s) => s.setView);
  const annotations = useProjectStore((s) => s.annotationsAll);
  const sources = useProjectStore((s) => s.sources);
  const notesUi = useProjectStore((s) => s.notesUi);
  const setNotesUi = useProjectStore((s) => s.setNotesUi);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editMode, setEditMode] = useState(false);

  const selected = annotations.find((a) => a.anid === notesUi.selectedId) ?? null;

  // Reset the draft only when the selected annotation CHANGES; a refresh
  // replaces the array with fresh objects, so keying on `selected` alone
  // would wipe the memo the user is currently editing.
  const prevAnidRef = useRef<number | null>(null);
  const dirtyRef = useRef(false);
  useEffect(() => {
    if (!selected) return;
    if (prevAnidRef.current === selected.anid) {
      if (!dirtyRef.current) setDraft(selected.memo ?? "");
      return;
    }
    prevAnidRef.current = selected.anid;
    dirtyRef.current = false;
    setDraft(selected.memo ?? "");
    setError(null);
  }, [selected]);

  // Open edit mode when an "edit request" is pending (fresh add or the
  // row's rename icon); otherwise drop back to read mode whenever the
  // selected row changes.
  const editAnidRef = useRef<number | null>(null);
  useEffect(() => {
    if (!selected) return;
    if (notesUi.newAnnotation) {
      editAnidRef.current = selected.anid;
      setNotesUi({ newAnnotation: false });
      setEditMode(true);
      return;
    }
    if (editAnidRef.current !== selected.anid) {
      editAnidRef.current = selected.anid;
      setEditMode(false);
    }
  }, [selected, notesUi.newAnnotation, setNotesUi]);

  async function saveMemo() {
    if (!selected || saving) return;
    setSaving(true);
    setError(null);
    try {
      await api.updateAnnotation(selected.anid, draft);
      useProjectStore.setState({ annotationsAll: await api.annotationsAll() });
    } catch (e) {
      setError(e instanceof Error ? e.message : t("coder.annotationUpdateError"));
    } finally {
      setSaving(false);
    }
  }

  async function deleteAnnotation() {
    if (!selected) return;
    if (!window.confirm(t("coder.deleteAnnotation"))) return;
    setError(null);
    try {
      await api.deleteAnnotation(selected.anid);
      useProjectStore.setState({ annotationsAll: await api.annotationsAll() });
      setNotesUi({ selectedId: null });
    } catch (e) {
      setError(e instanceof Error ? e.message : t("coder.annotationDeleteError"));
    }
  }

  /** PATCH only accepts memo/pos — moving to another file is create+delete. */
  async function moveAnnotation(fid: number) {
    if (!selected || saving || fid === selected.fid) return;
    setSaving(true);
    setError(null);
    try {
      // Guard against zero-length annotations: the backend rejects
      // pos1 <= pos0, and legacy rows may carry 0/0.
      const pos0 = Math.max(0, selected.pos0);
      const pos1 = Math.max(pos0 + 1, selected.pos1);
      const created = await api.createAnnotation({
        fid,
        pos0,
        pos1,
        memo: draft,
      });
      await api.deleteAnnotation(selected.anid);
      useProjectStore.setState({ annotationsAll: await api.annotationsAll() });
      setNotesUi({ selectedId: created.anid, newAnnotation: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : t("coder.annotationUpdateError"));
    } finally {
      setSaving(false);
    }
  }

  if (!selected) {
    return (
      <div className="flex h-full flex-1 flex-col items-center justify-center gap-2 text-text-secondary">
        <StickyNote size={24} aria-hidden />
        <p className="text-sm">{t("notes.annotationsSelectHint")}</p>
      </div>
    );
  }

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col bg-bg">
      <ViewHeader
        back={false}
        title={
          <span className="flex min-w-0 items-center gap-1.5">
            <Select
              value={selected.fid}
              onChange={(e) => void moveAnnotation(Number(e.target.value))}
              aria-label={t("notes.pickFileLabel")}
              className="h-7 max-w-64 min-w-0 text-xs"
            >
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
            <span className="shrink-0 rounded-sm bg-surface-higher px-1.5 py-px text-[10px] font-medium uppercase text-text-secondary">
              {selected.pos0}–{selected.pos1}
            </span>
          </span>
        }
        actions={
          <>
            <Button
              variant="secondary"
              icon={<FileText size={12} aria-hidden />}
              onClick={() => setView({ kind: "coding", sourceId: selected.fid })}
            >
              {t("notes.openFile")}
            </Button>
            {editMode && (
              <Button
                variant="primary"
                icon={
                  saving ? (
                    <LoaderCircle size={12} className="animate-spin" aria-hidden />
                  ) : (
                    <Save size={12} aria-hidden />
                  )
                }
                onClick={() => void saveMemo()}
                disabled={saving || draft === (selected.memo ?? "")}
              >
                {t("common.save")}
              </Button>
            )}
            <Button
              variant="danger"
              icon={<Trash2 size={12} aria-hidden />}
              onClick={() => void deleteAnnotation()}
              disabled={saving}
            >
              {t("common.delete")}
            </Button>
          </>
        }
      />

      <div className="flex min-h-0 flex-1 flex-col p-4">
        <h3 className="mb-2 shrink-0 text-xs font-medium uppercase tracking-wide text-text-secondary">
          {t("notes.annotationMemo")}
        </h3>
        {editMode ? (
          <textarea
            value={draft}
            onChange={(e) => {
              dirtyRef.current = true;
              setDraft(e.target.value);
            }}
            placeholder={t("coder.annotationMemoPlaceholder")}
            aria-label={t("coder.annotationMemo")}
            className="min-h-0 w-full flex-1 resize-none rounded-sm border border-border bg-surface px-2 py-1.5 text-sm leading-relaxed align-top outline-none focus:border-accent"
          />
        ) : (
          <button
            type="button"
            onClick={() => setEditMode(true)}
            className="flex min-h-0 w-full flex-1 flex-col justify-start rounded-sm border border-dashed border-border bg-surface px-2 py-1.5 text-left text-sm leading-relaxed text-text-primary hover:border-accent"
          >
            {(selected.memo ?? "").trim() ? (
              <span className="block">{selected.memo}</span>
            ) : (
              <span className="block italic text-text-secondary">{t("common.noMemo")}</span>
            )}
          </button>
        )}
        {error && <p className="mt-2 shrink-0 text-xs text-danger">{error}</p>}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Memos (codes + files)
// ---------------------------------------------------------------------------

function MemoItems() {
  const { t } = useI18n();
  const codeTree = useProjectStore((s) => s.codeTree);
  const sources = useProjectStore((s) => s.sources);
  const notesUi = useProjectStore((s) => s.notesUi);
  const setNotesUi = useProjectStore((s) => s.setNotesUi);
  const setView = useProjectStore((s) => s.setView);
  const [rowMenu, setRowMenu] = useState<
    | { x: number; y: number; kind: "code"; item: { id: number; name: string; memo: string | null } }
    | { x: number; y: number; kind: "file"; item: Source }
    | null
  >(null);

  const q = notesUi.query.trim().toLowerCase();
  const filesWithMemos = useMemo(
    () =>
      sources.filter((s) => (s.memo ?? "").trim() !== "" && (!q || s.name.toLowerCase().includes(q))),
    [sources, q],
  );

  const byParent = useMemo(() => {
    const map = new Map<
      string,
      { id: number; name: string; memo: string | null; kind: string; color: string | null }[]
    >();
    for (const item of codeTree) {
      if (q && !item.name.toLowerCase().includes(q) && !(item.memo ?? "").toLowerCase().includes(q)) {
        continue;
      }
      const parentKey =
        item.parent_id == null
          ? "root"
          : item.kind === "category" || !item.subcode
            ? `cat:${item.parent_id}`
            : `code:${item.parent_id}`;
      const list = map.get(parentKey) ?? [];
      list.push({ id: item.id, name: item.name, memo: item.memo, kind: item.kind, color: item.color });
      map.set(parentKey, list);
    }
    return map;
  }, [codeTree, q]);

  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  function renderNode(parent: string, depth: number): React.ReactNode {
    if (depth >= MAX_TREE_DEPTH) return null;
    const items = byParent.get(parent) ?? [];
    return items.map((item) => {
      const key = `${item.kind}:${item.id}`;
      const childrenKey = item.kind === "category" ? `cat:${item.id}` : `code:${item.id}`;
      const hasChildren = (byParent.get(childrenKey)?.length ?? 0) > 0;
      const isCollapsed = collapsed[key] ?? false;
      return (
        <div key={key} className="group">
          {item.kind === "code" ? (
            <button
              type="button"
              onClick={() => {
                setNotesUi({ selectedId: item.id, selectedKind: "code" });
                if (hasChildren) setCollapsed((c) => ({ ...c, [key]: !isCollapsed }));
              }}
              onContextMenu={(e) => {
                e.preventDefault();
                setRowMenu({ x: e.clientX, y: e.clientY, kind: "code", item });
              }}
              className={`flex w-full items-center gap-1.5 rounded-sm px-2 py-1 text-left text-sm hover:bg-surface-higher ${
                notesUi.selectedId === item.id && notesUi.selectedKind === "code"
                  ? "bg-accent/10 text-accent"
                  : ""
              }`}
              style={{ paddingLeft: `${8 + depth * 14}px` }}
              title={item.memo || undefined}
            >
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
              <span className="truncate">{item.name}</span>
              {item.memo ? (
                <span className="ml-auto shrink-0 text-[10px] text-text-secondary">memo</span>
              ) : (
                hasChildren && <span className="ml-auto shrink-0 text-[10px] text-text-secondary" />
              )}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => {
                if (hasChildren) setCollapsed((c) => ({ ...c, [key]: !isCollapsed }));
              }}
              className="flex w-full items-center gap-1.5 rounded-sm px-2 py-1 text-left text-sm font-medium text-text-secondary hover:bg-surface-higher"
              style={{ paddingLeft: `${8 + depth * 14}px` }}
            >
              {hasChildren ? (
                isCollapsed ? (
                  <ChevronRight size={14} className="shrink-0" aria-hidden />
                ) : (
                  <ChevronDown size={14} className="shrink-0" aria-hidden />
                )
              ) : (
                <FolderOpen size={14} className="shrink-0" aria-hidden />
              )}
              <span className="truncate">{item.name}</span>
            </button>
          )}
          {hasChildren && !isCollapsed && renderNode(childrenKey, depth + 1)}
        </div>
      );
    });
  }

  return (
    <div>
      <div className="sticky top-0 z-10 border-b border-border bg-surface px-3 py-1 text-xs font-medium uppercase tracking-wide text-text-secondary">
        {t("notes.kindCode")}
      </div>
      <div className="p-1">
        {codeTree.length === 0 ? (
          <p className="px-2 py-2 text-sm text-text-secondary">{t("notes.noCodes")}</p>
        ) : (
          renderNode("root", 0)
        )}
      </div>
      {filesWithMemos.length > 0 && (
        <>
          <div className="sticky top-0 z-10 border-b border-t border-border bg-surface px-3 py-1 text-xs font-medium uppercase tracking-wide text-text-secondary">
            {t("notes.kindFile")}
          </div>
          <div className="p-1">
            {filesWithMemos.map((s) => (
              <div key={s.id} className="group">
                <button
                  type="button"
                  onClick={() => setNotesUi({ selectedId: s.id, selectedKind: "file" })}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    setRowMenu({ x: e.clientX, y: e.clientY, kind: "file", item: s });
                  }}
                  className={`flex w-full items-center gap-1.5 rounded-sm px-2 py-1 text-left text-sm hover:bg-surface-higher ${
                    notesUi.selectedId === s.id && notesUi.selectedKind === "file"
                      ? "bg-accent/10 text-accent"
                      : ""
                  }`}
                >
                  <FileText size={13} className="shrink-0 text-text-secondary" aria-hidden />
                  <span className="truncate">{s.name}</span>
                  <span className="ml-auto shrink-0 text-[10px] text-text-secondary">memo</span>
                </button>
              </div>
            ))}
          </div>
        </>
      )}
      {rowMenu && (
        <RowContextMenu
          x={rowMenu.x}
          y={rowMenu.y}
          onClose={() => setRowMenu(null)}
          items={[
            {
              label: t("sidebar.menuDetails"),
              icon: <Info size={14} aria-hidden />,
              run: () =>
                setNotesUi({
                  selectedId: rowMenu.item.id,
                  selectedKind: rowMenu.kind === "code" ? "code" : "file",
                }),
            },
            {
              label: t("notes.openFile"),
              icon: <FileText size={14} aria-hidden />,
              run: () => setView({ kind: "coding", sourceId: rowMenu.item.id }),
            },
            {
              label: t("common.rename"),
              icon: <Pencil size={14} aria-hidden />,
              run: () => {
                if (rowMenu.kind === "code") {
                  const next = window.prompt(t("sidebar.renamePrompt", { name: rowMenu.item.name }), rowMenu.item.name);
                  const name = next?.trim();
                  if (name && name !== rowMenu.item.name) {
                    void api.patchCode(rowMenu.item.id, { name }).then(() => useProjectStore.getState().refreshProject());
                  }
                } else {
                  const next = window.prompt(t("files.renamePrompt", { name: rowMenu.item.name }), rowMenu.item.name);
                  const name = next?.trim();
                  if (name && name !== rowMenu.item.name) {
                    void api.patchSource(rowMenu.item.id, { name }).then(() => useProjectStore.getState().refreshProject());
                  }
                }
              },
            },
          ]}
        />
      )}
    </div>
  );
}

function MemoEditor() {
  const { t } = useI18n();
  const refreshProject = useProjectStore((s) => s.refreshProject);
  const codeTree = useProjectStore((s) => s.codeTree);
  const sources = useProjectStore((s) => s.sources);
  const notesUi = useProjectStore((s) => s.notesUi);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedCode = useMemo(
    () =>
      notesUi.selectedKind === "code"
        ? codeTree.find((c) => c.kind === "code" && c.id === notesUi.selectedId) ?? null
        : null,
    [codeTree, notesUi.selectedKind, notesUi.selectedId],
  );
  const selectedFile = useMemo(
    () =>
      notesUi.selectedKind === "file"
        ? sources.find((s) => s.id === notesUi.selectedId) ?? null
        : null,
    [sources, notesUi.selectedKind, notesUi.selectedId],
  );

  // Reset the draft only when the selected memo target CHANGES; a refresh
  // replaces the codeTree/sources arrays, so keying on the objects would
  // wipe the memo text the user is currently typing.
  const memoDirtyRef = useRef(false);
  const memoKeyRef = useRef<string | null>(null);
  useEffect(() => {
    const key = selectedCode ? `code:${selectedCode.id}` : selectedFile ? `file:${selectedFile.id}` : null;
    if (!key) return;
    if (memoKeyRef.current === key) {
      if (!memoDirtyRef.current) {
        setDraft(selectedCode?.memo ?? selectedFile?.memo ?? "");
      }
      return;
    }
    memoKeyRef.current = key;
    memoDirtyRef.current = false;
    setDraft(selectedCode?.memo ?? selectedFile?.memo ?? "");
    setError(null);
  }, [selectedCode, selectedFile]);

  async function saveMemo() {
    if (saving || (!selectedCode && !selectedFile)) return;
    setSaving(true);
    setError(null);
    try {
      if (selectedCode) await api.patchCode(selectedCode.id, { memo: draft });
      else if (selectedFile) await api.patchSource(selectedFile.id, { memo: draft });
      await refreshProject();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("notes.memoError"));
    } finally {
      setSaving(false);
    }
  }

  async function deleteMemo() {
    if (saving || (!selectedCode && !selectedFile)) return;
    const name = selectedCode?.name ?? selectedFile?.name ?? "";
    if (!window.confirm(t("notes.memoDeleteConfirm", { name }))) return;
    setSaving(true);
    setError(null);
    try {
      if (selectedCode) await api.patchCode(selectedCode.id, { memo: "" });
      else if (selectedFile) await api.patchSource(selectedFile.id, { memo: "" });
      await refreshProject();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("notes.memoError"));
    } finally {
      setSaving(false);
    }
  }

  const selected = selectedCode ?? selectedFile;
  const isCode = selectedCode != null;

  if (!selected) {
    return (
      <div className="flex h-full flex-1 flex-col items-center justify-center gap-2 text-text-secondary">
        <Hash size={24} aria-hidden />
        <p className="text-sm">{t("notes.memoSelectHint")}</p>
      </div>
    );
  }

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col bg-bg">
      <ViewHeader
        back={false}
        title={
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="truncate">{selected.name}</span>
            <span className="shrink-0 rounded-sm bg-surface-higher px-1.5 py-px text-[10px] font-medium uppercase text-text-secondary">
              {isCode ? t("notes.kindCode") : t("notes.kindFile")}
            </span>
          </span>
        }
        actions={
          <>
            {!isCode && (
              <Button
                variant="secondary"
                icon={<FileText size={12} aria-hidden />}
                onClick={() => useProjectStore.getState().setView({ kind: "coding", sourceId: selected.id })}
              >
                {t("notes.openFile")}
              </Button>
            )}
            <Button
              variant="primary"
              icon={
                saving ? (
                  <LoaderCircle size={12} className="animate-spin" aria-hidden />
                ) : (
                  <Save size={12} aria-hidden />
                )
              }
              onClick={() => void saveMemo()}
              disabled={saving || draft === (selected.memo ?? "")}
            >
              {t("common.save")}
            </Button>
            <Button
              variant="danger"
              icon={<Trash2 size={12} aria-hidden />}
              onClick={() => void deleteMemo()}
              disabled={saving || !selected.memo}
            >
              {t("common.delete")}
            </Button>
          </>
        }
      />
      <div className="flex min-h-0 flex-1 flex-col p-4">
        <textarea
          value={draft}
          onChange={(e) => {
            memoDirtyRef.current = true;
            setDraft(e.target.value);
          }}
          placeholder={t("notes.memoPlaceholder")}
          aria-label={t("notes.memoPlaceholder")}
          className="min-h-0 w-full flex-1 resize-none rounded-sm border border-border bg-surface px-2 py-1.5 align-top text-sm leading-relaxed outline-none focus:border-accent"
        />
        {error && <p className="mt-1 shrink-0 text-xs text-danger">{error}</p>}
      </div>
    </section>
  );
}
