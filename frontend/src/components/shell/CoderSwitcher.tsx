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
import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Eye, EyeOff, RefreshCw, User, UserPlus, X } from "lucide-react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";

const SYNC_POLL_MS = 30_000;

function formatSince(ts: number): string {
  if (!ts) return "—";
  const delta = Date.now() / 1000 - ts;
  if (delta < 60) return "0m";
  if (delta < 3600) return `${Math.round(delta / 60)}m`;
  if (delta < 86400) return `${Math.round(delta / 3600)}h`;
  return `${Math.round(delta / 86400)}d`;
}

export function CoderSwitcher() {
  const { t } = useI18n();
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
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const syncEnabled = syncStatus?.ok === true && syncStatus.enabled === true;
  const syncError = Boolean(syncStatus?.last_error);

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
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        setAdding(false);
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

  function closeAll() {
    setOpen(false);
    setAdding(false);
  }

  return (
    <div ref={rootRef} className="relative flex items-center gap-1">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t("coder.switchAria", { name: coderName })}
        title={t("coder.switchTitle")}
        className="flex max-w-44 items-center gap-1.5 rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher"
      >
        <User size={12} className="shrink-0 text-text-secondary" aria-hidden />
        <span className="truncate">{coderName}</span>
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
            syncEnabled ? (syncError ? "bg-danger" : "bg-success") : "bg-transparent"
          }`}
          aria-hidden={!syncEnabled}
        />
        <ChevronDown size={12} className="shrink-0 text-text-secondary" aria-hidden />
      </button>

      {open && (
        <div
          role="listbox"
          aria-label={t("coder.listAria")}
          className="absolute right-0 top-full z-50 mt-1 min-w-60 rounded-md border border-border bg-surface py-1 shadow-lg"
        >
          {coders.map((c) => (
            <div
              key={c.name}
              role="option"
              aria-selected={c.name === coderName}
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
                  className="w-full min-w-0 flex-1 rounded-sm border border-border bg-bg px-2 py-1 text-sm outline-none focus:border-accent"
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

          {/* Collaboration sync */}
          <div className="my-1 h-px bg-border" aria-hidden />
          <div className="px-2 py-1.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-text-primary">{t("sync.title")}</span>
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
            </div>
            {syncEnabled && (
              <div className="mt-1.5 space-y-1 text-[11px] leading-snug text-text-secondary">
                <p>
                  {t("sync.lastSyncShort", {
                    when: formatSince(syncStatus?.last_sync ?? 0),
                  })}
                  {syncStatus && (syncStatus.pending_export > 0 || syncStatus.pending_import > 0) && (
                    <span className="text-warning">
                      {" · "}
                      {t("sync.pending", {
                        n: String(syncStatus.pending_export + syncStatus.pending_import),
                      })}
                    </span>
                  )}
                </p>
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
                <button
                  type="button"
                  onClick={() => void syncNow()}
                  disabled={syncBusy}
                  className="mt-1 flex items-center gap-1 rounded-sm bg-accent px-2 py-0.5 text-[11px] font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50"
                >
                  <RefreshCw size={10} className={syncBusy ? "animate-spin" : undefined} aria-hidden />
                  {t("sync.now")}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
