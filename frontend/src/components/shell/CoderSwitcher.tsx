/**
 * CoderSwitcher — shows the current coder; the dropdown switches coders or
 * adds a new one with an inline name input. The flyout also hosts the
 * collaboration-sync switch (Option B): toggle the background sync cycle,
 * see last-sync time / pending changes / errors and run an immediate sync.
 *
 * When sync is enabled a tiny indicator sits next to the coder button in
 * the top bar, showing the time since the last successful sync (red on
 * errors); clicking it opens the flyout.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  BarChart3,
  Check,
  ChevronDown,
  Eye,
  EyeOff,
  HelpCircle,
  LoaderCircle,
  Pencil,
  RefreshCw,
  Trash2,
  User,
  UserPlus,
  X,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";
import { useToast } from "@/lib/toast";
import { HelpFlyout, IconButton, Menu, MenuItem, Modal } from "@/components/ui/orchestrator";
import { cls } from "@/components/ui/tokens";

const SYNC_POLL_MS = 30_000;

const FLYOUT_WIDTH = 260;
const FLYOUT_MIN_HEIGHT = 240;
const FLYOUT_MARGIN = 8;
const FLYOUT_GAP = 4;

function formatSince(ts: number): string {
  if (!ts) return "—";
  const delta = Date.now() / 1000 - ts;
  if (delta < 60) return "0m";
  if (delta < 3600) return `${Math.round(delta / 60)}m`;
  if (delta < 86400) return `${Math.round(delta / 3600)}h`;
  return `${Math.round(delta / 86400)}d`;
}

interface CoderStats {
  coder: string;
  tables: { entity: string; count: number }[];
  total: number;
}

function errorMessage(e: unknown): string {
  if (e instanceof ApiError && typeof e.detail === "string") return e.detail;
  return e instanceof Error ? e.message : "Operation failed";
}

export function CoderSwitcher() {
  const { t } = useI18n();
  const toast = useToast();
  const coderName = useProjectStore((s) => s.coderName);
  const coders = useProjectStore((s) => s.coders);
  const switchCoder = useProjectStore((s) => s.switchCoder);
  const createCoder = useProjectStore((s) => s.createCoder);
  const syncStatus = useProjectStore((s) => s.syncStatus);
  const setSyncStatus = useProjectStore((s) => s.setSyncStatus);
  const setSyncEnabled = useProjectStore((s) => s.setSyncEnabled);
  const runSyncNow = useProjectStore((s) => s.runSyncNow);
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [syncBusy, setSyncBusy] = useState(false);
  const [visibility, setVisibility] = useState<Record<string, number>>({});
  const [menu, setMenu] = useState<{ name: string; x: number; y: number } | null>(null);
  // Help popovers (anchored for the shared HelpFlyout)
  const [helpOpen, setHelpOpen] = useState<null | "refresh">(null);
  const [refreshHelpAnchorEl, setRefreshHelpAnchorEl] = useState<HTMLElement | null>(null);
  const [stats, setStats] = useState<CoderStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [viewportTick, setViewportTick] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const syncEnabled = syncStatus?.ok === true && syncStatus.enabled === true;
  const syncError = Boolean(syncStatus?.last_error);
  const refreshHelpAnchor = helpOpen === "refresh" ? refreshHelpAnchorEl : null;

  /* Recompute the flyout position whenever the window is resized. */
  useEffect(() => {
    const onResize = () => setViewportTick((n) => n + 1);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  /* Poll sync status while the flyout is open or the switch is on. */
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const status = await api.syncStatus();
        if (!cancelled) setSyncStatus(status);
      } catch {
        /* project closed etc. — keep the last known state */
      }
    };
    if (open || syncEnabled) {
      void poll();
      timer = window.setInterval(() => void poll(), SYNC_POLL_MS);
    }
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearInterval(timer);
    };
  }, [open, syncEnabled, setSyncStatus]);

  useEffect(() => {
    if (!open) return;
    void api
      .coderVisibility()
      .then((res) => setVisibility(res.visibility))
      .catch(() => setVisibility({}));
    const onDown = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (target && !rootRef.current?.contains(target)) {
        setOpen(false);
        setAdding(false);
        setMenu(null);
        setHelpOpen(null);
        setRefreshHelpAnchorEl(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        setAdding(false);
        setMenu(null);
        setHelpOpen(null);
        setRefreshHelpAnchorEl(null);
      }
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (adding) inputRef.current?.focus();
  }, [adding]);

  useEffect(() => {
    if (!stats && !statsLoading) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setStats(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [stats, statsLoading]);

  async function toggleVisibility(name: string) {
    const next = (visibility[name] ?? 1) === 1 ? 0 : 1;
    try {
      await api.setCoderVisibility(name, next === 1);
      setVisibility((v) => ({ ...v, [name]: next }));
    } catch {
      setError(t("coder.visibilityHint"));
    }
  }

  async function toggleSync() {
    const next = !syncEnabled;
    setSyncBusy(true);
    try {
      await setSyncEnabled(next);
    } finally {
      setSyncBusy(false);
    }
  }

  async function syncNow() {
    setSyncBusy(true);
    try {
      await runSyncNow();
    } finally {
      setSyncBusy(false);
    }
  }

  async function confirmAdd() {
    const name = newName.trim();
    if (!name) return;
    setError(null);
    const ok = await createCoder(name);
    if (!ok) {
      setError(t("coder.addFailed"));
      return;
    }
    await switchCoder(name);
    setAdding(false);
    setNewName("");
  }

  async function refreshCoders() {
    await useProjectStore.getState().loadCoders();
    try {
      const res = await api.coderVisibility();
      setVisibility(res.visibility);
    } catch {
      setVisibility({});
    }
  }

  async function handleRenameCoder(name: string) {
    const next = window.prompt(t("coder.renamePrompt", { name }), name);
    if (!next || next.trim() === name) return;
    const newName = next.trim();
    setMenu(null);
    try {
      await api.renameCoder(name, newName);
      toast.success(t("coder.renamed", { name: newName }));
      await refreshCoders();
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  async function handleDeleteCoder(name: string) {
    setMenu(null);
    if (name === coderName) {
      toast.error(t("coder.deleteCurrent"));
      return;
    }
    try {
      await api.deleteCoder(name);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && typeof e.detail === "string") {
        const target = window.prompt(t("coder.deleteReassignPrompt", { name }));
        if (!target?.trim()) return;
        try {
          await api.deleteCoder(name, target.trim());
        } catch (err) {
          toast.error(errorMessage(err));
          return;
        }
      } else {
        toast.error(errorMessage(e));
        return;
      }
    }
    toast.success(t("coder.deleted", { name }));
    await refreshCoders();
  }

  async function handleCoderStats(name: string) {
    setMenu(null);
    setStatsLoading(true);
    setStats(null);
    try {
      setStats(await api.coderStats(name));
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setStatsLoading(false);
    }
  }

  function closeAll() {
    setOpen(false);
    setAdding(false);
    setHelpOpen(null);
    setRefreshHelpAnchorEl(null);
  }

  /**
   * Flyout position: anchored under the button and clamped so the panel
   * always stays fully inside the window (8px inset on every side). When
   * there is not enough room below the button it opens ABOVE it. The
   * max-height shrinks with the window (never exceeding the viewport) so
   * the bottom never overflows, even on very small screens.
   */
  const menuPos = useMemo(() => {
    const el = rootRef.current;
    if (!el) return undefined;
    const rect = el.getBoundingClientRect();
    const iw = window.innerWidth;
    const ih = window.innerHeight;
    const left = Math.max(
      FLYOUT_MARGIN,
      Math.min(rect.right - FLYOUT_WIDTH, iw - FLYOUT_WIDTH - FLYOUT_MARGIN),
    );
    const below = ih - rect.bottom - FLYOUT_GAP - FLYOUT_MARGIN;
    const above = rect.top - FLYOUT_GAP - FLYOUT_MARGIN;
    const openAbove = below < FLYOUT_MIN_HEIGHT && above > below;
    const maxHeight = Math.max(
      FLYOUT_MIN_HEIGHT,
      Math.min(ih - 2 * FLYOUT_MARGIN, openAbove ? above : below),
    );
    const top = openAbove
      ? Math.max(FLYOUT_MARGIN, rect.top - FLYOUT_GAP - maxHeight)
      : Math.max(
          FLYOUT_MARGIN,
          Math.min(rect.bottom + FLYOUT_GAP, ih - FLYOUT_MARGIN - maxHeight),
        );
    return { left, top, maxHeight };
    // open + viewportTick are intentional recompute triggers (refs/globals
    // inside are not tracked by exhaustive-deps).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, viewportTick]);

  return (
    <div ref={rootRef} className="relative flex shrink-0 items-center gap-1">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t("coder.switchAria", { name: coderName })}
        title={t("coder.switchTitle")}
        // Flex row so a long coder name ellipsizes instead of wrapping
        // the trailing dot/chevron to a second (clipped) line; auto-adapts
        // to the text width, capped so it never dominates the ribbon.
        className={`${cls.secondary} flex h-7 min-w-[4.5rem] max-w-[20rem] items-center gap-1 overflow-hidden leading-none`}
      >
        <User size={12} className="shrink-0 text-text-secondary" aria-hidden />
        <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap">{coderName}</span>
        <span
          role="status"
          aria-label={syncEnabled ? (syncError ? "sync-error" : "sync-on") : "sync-off"}
          title={
            syncEnabled
              ? syncError
                ? syncStatus?.last_error ?? t("sync.error")
                : t("sync.lastSyncShort", { when: formatSince(syncStatus?.last_sync ?? 0) })
              : undefined
          }
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${
            syncEnabled ? (syncError ? "bg-danger" : "bg-success") : "bg-border"
          }`}
        />
        <ChevronDown size={12} className="shrink-0 text-text-secondary" aria-hidden />
      </button>

      {open && (
        <Menu
          position="fixed"
          role="listbox"
          aria-label={t("coder.listAria")}
          className="min-w-60 overflow-y-auto"
          style={{ ...menuPos, width: FLYOUT_WIDTH }}
        >
          {coders.map((c) => (
            <div
              key={c.name}
              role="option"
              aria-selected={c.name === coderName}
              onContextMenu={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setMenu({ name: c.name, x: e.clientX, y: e.clientY });
              }}
              className={`flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher ${
                c.name === coderName ? "text-accent" : ""
              }`}
            >
              <button
                type="button"
                onClick={() => {
                  if (c.name !== coderName) void switchCoder(c.name);
                  closeAll();
                }}
                className="flex min-w-0 flex-1 items-center gap-2"
              >
                <User size={13} aria-hidden />
                <span className="truncate">{c.name}</span>
                {c.coding_count > 0 && (
                  <span className="ml-auto text-xs text-text-secondary">{c.coding_count}</span>
                )}
              </button>
              <button
                type="button"
                title={t((visibility[c.name] ?? 1) === 1 ? "coder.hide" : "coder.show")}
                aria-label={t((visibility[c.name] ?? 1) === 1 ? "coder.hide" : "coder.show")}
                onClick={(e) => {
                  e.stopPropagation();
                  void toggleVisibility(c.name);
                }}
                className={`shrink-0 rounded-sm p-1 hover:bg-surface-higher ${
                  (visibility[c.name] ?? 1) === 1 ? "text-text-secondary" : "text-danger"
                }`}
              >
                {(visibility[c.name] ?? 1) === 1 ? (
                  <Eye size={13} aria-hidden />
                ) : (
                  <EyeOff size={13} aria-hidden />
                )}
              </button>
              <button
                type="button"
                title={c.name === coderName ? t("coder.deleteCurrent") : t("coder.delete")}
                aria-label={t("coder.delete")}
                disabled={c.name === coderName}
                onClick={(e) => {
                  e.stopPropagation();
                  void handleDeleteCoder(c.name);
                }}
                className={`shrink-0 rounded-sm p-1 hover:bg-surface-higher ${
                  c.name === coderName
                    ? "cursor-not-allowed opacity-40"
                    : "text-text-secondary hover:text-danger"
                }`}
              >
                <Trash2 size={13} aria-hidden />
              </button>
            </div>
          ))}
          <div className="my-1 h-px bg-border" aria-hidden />
          {adding ? (
            <div className="px-2 py-1.5">
              <div className="flex items-center gap-1">
                <input
                  ref={inputRef}
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void confirmAdd();
                  }}
                  placeholder={t("coder.newNamePlaceholder")}
                  aria-label={t("coder.newNamePlaceholder")}
                  className="min-w-0 flex-1"
                />
                <button
                  type="button"
                  onClick={() => void confirmAdd()}
                  disabled={!newName.trim()}
                  aria-label={t("coder.confirmAdd")}
                  className="shrink-0 rounded-sm bg-accent p-1 text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-40"
                >
                  <Check size={13} aria-hidden />
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setAdding(false);
                    setNewName("");
                    setError(null);
                  }}
                  aria-label={t("common.cancel")}
                  className="shrink-0 rounded-sm border border-border bg-bg p-1 text-text-secondary hover:bg-surface-higher"
                >
                  <X size={13} aria-hidden />
                </button>
              </div>
              {error && <p className="mt-1 text-xs text-danger">{error}</p>}
            </div>
          ) : (
            <button
              type="button"
              onClick={() => {
                setAdding(true);
                setError(null);
              }}
              className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-surface-higher"
            >
              <UserPlus size={13} aria-hidden />
              {t("coder.addNew")}
            </button>
          )}

          {/* Refresh project data */}
          <div className="my-1 h-px bg-border" aria-hidden />
          <div className="flex items-center justify-between px-2 py-1.5">
            <span className="flex min-w-0 items-center gap-1 text-sm text-text-primary">
              <span className="truncate">{t("coder.refreshProject")}</span>
              <IconButton
                label={t("coder.refreshProjectHint")}
                title={t("coder.refreshProjectHint")}
                size="sm"
                aria-expanded={helpOpen === "refresh"}
                onClick={(e) => {
                  setRefreshHelpAnchorEl(e.currentTarget);
                  setHelpOpen(helpOpen === "refresh" ? null : "refresh");
                }}
              >
                <HelpCircle size={12} aria-hidden />
              </IconButton>
              {helpOpen === "refresh" && refreshHelpAnchor && (
                <HelpFlyout anchor={refreshHelpAnchor} onClose={() => setHelpOpen(null)}>
                  <p className="text-xs leading-relaxed text-text-secondary">
                    {t("coder.refreshProjectHint")}
                  </p>
                </HelpFlyout>
              )}
            </span>
            <button
              type="button"
              onClick={() => {
                void useProjectStore.getState().refreshProject();
                closeAll();
              }}
              aria-label={t("coder.refreshProject")}
              title={t("coder.refreshProject")}
              className="shrink-0 rounded-sm p-1 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
            >
              <RefreshCw size={13} aria-hidden />
            </button>
          </div>

          {/* Enable collaboration */}
          <div className="px-2 py-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 truncate text-sm text-text-primary">
                {t("coder.enableCollaboration")}
              </span>
              <div className="flex shrink-0 items-center gap-1.5">
                <button
                  type="button"
                  role="switch"
                  aria-checked={syncEnabled}
                  onClick={() => void toggleSync()}
                  disabled={syncBusy}
                  className={`relative h-4 w-8 rounded-full transition-colors ${
                    syncEnabled ? "bg-accent" : "bg-border"
                  } disabled:opacity-50`}
                  aria-label={t("sync.toggle")}
                >
                  <span
                    className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${
                      syncEnabled ? "left-4.5" : "left-0.5"
                    }`}
                    style={{ left: syncEnabled ? 18 : 2 }}
                  />
                </button>
                <button
                  type="button"
                  onClick={() => void syncNow()}
                  disabled={syncBusy}
                  title={
                    syncError ? (syncStatus?.last_error ?? t("sync.error")) : t("sync.now")
                  }
                  // Solid warning/yellow button: the app's warning color
                  // (--qc-warning) with the solid-button text convention
                  // (--qc-bg, as in cls.primary) so it reads as an obvious
                  // action in both themes and in high-contrast mode.
                  className="flex shrink-0 items-center gap-1 whitespace-nowrap rounded-sm bg-warning px-2 py-0.5 text-xs font-medium leading-none text-[var(--qc-bg)] hover:bg-warning/90 disabled:opacity-50"
                >
                  <RefreshCw
                    size={9}
                    className={`shrink-0 ${syncBusy ? "animate-spin" : ""}`}
                    aria-hidden
                  />
                  {t("sync.now")}
                </button>
              </div>
            </div>
            {syncEnabled && (
              <div className="mt-1.5 space-y-1 text-[11px] leading-snug text-text-secondary">
                <p>
                  {t("sync.lastSyncShort", {
                    when: formatSince(syncStatus?.last_sync ?? 0),
                  })}
                </p>
                {syncStatus && (syncStatus.pending_export > 0 || syncStatus.pending_import > 0) && (
                  <p className="text-warning">
                    {t("sync.pending", {
                      n: String(syncStatus.pending_export + syncStatus.pending_import),
                    })}
                  </p>
                )}
                {syncStatus?.collaborators.map((c) => (
                  <p key={c.user} className="truncate">
                    {c.user} · {t("sync.lastSyncShort", { when: formatSince(c.last_sync) })}
                    {c.pending_import > 0 && (
                      <span className="text-warning"> · {t("sync.pending", { n: String(c.pending_import) })}</span>
                    )}
                  </p>
                ))}
                {syncError && (
                  <p className="text-danger">{syncStatus?.last_error ?? t("sync.error")}</p>
                )}
              </div>
            )}
          </div>
        </Menu>
      )}

      {/* Coder context menu (right-click) */}
      {menu && (
        <Menu
          position="fixed"
          className="min-w-44"
          role="menu"
          aria-label={t("coder.contextMenu", { name: menu.name })}
          style={{
            left: Math.min(menu.x, window.innerWidth - 190),
            top: Math.min(menu.y, window.innerHeight - 130),
          }}
        >
          <MenuItem onClick={() => void handleRenameCoder(menu.name)}>
            <Pencil size={13} aria-hidden />
            {t("coder.rename")}
          </MenuItem>
          <MenuItem className="text-danger" onClick={() => void handleDeleteCoder(menu.name)}>
            <Trash2 size={13} aria-hidden />
            {t("coder.delete")}
          </MenuItem>
          <div className="my-1 h-px bg-border" aria-hidden />
          <MenuItem onClick={() => void handleCoderStats(menu.name)}>
            <BarChart3 size={13} aria-hidden />
            {t("coder.statistics")}
          </MenuItem>
        </Menu>
      )}

      {/* Coder statistics modal */}
      {(stats || statsLoading) && (
        <Modal
          open
          onClose={() => setStats(null)}
          size="sm"
          title={t("coder.statisticsTitle", { name: stats?.coder ?? coderName })}
        >
          <div className="max-h-80 overflow-y-auto p-4">
            {statsLoading ? (
              <div className="flex items-center justify-center gap-2 py-6 text-text-secondary">
                <LoaderCircle size={14} className="animate-spin" aria-hidden />
                {t("coder.statsLoading")}
              </div>
            ) : (
              <ul className="space-y-1.5">
                {stats?.tables.map((row) => (
                  <li key={row.entity} className="flex items-center justify-between text-sm">
                    <span className="text-text-secondary">{row.entity}</span>
                    <span className="font-medium text-text-primary">{row.count}</span>
                  </li>
                ))}
                {stats && (
                  <li className="mt-2 flex items-center justify-between border-t border-border pt-2 text-sm">
                    <span className="font-medium text-text-primary">{t("coder.statsTotal")}</span>
                    <span className="font-bold text-text-primary">{stats.total}</span>
                  </li>
                )}
              </ul>
            )}
          </div>
        </Modal>
      )}
    </div>
  );
}