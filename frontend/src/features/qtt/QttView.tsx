/**
 * QTT workspace — MAXQDA-style Questions-Themes-Theories worksheets.
 *
 * Left bar (QttList): the worksheet list with a create dialog (qualitative
 * or mixed template) and a per-row context menu (details / rename /
 * delete). Center (QttView): the selected worksheet — research question,
 * purpose and framework editors on top, then the worksheet's sections as
 * cards collecting insights (segments as quotes with a jump-to-source,
 * notes, chart references and links). Items can be moved between sections
 * and deleted; each section has a "new note" input.
 */
import { errorMessage } from "@/lib/utils";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUpRight,
  BarChart3,
  ExternalLink,
  LoaderCircle,
  Pencil,
  Plus,
  Quote,
  ScrollText,
  Search,
  StickyNote,
  Trash2,
} from "lucide-react";
import {
  BarHeader,
  Button,
  CountBadge,
  EmptyState,
  ErrorBanner,
  IconButton,
  Input,
  LeftBar,
  LoadingState,
  Modal,
  Select,
  Textarea,
  ViewHeader,
} from "@/components/ui/orchestrator";
import { RowContextMenu } from "@/features/shell/RowContextMenu";
import { jumpToSpan } from "@/features/coding/links";
import { useI18n } from "@/lib/i18n";
import { useWorkspaceStore } from "@/stores/workspace";
import {
  createQttItem,
  createQttSheet,
  deleteQttItem,
  deleteQttSheet,
  getQttSheet,
  listQttSheets,
  patchQttItem,
  patchQttSheet,
  type QttItem,
  type QttSheet,
  type QttSheetDetail,
  type QttSheetKind,
} from "@/lib/qttApi";

/** Jump into the coder and flash the item's source span. */
function jumpToSegment(item: QttItem) {
  const fid = Number(item.payload.fid);
  const pos0 = Number(item.payload.pos0);
  const pos1 = Number(item.payload.pos1);
  if (!Number.isFinite(fid) || !Number.isFinite(pos0) || !Number.isFinite(pos1)) return;
  useWorkspaceStore.getState().setView({ kind: "coding", sourceId: fid });
  jumpToSpan(fid, pos0, pos1);
}

/* ------------------------------------------------------------------ */
/* Left bar                                                            */
/* ------------------------------------------------------------------ */

