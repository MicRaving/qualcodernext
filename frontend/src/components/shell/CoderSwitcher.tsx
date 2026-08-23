/**
 * CoderSwitcher — shows the current coder; the dropdown switches coders or
 * adds a new one with an inline name input. The flyout also hosts the
 * collaboration block: a background-sync switch, last-sync time / pending
 * changes / errors, an immediate "Sync now", live peer presence and the
 * collaboration-mode activation.
 *
 * Indicator model:
 * - The RIBBON button carries a single overall sync dot (off / pending /
 *   conflict / error / in-sync) — never a per-coder indicator.
 * - The FLYOUT shows a per-coder activity dot on every coder row, combining
 *   live presence (who is actively working right now) with the collaborator
 *   sync state, plus a "Live now" section listing who is working and on which
 *   file. Presence is polled while the flyout is open so the dots stay fresh.
 */
import { errorMessage } from "@/lib/utils";
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
import { SYNC_POLL_MS } from "@/lib/config";
import { useI18n } from "@/lib/i18n";
import { useCoderStore } from "@/stores/coder";
import { usePrefsStore } from "@/stores/prefs";
import { useProjectStore } from "@/stores/project";
import { useToast } from "@/lib/toast";
import { Button, HelpFlyout, IconButton, Menu, MenuItem, Modal } from "@/components/ui/orchestrator";
import { ConflictResolver } from "@/components/collaboration/ConflictResolver";

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

/** How fresh a presence heartbeat counts as "live" (seconds). */
const LIVE_ACTIVITY_SECS = 60;

function isLive(ts: number): boolean {
  return ts > 0 && Date.now() / 1000 - ts < LIVE_ACTIVITY_SECS;
}

interface CoderStats {
  coder: string;
  tables: { entity: string; count: number }[];
  total: number;
}

/** Per-coder activity state derived from presence + collaborator sync data. */
type CoderActivity = "live" | "active" | "stale" | "offline";

