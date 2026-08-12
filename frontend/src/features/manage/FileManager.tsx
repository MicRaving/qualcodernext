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
  Pencil,
  Replace,
  StickyNote,
  Trash2,
  Upload,
  UserRound,
} from "lucide-react";
import { api, ApiError, type BadLink, type FileFilter, type Source } from "@/lib/api";
import { cn } from "@/lib/utils";
import { cls } from "@/components/ui/tokens";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import {
  Button,
  EmptyState,
  ErrorBanner,
  IconButton,

  LoadingState,
  Menu,
  MenuItem,
  Modal,
  Select,
  TableHead,
  ViewHeader,
} from "@/components/ui/orchestrator";
import { useProjectStore } from "@/stores/project";
import { TranscribeDialog } from "@/features/coding/TranscribeDialog";
import { AutocodeDialog } from "@/features/coding/AutocodeDialog";
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
    <th className={cls.tableHead}>
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
  const toast = useToast();
  const setView = useProjectStore((s) => s.setView);
  const selectFile = useProjectStore((s) => s.selectFile);
  const sources = useProjectStore((s) => s.sources);
  const codeTree = useProjectStore((s) => s.codeTree);

  const fileQuery = useProjectStore((s) => s.fileQuery);
  const setFileQuery = useProjectStore((s) => s.setFileQuery);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ id: number; x: number; y: number } | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [linkModal, setLinkModal] = useState(false);
  const [badLinks, setBadLinks] = useState<BadLink[]>([]);
  const [filters, setFilters] = useState<FileFilter[]>([]);
  const [activeFilter, setActiveFilter] = useState<number | "">("");
  const [batchTranscribe, setBatchTranscribe] = useState<number[] | null>(null);
  const [batchAutocode, setBatchAutocode] = useState<number[] | null>(null);

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

  // The left bar's Import button requests the file picker via the store.
  const importTick = useProjectStore((s) => s.importTick);
  useEffect(() => {
    if (importTick === 0) return;
    fileInputRef.current?.click();
  }, [importTick]);

  const applyFilter = useCallback((f: FileFilter) => {
    try {
      const parsed = JSON.parse(f.filter) as { query?: string };
      setFileQuery(parsed.query ?? "");
    } catch {
      setFileQuery("");
    }
  }, [setFileQuery]);

  async function saveCurrentFilter() {
    const name = window.prompt(t("files.filtersNamePrompt"));
    if (!name?.trim()) return;
    try {
      const filterJson = JSON.stringify({ query: fileQuery });
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
      setFileQuery("");
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

  const filtered = useMemo(() => filterSources(sources, fileQuery), [sources, fileQuery]);  const rows = useMemo(
    () => sortSources(filtered, sortKey, sortDir),
    [filtered, sortKey, sortDir],
  );
  const menuRow = menu ? rows.find((r) => r.id === menu.id) : undefined;

  // Drop selections for rows that left the filtered list.
  useEffect(() => {
    const visible = new Set(rows.map((r) => r.id));
    setSelected((prev) => {
      if (prev.size === 0) return prev;
      const next = new Set([...prev].filter((id) => visible.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [rows]);

  function toggleSelected(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function toggleSelectAll() {
    setSelected((prev) => {
      const allSelected = rows.length > 0 && rows.every((r) => prev.has(r.id));
      return allSelected ? new Set() : new Set(rows.map((r) => r.id));
    });
  }

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

  async function deleteSelected() {
    if (selected.size === 0) return;
    const n = selected.size;
    if (!window.confirm(t("files.deleteSelectedConfirm", { n }))) return;
    setActionError(null);
    try {
      for (const id of selected) {
        await api.deleteSource(id);
      }
      setSelected(new Set());
      await useProjectStore.getState().refreshProject();
      toast.success(t("files.deletedSelected", { n }));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : t("files.deleteError"));
    }
  }

  function openBatchTranscribe() {
    const ids = sources
      .filter(
        (s) =>
          selected.has(s.id) &&
          (s.media_type === "audio" || s.media_type === "video") &&
          s.av_text_id == null,
      )
      .map((s) => s.id);
    if (ids.length === 0) {
      toast.error(t("files.transcribeNone"));
      return;
    }
    setBatchTranscribe(ids);
  }

  function openBatchAutocode() {
    const ids = sources
      .filter((s) => selected.has(s.id) && s.media_type === "text")
      .map((s) => s.id);
    if (ids.length === 0) {
      toast.error(t("files.autocodeNone"));
      return;
    }
    setBatchAutocode(ids);
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

  function openMenuAt(e: MouseEvent<HTMLTableRowElement>, row: Source) {
    e.preventDefault();
    setMenu({ id: row.id, x: e.clientX, y: e.clientY });
  }

  return (
    <div className="flex h-full flex-col bg-bg">
      {/* Header */}
      <ViewHeader back={false}
        title={t("nav.files")}
        actions={
          <>
            {filters.length > 0 && (
          <div className="flex items-center gap-1">
            <Select
              value={activeFilter}
              onChange={(e) => {
                const id = e.target.value === "" ? "" : Number(e.target.value);
                setActiveFilter(id);
                const f = filters.find((x) => x.filterid === id);
                if (f) applyFilter(f);
              }}
              aria-label={t("files.filters")}
            >
              <option value="">{t("files.filtersAll")}</option>
              {filters.map((f) => (
                <option key={f.filterid} value={f.filterid}>
                  {f.name}
                </option>
              ))}
            </Select>
            <IconButton
              label={t("files.filtersSave")}
              title={t("files.filtersSave")}
              size="sm"
              onClick={() => void saveCurrentFilter()}
            >
              <StickyNote size={13} aria-hidden />
            </IconButton>
            {activeFilter !== "" && (
              <IconButton
                label={t("files.filtersDelete")}
                title={t("files.filtersDelete")}
                size="sm"
                onClick={() => {
                  const f = filters.find((x) => x.filterid === activeFilter);
                  if (f) void removeFilter(f);
                }}
                className="hover:bg-danger/10 hover:text-danger"
              >
                <Trash2 size={13} aria-hidden />
              </IconButton>
            )}
          </div>
        )}
        {selected.size > 0 && (
          <>
            <Button
              variant="secondary"
              onClick={() => openBatchTranscribe()}
              title={t("files.transcribeSelected", { n: selected.size })}
            >
              {t("files.transcribeSelected", { n: selected.size })}
            </Button>
            <Button
              variant="secondary"
              onClick={() => openBatchAutocode()}
              title={t("files.autocodeSelected", { n: selected.size })}
            >
              {t("files.autocodeSelected", { n: selected.size })}
            </Button>
            <Button
              variant="danger"
              icon={<Trash2 size={13} aria-hidden />}
              onClick={() => void deleteSelected()}
              title={t("files.deleteSelectedConfirm", { n: selected.size })}
            >
              {t("files.deleteSelectedButton", { n: selected.size })}
            </Button>
          </>
        )}
        <IconButton
          label={t("files.badLinks")}
          title={t("files.badLinks")}
          onClick={() => void openLinkModal()}
        >
          <Link2 size={15} aria-hidden />
        </IconButton>
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
        <ErrorBanner tone="warning" onClose={() => setSkipped([])}>
          {t("files.skipped", {
            names: skipped.map((n) => t("files.duplicate", { name: n })).join(", "),
          })}
        </ErrorBanner>
      )}
      {actionError && <ErrorBanner onClose={() => setActionError(null)}>{actionError}</ErrorBanner>}

      {/* Body */}
      {loading && sources.length === 0 ? (
        <LoadingState>{t("files.loading")}</LoadingState>
      ) : loadError ? (
        <div className="flex flex-1 items-center justify-center">
          <div className="max-w-md text-center">
            <p className="flex items-center justify-center gap-1.5 text-sm text-danger">
              <CircleAlert size={16} aria-hidden />
              {loadError}
            </p>
            <Button variant="secondary" className="mt-3" onClick={() => void load()}>
              {t("common.retry")}
            </Button>
          </div>
        </div>
      ) : sources.length === 0 ? (
        <EmptyState>
          <p className="text-sm text-text-secondary">{t("files.empty")}</p>
          <Button
            variant="primary"
            icon={<Upload size={14} aria-hidden />}
            onClick={() => fileInputRef.current?.click()}
          >
            {t("files.importFiles")}
          </Button>
        </EmptyState>
      ) : rows.length === 0 ? (
        <EmptyState>
          {t("files.noMatch", { query: fileQuery })}
        </EmptyState>
      ) : (
        <div
          ref={scrollRef}
          onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
          className="min-h-0 flex-1 overflow-auto"
        >
          <table className="w-full border-separate border-spacing-0">
            <thead className="sticky top-0 z-10 bg-surface">
              <tr>
                <th className="w-8 border-b border-border px-1 text-center">
                  <input
                    type="checkbox"
                    checked={rows.length > 0 && rows.every((r) => selected.has(r.id))}
                    onChange={toggleSelectAll}
                    className={"h-3.5 w-3.5 shrink-0 cursor-pointer rounded-sm border border-border accent-[var(--qc-accent)]"}
                    aria-label={t("files.selectAll")}
                    title={t("files.selectAll")}
                  />
                </th>
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
                <TableHead>{t("files.colMemo")}</TableHead>
              </tr>
            </thead>
            <tbody>
              {/* Only [start, end) of the rows are mounted: O(visible) DOM
                  nodes regardless of total. The spacer rows keep the table at
                  its natural height so the scrollbar and sticky header stay
                  aligned. */}
              {start > 0 && (
                <tr aria-hidden>
                  <td colSpan={5} className="p-0" style={{ height: start * ROW_HEIGHT }} />
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
                  <td className="w-8 border-b border-border px-1 text-center">
                    <input
                      type="checkbox"
                      checked={selected.has(row.id)}
                      onChange={() => toggleSelected(row.id)}
                      onClick={(e) => e.stopPropagation()}
                      className={"h-3.5 w-3.5 shrink-0 cursor-pointer rounded-sm border border-border accent-[var(--qc-accent)]"}
                    aria-label={t("files.selectRow", { name: row.name })}
                    title={t("files.selectRow", { name: row.name })}
                    />
                  </td>
                  <td className="max-w-64 border-b border-border px-3 py-2">
                    <span className="flex items-center gap-2">
                      {fileIcon(row.media_type)}
                      <span className="truncate font-medium">{row.name}</span>
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
                </tr>
              ))}
              {end < rows.length && (
                <tr aria-hidden>
                  <td colSpan={5} className="p-0" style={{ height: (rows.length - end) * ROW_HEIGHT }} />
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
          <Menu
            position="fixed"
            className="min-w-40"
            style={{ left: menu.x, top: menu.y, transform: "translateX(-100%)" }}
            role="menu"
            aria-label={t("files.actionsTitle")}
          >
            <MenuItem
              role="menuitem"
              onClick={() => {
                setMenu(null);
                void selectFile(menuRow.id);
              }}
            >
              <Info size={14} aria-hidden />
              {t("sidebar.menuDetails")}
            </MenuItem>
            <MenuItem
              role="menuitem"
              onClick={() => {
                setMenu(null);
                void renameSource(menuRow);
              }}
            >
              <Pencil size={14} aria-hidden />
              {t("files.menuRename")}
            </MenuItem>
            <MenuItem
              role="menuitem"
              onClick={() => {
                setMenu(null);
                void editMemo(menuRow);
              }}
            >
              <StickyNote size={14} aria-hidden />
              {t("files.menuEditMemo")}
            </MenuItem>
            <MenuItem
              role="menuitem"
              className="text-danger"
              onClick={() => {
                setMenu(null);
                void deleteSource(menuRow);
              }}
            >
              <Trash2 size={14} aria-hidden />
              {t("common.delete")}
            </MenuItem>
            <MenuItem
              role="menuitem"
              onClick={() => {
                setMenu(null);
                void assignToCase(menuRow);
              }}
            >
              <UserRound size={14} aria-hidden />
              {t("files.menuAssignCase")}
            </MenuItem>
            {menuRow.media_type === "text" && (
              <MenuItem
                role="menuitem"
                onClick={() => {
                  setMenu(null);
                  replaceInputRef.current?.click();
                }}
              >
                <Replace size={14} aria-hidden />
                {t("files.menuReplace")}
              </MenuItem>
            )}
          </Menu>
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
      <Modal
        open={linkModal}
        onClose={() => setLinkModal(false)}
        title={t("files.badLinks")}
        panelClassName="w-full max-w-lg"
      >
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
                      <Button variant="secondary" onClick={() => void fixLink(link)}>
                        {t("files.badLinksFix")}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="flex items-center justify-between border-t border-border px-4 py-2.5">
          <Button variant="secondary" onClick={() => void bulkRename()}>
            {t("files.bulkRename")}
          </Button>
          <Button variant="primary" onClick={() => setLinkModal(false)}>
            {t("common.close")}
          </Button>
        </div>
      </Modal>

      {/* Batch transcribe / autocode dialogs for the selected files */}
      {batchTranscribe && (
        <TranscribeDialog sourceIds={batchTranscribe} onClose={() => setBatchTranscribe(null)} />
      )}
      {batchAutocode && (
        <AutocodeDialog
          open
          onClose={() => setBatchAutocode(null)}
          fid={null}
          codes={codeTree}
          sourceIds={batchAutocode}
          onDone={() => setBatchAutocode(null)}
        />
      )}
    </div>
  );
}