export function QttList() {
  const { t } = useI18n();
  const qttUi = useWorkspaceStore((s) => s.qttUi);
  const setQttUi = useWorkspaceStore((s) => s.setQttUi);

  const [sheets, setSheets] = useState<QttSheet[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newKind, setNewKind] = useState<QttSheetKind>("qual");
  const [createBusy, setCreateBusy] = useState(false);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [rowMenu, setRowMenu] = useState<{ x: number; y: number; sheet: QttSheet } | null>(null);
  const [query, setQuery] = useState("");

  /** Client-side name filter — mirrors the other left bars' search boxes. */
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sheets;
    return sheets.filter((s) => s.name.toLowerCase().includes(q));
  }, [sheets, query]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSheets(await listQttSheets());
    } catch (e) {
      setError(errorMessage(e, t("qtt.loadError")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  // Refresh the list whenever the workspace ticks (create/rename/delete
  // elsewhere, e.g. a segment sent from the coder while the view is open).
  useEffect(() => {
    void load();
  }, [load, qttUi.tick]);

  async function handleCreate() {
    const name = newName.trim();
    if (!name || createBusy) return;
    setCreateBusy(true);
    setError(null);
    try {
      const sheet = await createQttSheet({ name, kind: newKind });
      setNewName("");
      setCreateOpen(false);
      setQttUi({ selectedId: sheet.id, tick: qttUi.tick + 1 });
      await load();
    } catch (e) {
      setError(errorMessage(e, t("qtt.createError")));
    } finally {
      setCreateBusy(false);
    }
  }

  async function renameSheet(sheet: QttSheet, name: string) {
    try {
      await patchQttSheet(sheet.id, { name });
      await load();
    } catch (e) {
      setError(errorMessage(e, t("qtt.renameError")));
    }
  }

  async function deleteSheet(sheet: QttSheet) {
    if (!window.confirm(t("qtt.deleteConfirm", { name: sheet.name }))) return;
    setError(null);
    try {
      await deleteQttSheet(sheet.id);
      if (qttUi.selectedId === sheet.id) setQttUi({ selectedId: null, tick: qttUi.tick + 1 });
      else setQttUi({ tick: qttUi.tick + 1 });
      await load();
    } catch (e) {
      setError(errorMessage(e, t("qtt.deleteError")));
    }
  }

  const totalItems = useMemo(
    () => sheets.reduce((sum, s) => sum + Object.values(s.counts).reduce((a, b) => a + b, 0), 0),
    [sheets],
  );

  return (
    <LeftBar
      className="h-full min-h-0"
      header={
        <BarHeader
          title={
            <span className="flex items-center gap-1.5">
              <ScrollText size={15} aria-hidden />
              {t("nav.qtt")}
            </span>
          }
          count={totalItems}
          actions={
            <Button
              variant="primary"
              icon={<Plus size={12} aria-hidden />}
              aria-label={t("common.add")}
              title={t("common.add")}
              onClick={() => setCreateOpen(true)}
            >
              {t("common.add")}
            </Button>
          }
        />
      }
    >
      {/* Search — same pattern as the files/codes left bars. */}
      <div className="relative shrink-0 border-b border-border px-3 py-1.5">
        <Search
          size={14}
          className="pointer-events-none absolute left-5 top-1/2 -translate-y-1/2 text-text-secondary"
          aria-hidden
        />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("qtt.search")}
          aria-label={t("qtt.search")}
          className="w-full pl-7!"
        />
      </div>
      {error && <ErrorBanner onClose={() => setError(null)}>{error}</ErrorBanner>}
      {loading && sheets.length === 0 ? (
        <LoadingState>{t("qtt.loading")}</LoadingState>
      ) : sheets.length === 0 ? (
        <EmptyState>{t("qtt.empty")}</EmptyState>
      ) : visible.length === 0 ? (
        <EmptyState>{t("qtt.searchEmpty")}</EmptyState>
      ) : (
        <div className="divide-y divide-border">
          {visible.map((sheet) => {
            const count = Object.values(sheet.counts).reduce((a, b) => a + b, 0);
            if (renamingId === sheet.id) {
              return (
                <div key={sheet.id} className="px-3 py-2">
                  <Input
                    defaultValue={sheet.name}
                    autoFocus
                    placeholder={t("qtt.namePlaceholder")}
                    aria-label={t("qtt.namePlaceholder")}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        const name = (e.target as HTMLInputElement).value.trim();
                        setRenamingId(null);
                        if (name && name !== sheet.name) void renameSheet(sheet, name);
                      } else if (e.key === "Escape") {
                        setRenamingId(null);
                      }
                    }}
                    onBlur={(e) => {
                      const name = e.target.value.trim();
                      setRenamingId(null);
                      if (name && name !== sheet.name) void renameSheet(sheet, name);
                    }}
                  />
                </div>
              );
            }
            return (
              <div key={sheet.id} className="qc-row-in group flex items-center">
                <button
                  type="button"
                  onClick={() => setQttUi({ selectedId: sheet.id })}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    setRowMenu({ x: e.clientX, y: e.clientY, sheet });
                  }}
                  className={`flex min-w-0 flex-1 items-center gap-1.5 px-3 py-2 text-left hover:bg-surface-higher ${
                    qttUi.selectedId === sheet.id ? "bg-accent/10" : ""
                  }`}
                >
                  <ScrollText
                    size={14}
                    className="shrink-0 text-text-secondary"
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-text-primary">{sheet.name}</span>
                    <span className="mt-0.5 flex items-center gap-1.5 text-xs text-text-secondary">
                      <span
                        className={`rounded-sm px-1 py-px text-[10px] font-medium uppercase ${
                          sheet.kind === "mixed" ? "bg-accent/15 text-accent" : "bg-surface-higher"
                        }`}
                      >
                        {sheet.kind === "mixed" ? t("qtt.kindMixed") : t("qtt.kindQual")}
                      </span>
                      <span className="truncate">
                        {count} {t("qtt.itemCount", { count })}
                      </span>
                    </span>
                  </span>
                </button>
                {/* Inline rename/delete on hover — aligned with the other bars. */}
                <span className="flex shrink-0 items-center gap-0.5 pr-2 opacity-0 transition-opacity group-hover:opacity-100">
                  <IconButton
                    label={t("qtt.renameFor", { name: sheet.name })}
                    title={t("qtt.renameFor", { name: sheet.name })}
                    size="row"
                    onClick={() => setRenamingId(sheet.id)}
                  >
                    <Pencil size={12} aria-hidden />
                  </IconButton>
                  <IconButton
                    label={t("common.delete")}
                    title={t("common.delete")}
                    size="row"
                    className="hover:text-danger"
                    onClick={() => void deleteSheet(sheet)}
                  >
                    <Trash2 size={12} aria-hidden />
                  </IconButton>
                </span>
              </div>
            );
          })}
        </div>
      )}

      {rowMenu && (
        <RowContextMenu
          x={rowMenu.x}
          y={rowMenu.y}
          onClose={() => setRowMenu(null)}
          items={[
            {
              label: t("sidebar.menuDetails"),
              icon: <ScrollText size={14} aria-hidden />,
              run: () => setQttUi({ selectedId: rowMenu.sheet.id }),
            },
            {
              label: t("common.rename"),
              icon: <Pencil size={14} aria-hidden />,
              run: () => setRenamingId(rowMenu.sheet.id),
            },
            {
              label: t("common.delete"),
              icon: <Trash2 size={14} aria-hidden />,
              danger: true,
              run: () => void deleteSheet(rowMenu.sheet),
            },
          ]}
        />
      )}

      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        size="sm"
        ariaLabel={t("qtt.createTitle")}
        title={t("qtt.createTitle")}
      >
        <div className="flex flex-col gap-3 p-3">
          <Input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && newName.trim()) void handleCreate();
            }}
            placeholder={t("qtt.namePlaceholder")}
            aria-label={t("qtt.namePlaceholder")}
          />
          <Select
            value={newKind}
            onChange={(e) => setNewKind(e.target.value as QttSheetKind)}
            aria-label={t("qtt.kindLabel")}
          >
            <option value="qual">{t("qtt.kindQual")}</option>
            <option value="mixed">{t("qtt.kindMixed")}</option>
          </Select>
          <p className="text-xs text-text-secondary">
            {newKind === "mixed" ? t("qtt.mixedHint") : t("qtt.qualHint")}
          </p>
          <div className="flex items-center justify-end gap-1.5">
            <Button variant="secondary" onClick={() => setCreateOpen(false)} disabled={createBusy}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="primary"
              icon={
                createBusy ? (
                  <span className="h-3 w-3 animate-spin rounded-full border border-current border-t-transparent" aria-hidden />
                ) : (
                  <Plus size={12} aria-hidden />
                )
              }
              onClick={() => void handleCreate()}
              disabled={createBusy || newName.trim() === ""}
            >
              {t("qtt.create")}
            </Button>
          </div>
        </div>
      </Modal>
    </LeftBar>
  );
}

