/**
 * CreativePanel — MAXQDA-style creative coding scratchpad as a right-bar
 * pane: collect ideas, quotes and fragments, edit them inline, and promote
 * an item into a new code. Promoting a sourced item additionally codes the
 * referenced span with the new code.
 */
import { errorMessage } from "@/lib/utils";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  Lightbulb,
  Pencil,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import {
  BarHeader,
  BarTitle,
  Button,
  EmptyState,
  ErrorBanner,
  IconButton,
  Input,
  LeftBar,
  LoadingState,
  Modal,
  Select,
  Textarea,
} from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useWorkspaceStore } from "@/stores/workspace";
import { useProjectStore } from "@/stores/project";
import {
  createCreativeItem,
  deleteCreativeItem,
  listCreativeItems,
  patchCreativeItem,
  promoteCreativeItem,
  type CreativeItem,
} from "@/lib/creativeApi";

export function CreativePanel() {
  const { t } = useI18n();
  const codeTree = useProjectStore((s) => s.codeTree);
  const [items, setItems] = useState<CreativeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const [newText, setNewText] = useState("");
  const [newBusy, setNewBusy] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [editNote, setEditNote] = useState("");
  const [editBusy, setEditBusy] = useState(false);

  const [promoting, setPromoting] = useState<CreativeItem | null>(null);
  const [codeName, setCodeName] = useState("");
  const [catid, setCatid] = useState("");
  const [promoteBusy, setPromoteBusy] = useState(false);
  const [promoteError, setPromoteError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await listCreativeItems());
    } catch (e) {
      setError(errorMessage(e, t("creative.loadError")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const categories = useMemo(
    () =>
      codeTree
        .filter((c) => c.kind === "category")
        .sort((a, b) => a.name.localeCompare(b.name)),
    [codeTree],
  );

  const visibleItems = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (i) =>
        i.text.toLowerCase().includes(q) ||
        i.note.toLowerCase().includes(q) ||
        i.source_name.toLowerCase().includes(q),
    );
  }, [items, query]);

  async function handleAdd() {
    const text = newText.trim();
    if (!text || newBusy) return;
    setNewBusy(true);
    setError(null);
    try {
      await createCreativeItem({ text });
      setNewText("");
      await load();
    } catch (e) {
      setError(errorMessage(e, t("creative.addError")));
    } finally {
      setNewBusy(false);
    }
  }

  function startEdit(item: CreativeItem) {
    setEditingId(item.id);
    setEditText(item.text);
    setEditNote(item.note ?? "");
  }

  async function handleSaveEdit(item: CreativeItem) {
    const text = editText.trim();
    if (!text || editBusy) return;
    setEditBusy(true);
    setError(null);
    try {
      const updated = await patchCreativeItem(item.id, {
        text,
        note: editNote,
      });
      setItems((prev) => prev.map((i) => (i.id === item.id ? updated : i)));
      setEditingId(null);
    } catch (e) {
      setError(errorMessage(e, t("creative.saveError")));
    } finally {
      setEditBusy(false);
    }
  }

  async function handleDelete(item: CreativeItem) {
    setError(null);
    try {
      await deleteCreativeItem(item.id);
      setItems((prev) => prev.filter((i) => i.id !== item.id));
    } catch (e) {
      setError(errorMessage(e, t("creative.deleteError")));
    }
  }

  function openPromote(item: CreativeItem) {
    setPromoting(item);
    setCodeName(item.text.length <= 60 ? item.text : "");
    setCatid("");
    setPromoteError(null);
  }

  async function handlePromote() {
    if (!promoting || promoteBusy) return;
    const name = codeName.trim();
    if (!name) return;
    setPromoteBusy(true);
    setPromoteError(null);
    try {
      await promoteCreativeItem(promoting.id, {
        code_name: name,
        catid: catid === "" ? null : Number(catid),
      });
      setPromoting(null);
      void useProjectStore.getState().refreshProject();
      await load();
    } catch (e) {
      setPromoteError(errorMessage(e, t("creative.promoteError")));
    } finally {
      setPromoteBusy(false);
    }
  }

  function jumpToSource(item: CreativeItem) {
    if (item.source_fid == null) return;
    useWorkspaceStore.getState().setView({ kind: "coding", sourceId: item.source_fid });
  }

  return (
    <LeftBar
      borderSide="l"
      className="h-full min-h-0"
      header={
        <>
          <BarHeader title={<BarTitle icon={Lightbulb} label={t("creative.title")} />} />
          {/* Add-note input */}
          <div className="flex shrink-0 flex-col gap-1.5 border-b border-border px-3 py-1.5">
            <Textarea
              value={newText}
              onChange={(e) => setNewText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void handleAdd();
                }
              }}
              placeholder={t("creative.addPlaceholder")}
              aria-label={t("creative.addPlaceholder")}
              rows={2}
              className="w-full"
            />
            <Button
              variant="primary"
              onClick={() => void handleAdd()}
              disabled={newBusy || newText.trim() === ""}
              icon={<Plus size={12} aria-hidden />}
              className="self-end"
            >
              {t("creative.add")}
            </Button>
          </div>
          {/* Search box */}
          <div className="relative shrink-0 border-b border-border px-3 py-1.5">
            <Search
              size={14}
              className="pointer-events-none absolute left-5 top-1/2 -translate-y-1/2 text-text-secondary"
              aria-hidden
            />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("creative.searchPlaceholder")}
              aria-label={t("creative.searchPlaceholder")}
              className="w-full pl-7!"
            />
          </div>
        </>
      }
    >
      {error && <ErrorBanner onClose={() => setError(null)}>{error}</ErrorBanner>}

      {loading && items.length === 0 ? (
        <LoadingState>{t("creative.loading")}</LoadingState>
      ) : items.length === 0 ? (
        <EmptyState>{t("creative.empty")}</EmptyState>
      ) : (
        <ul className="divide-y divide-border">
          {visibleItems.map((item) => {
            const editing = editingId === item.id;
            return (
              <li key={item.id} className="flex flex-col gap-1.5 px-3 py-2">
                {editing ? (
                  <>
                    <Textarea
                      value={editText}
                      onChange={(e) => setEditText(e.target.value)}
                      aria-label={t("creative.editText")}
                      rows={2}
                      className="w-full"
                    />
                    <Input
                      value={editNote}
                      onChange={(e) => setEditNote(e.target.value)}
                      placeholder={t("creative.notePlaceholder")}
                      aria-label={t("creative.notePlaceholder")}
                      className="w-full"
                    />
                    <div className="flex items-center gap-1.5">
                      <Button
                        variant="primary"
                        onClick={() => void handleSaveEdit(item)}
                        disabled={editBusy || editText.trim() === ""}
                      >
                        {t("common.save")}
                      </Button>
                      <Button variant="secondary" onClick={() => setEditingId(null)}>
                        {t("common.cancel")}
                      </Button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="flex items-start gap-1.5">
                      <button
                        type="button"
                        onClick={() => startEdit(item)}
                        className="min-w-0 flex-1 text-left"
                        title={t("creative.editTitle")}
                      >
                        <p className="text-sm text-text-primary">{item.text}</p>
                        {item.note && (
                          <p className="mt-0.5 text-xs text-text-secondary">{item.note}</p>
                        )}
                      </button>
                      <IconButton
                        label={t("creative.editTitle")}
                        title={t("creative.editTitle")}
                        size="row"
                        onClick={() => startEdit(item)}
                      >
                        <Pencil size={13} aria-hidden />
                      </IconButton>
                      <IconButton
                        label={t("creative.delete")}
                        title={t("creative.delete")}
                        size="row"
                        onClick={() => void handleDelete(item)}
                      >
                        <Trash2 size={13} aria-hidden />
                      </IconButton>
                    </div>
                    {item.source_fid != null && (
                      <button
                        type="button"
                        onClick={() => jumpToSource(item)}
                        title={t("creative.jumpTitle")}
                        className="flex min-w-0 items-center gap-1 self-start rounded-sm border border-border bg-bg px-1.5 py-0.5 text-[11px] text-text-secondary hover:text-accent"
                      >
                        <ArrowUpRight size={11} aria-hidden />
                        <span className="truncate">{item.source_name}</span>
                        {item.source_text && (
                          <span className="truncate text-text-secondary/70">
                            “{item.source_text}”
                          </span>
                        )}
                      </button>
                    )}
                  </>
                )}
                <div className="flex items-center gap-1.5">
                  <Button
                    variant="secondary"
                    icon={<Lightbulb size={11} aria-hidden />}
                    onClick={() => openPromote(item)}
                    className="ml-auto"
                  >
                    {t("creative.promote")}
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {visibleItems.length === 0 && items.length > 0 && (
        <p className="px-3 py-6 text-center text-sm text-text-secondary">
          {t("creative.noMatch")}
        </p>
      )}

      {/* Promote dialog */}
      <Modal
        open={promoting !== null}
        onClose={() => setPromoting(null)}
        size="sm"
        ariaLabel={t("creative.promoteTitle")}
        title={
          <span className="flex items-center gap-1.5">
            <Lightbulb size={14} aria-hidden />
            {t("creative.promoteTitle")}
          </span>
        }
      >
        {promoting && (
          <div className="flex flex-col gap-3 p-3">
            <div>
              <p className="text-xs font-medium text-text-secondary">{t("creative.promoteItem")}</p>
              <p className="mt-1 text-sm text-text-primary">{promoting.text}</p>
              {promoting.source_name && (
                <p className="mt-1 text-xs text-text-secondary">
                  {promoting.source_name}
                  {promoting.source_text ? ` · “${promoting.source_text}”` : ""}
                </p>
              )}
              {promoting.source_fid != null && (
                <p className="mt-1 text-xs text-text-secondary">{t("creative.promoteCodingHint")}</p>
              )}
            </div>
            <Input
              autoFocus
              value={codeName}
              onChange={(e) => setCodeName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && codeName.trim()) void handlePromote();
              }}
              placeholder={t("creative.codeNamePlaceholder")}
              aria-label={t("creative.codeNamePlaceholder")}
            />
            <Select
              value={catid}
              onChange={(e) => setCatid(e.target.value)}
              aria-label={t("creative.categoryLabel")}
            >
              <option value="">{t("creative.noCategory")}</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
            {promoteError && <p className="text-xs text-danger">{promoteError}</p>}
            <div className="flex items-center justify-end gap-1.5">
              <Button variant="secondary" onClick={() => setPromoting(null)} disabled={promoteBusy}>
                {t("common.cancel")}
              </Button>
              <Button
                variant="primary"
                onClick={() => void handlePromote()}
                disabled={promoteBusy || codeName.trim() === ""}
                icon={
                  promoteBusy ? (
                    <span className="h-3 w-3 animate-spin rounded-full border border-current border-t-transparent" aria-hidden />
                  ) : (
                    <Lightbulb size={12} aria-hidden />
                  )
                }
              >
                {t("creative.promote")}
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </LeftBar>
  );
}
