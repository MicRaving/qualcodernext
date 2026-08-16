/**
 * Settings (right-bar pane) — one scrollable pane with headline-separated
 * sections: General | AI | Updates | Maintenance. Each section is its own
 * component (features/settings/*Tab.tsx) so new settings can be added by
 * editing one section; the shell below only owns the scroll container.
 */
import { useI18n } from "@/lib/i18n";
import { BarHeader, LeftBar } from "@/components/ui/orchestrator";
import { GeneralTab } from "@/features/settings/GeneralTab";
import { AiTab } from "@/features/settings/AiTab";
import { UpdatesTab } from "@/features/settings/UpdatesTab";
import { MaintenanceTab } from "@/features/settings/MaintenanceTab";

export function SettingsView() {
  const { t } = useI18n();

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
      </div>
    </LeftBar>
  );
}
