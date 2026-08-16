/**
 * Settings (right-bar pane) — tabbed: General | AI | Updates | Maintenance.
 * Each tab is its own component (features/settings/*Tab.tsx) so new
 * settings can be added by editing one tab; the shell below only owns the
 * tab bar and the bar layout.
 */
import { useState } from "react";
import { Download, Settings, Sparkles, Wrench } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { BarHeader, LeftBar } from "@/components/ui/orchestrator";
import { GeneralTab } from "@/features/settings/GeneralTab";
import { AiTab } from "@/features/settings/AiTab";
import { UpdatesTab } from "@/features/settings/UpdatesTab";
import { MaintenanceTab } from "@/features/settings/MaintenanceTab";

type SettingsTab = "general" | "ai" | "updates" | "maintenance";

const TABS: { id: SettingsTab; labelKey: string; icon: typeof Settings }[] = [
  { id: "general", labelKey: "settings.tabGeneral", icon: Settings },
  { id: "ai", labelKey: "settings.tabAi", icon: Sparkles },
  { id: "updates", labelKey: "settings.tabUpdates", icon: Download },
  { id: "maintenance", labelKey: "settings.tabMaintenance", icon: Wrench },
];

export function SettingsView() {
  const { t } = useI18n();
  const [tab, setTab] = useState<SettingsTab>("general");

  return (
    <LeftBar
      borderSide="l"
      width="lg"
      className="h-full min-h-0"
      header={<BarHeader title={t("settings.title")} />}
    >
      {/* Tab bar (segmented control) */}
      <div
        role="tablist"
        aria-label={t("settings.title")}
        className="flex shrink-0 items-center gap-0.5 border-b border-border bg-surface px-2 py-1.5"
      >
        {TABS.map(({ id, labelKey, icon: TabIcon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={`flex h-7 flex-1 items-center justify-center gap-1 rounded-sm text-xs transition-colors ${
              tab === id
                ? "bg-surface-higher text-accent"
                : "text-text-secondary hover:bg-surface-higher hover:text-text-primary"
            }`}
          >
            <TabIcon size={12} aria-hidden />
            {t(labelKey)}
          </button>
        ))}
      </div>

      {tab === "general" && <GeneralTab />}
      {tab === "ai" && <AiTab />}
      {tab === "updates" && <UpdatesTab />}
      {tab === "maintenance" && <MaintenanceTab />}
    </LeftBar>
  );
}
