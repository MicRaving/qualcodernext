/**
 * FileManager — browse, search, import and manage project sources.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type MouseEvent,
} from "react";
import {
  ArrowDown,
  ArrowUp,
  CircleAlert,
  Info,
  FileAudio,
  FileImage,
  FileText,
  Link2,
  LoaderCircle,
  MoreHorizontal,
  Pencil,
  RefreshCw,
  Replace,
  Search,
  StickyNote,
  Trash2,
  Upload,
  UserRound,
  X,
} from "lucide-react";
import { api, ApiError, type BadLink, type FileFilter, type Source } from "@/lib/api";
import { isPdf } from "@/lib/media";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { ViewHeader } from "@/components/ui/orchestrator";
import { useProjectStore } from "@/stores/project";
import {
  filterSources,
  mediaTypeLabel,
  sortSources,
  type SortDir,
  type SortKey,
} from "@/features/manage/files";
import { ROW_HEIGHT, visibleRange } from "@/features/manage/virtual";

function fileIcon(mediaType: string) {
  if (mediaType === "image") {
    return <FileImage size={14} className="shrink-0 text-text-secondary" aria-hidden />;
  }
  if (mediaType === "audio" || mediaType === "video") {
    return <FileAudio size={14} className="shrink-0 text-text-secondary" aria-hidden />;
  }
  return <FileText size={14} className="shrink-0 text-text-secondary" aria-hidden />;
}

function SortableTh({
  label,
  sortKey,
  active,
  dir,
  onSort,
}: {
  label: string;
  sortKey: SortKey;
  active: boolean;
  dir: SortDir;
  onSort: (key: SortKey) => void;
}) {
  return (
    <th className="border-b border-border px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-text-secondary">
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cn(
          "flex items-center gap-1 hover:text-text-primary",
          active && "text-accent",
        )}
      >
        {label}
        {active &&
          (dir === "asc" ? (
            <ArrowUp size={12} aria-hidden />
          ) : (
            <ArrowDown size={12} aria-hidden />
          ))}
      </button>
    </th>
  );
}

export function FileManager() {
  const { t } = useI18n();
  const setView = useProjectStore((s) => s.setView);
  const selectFile = useProjectStore((s) => s.selectFile);
  const sources = useProjectStore((s) => s.sources);

  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ id: number; x: number; y: number } | null>(null);
  const [linkModal, setLinkModal] = useState(false);
  const [badLinks, setBadLinks] = useState<BadLink[]>([]);
  const [filters, setFilters] = useState<FileFilter[]>([]);
  const [activeFilter, setActiveFilter] = useState<number | "">("");

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const replaceInputRef = useRef<HTMLInputElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const list = await api.sources();
      useProjectStore.setState({ sources: list });
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : t("files.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  const loadFilters = useCallback(async () => {
    try {
      const res = await api.fileFilters();
      setFilters(res.filters);
    } catch {
      setFilters([]);
    }
  }, []);

  useEffect(() => {
    void load();
    void loadFilters();
  }, [load, loadFilters]);

  const applyFilter = useCallback((f: FileFilter) => {
    try {
      const parsed = JSON.parse(f.filter) as { query?: string };
      setQuery(parsed.query ?? "");
    } catch {
      setQuery("");
    }
  }, []);

  async function saveCurrentFilter() {
    const name = window.prompt(t("files.filtersNamePrompt"));
    if (!name?.trim()) return;
    try {
      const filterJson = JSON.stringify({ query });
      await api.createFileFilter(name.trim(), filterJson);
      await loadFilters();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("files.filtersSave"));
    }
  }

  async function removeFilter(f: FileFilter) {
    if (!window.confirm(t("files.filtersDeleteConfirm", { name: f.name }))) return;
    try {
      await api.deleteFileFilter(f.filterid);
      setActiveFilter("");
      setQuery("");
      await loadFilters();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("files.filtersDelete"));
    }
  }

  async function openLinkModal() {
    setLinkModal(true);
    try {
      const res = await api.badLinks();
      setBadLinks(res.links);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("files.badLinksHint"));
      setBadLinks([]);
    }
  }

  async function fixLink(link: BadLink) {
    const path = window.prompt(t("files.badLinksFixPrompt", { name: link.name }), link.path);
    if (path === null) return;
    try {
      await api.fixLink(link.id, path);
      setBadLinks((list) => list.filter((l) => l.id !== link.id));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("files.badLinksHint"));
    }
  }

  async function bulkRename() {
    const old = window.prompt(t("files.bulkRenameOld"));
    if (old === null || !old.trim()) return;
    const next = window.prompt(t("files.bulkRenameNew"));
    if (next === null) return;
    try {
      const res = await api.bulkRenamePath(old.trim(), next);
      setActionError(t("files.bulkRenameDone", { updated: String(res.updated) }));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("files.badLinksHint"));
    }
  }

  async function replaceSourceFile(row: Source, file: File) {
    try {
      const res = await api.replaceSource(row.id, file);
      await load();
      setActionError(t("files.replaced", { message: res.message }));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("files.replaceError"));
    }
  }

  // Close the row actions menu with Escape.
  useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenu(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menu]);

  const filtered = useMemo(() => filterSources(sources, query), [sources, query]);  const rows = useMemo(
    () => sortSources(filtered, sortKey, sortDir),
    [filtered, sortKey, sortDir],
  );
  const menuRow = menu ? rows.find((r) => r.id === menu.id) : undefined;

  // Measure the scroll viewport so the visible row window tracks its size.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const update = () => setViewportHeight(el.clientHeight);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [loading, loadError, sources.length, rows.length]);

  // Window math: only rows [start, end) are mounted; spacers preserve the
  // scrollbar size, so the DOM stays O(visible) regardless of total.
  const { start, end } = visibleRange(scrollTop, viewportHeight, rows.length);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  async function importFiles(list: File[]) {
    if (list.length === 0) return;
    setSkipped([]);
    setActionError(null);
    useProjectStore.getState().setImportState({ done: 0, total: list.length });
    const dupes: string[] = [];
    let failed: string | null = null;
    for (let i = 0; i < list.length; i++) {
      const file = list[i];
      try {
        const src = await api.importSource(file);
        useProjectStore.setState((s) => ({
          sources: [...s.sources.filter((x) => x.name !== src.name), src],
        }));
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          dupes.push(file.name);
        } else {
          failed = e instanceof Error ? e.message : t("files.importFailed", { name: file.name });
        }
      }
      useProjectStore.getState().setImportState({ done: i + 1, total: list.length });
    }
    useProjectStore.getState().setImportState(null);
    setSkipped(dupes);
    if (failed) setActionError(failed);
    await load();
  }

  function handleFilesChange(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    void importFiles(files);
  }

  async function renameSource(row: Source) {
    const next = window.prompt(t("files.renamePrompt", { name: row.name }), row.name);
    if (next === null) return;
    const name = next.trim();
    if (!name || name === row.name) return;
    try {
      const updated = await api.patchSource(row.id, { name });
      useProjectStore.setState((s) => ({
        sources: s.sources.map((x) => (x.id === updated.id ? updated : x)),
      }));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("files.renameError"));
    }
  }

  async function editMemo(row: Source) {
    const next = window.prompt(t("files.memoPrompt", { name: row.name }), row.memo);
    if (next === null) return;
    try {
      const updated = await api.patchSource(row.id, { memo: next });
      useProjectStore.setState((s) => ({
        sources: s.sources.map((x) => (x.id === updated.id ? updated : x)),
      }));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("files.memoError"));
    }
  }

  async function deleteSource(row: Source) {
    if (!window.confirm(t("files.deleteConfirm", { name: row.name }))) return;
    try {
      await api.deleteSource(row.id);
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("files.deleteError"));
    }
  }

  async function assignToCase(row: Source) {
    const name = window.prompt(t("files.assignCasePrompt", { name: row.name }));
    if (name === null) return;
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      const casesList = await api.cases();
      const match = casesList.find((c) => c.name === trimmed);
      if (!match) {
        setActionError(t("files.assignCaseNotFound", { name: trimmed }));
        return;
      }
      await api.linkFileToCase(match.caseid, row.id);
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("files.assignCaseError"));
    }
  }

  function openMenu(e: MouseEvent<HTMLButtonElement>, row: Source) {
    e.stopPropagation();
    const rect = e.currentTarget.getBoundingClientRect();
    setMenu({ id: row.id, x: rect.right, y: rect.bottom + 4 });
  }

  function openMenuAt(e: MouseEvent<HTMLTableRowElement>, row: Source) {
    e.preventDefault();
    setMenu({ id: row.id, x: e.clientX, y: e.clientY });
  }

  const primaryBtnCls =
    "flex items-center gap-1 rounded-sm bg-accent px-2.5 py-1 text-xs font-medium text-bg hover:bg-accent-hover";

  return (
    <div className="flex h-full flex-col bg-bg">
      {/* Header */}
      <ViewHeader
        title={t("nav.files")}
        meta={
          <span className="rounded-sm bg-surface-higher px-1.5 py-px text-xs font-medium text-text-secondary">
            {rows.length}
          </span>
        }
        actions={
          <>
            <div className="relative ml-2">
          <Search
            size={14}
            className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-text-secondary"
            aria-hidden
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("files.searchPlaceholder")}
            aria-label={t("files.searchAria")}
            className="h-7 w-56 rounded-sm border border-border bg-bg pl-7 pr-2 text-sm outline-none focus:border-accent"
          />
        </div>
        {filters.length > 0 && (
          <div className="flex items-center gap-1">
            <select
              value={activeFilter}
              onChange={(e) => {
                const id = e.target.value === "" ? "" : Number(e.target.value);
                setActiveFilter(id);
                const f = filters.find((x) => x.filterid === id);
                if (f) applyFilter(f);
              }}
              className="h-7 rounded-sm border border-border bg-bg px-1.5 text-xs outline-none focus:border-accent"
              aria-label={t("files.filters")}
            >
              <option value="">{t("files.filtersAll")}</option>
              {filters.map((f) => (
                <option key={f.filterid} value={f.filterid}>
                  {f.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void saveCurrentFilter()}
              title={t("files.filtersSave")}
              className="rounded-sm p-1 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
            >
              <StickyNote size={13} aria-hidden />
            </button>
            {activeFilter !== "" && (
              <button
                type="button"
                onClick={() => {
                  const f = filters.find((x) => x.filterid === activeFilter);
                  if (f) void removeFilter(f);
                }}
                title={t("files.filtersDelete")}
                className="rounded-sm p-1 text-text-secondary hover:bg-danger/10 hover:text-danger"
              >
                <Trash2 size={13} aria-hidden />
              </button>
            )}
          </div>
        )}
        <button
          type="button"
          onClick={() => void openLinkModal()}
          title={t("files.badLinks")}
          className="rounded-sm p-1.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
        >
          <Link2 size={15} aria-hidden />
        </button>
        <button
          type="button"
          onClick={() => void load()}
          aria-label={t("files.refreshAria")}
          title={t("common.refresh")}
          className="rounded-sm p-1.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
        >
          <RefreshCw size={16} aria-hidden />
        </button>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          className={primaryBtnCls}
        >
          <Upload size={14} aria-hidden />
          {t("files.import")}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          hidden
          aria-hidden
          onChange={handleFilesChange}
        />
          </>
        }
      />

      {/* Inline notices */}
      {skipped.length > 0 && (
        <div
          role="status"
          className="flex shrink-0 items-center gap-2 border-b border-border bg-surface px-3 py-1.5 text-sm text-warning"
        >
          <CircleAlert size={14} aria-hidden />
          <span className="min-w-0 flex-1 truncate">
            {t("files.skipped", {
              names: skipped.map((n) => t("files.duplicate", { name: n })).join(", "),
            })}
          </span>
          <button
            type="button"
            onClick={() => setSkipped([])}
            aria-label={t("common.dismiss")}
            className="rounded-sm p-0.5 hover:bg-surface-higher"
          >
            <X size={14} aria-hidden />
          </button>
        </div>
      )}
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

      {/* Body */}
      {loading && sources.length === 0 ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-text-secondary">
          <LoaderCircle size={16} className="animate-spin" aria-hidden />
          {t("files.loading")}
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
      ) : sources.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3">
          <p className="text-sm text-text-secondary">
            {t("files.empty")}
          </p>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className={cn(primaryBtnCls, "px-3 py-1.5 text-sm")}
          >
            <Upload size={14} aria-hidden />
            {t("files.importFiles")}
          </button>
        </div>
      ) : rows.length === 0 ? (
        <div className="flex flex-1 items-center justify-center">
          <p className="text-sm text-text-secondary">
            {t("files.noMatch", { query })}
          </p>
        </div>
      ) : (
        <div
          ref={scrollRef}
          onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
          className="min-h-0 flex-1 overflow-auto"
        >
          <table className="w-full border-separate border-spacing-0">
            <thead className="sticky top-0 z-10 bg-surface">
              <tr>
                <SortableTh
                  label={t("files.colName")}
                  sortKey="name"
                  active={sortKey === "name"}
                  dir={sortDir}
                  onSort={toggleSort}
                />
                <SortableTh
                  label={t("files.colType")}
                  sortKey="type"
                  active={sortKey === "type"}
                  dir={sortDir}
                  onSort={toggleSort}
                />
                <SortableTh
                  label={t("files.colDate")}
                  sortKey="date"
                  active={sortKey === "date"}
                  dir={sortDir}
                  onSort={toggleSort}
                />
                <SortableTh
                  label={t("files.colOwner")}
                  sortKey="owner"
                  active={sortKey === "owner"}
                  dir={sortDir}
                  onSort={toggleSort}
                />
                <th className="border-b border-border px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-text-secondary">
                  {t("files.colMemo")}
                </th>
                <th className="w-10 border-b border-border" />
              </tr>
            </thead>
            <tbody>
              {/* Only [start, end) of the rows are mounted: O(visible) DOM
                  nodes regardless of total. The spacer rows keep the table at
                  its natural height so the scrollbar and sticky header stay
                  aligned. */}
              {start > 0 && (
                <tr aria-hidden>
                  <td colSpan={6} className="p-0" style={{ height: start * ROW_HEIGHT }} />
                </tr>
              )}
              {rows.slice(start, end).map((row) => (
                <tr
                  key={row.id}
                  onClick={() => setView({ kind: "coding", sourceId: row.id })}
                  onContextMenu={(e) => openMenuAt(e, row)}
                  style={{ height: ROW_HEIGHT }}
                  className="cursor-pointer hover:bg-surface-higher"
                >
                  <td className="max-w-64 border-b border-border px-3 py-2">
                    <span className="flex items-center gap-2">
                      {fileIcon(row.media_type)}
                      <span className="truncate font-medium">{row.name}</span>
                      {isPdf(row.name) && (
                        <span className="shrink-0 rounded-sm bg-surface-higher px-1 py-px text-[10px] font-medium uppercase text-text-secondary">
                          {t("files.badgePdf")}
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="whitespace-nowrap border-b border-border px-3 py-2 text-text-secondary">
                    {mediaTypeLabel(row.media_type, row.name)}
                  </td>
                  <td className="whitespace-nowrap border-b border-border px-3 py-2 text-text-secondary">
                    {row.date}
                  </td>
                  <td className="max-w-40 truncate border-b border-border px-3 py-2 text-text-secondary">
                    {row.owner}
                  </td>
                  <td className="max-w-64 truncate border-b border-border px-3 py-2 text-text-secondary">
                    {row.memo || <span className="italic">—</span>}
                  </td>
                  <td className="w-10 border-b border-border px-2 py-2 text-right">
                    <button
                      type="button"
                      onClick={(e) => openMenu(e, row)}
                      aria-label={t("files.actionsFor", { name: row.name })}
                      title={t("files.actionsTitle")}
                      className="rounded-sm p-1 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
                    >
                      <MoreHorizontal size={16} aria-hidden />
                    </button>
                  </td>
                </tr>
              ))}
              {end < rows.length && (
                <tr aria-hidden>
                  <td colSpan={6} className="p-0" style={{ height: (rows.length - end) * ROW_HEIGHT }} />
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Row actions menu */}
      {menu && menuRow && (
        <>
          <div
            className="fixed inset-0 z-30"
            onClick={() => setMenu(null)}
            aria-hidden
          />
          <div
            className="fixed z-40 min-w-40 rounded-md border border-border bg-surface py-1 shadow-lg"
            style={{ left: menu.x, top: menu.y, transform: "translateX(-100%)" }}
            role="menu"
            aria-label={t("files.actionsTitle")}
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenu(null);
                void selectFile(menuRow.id);
              }}
              className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher"
            >
              <Info size={14} aria-hidden />
              {t("sidebar.menuDetails")}
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenu(null);
                void renameSource(menuRow);
              }}
              className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher"
            >
              <Pencil size={14} aria-hidden />
              {t("files.menuRename")}
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenu(null);
                void editMemo(menuRow);
              }}
              className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher"
            >
              <StickyNote size={14} aria-hidden />
              {t("files.menuEditMemo")}
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenu(null);
                void deleteSource(menuRow);
              }}
              className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm text-danger hover:bg-surface-higher"
            >
              <Trash2 size={14} aria-hidden />
              {t("common.delete")}
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenu(null);
                void assignToCase(menuRow);
              }}
              className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher"
            >
              <UserRound size={14} aria-hidden />
              {t("files.menuAssignCase")}
            </button>
            {menuRow.media_type === "text" && (
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenu(null);
                  replaceInputRef.current?.click();
                }}
                className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher"
              >
                <Replace size={14} aria-hidden />
                {t("files.menuReplace")}
              </button>
            )}
          </div>
        </>
      )}

      {/* Replace-file picker (targets the source whose menu was opened) */}
      <input
        ref={replaceInputRef}
        type="file"
        hidden
        aria-hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file && menuRow) void replaceSourceFile(menuRow, file);
        }}
      />

      {/* Broken link repair modal */}
      {linkModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setLinkModal(false)}
        >
          <div
            className="w-full max-w-lg rounded-lg border border-border bg-surface shadow-xl"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-label={t("files.badLinks")}
          >
            <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
              <h2 className="text-sm font-semibold text-text-primary">{t("files.badLinks")}</h2>
              <button
                type="button"
                onClick={() => setLinkModal(false)}
                aria-label={t("common.close")}
                className="rounded-sm p-1 text-text-secondary hover:bg-surface-higher"
              >
                <X size={15} aria-hidden />
              </button>
            </div>
            <p className="border-b border-border px-4 py-2 text-xs text-text-secondary">
              {t("files.badLinksHint")}
            </p>
            <div className="max-h-72 overflow-auto">
              {badLinks.length === 0 ? (
                <p className="px-4 py-6 text-center text-sm text-text-secondary">
                  {t("files.badLinksEmpty")}
                </p>
              ) : (
                <table className="w-full border-collapse">
                  <tbody>
                    {badLinks.map((link) => (
                      <tr key={link.id} className="border-b border-border last:border-0">
                        <td className="max-w-40 truncate px-4 py-2 text-sm font-medium">
                          {link.name}
                        </td>
                        <td className="max-w-48 truncate px-2 py-2 text-xs text-text-secondary">
                          {link.path}
                        </td>
                        <td className="px-2 py-2 text-right">
                          <button
                            type="button"
                            onClick={() => void fixLink(link)}
                            className="rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher"
                          >
                            {t("files.badLinksFix")}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div className="flex items-center justify-between border-t border-border px-4 py-2.5">
              <button
                type="button"
                onClick={() => void bulkRename()}
                className="rounded-sm border border-border bg-bg px-2.5 py-1 text-xs hover:bg-surface-higher"
              >
                {t("files.bulkRename")}
              </button>
              <button
                type="button"
                onClick={() => setLinkModal(false)}
                className="rounded-sm bg-accent px-3 py-1 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover"
              >
                {t("common.close")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
