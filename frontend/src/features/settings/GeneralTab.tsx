/**
 * GeneralTab — Settings "General" tab: appearance & language, accessibility,
 * Import/Export. Auto-load, sync cadence and compaction live together in the
 * Project maintenance category (MaintenanceTab).
 */
import { CircleDot, Moon, SlidersHorizontal, Sun } from "lucide-react";
import { A11yControls } from "@/features/accessibility/A11yControls";
import { useI18n, LOCALE_NAMES, type Locale } from "@/lib/i18n";
import { SectionLabel, Select } from "@/components/ui/orchestrator";
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

  return (
    <div className="p-3">
      <section>
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-text-primary">
          <SlidersHorizontal size={13} className="shrink-0" aria-hidden />
          {t("settings.general")}
        </h2>
        <div className="mt-2 flex flex-col gap-4">
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
          <A11yControls />
        </div>
      </section>

      {/* Import / Export — embedded in the General tab (no ribbon entry) */}
      <section className="mt-3 border-t border-border pt-3 [&>div>p]:hidden">
        <InterchangeView />
      </section>
    </div>
  );
}


