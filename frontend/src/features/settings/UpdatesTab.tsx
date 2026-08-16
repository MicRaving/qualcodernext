/**
 * UpdatesTab — Settings "Updates" tab: the auto-update toggle with the
 * check-interval select right beside it, plus Check now / Install and the
 * live update status.
 */
import { useEffect, useState } from "react";
import { Check, Download, LoaderCircle, RotateCw } from "lucide-react";
import { Button, Field, Select, Toggle } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useUpdatesStore } from "@/stores/updates";
import type { UpdatesSettings } from "@/lib/api";

export function UpdatesTab() {
  const { t } = useI18n();

  const updatesStatus = useUpdatesStore((s) => s.status);
  const updatesInfo = useUpdatesStore((s) => s.info);
  const updatesProgress = useUpdatesStore((s) => s.progress);
  const updatesError = useUpdatesStore((s) => s.error);
  const updatesSettings = useUpdatesStore((s) => s.settings);
  const [checkInterval, setCheckInterval] = useState<UpdatesSettings["check_interval"]>("daily");
  const [autoUpdate, setAutoUpdate] = useState(
    () => useUpdatesStore.getState().settings?.auto_update ?? true,
  );

  useEffect(() => {
    const store = useUpdatesStore.getState();
    if (!updatesSettings) void store.loadSettings();
  }, [updatesSettings]);

  useEffect(() => {
    if (updatesSettings) {
      setCheckInterval(updatesSettings.check_interval);
      setAutoUpdate(updatesSettings.auto_update);
    }
  }, [updatesSettings]);

  async function toggleAutoUpdate() {
    const next = !autoUpdate;
    setAutoUpdate(next);
    const settings = { check_interval: checkInterval, auto_update: next };
    try {
      await useUpdatesStore.getState().saveSettings(settings);
      if (next) {
        // Enabling auto-update checks immediately (matches the scheduler).
        void useUpdatesStore.getState().checkNow();
      }
    } catch {
      /* keep the local toggle; the backend error surfaces on the next load */
    }
  }

  async function setIntervalAndSave(interval: UpdatesSettings["check_interval"]) {
    setCheckInterval(interval);
    try {
      await useUpdatesStore
        .getState()
        .saveSettings({ check_interval: interval, auto_update: autoUpdate });
    } catch {
      /* same as above */
    }
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      <h2 className="text-sm font-semibold text-text-primary">{t("settings.updatesSection")}</h2>

      {/* Auto-update toggle + check interval, side by side */}
      <div className="mt-3 grid grid-cols-2 items-end gap-3">
        <Field label={t("settings.updatesAuto")}>
          <div className="mt-1">
            <Toggle
              checked={autoUpdate}
              onChange={() => void toggleAutoUpdate()}
              label={t("settings.updatesAuto")}
            />
          </div>
        </Field>
        <Field label={t("settings.updatesInterval")}>
          <Select
            value={checkInterval}
            onChange={(e) => void setIntervalAndSave(e.target.value as UpdatesSettings["check_interval"])}
            className="mt-1 w-full"
          >
            <option value="daily">{t("settings.updatesIntervalDaily")}</option>
            <option value="weekly">{t("settings.updatesIntervalWeekly")}</option>
            <option value="never">{t("settings.updatesIntervalNever")}</option>
          </Select>
        </Field>
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-3">
        <Button
          variant="secondary"
          icon={
            updatesStatus === "checking" ? (
              <LoaderCircle size={12} className="animate-spin" aria-hidden />
            ) : (
              <RotateCw size={12} aria-hidden />
            )
          }
          disabled={updatesStatus === "checking" || updatesStatus === "downloading"}
          onClick={() => void useUpdatesStore.getState().checkNow()}
        >
          {t("settings.updatesCheckNow")}
        </Button>
        {updatesStatus === "available" && updatesInfo && (
          <Button
            variant="primary"
            icon={<Download size={12} aria-hidden />}
            onClick={() => void useUpdatesStore.getState().install()}
          >
            {t("settings.updatesInstall")}
          </Button>
        )}
      </div>

      {updatesStatus === "checking" && (
        <p className="mt-2 text-xs text-text-secondary">{t("settings.updatesChecking")}</p>
      )}
      {updatesStatus === "up-to-date" && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-success" role="status">
          <Check size={12} aria-hidden />
          {t("settings.updatesUpToDate")}
        </p>
      )}
      {updatesStatus === "available" && updatesInfo && (
        <p className="mt-2 text-xs text-text-primary">
          {t("settings.updatesAvailable", { version: updatesInfo.version })}
        </p>
      )}
      {updatesStatus === "downloading" && (
        <div className="mt-2">
          <div className="h-1 w-full overflow-hidden rounded-full bg-border">
            <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${updatesProgress}%` }} />
          </div>
          <p className="mt-1 text-xs text-text-secondary">
            {t("settings.updatesDownloading", { pct: String(updatesProgress) })}
          </p>
        </div>
      )}
      {updatesStatus === "error" && (
        <p className="mt-2 text-xs text-danger">
          {updatesError === "desktop only"
            ? t("settings.updatesDesktopOnly")
            : t("settings.updatesError", { detail: updatesError ?? "" })}
        </p>
      )}
    </div>
  );
}
