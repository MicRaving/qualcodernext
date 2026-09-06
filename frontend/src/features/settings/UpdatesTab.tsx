/**
 * UpdatesTab — Settings "Updates" tab: the auto-update toggle with the
 * check-interval select right beside it, the stable/nightly channel
 * opt-in, plus Check now / Install and the live update status.
 *
 * Nightlies (`X.Y.Z_NNN`) are opt-in delta patches: small downloads that
 * hotpatch without a full installer. The channel persists in the backend
 * (`~/.qualcoder/settings.json` → `updates.channel`).
 */
import { useEffect, useState } from "react";
import { Check, Download, LoaderCircle, RotateCw, Undo2 } from "lucide-react";
import { Button, Select, Toggle } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import {
  LARGE_UPDATE_BYTES,
  NIGHTLY_MANIFEST_URL,
  formatBytes,
  updateDownloadSize,
  useUpdatesStore,
} from "@/stores/updates";
import { NO_UPDATE_MANIFEST } from "@/stores/updates";
import type { UpdatesSettings } from "@/lib/api";

export function UpdatesTab() {
  const { t } = useI18n();

  const updatesStatus = useUpdatesStore((s) => s.status);
  const updatesInfo = useUpdatesStore((s) => s.info);
  const updatesProgress = useUpdatesStore((s) => s.progress);
  const updatesError = useUpdatesStore((s) => s.error);
  const updatesSettings = useUpdatesStore((s) => s.settings);
  const hotpatch = useUpdatesStore((s) => s.hotpatch);
  const overlay = useUpdatesStore((s) => s.overlay);
  const nativeState = useUpdatesStore((s) => s.native);
  const [checkInterval, setCheckInterval] = useState<UpdatesSettings["check_interval"]>("daily");
  const [channel, setChannel] = useState<UpdatesSettings["channel"]>("stable");
  const [autoLarge, setAutoLarge] = useState(true);

  useEffect(() => {
    const store = useUpdatesStore.getState();
    if (!updatesSettings) void store.loadSettings();
    void store.loadHotpatch();
  }, [updatesSettings]);

  useEffect(() => {
    if (updatesSettings) {
      setCheckInterval(updatesSettings.check_interval);
      setChannel(updatesSettings.channel ?? "stable");
      setAutoLarge(updatesSettings.auto_large_updates ?? true);
    }
  }, [updatesSettings]);

  async function persist(patch: Partial<UpdatesSettings>) {
    const current = useUpdatesStore.getState().settings;
    try {
      await useUpdatesStore.getState().saveSettings({
        check_interval: patch.check_interval ?? checkInterval,
        auto_update: patch.auto_update ?? (current?.auto_update ?? true),
        channel: patch.channel ?? channel,
        auto_large_updates: patch.auto_large_updates ?? autoLarge,
      });
    } catch {
      /* the backend error surfaces on the next load */
    }
  }

  async function setIntervalAndSave(interval: UpdatesSettings["check_interval"]) {
    setCheckInterval(interval);
    await persist({ check_interval: interval });
  }

  async function setChannelAndSave(next: UpdatesSettings["channel"]) {
    setChannel(next);
    await persist({ channel: next });
  }

  async function setAutoLargeAndSave(next: boolean) {
    setAutoLarge(next);
    await persist({ auto_large_updates: next });
  }

  const isNightly = updatesInfo?.kind === "nightly";
  const offerSize = updatesInfo ? updateDownloadSize(updatesInfo) : 0;
  const offerSizeLabel =
    updatesInfo && Number.isFinite(offerSize) && offerSize > 0
      ? ` · ${formatBytes(offerSize)}`
      : "";

  return (
    <div className="p-3">
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-text-primary">{t("settings.updatesSection")}</h2>
      </div>

      {hotpatch?.frontend_version && (
        <p className="mt-1 text-[11px] text-text-secondary">
          {t("settings.updatesHotpatchActive", { version: hotpatch.frontend_version })}
        </p>
      )}
      {overlay?.overlay_version && overlay.overlay_active && (
        <p className="mt-1 text-[11px] text-text-secondary">
          {t("settings.updatesOverlayActive", { version: overlay.overlay_version })}
        </p>
      )}
      {nativeState?.applied_to && (
        <p className="mt-1 text-[11px] text-text-secondary">
          {t("settings.updatesNativeActive", { version: nativeState.applied_to })}
        </p>
      )}

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
              updatesStatus === "checking" || updatesStatus === "patching" ? (
                <LoaderCircle size={12} className="animate-spin" aria-hidden />
              ) : (
                <RotateCw size={12} aria-hidden />
              )
            }
            disabled={
              updatesStatus === "checking" ||
              updatesStatus === "downloading" ||
              updatesStatus === "patching"
            }
            onClick={() => void useUpdatesStore.getState().checkNow()}
          >
            {t("settings.updatesCheckNow")}
          </Button>
          {updatesStatus === "available" && updatesInfo && (
            <Button
              variant="primary"
              icon={<Download size={12} aria-hidden />}
              onClick={() => void useUpdatesStore.getState().install({ manual: true })}
            >
              {isNightly ? t("settings.updatesNightlyInstall") : t("settings.updatesInstall")}
            </Button>
          )}
          {(hotpatch?.previous_version ||
            overlay?.previous_version ||
            nativeState?.applied_to) &&
            updatesStatus !== "patching" && (
              <Button
                variant="secondary"
                icon={<Undo2 size={12} aria-hidden />}
                onClick={() => void useUpdatesStore.getState().rollback()}
                title={t("settings.updatesRollbackHint", {
                  version:
                    hotpatch?.previous_version ??
                    overlay?.previous_version ??
                    nativeState?.applied_to ??
                    "",
                })}
              >
                {t("settings.updatesRollback")}
              </Button>
            )}
        </div>
      </div>

      {/* Channel opt-in/out */}
      <label className="mt-3 flex items-center gap-1.5 text-[11px] text-text-secondary">
        <span>{t("settings.updatesChannel")}</span>
        <Select
          value={channel}
          onChange={(e) => void setChannelAndSave(e.target.value as UpdatesSettings["channel"])}
          className="w-28"
        >
          <option value="stable">{t("settings.updatesChannelStable")}</option>
          <option value="nightly">{t("settings.updatesChannelNightly")}</option>
        </Select>
      </label>
      <p className="mt-1 text-[11px] text-text-secondary">{t("settings.updatesChannelHint")}</p>

      {/* Large-update bandwidth control */}
      <div className="mt-3">
        <Toggle
          checked={autoLarge}
          onChange={() => void setAutoLargeAndSave(!autoLarge)}
          label={<span className="text-[11px]">{t("settings.updatesAutoLarge")}</span>}
          ariaLabel={t("settings.updatesAutoLarge")}
          hint={
            <span className="text-[11px]">
              {t("settings.updatesAutoLargeHint", { size: formatBytes(LARGE_UPDATE_BYTES) })}
            </span>
          }
        />
      </div>

      {updatesStatus === "checking" && (
        <p className="mt-2 text-xs text-text-secondary">{t("settings.updatesChecking")}</p>
      )}
      {updatesStatus === "patching" && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-text-secondary">
          <LoaderCircle size={12} className="animate-spin" aria-hidden />
          {t("settings.updatesPatching")}
        </p>
      )}
      {updatesStatus === "up-to-date" && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-success" role="status">
          <Check size={12} aria-hidden />
          {t("settings.updatesUpToDate")}
        </p>
      )}
      {updatesStatus === "available" && updatesInfo && (
        <>
          <p className="mt-2 text-xs text-text-primary">
            {isNightly
              ? t("settings.updatesNightlyAvailable", { version: updatesInfo.version })
              : t("settings.updatesAvailable", { version: updatesInfo.version })}
            {offerSizeLabel && (
              <span className="text-text-secondary">{offerSizeLabel}</span>
            )}
          </p>
          {updatesInfo.body && (
            <p className="mt-1 line-clamp-3 text-[11px] whitespace-pre-wrap text-text-secondary">
              {updatesInfo.body}
            </p>
          )}
        </>
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
      {channel === "nightly" && (
        <p className="mt-2 text-[11px] text-text-secondary">
          <a
            className="underline"
            href={NIGHTLY_MANIFEST_URL}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("settings.updatesNightlyManifest")}
          </a>
        </p>
      )}
    </div>
  );
}