export function CoderSwitcher() {
  const { t } = useI18n();
  const toast = useToast();
  const coderName = useCoderStore((s) => s.coderName);
  const coders = useCoderStore((s) => s.coders);
  const switchCoder = useCoderStore((s) => s.switchCoder);
  const createCoder = useCoderStore((s) => s.createCoder);
  const syncStatus = usePrefsStore((s) => s.syncStatus);
  const setSyncStatus = usePrefsStore((s) => s.setSyncStatus);
  const setSyncEnabled = usePrefsStore((s) => s.setSyncEnabled);
  const runSyncNow = usePrefsStore((s) => s.runSyncNow);
  const presence = usePrefsStore((s) => s.presence);
  const collabMode = usePrefsStore((s) => s.collabMode);
  const activateCollaboration = usePrefsStore((s) => s.activateCollaboration);
  const revertCollaboration = usePrefsStore((s) => s.revertCollaboration);
  const consolidate = usePrefsStore((s) => s.consolidate);
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
  const [conflictOpen, setConflictOpen] = useState(false);
  const [viewportTick, setViewportTick] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const syncEnabled = syncStatus?.ok === true && syncStatus.enabled === true;
  const syncError = Boolean(syncStatus?.last_error);
  const refreshHelpAnchor = helpOpen === "refresh" ? refreshHelpAnchorEl : null;

  // Latest live presence entry per coder (fresh heartbeat wins).
  const liveByCoder = useMemo(() => {
    const map = new Map<string, { ts: number; file_name: string }>();
    for (const e of presence) {
      if (!e.coder) continue;
      const prev = map.get(e.coder);
      if (!prev || e.ts > prev.ts) map.set(e.coder, { ts: e.ts, file_name: e.file_name });
    }
    return map;
  }, [presence]);

  /** Live peers (fresh heartbeat), newest first — rendered in the flyout so
   *  the user can see who is working on what right now. */
  const livePeers = useMemo(
    () =>
      [...liveByCoder.entries()]
        .filter(([, p]) => isLive(p.ts))
        .sort((a, b) => b[1].ts - a[1].ts)
        .map(([coder, p]) => ({ coder, file_name: p.file_name })),
    [liveByCoder],
  );

  // Per-coder sync state from collaborator data (instance → coder name).
  const coderSyncState = useMemo(() => {
    const map: Record<string, { state: string; pending: number; last_sync: number }> = {};
    if (syncStatus?.collaborators) {
      for (const c of syncStatus.collaborators) {
        const name = c.coder || c.instance;
        // A live presence heartbeat wins over a stale sidecar mtime.
        map[name] = { state: c.state, pending: c.pending_import, last_sync: c.last_sync };
      }
    }
    return map;
  }, [syncStatus]);

  /** Per-coder activity: live presence first, then collaborator sync state. */
  function coderActivity(name: string): CoderActivity {
    if (!syncEnabled) return "offline";
    const live = liveByCoder.get(name);
    if (live && isLive(live.ts)) return "live";
    const cs = coderSyncState[name];
    if (cs?.state === "active") return "active";
    if (cs?.state === "stale") return "stale";
    return "offline";
  }

  function activityDot(activity: CoderActivity): string {
    switch (activity) {
      case "live":
      case "active":
        return "bg-success";
      case "stale":
        return "bg-warning";
      default:
        return "bg-border";
    }
  }

  function activityTitle(activity: CoderActivity): string {
    switch (activity) {
      case "live":
        return t("sync.presenceLive");
      case "active":
        return t("sync.stateActive");
      case "stale":
        return t("sync.stateStale");
      default:
        return t("sync.stateOffline");
    }
  }

  /** Overall sync dot in the ribbon (single, not per-coder). */
  const overallState = syncStatus?.state;
  const overallDot = !syncEnabled
    ? "bg-border"
    : overallState === "conflict" || overallState === "error"
      ? "bg-danger"
      : overallState === "syncing"
        ? "bg-warning"
        : "bg-success";
  const overallTitle = !syncEnabled
    ? t("sync.indicatorOff")
    : overallState === "conflict"
      ? t("sync.indicatorConflict")
      : overallState === "error"
        ? t("sync.indicatorError")
        : overallState === "syncing"
          ? t("sync.indicatorPending")
          : t("sync.indicatorActive");

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
    // Refresh presence immediately so the "Live now" section is fresh, then
    // keep polling while the flyout stays open — otherwise every peer's dot
    // flips to offline after the 60s liveness window despite active
    // heartbeats (the backend beats every 15s).
    void usePrefsStore.getState().refreshPresence();
    const presenceTimer = window.setInterval(
      () => void usePrefsStore.getState().refreshPresence(),
      SYNC_POLL_MS,
    );
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
      window.clearInterval(presenceTimer);
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
      // Force all open coder views to re-fetch — the backend *_visible
      // views now exclude/include the toggled coder's rows.
      window.dispatchEvent(new CustomEvent("qc:codings-changed"));
    } catch {
      setError(t("coder.visibilityHint"));
    }
  }

  async function syncNow() {
    setSyncBusy(true);
    try {
      const ok = await runSyncNow();
      if (ok) {
        // Pulled entries land in the DB but not in open views — refresh so
        // the user sees pulled codes/sources without a second click.
        await useProjectStore.getState().refreshProject();
      }
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
    // Adding a second coder with sync on starts collaboration mode.
    if (syncEnabled && collabMode !== "collaboration") {
      const activated = await activateCollaboration();
      if (activated) {
        toast.success(t("collab.activated"));
      } else {
        toast.error(t("collab.activateFailed"));
      }
    }
  }

  async function handleActivateCollab() {
    setSyncBusy(true);
    try {
      // Collaboration requires background sync; enabling is part of the
      // explicit activation (never automatic elsewhere).
      await setSyncEnabled(true, { remember: true });
      const ok = await activateCollaboration();
      if (ok) toast.success(t("collab.activated"));
      else toast.error(t("collab.activateFailed"));
    } finally {
      setSyncBusy(false);
    }
  }

  async function handleRevertCollab() {
    if (!window.confirm(t("collab.revertConfirm"))) return;
    setSyncBusy(true);
    try {
      const ok = await revertCollaboration();
      if (ok) {
        toast.success(t("collab.reverted"));
        // Leaving collaboration makes background sync irrelevant.
        await setSyncEnabled(false, { remember: true });
      } else {
        toast.error(t("collab.activateFailed"));
      }
    } finally {
      setSyncBusy(false);
    }
  }

  async function handleRefresh() {
    // Unified refresh: reload the project data and, in collaboration mode,
    // also refresh the cold data.qda archive from the sandbox.
    await useProjectStore.getState().refreshProject();
    if (collabMode === "collaboration") {
      const ok = await consolidate();
      if (ok) toast.success(t("collab.consolidated"));
    }
    closeAll();
  }

  async function refreshCoders() {
    await useCoderStore.getState().loadCoders();
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
      toast.error(errorMessage(e, "Operation failed"));
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
          toast.error(errorMessage(err, "Operation failed"));
          return;
        }
      } else {
        toast.error(errorMessage(e, "Operation failed"));
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
      toast.error(errorMessage(e, "Operation failed"));
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
      <Button
        variant="toolbar"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t("coder.switchAria", { name: coderName })}
        title={t("coder.switchTitle")}
        // Flex row so a long coder name ellipsizes instead of wrapping
        // the trailing dot/chevron to a second (clipped) line; auto-adapts
        // to the text width, capped so it never dominates the ribbon.
        className="min-w-[4.5rem] max-w-[20rem] overflow-hidden leading-none"
      >
        <User size={12} className="shrink-0 text-text-secondary" aria-hidden />
        <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap">{coderName}</span>
        <span
          role="status"
          aria-label={overallTitle}
          title={overallTitle}
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${overallDot}`}
        />
        <ChevronDown size={12} className="shrink-0 text-text-secondary" aria-hidden />
      </Button>

      {open && (
        <Menu
          position="fixed"
          role="listbox"
          aria-label={t("coder.listAria")}
          className="min-w-60 overflow-y-auto"
          style={{ ...menuPos, width: FLYOUT_WIDTH }}
        >
          {coders.map((c) => {
            const activity = coderActivity(c.name);
            const dotColor = activityDot(activity);
            const dotTitle = activityTitle(activity);
            const cs = coderSyncState[c.name];
            return (
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
                  <span
                    role="status"
                    aria-label={dotTitle}
                    title={dotTitle}
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotColor}`}
                  />
                  {cs && cs.last_sync > 0 && (
                    <span className="text-[10px] text-text-secondary" title={t("sync.lastSyncShort", { when: formatSince(cs.last_sync) })}>
                      {formatSince(cs.last_sync)}
                    </span>
                  )}
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
            );
          })}
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
              <span className="truncate">
                {collabMode === "collaboration"
                  ? t("coder.consolidateRefresh")
                  : t("coder.refreshProject")}
              </span>
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
              onClick={() => void handleRefresh()}
              aria-label={t("coder.refreshProject")}
              title={t("coder.refreshProject")}
              className="shrink-0 rounded-sm p-1 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
            >
              <RefreshCw size={13} aria-hidden />
            </button>
          </div>

          {/* Collaboration + sync */}
          <div className="my-1 h-px bg-border" aria-hidden />
          <div className="px-2 py-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1 text-sm text-text-primary">
                <span className="truncate">{t("collab.mode")}</span>
                <IconButton
                  label={t("collab.activateHint")}
                  title={t("collab.activateHint")}
                  size="sm"
                >
                  <HelpCircle size={12} aria-hidden />
                </IconButton>
              </span>
              <span
                role="status"
                className={`shrink-0 rounded-sm px-1.5 py-0.5 text-[10px] font-medium leading-none ${
                  collabMode === "collaboration"
                    ? "bg-accent/15 text-accent"
                    : "bg-border/50 text-text-secondary"
                }`}
              >
                {collabMode === "collaboration" ? t("collab.active") : t("collab.single")}
              </span>
            </div>
            {/* Background sync is inherently ON while collaborating and
                irrelevant otherwise — no standalone toggle (user directive).
                Sync-now + Revert/Activate live on one row below. */}
            {livePeers.length > 0 && (
              /* Live peers (fresh heartbeats): who is working on what now. */
              <div className="mt-1.5 space-y-1" data-testid="live-peers">
                {livePeers.map((p) => (
                  <div key={p.coder} className="flex min-w-0 items-center gap-1.5 text-xs">
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-success" aria-hidden />
                    <span className="truncate font-medium text-text-primary">{p.coder}</span>
                    {p.file_name && (
                      <>
                        <span className="shrink-0 text-text-secondary" aria-hidden>
                          —
                        </span>
                        <span className="min-w-0 truncate text-text-secondary">
                          {p.file_name}
                        </span>
                      </>
                    )}
                    <span className="shrink-0 text-[10px] text-success">
                      {t("sync.presenceLive")}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-1.5 flex items-center gap-1.5">
              {collabMode === "collaboration" && (
                /* Sync-now only exists inside collaboration: background sync
                   is always on there, and irrelevant otherwise. */
                <button
                  type="button"
                  onClick={() => void syncNow()}
                  disabled={syncBusy}
                  title={syncError ? (syncStatus?.last_error ?? t("sync.error")) : t("sync.now")}
                  className="flex shrink-0 items-center gap-1 whitespace-nowrap rounded-sm bg-warning px-2 py-0.5 text-xs font-medium leading-none text-[var(--qc-bg)] hover:bg-warning/90 disabled:opacity-50"
                >
                  <RefreshCw
                    size={9}
                    className={`shrink-0 ${syncBusy ? "animate-spin" : ""}`}
                    aria-hidden
                  />
                  {syncStatus?.last_sync
                    ? t("sync.lastSyncShort", { when: formatSince(syncStatus.last_sync) })
                    : t("sync.never")}
                </button>
              )}
              {collabMode === "collaboration" ? (
                <button
                  type="button"
                  onClick={() => void handleRevertCollab()}
                  disabled={syncBusy}
                  className="shrink-0 rounded-sm border border-danger/30 bg-danger/5 px-2 py-0.5 text-xs text-danger hover:bg-danger/10 disabled:opacity-50"
                >
                  {t("collab.revert")}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void handleActivateCollab()}
                  disabled={syncBusy}
                  title={t("collab.needsTwoCoders")}
                  className="flex-1 rounded-sm bg-accent px-2 py-0.5 text-xs font-medium leading-none text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50"
                >
                  {t("collab.activate")}
                </button>
              )}
            </div>
            {collabMode === "collaboration" && syncEnabled && (
              <div className="mt-1.5 space-y-1 text-[11px] leading-snug text-text-secondary">
                {syncStatus && (syncStatus.pending_export > 0 || syncStatus.pending_import > 0) && (
                  <p className="text-warning">
                    {t("sync.pending", {
                      n: String(syncStatus.pending_export + syncStatus.pending_import),
                    })}
                  </p>
                )}
                {syncStatus && syncStatus.pending_conflicts > 0 && (
                  <div className="space-y-1 rounded-sm border border-danger/30 bg-danger/5 p-1.5">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-text-primary">
                        {t("sync.conflicts", { n: String(syncStatus.pending_conflicts) })}
                      </span>
                      <button
                        type="button"
                        onClick={() => void usePrefsStore.getState().loadConflicts().then(() => setConflictOpen(true))}
                        disabled={syncBusy}
                        className="rounded-sm bg-danger px-1.5 py-0.5 text-[10px] font-medium leading-none text-white hover:bg-danger/90 disabled:opacity-50"
                      >
                        {t("sync.conflictsResolve", { n: String(syncStatus.pending_conflicts) })}
                      </button>
                    </div>
                  </div>
                )}
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

      {/* Conflict Resolution Modal */}
      {conflictOpen && (
        <ConflictResolver open={conflictOpen} onClose={() => setConflictOpen(false)} />
      )}
    </div>
  );
}
