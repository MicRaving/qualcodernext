/**
 * UpdatesTab — Settings "Updates" tab: the auto-update toggle with the
 * check-interval select right beside it, plus Check now / Install and the
 * live update status.
 */
import { useEffect, useState } from "react";
import { Check, Download, LoaderCircle, RotateCw } from "lucide-react";
import { Button, Select } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { NO_UPDATE_MANIFEST, useUpdatesStore } from "@/stores/updates";
import type { UpdatesSettings } from "@/lib/api";

export function UpdatesTab() {
  const { t } = useI18n();

  const updatesStatus = useUpdatesStore((s) => s.status);
  const updatesInfo = useUpdatesStore((s) => s.info);
  const updatesProgress = useUpdatesStore((s) => s.progress);
  const updatesError = useUpdatesStore((s) => s.error);
  const updatesSettings = useUpdatesStore((s) => s.settings);
  const [checkInterval, setCheckInterval] = useState<UpdatesSettings["check_interval"]>("daily");

  useEffect(() => {
    const store = useUpdatesStore.getState();
    if (!updatesSettings) void store.loadSettings();
  }, [updatesSettings]);

  useEffect(() => {
    if (updatesSettings) {
      setCheckInterval(updatesSettings.check_interval);
    }
  }, [updatesSettings]);

  async function setIntervalAndSave(interval: UpdatesSettings["check_interval"]) {
    setCheckInterval(interval);
    try {
      await useUpdatesStore
        .getState()
        .saveSettings({ check_interval: interval, auto_update: updatesSettings?.auto_update ?? true });
    } catch {
      /* the backend error surfaces on the next load */
    }
  }

  return (
    <div className="p-3">
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-text-primary">{t("settings.updatesSection")}</h2>
      </div>

      {/* Interval (left) | Check now (right) */}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-1.5 text-[11px] text-text-secondary">
          <span>{t("settings.updatesInterval")}</span>
          <Select
            value={checkInterval}
            onChange={(e) => void setIntervalAndSave(e.target.value as UpdatesSettings["check_interval"])}
            className="w-28"
          >
            <option value="daily">{t("settings.updatesIntervalDaily")}</option>
            <option value="weekly">{t("settings.updatesIntervalWeekly")}</option>
            <option value="never">{t("settings.updatesIntervalNever")}</option>
          </Select>
        </label>
        <div className="flex flex-wrap items-center gap-2">
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
            : updatesError === NO_UPDATE_MANIFEST
              ? t("settings.updatesNoManifest")
              : t("settings.updatesError", { detail: updatesError ?? "" })}
        </p>
      )}
    </div>
  );
}
