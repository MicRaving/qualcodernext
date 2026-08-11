/**
 * Notes workspace — split into the shell's left bar (NotesList) and center
 * (NotesEditor). A dropdown in the left bar's header picks the note type;
 * the per-type list and editor fill the left/center slots.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  FileText,
  FolderOpen,
  Hash,
  LoaderCircle,
  Plus,
  RefreshCw,
  Save,
  Search,
  StickyNote,
  Trash2,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button, CountBadge, IconButton, LeftBar, ViewHeader } from "@/components/ui/orchestrator";
import { JournalEditor, JournalList } from "@/features/journals/JournalView";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";

type NotesTab = "journal" | "annotations" | "memos";

const MAX_TREE_DEPTH = 64;

/** Left bar: header with the type dropdown + per-tab list. */
export function NotesList() {
  const { t } = useI18n();
  const notesUi = useProjectStore((s) => s.notesUi);
  const setNotesUi = useProjectStore((s) => s.setNotesUi);
  const journals = useProjectStore((s) => s.journals);
  const annotations = useProjectStore((s) => s.annotationsAll);
  const sources = useProjectStore((s) => s.sources);
  const codeTree = useProjectStore((s) => s.codeTree);
  const [typeMenuOpen, setTypeMenuOpen] = useState(false);
  const typeMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!typeMenuOpen) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (target && !typeMenuRef.current?.contains(target)) setTypeMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setTypeMenuOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [typeMenuOpen]);

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

  const count =
    notesUi.tab === "journal"
      ? journals.length
      : notesUi.tab === "annotations"
        ? annotations.length
        : sources.filter((s) => (s.memo ?? "").trim() !== "").length +
          codeTree.filter((c) => (c.memo ?? "").trim() !== "").length;

  function pickTab(tab: NotesTab) {
    setTypeMenuOpen(false);
    setNotesUi({ tab, selectedId: null, selectedKind: null });
  }

  return (
    <LeftBar
      header={
        <header className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-3">
          <div className="relative" ref={typeMenuRef}>
            <button
              type="button"
              onClick={() => setTypeMenuOpen((o) => !o)}
              aria-expanded={typeMenuOpen}
              aria-haspopup="listbox"
              aria-label={t("notes.tabsAria")}
              className="flex items-center gap-1 rounded-sm border border-border bg-bg px-2 py-1 text-xs font-medium hover:bg-surface-higher"
            >
              {t(`notes.tab.${notesUi.tab}`)}
              <ChevronDown size={11} className="text-text-secondary" aria-hidden />
            </button>
            {typeMenuOpen && (
              <div
                role="listbox"
                aria-label={t("notes.tabsAria")}
                className="absolute left-0 top-full z-50 mt-1 min-w-36 rounded-md border border-border bg-surface py-1 shadow-lg"
              >
                {(["journal", "annotations", "memos"] as NotesTab[]).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    role="option"
                    aria-selected={notesUi.tab === tab}
                    onClick={() => pickTab(tab)}
                    className={`flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher ${
                      notesUi.tab === tab ? "text-accent" : ""
                    }`}
                  >
                    {tab === "journal" ? (
                      <Hash size={12} aria-hidden />
                    ) : tab === "annotations" ? (
                      <StickyNote size={12} aria-hidden />
                    ) : (
                      <Hash size={12} aria-hidden />
                    )}
                    {t(`notes.tab.${tab}`)}
                  </button>
                ))}
              </div>
            )}
          </div>
          <CountBadge value={count} />
          <div className="flex-1" />
          {notesUi.tab === "journal" && (
            <Button
              variant="primaryCompact"
              icon={<Plus size={10} aria-hidden />}
              aria-label={t("journal.newEntry")}
              title={t("journal.newEntry")}
              onClick={() => void newEntry()}
            >
              {t("journal.newEntry")}
            </Button>
          )}
          <IconButton
            label={t("common.refresh")}
            title={t("common.refresh")}
            size="sm"
            onClick={() => setNotesUi({ tick: notesUi.tick + 1 })}
          >
            <RefreshCw size={14} aria-hidden />
          </IconButton>
        </header>
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
  const { t } = useI18n();
  const tab = useProjectStore((s) => s.notesUi.tab);
  const name =
    tab === "journal"
      ? t("notes.tab.journal")
      : tab === "annotations"
        ? t("notes.tab.annotations")
        : t("notes.tab.memos");
  return (
    <div className="flex h-full flex-col">
      <ViewHeader back={false} title={name} />
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
      {filtered.map((a) => (
        <button
          key={a.anid}
          type="button"
          onClick={() => setNotesUi({ selectedId: a.anid })}
          className={`block w-full px-3 py-2 text-left hover:bg-surface-higher ${
            notesUi.selectedId === a.anid ? "bg-accent/10" : ""
          }`}
        >
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
        </button>
      ))}
    </div>
  );
}

