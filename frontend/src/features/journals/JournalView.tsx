/**
 * Journal workspace — split into the shell's left bar (JournalList) and
 * center (JournalEditor). Both share the selection via the project store.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Info,
  LoaderCircle,
  Pencil,
  Save,
  ScrollText,
  Trash2,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn, errorMessage } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { Button, ErrorBanner, IconButton, Input, ViewHeader } from "@/components/ui/orchestrator";
import { InlineNameEdit } from "@/components/ui/InlineNameEdit";
import { RowContextMenu } from "@/features/shell/RowContextMenu";
import { useWorkspaceStore } from "@/stores/workspace";
import { useProjectStore } from "@/stores/project";

/** Left bar: the journal entry list (header lives in the notes left bar). */
export function JournalList() {
  const { t } = useI18n();
  const journals = useProjectStore((s) => s.journals);
  const notesUi = useWorkspaceStore((s) => s.notesUi);
  const setNotesUi = useWorkspaceStore((s) => s.setNotesUi);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      useProjectStore.setState({ journals: await api.journals() });
    } catch (e) {
      setLoadError(errorMessage(e, t("journal.loadError")));
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

  const [rowMenu, setRowMenu] = useState<{ x: number; y: number; j: (typeof journals)[number] } | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);

  /** The row after the given journal in the visible list (Tab cycles). */
  function nextEditingId(jid: number): number | null {
    const idx = filtered.findIndex((j) => j.jid === jid);
    const next = idx >= 0 ? filtered[idx + 1] : undefined;
    return next ? next.jid : null;
  }

  async function renameJournal(j: (typeof journals)[number], name: string) {
    // Close the editor synchronously so Tab can move it to the next row.
    setEditingId(null);
    if (!name || name === j.name) return;
    try {
      await api.updateJournal(j.jid, { name, jentry: j.jentry });
      await load();
    } catch {
      /* surface via the list's reload */
    }
  }

  async function deleteJournal(j: (typeof journals)[number]) {
    if (!window.confirm(t("journal.deleteConfirm", { name: j.name }))) return;
    try {
      await api.deleteJournal(j.jid);
      if (notesUi.selectedId === j.jid) setNotesUi({ selectedId: null });
      if (editingId === j.jid) setEditingId(null);
      await load();
    } catch {
      /* surface via the list's reload */
    }
  }

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
        filtered.map((j) => {
          if (editingId === j.jid) {
            return (
              <div key={j.jid} className="border-b border-border px-3 py-2">
                <InlineNameEdit
                  value={j.name}
                  placeholder={t("journal.namePlaceholder")}
                  onSave={(name) => void renameJournal(j, name)}
                  onCancel={() => setEditingId(null)}
                  onTab={() => setEditingId(nextEditingId(j.jid))}
                />
              </div>
            );
          }
          return (
            <div key={j.jid} className="group border-b border-border">
              <button
                type="button"
                onClick={() => setNotesUi({ selectedId: j.jid })}
                onContextMenu={(e) => {
                  e.preventDefault();
                  setRowMenu({ x: e.clientX, y: e.clientY, j });
                }}
                className={cn(
                  "flex w-full items-center gap-1.5 px-3 py-2 text-left hover:bg-surface-higher",
                  notesUi.selectedId === j.jid && "bg-accent/10",
                )}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{j.name}</span>
                  <span className="block truncate text-xs text-text-secondary">{j.date}</span>
                </span>
                <span className="ml-auto flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 hover:opacity-100">
                  <IconButton
                    label={t("notes.renameFor", { name: j.name })}
                    title={t("notes.renameFor", { name: j.name })}
                    size="row"
                    onClick={(e) => {
                      e.stopPropagation();
                      setEditingId(j.jid);
                    }}
                  >
                    <Pencil size={12} aria-hidden />
                  </IconButton>
                  <IconButton
                    label={t("notes.deleteFor", { name: j.name })}
                    title={t("common.delete")}
                    size="row"
                    className="hover:text-danger"
                    onClick={(e) => {
                      e.stopPropagation();
                      void deleteJournal(j);
                    }}
                  >
                    <Trash2 size={12} aria-hidden />
                  </IconButton>
                </span>
              </button>
            </div>
          );
        })
      )}
      {!loading && filtered.length === 0 && (
        <p className="px-3 py-6 text-center text-sm text-text-secondary">{t("journal.empty")}</p>
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
              run: () => setNotesUi({ selectedId: rowMenu.j.jid }),
            },
            {
              label: t("common.rename"),
              icon: <Pencil size={14} aria-hidden />,
              run: () => setEditingId(rowMenu.j.jid),
            },
            {
              label: t("common.delete"),
              icon: <Trash2 size={14} aria-hidden />,
              danger: true,
              run: () => void deleteJournal(rowMenu.j),
            },
          ]}
        />
      )}
    </div>
  );
}

