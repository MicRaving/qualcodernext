/**
 * Settings (right-bar pane) — one scrollable pane with headline-separated
 * sections: General | AI | Updates | Maintenance, then R integration and
 * About ALWAYS at the very bottom (R directly above About). Each section
 * is its own component (features/settings/*Tab.tsx) so new settings can be
 * added by editing one section; the shell below only owns the scroll
 * container and the fixed R/About footer order.
 */
import { useState } from "react";
import { useAsyncEffect } from "@/lib/useAsync";
import { CircleAlert, CircleCheck, LoaderCircle } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { api, type RStatus } from "@/lib/api";
import { BarHeader, LeftBar } from "@/components/ui/orchestrator";
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

  return (
    <LeftBar
      borderSide="l"
      width="lg"
      className="h-full min-h-0"
      header={<BarHeader title={t("settings.title")} />}
    >
      <div className="min-h-0 flex-1 divide-y divide-border overflow-y-auto">
        <GeneralTab />
        <AiTab />
        <UpdatesTab />
        <MaintenanceTab />

        {/* R integration — fixed position: directly above About. */}
        <section className="p-3">
          <h2 className="text-sm font-semibold text-text-primary">{t("r.statusTitle")}</h2>
          {rStatus === null ? (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-text-secondary">
              <LoaderCircle size={12} className="animate-spin" aria-hidden />
              {t("r.checking")}
            </p>
          ) : rStatus.available ? (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-success">
              <CircleCheck size={13} aria-hidden />
              {t("r.detected", { version: rStatus.version ?? "?", path: rStatus.path ?? "?" })}
            </p>
          ) : (
            <div className="mt-2">
              <p className="flex items-center gap-1.5 text-xs text-warning">
                <CircleAlert size={13} aria-hidden />
                {t("r.notFound")}
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

        {/* About — ALWAYS the very last section. */}
        <section className="p-3">
          <h2 className="text-sm font-semibold text-text-primary">{t("settings.about")}</h2>
          <p className="mt-1 text-xs text-text-secondary">{t("settings.aboutText")}</p>
        </section>
      </div>
    </LeftBar>
  );
}