/* ------------------------------------------------------------------ */
/* Center                                                              */
/* ------------------------------------------------------------------ */

function SheetInfo({ sheet, onChange }: { sheet: QttSheetDetail; onChange: () => void }) {
  const { t } = useI18n();
  const [draft, setDraft] = useState({
    research_question: sheet.research_question,
    purpose: sheet.purpose,
    framework: sheet.framework,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirtyRef = useRef(false);

  // Reset the drafts only when the selected sheet CHANGES (a reload replaces
  // the object, so keying on it would wipe what the user is typing).
  const sheetIdRef = useRef<number | null>(null);
  useEffect(() => {
    if (sheetIdRef.current === sheet.id) {
      if (!dirtyRef.current) {
        setDraft({
          research_question: sheet.research_question,
          purpose: sheet.purpose,
          framework: sheet.framework,
        });
      }
      return;
    }
    sheetIdRef.current = sheet.id;
    dirtyRef.current = false;
    setDraft({
      research_question: sheet.research_question,
      purpose: sheet.purpose,
      framework: sheet.framework,
    });
    setError(null);
  }, [sheet]);

  const dirty =
    draft.research_question !== sheet.research_question ||
    draft.purpose !== sheet.purpose ||
    draft.framework !== sheet.framework;

  async function save() {
    if (saving || !dirty) return;
    setSaving(true);
    setError(null);
    try {
      await patchQttSheet(sheet.id, {
        research_question: draft.research_question,
        purpose: draft.purpose,
        framework: draft.framework,
      });
      dirtyRef.current = false;
      onChange();
    } catch (e) {
      setError(errorMessage(e, t("qtt.infoSaveError")));
    } finally {
      setSaving(false);
    }
  }

  const field = (key: keyof typeof draft, label: string, placeholder: string, rows: number) => (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium uppercase tracking-wide text-text-secondary">{label}</span>
      <Textarea
        value={draft[key]}
        rows={rows}
        placeholder={placeholder}
        aria-label={label}
        onChange={(e) => {
          dirtyRef.current = true;
          setDraft((d) => ({ ...d, [key]: e.target.value }));
        }}
        className="w-full resize-y"
      />
    </label>
  );

  return (
    <div className="rounded-sm border border-border bg-surface p-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wide text-text-secondary">
          {t("qtt.infoTitle")}
        </h2>
        <Button
          variant="primary"
          icon={
            saving ? (
              <LoaderCircle size={12} className="animate-spin" aria-hidden />
            ) : (
              <Pencil size={12} aria-hidden />
            )
          }
          onClick={() => void save()}
          disabled={saving || !dirty}
        >
          {t("common.save")}
        </Button>
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-3">
        {field("research_question", t("qtt.researchQuestion"), t("qtt.researchQuestionPlaceholder"), 3)}
        {field("purpose", t("qtt.purpose"), t("qtt.purposePlaceholder"), 3)}
        {field("framework", t("qtt.framework"), t("qtt.frameworkPlaceholder"), 3)}
      </div>
      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
    </div>
  );
}

function ItemCard({
  item,
  sheet,
  onReload,
}: {
  item: QttItem;
  sheet: QttSheetDetail;
  onReload: () => void;
}) {
  const { t } = useI18n();
  const [error, setError] = useState<string | null>(null);

  async function move(section: string) {
    if (section === item.section) return;
    setError(null);
    try {
      await patchQttItem(item.id, { section });
      onReload();
    } catch (e) {
      setError(errorMessage(e, t("qtt.moveError")));
    }
  }

  async function remove() {
    setError(null);
    try {
      await deleteQttItem(item.id);
      onReload();
    } catch (e) {
      setError(errorMessage(e, t("qtt.itemDeleteError")));
    }
  }

  return (
    <div className="rounded-sm border border-border bg-bg px-2 py-1.5">
      <div className="flex items-start gap-1.5">
        <div className="min-w-0 flex-1">
          {item.kind === "segment" && (
            <>
              <p className="flex items-start gap-1 text-sm text-text-primary">
                <Quote size={12} className="mt-0.5 shrink-0 text-text-secondary" aria-hidden />
                <span className="line-clamp-4 whitespace-pre-wrap">
                  “{String(item.payload.text ?? "")}”
                </span>
              </p>
              {item.source_name && (
                <button
                  type="button"
                  onClick={() => jumpToSegment(item)}
                  title={t("qtt.jumpTitle")}
                  className="mt-1 flex max-w-full items-center gap-1 rounded-sm border border-border bg-surface px-1.5 py-0.5 text-[11px] text-text-secondary hover:text-accent"
                >
                  <ArrowUpRight size={11} aria-hidden />
                  <span className="truncate">{item.source_name}</span>
                </button>
              )}
            </>
          )}
          {item.kind === "note" && (
            <p className="flex items-start gap-1 text-sm text-text-primary">
              <StickyNote size={12} className="mt-0.5 shrink-0 text-text-secondary" aria-hidden />
              <span className="whitespace-pre-wrap">{String(item.payload.text ?? "")}</span>
            </p>
          )}
          {item.kind === "chart" && (
            <p className="flex items-start gap-1 text-sm text-text-primary">
              <BarChart3 size={12} className="mt-0.5 shrink-0 text-text-secondary" aria-hidden />
              <span className="min-w-0">
                <span className="block truncate font-medium">{String(item.payload.report ?? "")}</span>
                {typeof item.payload.params === "object" &&
                  item.payload.params !== null &&
                  Object.keys(item.payload.params).length > 0 && (
                    <span className="mt-0.5 block truncate text-xs text-text-secondary">
                      {JSON.stringify(item.payload.params)}
                    </span>
                  )}
              </span>
            </p>
          )}
          {item.kind === "link" && (
            <p className="flex items-start gap-1 text-sm text-text-primary">
              <ExternalLink size={12} className="mt-0.5 shrink-0 text-text-secondary" aria-hidden />
              <a
                href={String(item.payload.url ?? "")}
                target="_blank"
                rel="noreferrer"
                className="break-all text-accent hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                {String(item.payload.url ?? "")}
              </a>
            </p>
          )}
          {error && <p className="mt-1 text-xs text-danger">{error}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Select
            value={item.section}
            onChange={(e) => void move(e.target.value)}
            aria-label={t("qtt.moveLabel")}
            title={t("qtt.moveTitle")}
            className="h-6 max-w-40 text-[11px]"
          >
            {sheet.sections.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
          <IconButton
            label={t("qtt.itemDelete")}
            title={t("qtt.itemDelete")}
            size="row"
            className="hover:text-danger"
            onClick={() => void remove()}
          >
            <Trash2 size={13} aria-hidden />
          </IconButton>
        </div>
      </div>
    </div>
  );
}

function SectionCard({
  name,
  sheet,
  onReload,
}: {
  name: string;
  sheet: QttSheetDetail;
  onReload: () => void;
}) {
  const { t } = useI18n();
  const items = sheet.items[name] ?? [];
  const [newNote, setNewNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function addNote() {
    const text = newNote.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      await createQttItem(sheet.id, { section: name, kind: "note", payload: { text } });
      setNewNote("");
      onReload();
    } catch (e) {
      setError(errorMessage(e, t("qtt.noteAddError")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flex flex-col rounded-sm border border-border bg-surface">
      <header className="flex items-center gap-1.5 border-b border-border px-2 py-1.5">
        <h3 className="min-w-0 flex-1 truncate text-sm font-medium text-text-primary">{name}</h3>
        <CountBadge value={items.length} />
      </header>
      <div className="flex flex-col gap-1.5 p-2">
        <div className="flex items-center gap-1.5">
          <Input
            value={newNote}
            onChange={(e) => setNewNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void addNote();
              }
            }}
            placeholder={t("qtt.notePlaceholder")}
            aria-label={t("qtt.notePlaceholder")}
            className="min-w-0 flex-1"
          />
          <Button
            variant="secondary"
            icon={<Plus size={12} aria-hidden />}
            onClick={() => void addNote()}
            disabled={busy || newNote.trim() === ""}
            title={t("qtt.noteAdd")}
          >
            {t("qtt.noteAdd")}
          </Button>
        </div>
        {error && <p className="text-xs text-danger">{error}</p>}
        {items.length === 0 ? (
          <p className="px-1 py-2 text-center text-xs text-text-secondary">{t("qtt.sectionEmpty")}</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {items.map((item) => (
              <li key={item.id}>
                <ItemCard item={item} sheet={sheet} onReload={onReload} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

export function QttView() {
  const { t } = useI18n();
  const qttUi = useWorkspaceStore((s) => s.qttUi);
  const [sheet, setSheet] = useState<QttSheetDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (qttUi.selectedId == null) {
      setSheet(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setSheet(await getQttSheet(qttUi.selectedId));
    } catch (e) {
      setError(errorMessage(e, t("qtt.loadSheetError")));
      setSheet(null);
    } finally {
      setLoading(false);
    }
  }, [qttUi.selectedId, t]);

  // Reload on sheet switch and on any workspace tick (an item was added via
  // "Send to QTT" from the coder, an item was moved/deleted, info saved…).
  useEffect(() => {
    void load();
  }, [load, qttUi.tick]);

  if (qttUi.selectedId == null) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 bg-bg text-text-secondary">
        <ScrollText size={24} aria-hidden />
        <p className="text-sm">{t("qtt.selectHint")}</p>
      </div>
    );
  }

  if (loading && !sheet) {
    return <LoadingState>{t("qtt.loading")}</LoadingState>;
  }

  if (!sheet) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 bg-bg text-text-secondary">
        <p className="text-sm">{t("qtt.selectHint")}</p>
        {error && (
          <ErrorBanner onClose={() => setError(null)}>{error}</ErrorBanner>
        )}
      </div>
    );
  }

  const total = Object.values(sheet.counts).reduce((a, b) => a + b, 0);
  const mixed = sheet.kind === "mixed";

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col bg-bg">
      <ViewHeader
        back={false}
        title={
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="truncate">{sheet.name}</span>
            <span
              className={`shrink-0 rounded-sm px-1.5 py-px text-[10px] font-medium uppercase ${
                mixed ? "bg-accent/15 text-accent" : "bg-surface-higher text-text-secondary"
              }`}
            >
              {mixed ? t("qtt.kindMixed") : t("qtt.kindQual")}
            </span>
            <span className="shrink-0 text-xs text-text-secondary">
              {sheet.sections.length} {t("qtt.sectionCount")} · {total} {t("qtt.itemCount", { count: total })}
            </span>
          </span>
        }
      />
      {error && <ErrorBanner onClose={() => setError(null)}>{error}</ErrorBanner>}
      <div className="qc-scroll min-h-0 flex-1 overflow-y-auto p-3">
        <div className="mx-auto flex max-w-6xl flex-col gap-3">
          <SheetInfo sheet={sheet} onChange={() => void load()} />
          <div className={mixed ? "grid grid-cols-1 gap-3 xl:grid-cols-2" : "flex flex-col gap-3"}>
            {sheet.sections.map((name) => (
              <SectionCard key={name} name={name} sheet={sheet} onReload={() => void load()} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
