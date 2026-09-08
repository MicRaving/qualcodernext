/**
 * UpdatesTab — Settings "Updates" tab: check cadence, the stable/nightly
 * channel opt-in, plus Install and the live update status.
 *
 * Nightlies (`X.Y.Z_NNN`) are opt-in delta patches: small downloads that
 * hotpatch without a full installer. The channel persists in the backend
 * (`~/.qualcoder/settings.json` → `updates.channel`). Every available
 * update auto-installs (including large ones) — there is no size gate.
 */
import { useEffect, useState } from "react";
import { Check, Download, Info, LoaderCircle, RotateCw, Undo2 } from "lucide-react";
import { Button, SectionLabel, Select } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import {
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

  useEffect(() => {
    const store = useUpdatesStore.getState();
    if (!updatesSettings) void store.loadSettings();
    void store.loadHotpatch();
  }, [updatesSettings]);

  useEffect(() => {
    if (updatesSettings) {
      setCheckInterval(updatesSettings.check_interval);
      setChannel(updatesSettings.channel ?? "stable");
    }
  }, [updatesSettings]);

  async function persist(patch: Partial<UpdatesSettings>) {
    try {
      await useUpdatesStore.getState().saveSettings({
        check_interval: patch.check_interval ?? checkInterval,
        auto_update: useUpdatesStore.getState().settings?.auto_update ?? true,
        channel: patch.channel ?? channel,
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

  const isNightly = updatesInfo?.kind === "nightly";
  const checking =
    updatesStatus === "checking" ||
    updatesStatus === "downloading" ||
    updatesStatus === "patching";
  const offerSize = updatesInfo ? updateDownloadSize(updatesInfo) : 0;
  const offerSizeLabel =
    updatesInfo && Number.isFinite(offerSize) && offerSize > 0
      ? ` · ${formatBytes(offerSize)}`
      : "";

  // Running patch as ONE row: a coherent nightly carries the frontend and
  // backend layers at the same version. Only transitional states (a newer
  // frontend over an older backend or vice versa) name both layers.
  const frontendPatch = hotpatch?.frontend_version ?? null;
  const backendPatch =
    overlay?.overlay_version && overlay.overlay_active ? overlay.overlay_version : null;
  const patchStatus =
    frontendPatch && backendPatch
      ? frontendPatch === backendPatch
        ? t("settings.updatesPatchActive", { version: frontendPatch })
        : `${t("settings.updatesHotpatchActive", { version: frontendPatch })} ${t("settings.updatesOverlayActive", { version: backendPatch })}`
      : frontendPatch
        ? t("settings.updatesHotpatchActive", { version: frontendPatch })
        : backendPatch
          ? t("settings.updatesOverlayActive", { version: backendPatch })
          : null;
  const canUndo =
    (!!hotpatch?.previous_version ||
      !!overlay?.previous_version ||
      !!nativeState?.applied_to) &&
    updatesStatus !== "patching";
  const rollbackHint = t("settings.updatesRollbackHint", {
    version:
      hotpatch?.previous_version ??
      overlay?.previous_version ??
      nativeState?.applied_to ??
      "",
  });

  return (
    <div className="p-3">
      {/* Header with the icon-only check button on the right. */}
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-text-primary">
          <Download size={13} className="shrink-0" aria-hidden />
          {t("settings.updatesSection")}
        </h2>
        <Button
          variant="secondary"
          icon={
            updatesStatus === "checking" || updatesStatus === "patching" ? (
              <LoaderCircle size={12} className="animate-spin" aria-hidden />
            ) : (
              <RotateCw size={12} aria-hidden />
            )
          }
          disabled={checking}
          onClick={() => void useUpdatesStore.getState().checkNow()}
          title={t("settings.updatesCheckNow")}
          aria-label={t("settings.updatesCheckNow")}
        />
      </div>

      {patchStatus && (
        <p className="mt-1 text-[11px] text-text-secondary">{patchStatus}</p>
      )}
      {nativeState?.applied_to && (
        <p className="mt-1 text-[11px] text-text-secondary">
          {t("settings.updatesNativeActive", { version: nativeState.applied_to })}
        </p>
      )}

      {/* Check cadence (label above the dropdown) */}
      <div className="mt-3 border-t border-border pt-3">
        <SectionLabel>{t("settings.updatesInterval")}</SectionLabel>
        <Select
          value={checkInterval}
          onChange={(e) => void setIntervalAndSave(e.target.value as UpdatesSettings["check_interval"])}
          className="mt-2 w-full"
          aria-label={t("settings.updatesInterval")}
        >
          <option value="daily">{t("settings.updatesIntervalDaily")}</option>
          <option value="weekly">{t("settings.updatesIntervalWeekly")}</option>
          <option value="never">{t("settings.updatesIntervalNever")}</option>
        </Select>
      </div>

      {/* Channel opt-in/out (hint lives in the hover tooltip on the label). */}
      <div className="mt-3 border-t border-border pt-3" title={t("settings.updatesChannelHint")}>
        <SectionLabel>
          <span className="inline-flex cursor-help items-center gap-1">
            {t("settings.updatesChannel")}
            <Info size={12} className="shrink-0 opacity-70" aria-hidden />
          </span>
        </SectionLabel>
        <Select
          value={channel}
          onChange={(e) => void setChannelAndSave(e.target.value as UpdatesSettings["channel"])}
          className="mt-2 w-full"
          aria-label={t("settings.updatesChannel")}
        >
          <option value="stable">{t("settings.updatesChannelStable")}</option>
          <option value="nightly">{t("settings.updatesChannelNightly")}</option>
        </Select>
      </div>

      {/* Actions: undo (icon-only) sits left of install. */}
      {(updatesStatus === "available" && updatesInfo) || canUndo ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {canUndo && (
            <Button
              variant="secondary"
              icon={<Undo2 size={12} aria-hidden />}
              onClick={() => void useUpdatesStore.getState().rollback()}
              title={rollbackHint}
              aria-label={rollbackHint}
            />
          )}
          {updatesStatus === "available" && updatesInfo && (
            <Button
              variant="primary"
              icon={<Download size={12} aria-hidden />}
              onClick={() => void useUpdatesStore.getState().install()}
            >
              {isNightly ? t("settings.updatesNightlyInstall") : t("settings.updatesInstall")}
            </Button>
          )}
        </div>
      ) : null}

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
