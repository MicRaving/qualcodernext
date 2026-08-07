/**
 * NotesView — unified notes workspace: journal entries, annotations and
 * memos (file + code) with type tabs and a search filter.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CircleAlert,
  FileText,
  FolderOpen,
  Hash,
  LoaderCircle,
  NotebookPen,
  RefreshCw,
  Save,
  ScrollText,
  Search,
  StickyNote,
  Trash2,
} from "lucide-react";
import { api } from "@/lib/api";
import { JournalView } from "@/features/journals/JournalView";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";

type NotesTab = "journal" | "annotations" | "memos";

export function NotesView() {
  const { t } = useI18n();
  const setView = useProjectStore((s) => s.setView);
  const [tab, setTab] = useState<NotesTab>("journal");
  const [query, setQuery] = useState("");
  const [refreshTick, setRefreshTick] = useState(0);
  const [annotations, setAnnotations] = useState<
    { anid: number; fid: number; file_name: string; memo: string; pos0: number; pos1: number; date: string; owner: string }[]
  >([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadLists = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const anns = await api.annotationsAll();
      setAnnotations(anns);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("notes.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (tab === "journal") return;
    void loadLists();
  }, [tab, loadLists, refreshTick]);

  const q = query.trim().toLowerCase();
  const filteredAnnotations = useMemo(
    () =>
      annotations.filter(
        (a) =>
          !q ||
          a.file_name.toLowerCase().includes(q) ||
          (a.memo ?? "").toLowerCase().includes(q),
      ),
    [annotations, q],
  );

  const tabCls = (active: boolean) =>
    `rounded-sm px-2.5 py-1 text-xs font-medium ${
      active ? "bg-surface-higher text-accent" : "text-text-secondary hover:text-text-primary"
    }`;

  return (
    <div className="flex h-full flex-col bg-bg">
      <header className="flex h-10 shrink-0 items-center gap-2 border-b border-border bg-surface px-3">
        <h1 className="flex items-center gap-1.5 text-sm font-semibold text-text-primary">
          <NotebookPen size={15} aria-hidden />
          {t("nav.notes")}
        </h1>
        <div className="ml-2 flex items-center gap-0.5" role="tablist" aria-label={t("notes.tabsAria")}>
          {(
            [
              ["journal", ScrollText],
              ["annotations", StickyNote],
              ["memos", Hash],
            ] as [NotesTab, typeof ScrollText][]
          ).map(([key, Icon]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={tabCls(tab === key)}
            >
              <Icon size={12} className="mr-1 inline" aria-hidden />
              {t(`notes.tab.${key}`)}
            </button>
          ))}
        </div>
        <div className="relative ml-2">
          <Search
            size={13}
            className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-text-secondary"
            aria-hidden
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("notes.searchPlaceholder")}
            aria-label={t("notes.searchAria")}
            className="h-7 w-56 rounded-sm border border-border bg-bg pl-7 pr-2 text-sm outline-none focus:border-accent"
          />
        </div>
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => {
            setRefreshTick((n) => n + 1);
            void loadLists();
          }}
          aria-label={t("common.refresh")}
          title={t("common.refresh")}
          className="rounded-sm p-1.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
        >
          <RefreshCw size={15} aria-hidden />
        </button>
      </header>

      {error && (
        <div className="flex shrink-0 items-center gap-2 border-b border-border bg-surface px-3 py-1.5 text-sm text-danger">
          <CircleAlert size={14} aria-hidden />
          <span className="min-w-0 flex-1 truncate">{error}</span>
        </div>
      )}

      {tab === "journal" && <JournalView query={query} />}

      {tab === "annotations" && (
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {loading && filteredAnnotations.length === 0 ? (
            <div className="flex items-center justify-center gap-2 py-10 text-text-secondary">
              <LoaderCircle size={16} className="animate-spin" aria-hidden />
              {t("notes.loading")}
            </div>
          ) : filteredAnnotations.length === 0 ? (
            <p className="py-10 text-center text-sm text-text-secondary">
              {t("notes.annotationsEmpty")}
            </p>
          ) : (
            <ul className="mx-auto flex max-w-3xl flex-col gap-2">
              {filteredAnnotations.map((a) => (
                <li
                  key={a.anid}
                  className="flex items-start gap-2 rounded-sm border border-border bg-surface px-3 py-2"
                >
                  <StickyNote size={14} className="mt-0.5 shrink-0 text-text-secondary" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium">{a.file_name}</span>
                      <span className="shrink-0 text-xs text-text-secondary">
                        {a.pos0}–{a.pos1} · {a.date}
                      </span>
                    </div>
                    <p className="mt-0.5 whitespace-pre-wrap text-sm text-text-primary">
                      {a.memo || <span className="italic text-text-secondary">{t("common.noMemo")}</span>}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setView({ kind: "coding", sourceId: a.fid })}
                    className="flex shrink-0 items-center gap-1 rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher"
                  >
                    <FileText size={12} aria-hidden />
                    {t("notes.openFile")}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {tab === "memos" && <MemosPane />}
    </div>
  );
}

/** Memos pane: the code tree on the left, memo editor on the right. */
function MemosPane() {
  const { t } = useI18n();
  const codeTree = useProjectStore((s) => s.codeTree);
  const refreshProject = useProjectStore((s) => s.refreshProject);
  const [selectedCid, setSelectedCid] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedCode = useMemo(
    () => codeTree.find((c) => c.kind === "code" && c.id === selectedCid) ?? null,
    [codeTree, selectedCid],
  );

  useEffect(() => {
    setDraft(selectedCode?.memo ?? "");
    setError(null);
  }, [selectedCid, selectedCode]);

  const byParent = useMemo(() => {
    const map = new Map<number | null, { id: number; name: string; memo: string | null; kind: string }[]>();
    for (const item of codeTree) {
      const list = map.get(item.parent_id) ?? [];
      list.push(item);
      map.set(item.parent_id, list);
    }
    return map;
  }, [codeTree]);

  function renderNode(parent: number | null, depth: number): React.ReactNode {
    const items = byParent.get(parent) ?? [];
    return items.map((item) => (
      <div key={`${item.kind}-${item.id}`}>
        {item.kind === "code" ? (
          <button
            type="button"
            onClick={() => setSelectedCid(item.id)}
            className={`flex w-full items-center gap-1.5 rounded-sm px-2 py-1 text-left text-sm hover:bg-surface-higher ${
              selectedCid === item.id ? "bg-accent/10 text-accent" : ""
            }`}
            style={{ paddingLeft: `${8 + depth * 14}px` }}
            title={item.memo || undefined}
          >
            <Hash size={13} className="shrink-0 text-text-secondary" aria-hidden />
            <span className="truncate">{item.name}</span>
            {item.memo && <span className="ml-auto shrink-0 text-[10px] text-text-secondary">memo</span>}
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
        {renderNode(item.id, depth + 1)}
      </div>
    ));
  }

  async function saveMemo() {
    if (!selectedCode || saving) return;
    setSaving(true);
    setError(null);
    try {
      await api.patchCode(selectedCode.id, { memo: draft });
      await refreshProject();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("notes.memoError"));
    } finally {
      setSaving(false);
    }
  }

  async function deleteMemo() {
    if (!selectedCode || saving) return;
    if (!window.confirm(t("notes.memoDeleteConfirm", { name: selectedCode.name }))) return;
    setSaving(true);
    setError(null);
    try {
      await api.patchCode(selectedCode.id, { memo: "" });
      await refreshProject();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("notes.memoError"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 bg-bg">
      <aside className="flex w-72 shrink-0 flex-col border-r border-border bg-surface">
        <div className="min-h-0 flex-1 overflow-auto p-1">
          {codeTree.length === 0 ? (
            <p className="px-2 py-2 text-sm text-text-secondary">{t("notes.noCodes")}</p>
          ) : (
            renderNode(null, 0)
          )}
        </div>
      </aside>
      <section className="flex min-w-0 flex-1 flex-col p-4">
        {!selectedCode ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-text-secondary">
            <Hash size={24} aria-hidden />
            <p className="text-sm">{t("notes.memoSelectHint")}</p>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <h2 className="min-w-0 truncate text-base font-semibold text-text-primary">
                {selectedCode.name}
              </h2>
              <span className="shrink-0 rounded-sm bg-surface-higher px-1.5 py-px text-[10px] font-medium uppercase text-text-secondary">
                {t("notes.kindCode")}
              </span>
              <div className="flex-1" />
              <button
                type="button"
                onClick={() => void saveMemo()}
                disabled={saving || draft === (selectedCode.memo ?? "")}
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
                disabled={saving || !selectedCode.memo}
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
          </>
        )}
      </section>
    </div>
  );
}
