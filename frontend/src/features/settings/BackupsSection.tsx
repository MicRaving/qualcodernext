/**
 * BackupsSection — server-mode backup management for the OPEN project
 * (SERVER_PLAN.md §9.3 UI): list snapshots, create one on demand, restore.
 * Rendered inside Settings → Maintenance only when running against a
 * server (VITE_SERVER_MODE) with an open project; invisible in local mode.
 */
import { useCallback, useEffect, useState } from "react";
import { Archive, LoaderCircle, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import { Button, ErrorBanner } from "@/components/ui/orchestrator";
import { errorMessage } from "@/lib/utils";
import { getProjectId } from "@/lib/session";
import { useI18n } from "@/lib/i18n";

interface BackupRow {
  id: number;
  kind: string;
  size_bytes: number;
  created_at: string;
}

export function BackupsSection() {
  const { t } = useI18n();
  const projectId = getProjectId();
  const [rows, setRows] = useState<BackupRow[]>([]);
  const [busy, setBusy] = useState<number | "create" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!projectId) return;
    try {
      const res = await api.serverListBackups(projectId);
      setRows(res.backups);
      setError(null);
    } catch (e) {
      setError(errorMessage(e, t("settings.backupLoadError")));
    }
  }, [projectId, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!projectId) return null;

  async function createBackup() {
    if (!projectId || busy) return;
    setBusy("create");
    try {
      await api.serverCreateBackup(projectId);
      await refresh();
      setError(null);
    } catch (e) {
      setError(errorMessage(e, t("settings.backupCreateError")));
    } finally {
      setBusy(null);
    }
  }

  async function restore(id: number) {
    if (!projectId || busy) return;
    setBusy(id);
    try {
      await api.serverRestoreBackup(projectId, id);
      await refresh();
      setError(null);
    } catch (e) {
      setError(errorMessage(e, t("settings.backupRestoreError")));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mt-6">
      <h2 className="text-sm font-semibold text-text-primary">{t("settings.backupSection")}</h2>
      {error && <ErrorBanner onClose={() => setError(null)}>{error}</ErrorBanner>}
      <div className="mt-2 flex items-center justify-between gap-2">
        <p className="text-xs text-text-secondary">{t("settings.backupHint")}</p>
        <Button
          variant="secondary"
          icon={<Archive size={13} aria-hidden />}
          disabled={busy === "create"}
          onClick={() => void createBackup()}
        >
          {busy === "create" ? (
            <LoaderCircle size={12} className="animate-spin" aria-hidden />
          ) : null}
          {t("settings.backupNow")}
        </Button>
      </div>
      {rows.length > 0 && (
        <ul className="mt-2 space-y-1">
          {rows.map((b) => (
            <li
              key={b.id}
              className="flex items-center gap-2 rounded-sm border border-border bg-bg px-2 py-1.5 text-xs"
            >
              <span className="truncate font-medium text-text-primary">
                {t("settings.backupKind", { kind: b.kind })}
              </span>
              <span className="min-w-0 flex-1 truncate text-text-secondary">
                {new Date(b.created_at).toLocaleString()} ·{" "}
                {(b.size_bytes / (1024 * 1024)).toFixed(1)} MB
              </span>
              <Button
                variant="secondary"
                icon={<RotateCcw size={12} aria-hidden />}
                disabled={busy !== null}
                onClick={() => void restore(b.id)}
              >
                {t("settings.backupRestore")}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
