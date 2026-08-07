/**
 * JournalView — journal pane embedded in the Notes workspace: create, edit
 * and delete journal entries.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import {
  CircleAlert,
  LoaderCircle,
  Plus,
  RefreshCw,
  Save,
  ScrollText,
  Trash2,
  X,
} from "lucide-react";
import { api, type Journal } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";

const primaryBtnCls =
  "flex items-center gap-1 rounded-sm bg-accent px-2.5 py-1 text-xs font-medium text-bg hover:bg-accent-hover disabled:opacity-50";
const iconBtnCls =
  "rounded-sm p-1 text-text-secondary hover:bg-surface-higher hover:text-text-primary";

export function JournalView({ query = "" }: { query?: string }) {
  const { t } = useI18n();
  const [journals, setJournals] = useState<Journal[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [entry, setEntry] = useState("");
  const [saving, setSaving] = useState(false);
  const entryRef = useRef<HTMLTextAreaElement | null>(null);

  const selected = useMemo(
    () => journals.find((j) => j.jid === selectedId) ?? null,
    [journals, selectedId],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return journals;
    return journals.filter(
      (j) => j.name.toLowerCase().includes(q) || j.jentry.toLowerCase().includes(q),
    );
  }, [journals, query]);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setJournals(await api.journals());
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : t("journal.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setName(selected?.name ?? "");
    setEntry(selected?.jentry ?? "");
    if (entryRef.current) entryRef.current.style.height = "auto";
  }, [selected]);

  function growTextarea(el: HTMLTextAreaElement) {
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }

  function handleEntryChange(e: ChangeEvent<HTMLTextAreaElement>) {
    setEntry(e.target.value);
    growTextarea(e.currentTarget);
  }

  const dirty = selected != null && (name !== selected.name || entry !== selected.jentry);

  async function newEntry() {
    setActionError(null);
    try {
      const created = await api.createJournal(t("journal.untitled"), "");
      setSelectedId(created.jid);
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("journal.createError"));
    }
  }

  async function saveEntry() {
    if (!selected || saving) return;
    setSaving(true);
    setActionError(null);
    try {
      await api.updateJournal(selected.jid, { name, jentry: entry });
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("journal.saveError"));
    } finally {
      setSaving(false);
    }
  }

  async function deleteEntry() {
    if (!selected) return;
    if (!window.confirm(t("journal.deleteConfirm", { name: selected.name }))) return;
    setActionError(null);
    try {
      await api.deleteJournal(selected.jid);
      setSelectedId(null);
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("journal.deleteError"));
    }
  }

  return (
    <div className="flex min-h-0 flex-1 bg-bg">
      {/* LEFT: entry list */}
      <aside className="flex w-72 shrink-0 flex-col border-r border-border bg-surface">
        <header className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-3">
          <h2 className="text-sm font-semibold text-text-primary">{t("notes.tab.journal")}</h2>
          <span className="rounded-sm bg-surface-higher px-1.5 py-px text-xs font-medium text-text-secondary">
            {journals.length}
          </span>
          <button
            type="button"
            onClick={() => void load()}
            aria-label={t("common.refresh")}
            title={t("common.refresh")}
            className={iconBtnCls}
          >
            <RefreshCw size={14} aria-hidden />
          </button>
          <div className="flex-1" />
          <button type="button" onClick={() => void newEntry()} className={primaryBtnCls}>
            <Plus size={14} aria-hidden />
            {t("journal.newEntry")}
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto">
          {filtered.map((j) => (
            <button
              key={j.jid}
              type="button"
              onClick={() => setSelectedId(j.jid)}
              className={cn(
                "block w-full border-b border-border px-3 py-2 text-left hover:bg-surface-higher",
                selectedId === j.jid && "bg-accent/10",
              )}
            >
              <span className="block truncate text-sm font-medium">{j.name}</span>
              <span className="block truncate text-xs text-text-secondary">{j.date}</span>
            </button>
          ))}
          {!loading && filtered.length === 0 && (
            <p className="px-3 py-6 text-center text-sm text-text-secondary">
              {t("journal.empty")}
            </p>
          )}
        </div>
      </aside>

      {/* RIGHT: editor */}
      <section className="flex min-w-0 flex-1 flex-col">
        {actionError && (
          <div className="flex shrink-0 items-center gap-2 border-b border-border bg-surface px-3 py-1.5 text-sm text-danger">
            <CircleAlert size={14} aria-hidden />
            <span className="min-w-0 flex-1 truncate">{actionError}</span>
            <button
              type="button"
              onClick={() => setActionError(null)}
              aria-label={t("common.dismiss")}
              className="rounded-sm p-0.5 hover:bg-surface-higher"
            >
              <X size={14} aria-hidden />
            </button>
          </div>
        )}

        {loading && journals.length === 0 ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-text-secondary">
            <LoaderCircle size={16} className="animate-spin" aria-hidden />
            {t("journal.loading")}
          </div>
        ) : loadError ? (
          <div className="flex flex-1 items-center justify-center">
            <div className="max-w-md text-center">
              <p className="flex items-center justify-center gap-1.5 text-sm text-danger">
                <CircleAlert size={16} aria-hidden />
                {loadError}
              </p>
              <button
                type="button"
                onClick={() => void load()}
                className="mt-3 rounded-sm border border-border bg-surface px-3 py-1.5 text-sm hover:bg-surface-higher"
              >
                {t("common.retry")}
              </button>
            </div>
          </div>
        ) : !selected ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-text-secondary">
            <ScrollText size={24} aria-hidden />
            <p className="text-sm">{t("journal.selectHint")}</p>
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void saveEntry();
                }}
                placeholder={t("journal.namePlaceholder")}
                aria-label={t("journal.namePlaceholder")}
                className="h-7 min-w-0 flex-1 rounded-sm border border-border bg-surface px-2 text-sm outline-none focus:border-accent"
              />
              <button
                type="button"
                onClick={() => void saveEntry()}
                disabled={saving || !dirty}
                className={primaryBtnCls}
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
                onClick={() => void deleteEntry()}
                className="flex items-center gap-1 rounded-sm border border-border px-2.5 py-1 text-xs font-medium text-danger hover:bg-surface-higher"
              >
                <Trash2 size={12} aria-hidden />
                {t("common.delete")}
              </button>
            </div>
            <textarea
              ref={entryRef}
              value={entry}
              onChange={handleEntryChange}
              rows={8}
              placeholder={t("journal.entryPlaceholder")}
              aria-label={t("journal.entryPlaceholder")}
              className="mt-3 w-full resize-none rounded-sm border border-border bg-surface px-2 py-1.5 text-sm leading-relaxed outline-none focus:border-accent"
            />
            <p className="mt-1.5 text-xs text-text-secondary">
              {selected.date} · {selected.owner}
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
