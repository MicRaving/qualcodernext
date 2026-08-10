/**
 * SyncChip — collaboration indicator (Option B: sidecar change files over
 * folder-sync tools). Shows pending outbound/inbound changes and the other
 * raters' last-sync times; "Sync now" triggers an immediate cycle.
 */
import { useEffect, useRef, useState } from "react";
import { RefreshCw, Users } from "lucide-react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";

const SYNC_POLL_MS = 60_000;

function formatLastSync(ts: number): string {
  if (!ts) return "—";
  const delta = Date.now() / 1000 - ts;
  if (delta < 60) return "now";
  if (delta < 3600) return `${Math.round(delta / 60)} min`;
  if (delta < 86400) return `${Math.round(delta / 3600)} h`;
  return `${Math.round(delta / 86400)} d`;
}

export function SyncChip() {
  const { t } = useI18n();
  const syncStatus = useProjectStore((s) => s.syncStatus);
  const setSyncStatus = useProjectStore((s) => s.setSyncStatus);
  const runSyncNow = useProjectStore((s) => s.runSyncNow);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const status = await api.syncStatus();
        if (!cancelled) setSyncStatus(status);
      } catch {
        /* project just closed etc. — keep the last known state */
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), SYNC_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [setSyncStatus]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (target && !rootRef.current?.contains(target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  if (!syncStatus || !syncStatus.ok) return null;
  const { pending_export: out, pending_import: incoming, collaborators } = syncStatus;
  const dirty = out > 0 || incoming > 0;

  async function syncNow() {
    setBusy(true);
    try {
      await runSyncNow();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        title={t("sync.title")}
        className={`flex items-center gap-1.5 rounded-sm border px-2 py-1 text-xs hover:bg-surface-higher ${
          dirty ? "border-accent/60 text-accent" : "border-border bg-bg text-text-secondary"
        }`}
      >
        <Users size={12} aria-hidden />
        {dirty
          ? `${t("sync.pending")} ${out + incoming}`
          : collaborators.length > 0
            ? `${collaborators.length} ${t("sync.active")}`
            : t("sync.synced")}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-80 rounded-md border border-border bg-surface py-1 shadow-lg">
          <div className="border-b border-border px-2 py-1 text-xs font-medium text-text-secondary">
            {t("sync.title")}
          </div>
          <div className="px-2 py-1.5 text-xs text-text-primary">
            {t("sync.pendingExport", { n: String(out) })}
            <span className="mx-1 text-text-secondary">·</span>
            {t("sync.pendingImport", { n: String(incoming) })}
          </div>
          {collaborators.length > 0 ? (
            <div className="max-h-40 overflow-y-auto border-t border-border">
              {collaborators.map((c) => (
                <div
                  key={c.user}
                  className="flex items-center gap-2 px-2 py-1.5 text-xs"
                >
                  <span className="h-2 w-2 shrink-0 rounded-full bg-accent" aria-hidden />
                  <span className="min-w-0 flex-1 truncate font-medium text-text-primary">
                    {c.user}
                  </span>
                  {c.pending_import > 0 && (
                    <span className="text-warning">{t("sync.pending", { n: String(c.pending_import) })}</span>
                  )}
                  <span className="shrink-0 text-text-secondary">
                    {t("sync.lastSync", { when: formatLastSync(c.last_sync) })}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="border-t border-border px-2 py-1.5 text-xs text-text-secondary">
              {t("sync.noCollaborators")}
            </p>
          )}
          <div className="flex items-center justify-between border-t border-border px-2 py-1.5">
            <p className="text-[11px] leading-snug text-text-secondary">{t("sync.hint")}</p>
            <button
              type="button"
              onClick={() => void syncNow()}
              disabled={busy}
              className="flex shrink-0 items-center gap-1 rounded-sm bg-accent px-2 py-1 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50"
            >
              <RefreshCw size={11} className={busy ? "animate-spin" : undefined} aria-hidden />
              {t("sync.now")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
