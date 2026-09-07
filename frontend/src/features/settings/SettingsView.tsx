/**
 * Settings (right-bar pane) — one scrollable pane with headline-separated
 * sections: General | AI | Updates | Maintenance, then About ALWAYS at the
 * very bottom. The R installation line lives inside About (the detected
 * path is clickable and opens a file selector for a manual Rscript pick).
 * Each section is its own component (features/settings/*Tab.tsx) so new
 * settings can be added by editing one section; the shell below only owns
 * the scroll container and the fixed About footer.
 */
import { useState } from "react";
import { useAsyncEffect } from "@/lib/useAsync";
import { Bug, CircleAlert, CircleCheck, Info, LoaderCircle, Settings } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { api, type RStatus } from "@/lib/api";
import { BarHeader, BarTitle, IconButton, LeftBar } from "@/components/ui/orchestrator";
import { useProjectStore } from "@/stores/project";
import { GeneralTab } from "@/features/settings/GeneralTab";
import { AiTab } from "@/features/settings/AiTab";
import { UpdatesTab } from "@/features/settings/UpdatesTab";
import { MaintenanceTab } from "@/features/settings/MaintenanceTab";

export function SettingsView() {
  const { t } = useI18n();

  // R integration status (probe runs in the backend without any console
  // window — the app itself never spawns one).
  const [rStatus, setRStatus] = useState<RStatus | null>(null);
  useAsyncEffect(async (signal) => {
    const s = await api.rStatus();
    signal.throwIfAborted();
    setRStatus(s);
  }, []);

  // Manual Rscript pick: a file dialog (desktop only) whose result is
  // validated backend-side (must exist + answer `--version`).
  async function chooseRscript() {
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const currentDir = rStatus?.path?.replace(/[/\\][^/\\]*$/, "");
      const selected = await open({
        multiple: false,
        directory: false,
        title: t("settings.rChooseTitle"),
        ...(currentDir ? { defaultPath: currentDir } : {}),
        ...(/win/i.test(navigator.platform ?? "")
          ? { filters: [{ name: "Rscript", extensions: ["exe"] }] }
          : {}),
      });
      if (typeof selected !== "string" || !selected) return;
      const s = await api.setRscriptPath(selected);
      setRStatus(s);
    } catch {
      /* dialog cancelled, non-desktop browser, or invalid pick — keep prior status */
    }
  }

  return (
    <LeftBar
      borderSide="l"
      width="lg"
      className="h-full min-h-0"
      header={
        <BarHeader
          title={<BarTitle icon={Settings} label={t("settings.title")} />}
          actions={
            <IconButton
              label={t("nav.bugReport")}
              title={t("nav.bugReport")}
              onClick={() => void useProjectStore.getState().openBugReport()}
            >
              <Bug size={14} aria-hidden />
            </IconButton>
          }
        />
      }
    >
      <div className="min-h-0 flex-1 divide-y divide-border overflow-y-auto">
        <GeneralTab />
        <AiTab />
        <UpdatesTab />
        <MaintenanceTab />

        {/* About — ALWAYS the very last section (R line merged in). */}
        <section className="p-3">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-text-primary">
            <Info size={13} className="shrink-0" aria-hidden />
            {t("settings.about")}
          </h2>
          <p className="mt-1 text-xs text-text-secondary">{t("settings.aboutText")}</p>
          {rStatus === null ? (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-text-secondary">
              <LoaderCircle size={12} className="animate-spin" aria-hidden />
              {t("r.checking")}
            </p>
          ) : rStatus.available ? (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-success">
              <CircleCheck size={13} aria-hidden />
              <span>
                {t("settings.rDetectedAt", { version: rStatus.version ?? "?" })}
              </span>
              <button
                type="button"
                onClick={() => void chooseRscript()}
                title={t("settings.rChooseTitle")}
                aria-label={t("settings.rChooseTitle")}
                className="min-w-0 cursor-pointer truncate text-left underline decoration-dotted underline-offset-2"
              >
                {rStatus.path ?? "?"}
              </button>
              {rStatus.custom ? (
                <span className="shrink-0 text-text-secondary">· {t("settings.rManual")}</span>
              ) : null}
            </p>
          ) : (
            <div className="mt-2">
              <p className="flex items-center gap-1.5 text-xs text-warning">
                <CircleAlert size={13} aria-hidden />
                {t("r.notFound")}
                {" · "}
                <button
                  type="button"
                  onClick={() => void chooseRscript()}
                  title={t("settings.rChooseTitle")}
                  aria-label={t("settings.rChooseTitle")}
                  className="cursor-pointer underline decoration-dotted underline-offset-2"
                >
                  {t("settings.rChoose")}
                </button>
              </p>
              <a
                href="https://www.r-project.org/"
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-block text-xs text-accent underline"
              >
                {t("r.installHint")}
              </a>
            </div>
          )}
        </section>
      </div>
    </LeftBar>
  );
}
