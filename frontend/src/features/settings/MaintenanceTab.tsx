/**
 * MaintenanceTab — Settings "Maintenance" section: the compact-on-close
 * switch (the full compaction runs automatically on project close). The
 * semantic index controls moved to the search dialog (ribbon search).
 */
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { errorDetail } from "@/features/ai/format";
import { useI18n } from "@/lib/i18n";
import { ErrorBanner, Toggle } from "@/components/ui/orchestrator";
import { BackupsSection } from "@/features/settings/BackupsSection";
import { isServerMode } from "@/lib/session";

export function MaintenanceTab() {
  const { t } = useI18n();

  // Project compaction (automatic only — no manual "compact now").
  const [compactOnClose, setCompactOnClose] = useState(false);
  const [compactError, setCompactError] = useState<string | null>(null);

  useEffect(() => {
    api
      .maintenanceSettings()
      .then((s) => setCompactOnClose(s.compact_on_close))
      .catch(() => undefined);
  }, []);

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

  return (
    <div className="p-3">
      {compactError && <ErrorBanner>{compactError}</ErrorBanner>}

      {/* Project compaction — the "Compact on close" switch only; the full
          pass runs automatically when the project is closed. */}
      <h2 className="text-sm font-semibold text-text-primary">{t("settings.maintenanceSection")}</h2>
      <div className="mt-2">
        <Toggle
          checked={compactOnClose}
          onChange={() => void toggleCompactOnClose()}
          label={t("settings.compactOnClose")}
          hint={t("settings.compactOnCloseHint")}
        />
      </div>

      {isServerMode() && <BackupsSection />}
    </div>
  );
}
