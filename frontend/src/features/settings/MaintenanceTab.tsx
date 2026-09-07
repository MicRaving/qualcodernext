/**
 * MaintenanceTab — Settings "Project maintenance" category: auto-load on
 * start, compact-on-close and the collaboration sync cadence in one place.
 * (The semantic index controls moved to the search dialog (ribbon search).)
 */
import { useEffect, useState } from "react";
import { Wrench } from "lucide-react";
import { api } from "@/lib/api";
import { errorDetail } from "@/features/ai/format";
import { useI18n } from "@/lib/i18n";
import { ErrorBanner, SectionLabel, Select, Toggle } from "@/components/ui/orchestrator";
import { BackupsSection } from "@/features/settings/BackupsSection";
import { isServerMode } from "@/lib/session";

export function MaintenanceTab() {
  const { t } = useI18n();

  // Auto-load project on start (packaged app only; harmless elsewhere).
  const [autoLoadProject, setAutoLoadProject] = useState(true);

  // Project compaction (automatic only — no manual "compact now").
  const [compactOnClose, setCompactOnClose] = useState(false);
  const [compactError, setCompactError] = useState<string | null>(null);

  // Collaboration sync cadence (1 min default).
  const [syncIntervalSecs, setSyncIntervalSecs] = useState(60);

  useEffect(() => {
    api
      .appSettings()
      .then((s) => setAutoLoadProject(s.auto_open_project))
      .catch(() => {
        /* backend unreachable — keep the default */
      });
    api
      .maintenanceSettings()
      .then((s) => setCompactOnClose(s.compact_on_close))
      .catch(() => undefined);
    api
      .syncSettings()
      .then((s) => setSyncIntervalSecs(s.interval_secs))
      .catch(() => {
        /* backend unreachable — keep the 1-minute default */
      });
  }, []);

  async function toggleAutoLoadProject() {
    const next = !autoLoadProject;
    setAutoLoadProject(next);
    try {
      await api.saveAppSettings({ auto_open_project: next });
    } catch {
      /* keep the local toggle; the backend error surfaces on the next load */
    }
  }

  async function toggleCompactOnClose() {
    const next = !compactOnClose;
    setCompactOnClose(next);
    try {
      await api.saveMaintenanceSettings({ compact_on_close: next });
      setCompactError(null);
    } catch (e) {
      setCompactError(errorDetail(e, "Could not save maintenance settings"));
      setCompactOnClose(!next);
    }
  }

  async function saveSyncInterval(secs: number) {
    setSyncIntervalSecs(secs);
    try {
      // Keep the enabled flag; the backend stores/validates the cadence.
      const s = await api.syncSettings();
      await api.setSyncEnabled(s.enabled, secs);
    } catch {
      /* the next load falls back to the stored value */
    }
  }

  return (
    <div className="p-3">
      {compactError && <ErrorBanner>{compactError}</ErrorBanner>}

      <h2 className="flex items-center gap-1.5 text-sm font-semibold text-text-primary">
        <Wrench size={13} className="shrink-0" aria-hidden />
        {t("settings.maintenanceSection")}
      </h2>

      {/* Auto-load on start */}
      <div className="mt-2">
        <Toggle
          checked={autoLoadProject}
          onChange={() => void toggleAutoLoadProject()}
          label={t("settings.autoLoadProject")}
          hint={t("settings.autoLoadProjectHint")}
        />
      </div>

      {/* Project compaction — the "Compact on close" switch only; the full
          pass runs automatically when the project is closed. */}
      <div className="mt-3 border-t border-border pt-3">
        <Toggle
          checked={compactOnClose}
          onChange={() => void toggleCompactOnClose()}
          label={t("settings.compactOnClose")}
          hint={t("settings.compactOnCloseHint")}
        />
      </div>

      {/* Collaboration sync cadence */}
      <div className="mt-3 border-t border-border pt-3">
        <SectionLabel>{t("sync.interval")}</SectionLabel>
        <Select
          value={syncIntervalSecs}
          onChange={(e) => void saveSyncInterval(Number(e.target.value))}
          className="mt-2 w-full"
          aria-label={t("sync.interval")}
        >
          <option value={15}>{t("sync.interval15s")}</option>
          <option value={30}>{t("sync.interval30s")}</option>
          <option value={60}>{t("sync.interval60s")}</option>
          <option value={120}>{t("sync.interval120s")}</option>
          <option value={300}>{t("sync.interval300s")}</option>
        </Select>
        <p className="mt-1 text-xs text-text-secondary">{t("sync.intervalHint")}</p>
      </div>

      {isServerMode() && <BackupsSection />}
    </div>
  );
}
