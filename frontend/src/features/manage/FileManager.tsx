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
  type DragEvent as ReactDragEvent,
  type MouseEvent,
} from "react";
import {
  ArrowDown,
  ArrowUp,
  AudioLines,
  CircleAlert,
  Info,
  FileAudio,
  FileImage,
  FileText,
  Link2,
  LoaderCircle,
  Pencil,
  Replace,
  Sparkles,
  StickyNote,
  Trash2,
  Upload,
  UserRound,
} from "lucide-react";
import { api, ApiError, type BadLink, type FileFilter, type Source } from "@/lib/api";
import { cn, errorMessage } from "@/lib/utils";
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
import { useInspectorStore } from "@/stores/inspector";
import { useWorkspaceStore } from "@/stores/workspace";
import { useProjectStore } from "@/stores/project";
import { usePrefsStore } from "@/stores/prefs";
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
import { extendRangeSelection } from "@/features/manage/selection";
import { canTranscribeSource, hasRealTranscript } from "@/lib/media";

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

// The left bar's Import button asks this view to open its file picker via
// the store's requestImport() tick. The tick only ever increments (it is
// never reset), so an effect watching it re-runs on every mount and would
// re-open the picker — and re-trigger the import — each time the user
// returns to this view. Remember which tick the picker was already opened
// for at module scope (survives this view unmounting) so that each request
// is consumed exactly once.
let pickerOpenedForTick = 0;

// Row context menu geometry. The menu is min-w-40 (160px) plus a 1px border
// on each side; the items are py-1.5 (12px) plus the text-sm line height
// (20px); the menu itself adds py-1 (8px) plus the 2px border. These are
// used to keep the menu fully inside the window: 8px inset on every side,
// recomputed on open and on window resize while open.
const MENU_MARGIN = 8;
const MENU_WIDTH = 160 + 2;
const MENU_ITEM_HEIGHT = 12 + 20;
const MENU_BASE_HEIGHT = 8 + 2;

// Clamp the row context menu at (x, y) so it stays fully inside the
// window. The menu is rendered with translateX(-100%), i.e. its RIGHT edge
// sits at `left`, so the horizontal clamp keeps that right edge inside the
// window while the (known, min-)width keeps the left edge on screen. The
// height is estimated from the item count (capped) and the menu is given a
// maxHeight + scroll so it can never exceed the window on small screens.
function clampRowMenu(
  x: number,
  y: number,
  itemCount: number,
): { left: number; top: number; maxHeight: number } {
  const iw = window.innerWidth;
  const ih = window.innerHeight;
  const left = Math.min(Math.max(x, MENU_WIDTH + MENU_MARGIN), iw - MENU_MARGIN);
  const natural = itemCount * MENU_ITEM_HEIGHT + MENU_BASE_HEIGHT;
  const maxHeight = Math.max(2 * MENU_MARGIN, Math.min(natural, ih - 2 * MENU_MARGIN));
  const top = Math.min(Math.max(y, MENU_MARGIN), ih - MENU_MARGIN - maxHeight);
  return { left, top, maxHeight };
}