/** Center: the selected journal entry editor. */
export function JournalEditor() {
  const { t } = useI18n();
  const journals = useProjectStore((s) => s.journals);
  const selectedId = useWorkspaceStore((s) => s.notesUi.selectedId);
  const setNotesUi = useWorkspaceStore((s) => s.setNotesUi);

  const [actionError, setActionError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [entry, setEntry] = useState("");
  const [saving, setSaving] = useState(false);

  const selected = useMemo(
    () => journals.find((j) => j.jid === selectedId) ?? null,
    [journals, selectedId],
  );

  const load = useCallback(async () => {
    try {
      useProjectStore.setState({ journals: await api.journals() });
    } catch (e) {
      setActionError(errorMessage(e, t("journal.loadError")));
    }
  }, [t]);

  // Reset the draft only when the SELECTED journal changes — a refresh
  // (e.g. a background transcription finishing) replaces the journals
  // array with fresh objects, and resetting on that would silently wipe
  // whatever the user is typing. Unsaved edits are never overwritten.
  const prevJidRef = useRef<number | null>(null);
  const dirtyRef = useRef(false);
  useEffect(() => {
    const j = selected;
    if (!j) return;
    if (prevJidRef.current === j.jid) {
      if (!dirtyRef.current) {
        setName(j.name);
        setEntry(j.jentry);
      }
      return;
    }
    prevJidRef.current = j.jid;
    dirtyRef.current = false;
    setName(j.name);
    setEntry(j.jentry);
  }, [selected]);

  function handleEntryChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    dirtyRef.current = true;
    setEntry(e.target.value);
  }

  function handleNameChange(v: string) {
    dirtyRef.current = true;
    setName(v);
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
      setActionError(errorMessage(e, t("journal.saveError")));
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
      setActionError(errorMessage(e, t("journal.deleteError")));
    }
  }

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col bg-bg">
      {actionError && (
        <ErrorBanner onClose={() => setActionError(null)}>{actionError}</ErrorBanner>
      )}

      {!selected ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 text-text-secondary">
          <ScrollText size={24} aria-hidden />
          <p className="text-sm">{t("journal.selectHint")}</p>
        </div>
      ) : (
        <>
          <ViewHeader
            back={false}
            title={
              <Input
                value={name}
                onChange={(e) => handleNameChange(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void saveEntry();
                }}
                placeholder={t("journal.namePlaceholder")}
                aria-label={t("journal.namePlaceholder")}
                className="w-64 min-w-0 font-normal"
              />
            }
            actions={
              <>
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
              </>
            }
          />
          <div className="flex min-h-0 flex-1 flex-col p-4">
            <textarea
              value={entry}
              onChange={handleEntryChange}
              placeholder={t("journal.entryPlaceholder")}
              aria-label={t("journal.entryPlaceholder")}
              className="min-h-0 w-full flex-1 resize-none rounded-sm border border-border bg-surface px-2 py-1.5 text-sm leading-relaxed outline-none focus:border-accent"
            />
          </div>
        </>
      )}
    </section>
  );
}