function AnnotationDetails() {
  const { t } = useI18n();
  const setView = useProjectStore((s) => s.setView);
  const annotations = useProjectStore((s) => s.annotationsAll);
  const notesUi = useProjectStore((s) => s.notesUi);
  const setNotesUi = useProjectStore((s) => s.setNotesUi);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selected = annotations.find((a) => a.anid === notesUi.selectedId) ?? null;

  useEffect(() => {
    setDraft(selected?.memo ?? "");
    setError(null);
  }, [selected]);

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
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="flex items-center gap-2">
          <h2 className="min-w-0 truncate text-base font-semibold text-text-primary">
            {selected.file_name}
          </h2>
          <span className="shrink-0 rounded-sm bg-surface-higher px-1.5 py-px text-[10px] font-medium uppercase text-text-secondary">
            {selected.pos0}–{selected.pos1}
          </span>
          <div className="flex-1" />
          <button
            type="button"
            onClick={() => setView({ kind: "coding", sourceId: selected.fid })}
            className="flex shrink-0 items-center gap-1 rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher"
          >
            <FileText size={12} aria-hidden />
            {t("notes.openFile")}
          </button>
        </div>

        <div className="mt-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-medium uppercase tracking-wide text-text-secondary">
              {t("notes.annotationMemo")}
            </h3>
            <button
              type="button"
              onClick={() => void saveMemo()}
              disabled={saving || draft === (selected.memo ?? "")}
              className="flex items-center gap-1 rounded-sm bg-accent px-2 py-0.5 text-[11px] font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50"
            >
              {saving ? (
                <LoaderCircle size={11} className="animate-spin" aria-hidden />
              ) : (
                <Save size={11} aria-hidden />
              )}
              {t("common.save")}
            </button>
          </div>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={8}
            placeholder={t("coder.annotationMemoPlaceholder")}
            aria-label={t("coder.annotationMemo")}
            className="mt-1.5 w-full resize-y rounded-sm border border-border bg-surface px-2 py-1.5 text-sm leading-relaxed outline-none focus:border-accent"
          />
        </div>
        {error && <p className="mt-1 text-xs text-danger">{error}</p>}

        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={() => void deleteAnnotation()}
            className="flex items-center gap-1 rounded-sm border border-border px-2 py-1 text-xs font-medium text-danger hover:bg-surface-higher"
          >
            <Trash2 size={12} aria-hidden />
            {t("common.delete")}
          </button>
        </div>
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

  const q = notesUi.query.trim().toLowerCase();
  const filesWithMemos = useMemo(
    () =>
      sources.filter((s) => (s.memo ?? "").trim() !== "" && (!q || s.name.toLowerCase().includes(q))),
    [sources, q],
  );

  const byParent = useMemo(() => {
    const map = new Map<string, { id: number; name: string; memo: string | null; kind: string }[]>();
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
      list.push(item);
      map.set(parentKey, list);
    }
    return map;
  }, [codeTree, q]);

  function renderNode(parent: string, depth: number): React.ReactNode {
    if (depth >= MAX_TREE_DEPTH) return null;
    const items = byParent.get(parent) ?? [];
    return items.map((item) => {
      const childrenKey = item.kind === "category" ? `cat:${item.id}` : `code:${item.id}`;
      const hasChildren = (byParent.get(childrenKey)?.length ?? 0) > 0;
      return (
        <div key={`${item.kind}-${item.id}`}>
          {item.kind === "code" ? (
            <button
              type="button"
              onClick={() => setNotesUi({ selectedId: item.id, selectedKind: "code" })}
              className={`flex w-full items-center gap-1.5 rounded-sm px-2 py-1 text-left text-sm hover:bg-surface-higher ${
                notesUi.selectedId === item.id && notesUi.selectedKind === "code"
                  ? "bg-accent/10 text-accent"
                  : ""
              }`}
              style={{ paddingLeft: `${8 + depth * 14}px` }}
              title={item.memo || undefined}
            >
              <Hash size={13} className="shrink-0 text-text-secondary" aria-hidden />
              <span className="truncate">{item.name}</span>
              {item.memo ? (
                <span className="ml-auto shrink-0 text-[10px] text-text-secondary">memo</span>
              ) : (
                hasChildren && <span className="ml-auto shrink-0 text-[10px] text-text-secondary" />
              )}
            </button>
          ) : (
            <div
              className="flex items-center gap-1.5 px-2 py-1 text-sm font-medium text-text-secondary"
              style={{ paddingLeft: `${8 + depth * 14}px` }}
            >
              <FolderOpen size={13} aria-hidden />
              <span className="truncate">{item.name}</span>
            </div>
          )}
          {hasChildren && renderNode(childrenKey, depth + 1)}
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
              <button
                key={s.id}
                type="button"
                onClick={() => setNotesUi({ selectedId: s.id, selectedKind: "file" })}
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
            ))}
          </div>
        </>
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

  useEffect(() => {
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
    <section className="flex h-full min-w-0 flex-1 flex-col bg-bg p-4">
      <div className="flex items-center gap-2">
        <h2 className="min-w-0 truncate text-base font-semibold text-text-primary">
          {selected.name}
        </h2>
        <span className="shrink-0 rounded-sm bg-surface-higher px-1.5 py-px text-[10px] font-medium uppercase text-text-secondary">
          {isCode ? t("notes.kindCode") : t("notes.kindFile")}
        </span>
        {!isCode && (
          <button
            type="button"
            onClick={() => useProjectStore.getState().setView({ kind: "coding", sourceId: selected.id })}
            className="flex shrink-0 items-center gap-1 rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher"
          >
            <FileText size={12} aria-hidden />
            {t("notes.openFile")}
          </button>
        )}
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => void saveMemo()}
          disabled={saving || draft === (selected.memo ?? "")}
          className="flex items-center gap-1 rounded-sm bg-accent px-2.5 py-1 text-xs font-medium text-bg hover:bg-accent-hover disabled:opacity-50"
        >
          {saving ? (
            <LoaderCircle size={12} className="animate-spin" aria-hidden />
          ) : (
            <Save size={12} aria-hidden />
          )}
          {t("common.save")}
        </button>
        <button
          type="button"
          onClick={() => void deleteMemo()}
          disabled={saving || !selected.memo}
          className="flex items-center gap-1 rounded-sm border border-border px-2.5 py-1 text-xs font-medium text-danger hover:bg-surface-higher disabled:opacity-40"
        >
          <Trash2 size={12} aria-hidden />
          {t("common.delete")}
        </button>
      </div>
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={10}
        placeholder={t("notes.memoPlaceholder")}
        aria-label={t("notes.memoPlaceholder")}
        className="mt-3 w-full flex-1 resize-none rounded-sm border border-border bg-surface px-2 py-1.5 text-sm leading-relaxed outline-none focus:border-accent"
      />
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
    </section>
  );
}
