/**
 * GeneralTab — Settings "General" tab: appearance & language, project
 * preferences (auto-load, auto-show details), accessibility, Import/Export.
 */
import { useEffect, useState } from "react";
import { CircleDot, Moon, Sun } from "lucide-react";
import { api } from "@/lib/api";
import { A11yControls } from "@/features/accessibility/A11yControls";
import { useI18n, LOCALE_NAMES, type Locale } from "@/lib/i18n";
import { SectionLabel, Select, Toggle } from "@/components/ui/orchestrator";
import { usePrefsStore, type ThemeMode } from "@/stores/prefs";
import { InterchangeView } from "@/features/interchange/InterchangeView";

/** The three theme choices for the appearance segmented control. */
const THEMES: { mode: ThemeMode; icon: typeof Sun; labelKey: string }[] = [
  { mode: "light", icon: Sun, labelKey: "theme.light" },
  { mode: "dark", icon: Moon, labelKey: "theme.dark" },
  { mode: "oled", icon: CircleDot, labelKey: "theme.oled" },
];

export function GeneralTab() {
  const { t, locale, setLocale } = useI18n();
  const themeMode = usePrefsStore((s) => s.themeMode);
  const setThemeMode = usePrefsStore((s) => s.setThemeMode);

  // Auto-load project on start (packaged app only; harmless elsewhere).
  const [autoLoadProject, setAutoLoadProject] = useState(true);

  // Collaboration sync cadence (1 min default; Settings → Sync).
  const [syncIntervalSecs, setSyncIntervalSecs] = useState(60);

  useEffect(() => {
    api
      .appSettings()
      .then((s) => setAutoLoadProject(s.auto_open_project))
      .catch(() => {
        /* backend unreachable — keep the default */
      });
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
      <section className="p-3">
        <div className="flex flex-col gap-4">
          <div>
            <SectionLabel>{t("settings.appearance")}</SectionLabel>
            <div className="mt-2 flex w-fit items-center gap-0.5 rounded-sm border border-border bg-bg p-0.5">
              {THEMES.map(({ mode, icon: Icon, labelKey }) => {
                const active = themeMode === mode;
                return (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setThemeMode(mode)}
                    aria-pressed={active}
                    aria-label={t("theme.switchLabel", { theme: t(labelKey) })}
                    className={`flex items-center gap-1 rounded-sm px-2 py-1 text-xs font-medium ${
                      active
                        ? "bg-surface-higher text-accent"
                        : "text-text-secondary hover:text-text-primary"
                    }`}
                  >
                    <Icon size={12} aria-hidden />
                    {t(labelKey)}
                  </button>
                );
              })}
            </div>
          </div>
          <div>
            <SectionLabel>{t("ai.language")}</SectionLabel>
            <Select
              value={locale}
              onChange={(e) => setLocale(e.target.value as Locale)}
              className="mt-2 w-full"
              aria-label={t("ai.language")}
            >
              {(Object.keys(LOCALE_NAMES) as Locale[]).map((l) => (
                <option key={l} value={l}>
                  {LOCALE_NAMES[l]}
                </option>
              ))}
            </Select>
          </div>
        </div>

        <div className="mt-3 border-t border-border pt-3">
          <Toggle
            checked={autoLoadProject}
            onChange={() => void toggleAutoLoadProject()}
            label={t("settings.autoLoadProject")}
            hint={t("settings.autoLoadProjectHint")}
          />
        </div>

<div className="mt-3 border-t border-border pt-3">
          <A11yControls />
        </div>
      </section>

      {/* Collaboration sync cadence */}
      <section className="p-3">
        <h2 className="text-sm font-semibold text-text-primary">{t("sync.title")}</h2>
        <div className="mt-2">
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
      </section>

      {/* Import / Export — embedded in the General tab (no ribbon entry) */}
      <section className="p-3 [&>div>p]:hidden">
        <InterchangeView />
      </section>
    </div>
  );
}