export function FileManager() {
  const { t } = useI18n();
  const toast = useToast();
  const setView = useWorkspaceStore((s) => s.setView);
  const selectFile = useInspectorStore((s) => s.selectFile);
  const sources = useProjectStore((s) => s.sources);
  const codeTree = useProjectStore((s) => s.codeTree);
  const presence = usePrefsStore((s) => s.presence);

  const fileQuery = useProjectStore((s) => s.fileQuery);
  const setFileQuery = useProjectStore((s) => s.setFileQuery);
  // Sort column/direction and the active saved filter live in the store so
  // they survive view switches and remounts for the app session (they are
  // never persisted to disk).
  const filesUi = useWorkspaceStore((s) => s.filesUi);
  const setFilesUi = useWorkspaceStore((s) => s.setFilesUi);
  const sortKey = filesUi.sortKey;
  const sortDir = filesUi.sortDir;
  const activeFilter = filesUi.activeFilter;
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ id: number; x: number; y: number } | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [linkModal, setLinkModal] = useState(false);
  const [badLinks, setBadLinks] = useState<BadLink[]>([]);
  const [filters, setFilters] = useState<FileFilter[]>([]);
  const [batchTranscribe, setBatchTranscribe] = useState<number[] | null>(null);
  const [batchAutocode, setBatchAutocode] = useState<number[] | null>(null);
  const [deleting, setDeleting] = useState<{ done: number; total: number } | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const replaceInputRef = useRef<HTMLInputElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(0);
  const [dragActive, setDragActive] = useState(false);
  // Depth of the dragenter/dragleave nesting while an OS drag hovers the
  // container (see handleDragEnter/handleDragLeave).
  const dragDepth = useRef(0);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const list = await api.sources();
      useProjectStore.setState({ sources: list });
    } catch (e) {
      setLoadError(errorMessage(e, t("files.loadError")));
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
  // Each tick opens the picker at most once: mount-time re-runs of this
  // effect (the view remounting) must not open it again.
  const importTick = useProjectStore((s) => s.importTick);
  useEffect(() => {
    if (importTick === 0 || importTick === pickerOpenedForTick) return;
    pickerOpenedForTick = importTick;
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
      setActionError(errorMessage(e, t("files.filtersSave")));
    }
  }

  async function removeFilter(f: FileFilter) {
    if (!window.confirm(t("files.filtersDeleteConfirm", { name: f.name }))) return;
    try {
      await api.deleteFileFilter(f.filterid);
      setFilesUi({ activeFilter: "" });
      setFileQuery("");
      await loadFilters();
    } catch (e) {
      setActionError(errorMessage(e, t("files.filtersDelete")));
    }
  }

  async function openLinkModal() {
    setLinkModal(true);
    try {
      const res = await api.badLinks();
      setBadLinks(res.links);
    } catch (e) {
      setActionError(errorMessage(e, t("files.badLinksHint")));
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
      setActionError(errorMessage(e, t("files.badLinksHint")));
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
      setActionError(errorMessage(e, t("files.badLinksHint")));
    }
  }

  async function replaceSourceFile(row: Source, file: File) {
    try {
      const res = await api.replaceSource(row.id, file);
      await load();
      setActionError(t("files.replaced", { message: res.message }));
    } catch (e) {
      setActionError(errorMessage(e, t("files.replaceError")));
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

  // Re-clamp the row actions menu while it is open: the window can resize
  // underneath a position:fixed menu, so recompute on every resize tick.
  const [viewportTick, setViewportTick] = useState(0);
  useEffect(() => {
    if (!menu) return;
    const onResize = () => setViewportTick((n) => n + 1);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [menu]);

  const filtered = useMemo(() => filterSources(sources, fileQuery), [sources, fileQuery]);  const rows = useMemo(
    () => sortSources(filtered, sortKey, sortDir),
    [filtered, sortKey, sortDir],
  );
  // Files being worked on by a live coder (fresh presence with a file).
  const liveFileIds = useMemo(() => {
    const set = new Set<number>();
    const now = Date.now() / 1000;
    for (const e of presence) {
      if (e.file_id != null && now - e.ts < 60) set.add(e.file_id);
    }
    return set;
  }, [presence]);
  const menuRow = menu ? rows.find((r) => r.id === menu.id) : undefined;
  // Row menu position, re-clamped on every render trigger while open (open
  // event + viewportTick for window resizes): translateX(-100%) anchors the
  // menu's right edge at `left`, so clamping keeps both edges in-window.
  const rowMenuStyle = useMemo(() => {
    if (!menu || !menuRow) return null;
    return clampRowMenu(menu.x, menu.y, menuRow.media_type === "text" ? 6 : 5);
    // viewportTick is an intentional recompute trigger on window resize
    // (the menu stays open while the window moves under it).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [menu, menuRow, viewportTick]);

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

  // Row ids in the VISIBLE order (the current sort/filter order) — the
  // frame shift-range selection operates on.
  const visibleIds = useMemo(() => rows.map((r) => r.id), [rows]);

  // Index of the last DIRECTLY-clicked row (a plain click). Shift-clicks
  // extend the range from this anchor and never move it — the range follows
  // the anchor, not the last shift-click.
  const anchorIndexRef = useRef<number | null>(null);

  // Shift-click at `index` in the visible order: select (or toggle) every
  // row from the anchor to the current one. The mode follows the clicked
  // row's state — clicking an unselected row extends by SELECTING the range
  // (add), clicking an already-selected row extends by toggling it (so a
  // shift-click on a checked row deselects the range).
  function extendSelectionTo(index: number) {
    setSelected((prev) => {
      const add = !prev.has(rows[index].id);
      return extendRangeSelection(anchorIndexRef.current, index, prev, visibleIds, add);
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
      setFilesUi({ sortDir: sortDir === "asc" ? "desc" : "asc" });
    } else {
      setFilesUi({ sortKey: key, sortDir: "asc" });
    }
  }

  const importFiles = useCallback(
    async (list: File[]) => {
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
            failed = errorMessage(e, t("files.importFailed", { name: file.name }));
          }
        }
        useProjectStore.getState().setImportState({ done: i + 1, total: list.length });
      }
      useProjectStore.getState().setImportState(null);
      setSkipped(dupes);
      if (failed) setActionError(failed);
      await load();
    },
    [load, t],
  );

  function handleFilesChange(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    void importFiles(files);
  }

  // Extract the files of an OS drag. `dataTransfer.files` is the standard
  // source, but WebView2 versions have shipped where a drop carries the
  // payload ONLY on `dataTransfer.items` (files list empty) — and vice
  // versa. Iterate both: `getAsFile()` is only valid synchronously inside
  // the event, which is exactly where this runs.
  function filesFromDataTransfer(dt: DataTransfer): File[] {
    const fromFiles = Array.from(dt.files ?? []);
    if (fromFiles.length > 0) return fromFiles;
    const items = Array.from(dt.items ?? []);
    return items
      .filter((item) => item.kind === "file")
      .map((item) => item.getAsFile())
      .filter((f): f is File => f !== null);
  }

  // Drop target on the center area: importing OS files goes through the
  // exact same path as the Import button (importFiles → api.importSource).
  // The dragover handler is deliberately permissive: WebView2 can report an
  // EMPTY dataTransfer.types list while an OS file drag hovers the window
  // ("Files" only appears on drop), so gating preventDefault() on it would
  // let the engine cancel the drop. Non-file payloads are ignored on drop.
  function handleDragEnter() {
    dragDepth.current += 1;
    setDragActive(true);
  }

  function handleDragOver(e: ReactDragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    setDragActive(true);
  }

  function handleDragLeave() {
    // Every transition inside the container pairs one dragleave with one
    // dragenter, so the depth only reaches 0 when the pointer really leaves
    // (or the drag is cancelled). Counting instead of checking
    // e.relatedTarget keeps the overlay stable in WebView2, where
    // relatedTarget may be null on child-boundary leaves.
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragActive(false);
  }

  function handleDrop(e: ReactDragEvent<HTMLDivElement>) {
    e.preventDefault();
    dragDepth.current = 0;
    setDragActive(false);
    const files = filesFromDataTransfer(e.dataTransfer);
    if (files.length === 0) {
      toast.error(t("files.dropNoFiles"));
      return;
    }
    void importFiles(files);
  }

  // Final net for WebView2 quirks: the OS drop can surface on `document`
  // instead of the element under the cursor (the engine sometimes skips the
  // target dispatch entirely), or the pointer can release outside the drop
  // container (e.g. over the header). A document-level listener catches
  // both. The container's own handler already called preventDefault() for
  // drops it processed, so `e.defaultPrevented` tells this net to stand
  // down — every drop is imported exactly once.
  useEffect(() => {
    const onDocumentDrop = (e: DragEvent) => {
      if (e.defaultPrevented) return;
      e.preventDefault();
      if (!e.dataTransfer) return;
      const files = filesFromDataTransfer(e.dataTransfer);
      if (files.length === 0) return;
      void importFiles(files);
    };
    document.addEventListener("drop", onDocumentDrop);
    return () => document.removeEventListener("drop", onDocumentDrop);
  }, [importFiles, toast]);

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
      setActionError(errorMessage(e, t("files.renameError")));
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
      setActionError(errorMessage(e, t("files.memoError")));
    }
  }

  async function deleteSource(row: Source) {
    if (!window.confirm(t("files.deleteConfirm", { name: row.name }))) return;
    try {
      await api.deleteSource(row.id);
      await load();
    } catch (e) {
      setActionError(errorMessage(e, t("files.deleteError")));
    }
  }

  async function deleteSelected() {
    if (deleting || selected.size === 0) return;
    const n = selected.size;
    if (!window.confirm(t("files.deleteSelectedConfirm", { n }))) return;
    setActionError(null);
    const ids = [...selected];
    setDeleting({ done: 0, total: n });
    let deleted = 0;
    let failed: string | null = null;
    try {
      for (let i = 0; i < ids.length; i++) {
        try {
          await api.deleteSource(ids[i]);
          deleted += 1;
          // Drop the row from the store list right away: the table renders
          // store sources, so each successful delete disappears immediately
          // without waiting for a final refetch.
          useProjectStore.setState((s) => ({
            sources: s.sources.filter((x) => x.id !== ids[i]),
          }));
        } catch (e) {
          // A single failure must not abort the batch (the old code bailed
          // out of the loop and skipped the refresh, leaving already-deleted
          // rows visible). Record it and keep going.
          if (!failed) failed = errorMessage(e, t("files.deleteError"));
        }
        setDeleting({ done: i + 1, total: n });
      }
    } finally {
      setDeleting(null);
    }
    setSelected(new Set());
    if (failed) setActionError(failed);
    // Reconcile through the same path the working single-row delete uses
    // (load() refetches sources and always sets them; refreshProject() runs
    // a 5-way Promise.all and swallows failures, so it can skip the sources
    // update when any other endpoint errors).
    await load();
    if (deleted > 0) toast.success(t("files.deletedSelected", { n: String(deleted) }));
  }

  // Eligible selection counts for the batch buttons: transcribe only AV
  // media that has no REAL transcript yet (same predicates as the AV coder's
  // transcribe button plus the transcript check), autocode only text
  // sources. A disabled button says "nothing eligible" on its own.
  const selectedList = useMemo(
    () => sources.filter((s) => selected.has(s.id)),
    [sources, selected],
  );
  const eligibleTranscribe = useMemo(
    () => selectedList.filter((s) => canTranscribeSource(s) && !hasRealTranscript(s)),
    [selectedList],
  );
  const transcribedSelected = useMemo(
    () => selectedList.filter((s) => canTranscribeSource(s) && hasRealTranscript(s)),
    [selectedList],
  );
  const eligibleAutocode = useMemo(
    () => selectedList.filter((s) => s.media_type === "text"),
    [selectedList],
  );

  function openBatchTranscribe() {
    const ids = eligibleTranscribe.map((s) => s.id);
    if (ids.length === 0) {
      toast.error(t("files.transcribeNone"));
      return;
    }
    setBatchTranscribe(ids);
  }

  function openBatchAutocode() {
    const ids = eligibleAutocode.map((s) => s.id);
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
      setActionError(errorMessage(e, t("files.assignCaseError")));
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
                setFilesUi({ activeFilter: id });
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
              disabled={eligibleTranscribe.length === 0 || deleting !== null}
              icon={<AudioLines size={13} aria-hidden />}
              title={
                transcribedSelected.length > 0
                  ? t("files.transcribeSkipped", {
                      n: String(eligibleTranscribe.length),
                      skipped: String(transcribedSelected.length),
                    })
                  : t("files.transcribeEligible", {
                      n: String(eligibleTranscribe.length),
                    })
              }
            >
              {t("files.transcribeEligible", {
                n: String(eligibleTranscribe.length),
              })}
            </Button>
            <Button
              variant="secondary"
              onClick={() => openBatchAutocode()}
              disabled={eligibleAutocode.length === 0 || deleting !== null}
              icon={<Sparkles size={13} aria-hidden />}
              title={t("files.autocodeSelectedCount", {
                eligible: String(eligibleAutocode.length),
                n: String(selected.size),
              })}
            >
              {t("files.autocodeSelectedCount", {
                eligible: String(eligibleAutocode.length),
                n: String(selected.size),
              })}
            </Button>
            <Button
              variant="danger"
              icon={
                deleting ? (
                  <LoaderCircle size={13} className="animate-spin" aria-hidden />
                ) : (
                  <Trash2 size={13} aria-hidden />
                )
              }
              onClick={() => void deleteSelected()}
              disabled={deleting !== null}
              title={t("files.deleteSelectedConfirm", { n: selected.size })}
            >
              {deleting
                ? t("files.deletingProgress", {
                    done: String(deleting.done),
                    total: String(deleting.total),
                  })
                : t("files.deleteSelectedButton", { n: selected.size })}
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

      {/* Body — the whole center area is a drop target for OS files */}
      <div
        data-testid="files-drop-zone"
        className="relative flex min-h-0 flex-1 flex-col"
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {dragActive && (
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 z-20 flex flex-col items-center justify-center gap-1.5 border-2 border-dashed border-accent bg-accent/10"
          >
            <Upload size={22} className="text-accent" aria-hidden />
            <p className="text-sm font-medium text-accent">{t("files.dropImport")}</p>
            <p className="text-xs text-text-secondary">{t("files.dropImportHint")}</p>
          </div>
        )}
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
                {rows.slice(start, end).map((row, i) => {
                  const rowIndex = start + i;
                  return (
                    <tr
                      key={row.id}
                      onClick={(e) => {
                        if (e.shiftKey) {
                          extendSelectionTo(rowIndex);
                          return;
                        }
                        setView({ kind: "coding", sourceId: row.id });
                      }}
                      onContextMenu={(e) => openMenuAt(e, row)}
                      style={{ height: ROW_HEIGHT }}
                      className="cursor-pointer hover:bg-surface-higher"
                    >
                      <td className="w-8 border-b border-border px-1 text-center">
                        <input
                          type="checkbox"
                          checked={selected.has(row.id)}
                          onChange={() => {
                            toggleSelected(row.id);
                            anchorIndexRef.current = rowIndex;
                          }}
                          onClick={(e) => {
                            e.stopPropagation();
                            if (e.shiftKey) {
                              // Suppress the native toggle: the range
                              // selection below is the only effect.
                              e.preventDefault();
                              extendSelectionTo(rowIndex);
                            }
                          }}
                          className={"h-3.5 w-3.5 shrink-0 cursor-pointer rounded-sm border border-border accent-[var(--qc-accent)]"}
                          aria-label={t("files.selectRow", { name: row.name })}
                          title={t("files.selectRow", { name: row.name })}
                        />
                      </td>
                    <td className="max-w-64 border-b border-border px-3 py-2">
                      <span className="flex items-center gap-2">
                        {fileIcon(row.media_type)}
                        <span className="truncate font-medium">{row.name}</span>
                        {liveFileIds.has(row.id) && (
                          <span
                            aria-hidden
                            className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--qc-success)]"
                            title={t("sync.liveOnFile")}
                          />
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
                  </tr>
                  );
                })}
                {end < rows.length && (
                  <tr aria-hidden>
                    <td colSpan={5} className="p-0" style={{ height: (rows.length - end) * ROW_HEIGHT }} />
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Row actions menu */}
      {menu && menuRow && rowMenuStyle && (
        <>
          <div
            className="fixed inset-0 z-30"
            onClick={() => setMenu(null)}
            aria-hidden
          />
          <Menu
            position="fixed"
            className="min-w-40 overflow-y-auto"
            style={{
              ...rowMenuStyle,
              transform: "translateX(-100%)",
            }}
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
