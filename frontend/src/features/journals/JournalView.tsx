/**
 * Journal workspace — split into the shell's left bar (JournalList) and
 * center (JournalEditor). Both share the selection via the project store.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import {
  CircleAlert,
  LoaderCircle,
  Save,
  ScrollText,
  Trash2,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { Button } from "@/components/ui/orchestrator";
import { useProjectStore } from "@/stores/project";

/** Left bar: the journal entry list (header lives in the notes left bar). */
export function JournalList() {
  const { t } = useI18n();
  const journals = useProjectStore((s) => s.journals);
  const notesUi = useProjectStore((s) => s.notesUi);
  const setNotesUi = useProjectStore((s) => s.setNotesUi);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      useProjectStore.setState({ journals: await api.journals() });
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : t("journal.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load, notesUi.tick]);

  const filtered = useMemo(() => {
    const q = notesUi.query.trim().toLowerCase();
    if (!q) return journals;
    return journals.filter(
      (j) => j.name.toLowerCase().includes(q) || j.jentry.toLowerCase().includes(q),
    );
  }, [journals, notesUi.query]);

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      {loading && journals.length === 0 ? (
        <div className="flex items-center justify-center gap-2 py-6 text-xs text-text-secondary">
          <LoaderCircle size={12} className="animate-spin" aria-hidden />
          {t("journal.loading")}
        </div>
      ) : loadError ? (
        <p className="px-3 py-6 text-center text-sm text-danger">{loadError}</p>
      ) : (
        filtered.map((j) => (
          <button
            key={j.jid}
            type="button"
            onClick={() => setNotesUi({ selectedId: j.jid })}
            className={cn(
              "block w-full border-b border-border px-3 py-2 text-left hover:bg-surface-higher",
              notesUi.selectedId === j.jid && "bg-accent/10",
            )}
          >
            <span className="block truncate text-sm font-medium">{j.name}</span>
            <span className="block truncate text-xs text-text-secondary">{j.date}</span>
          </button>
        ))
      )}
      {!loading && filtered.length === 0 && (
        <p className="px-3 py-6 text-center text-sm text-text-secondary">{t("journal.empty")}</p>
      )}
    </div>
  );
}

/** Center: the selected journal entry editor. */
export function JournalEditor() {
  const { t } = useI18n();
  const journals = useProjectStore((s) => s.journals);
  const selectedId = useProjectStore((s) => s.notesUi.selectedId);
  const setNotesUi = useProjectStore((s) => s.setNotesUi);

  const [actionError, setActionError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [entry, setEntry] = useState("");
  const [saving, setSaving] = useState(false);
  const entryRef = useRef<HTMLTextAreaElement | null>(null);

  const selected = useMemo(
    () => journals.find((j) => j.jid === selectedId) ?? null,
    [journals, selectedId],
  );

  const load = useCallback(async () => {
    try {
      useProjectStore.setState({ journals: await api.journals() });
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("journal.loadError"));
    }
  }, [t]);

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
      setNotesUi({ selectedId: null });
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("journal.deleteError"));
    }
  }

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col bg-bg">
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

      {!selected ? (
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
            <Button
              variant="primary"
              icon={
                saving ? (
                  <LoaderCircle size={12} className="animate-spin" aria-hidden />
                ) : (
                  <Save size={12} aria-hidden />
                )
              }
              onClick={() => void saveEntry()}
              disabled={saving || !dirty}
            >
              {t("common.save")}
            </Button>
            <Button
              variant="danger"
              icon={<Trash2 size={12} aria-hidden />}
              onClick={() => void deleteEntry()}
            >
              {t("common.delete")}
            </Button>
          </div>
          <textarea
            ref={entryRef}
            value={entry}
            onChange={handleEntryChange}
            placeholder={t("journal.entryPlaceholder")}
            aria-label={t("journal.entryPlaceholder")}
            className="mt-3 w-full resize-none rounded-sm border border-border bg-surface px-2 py-1.5 text-sm leading-relaxed outline-none focus:border-accent"
          />
        </div>
      )}
    </section>
  );
}
