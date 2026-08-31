/**
 * GeneralTab — Settings "General" tab: appearance & language, project
 * preferences (auto-load, auto-show details), accessibility, Import/Export,
 * pseudonyms, R integration and About.
 */
import { useEffect, useState, type FormEvent } from "react";
import { Moon, Sun, Trash2 } from "lucide-react";
import { api, type Pseudonym } from "@/lib/api";
import { errorDetail } from "@/features/ai/format";
import { A11yControls } from "@/features/accessibility/A11yControls";
import { useI18n, LOCALE_NAMES, type Locale } from "@/lib/i18n";
import { Button, Field, IconButton, Input, SectionLabel, Select, Toggle } from "@/components/ui/orchestrator";
import { usePrefsStore } from "@/stores/prefs";
import { InterchangeView } from "@/features/interchange/InterchangeView";

export function GeneralTab() {
  const { t, locale, setLocale } = useI18n();
  const themeMode = usePrefsStore((s) => s.themeMode);
  const setThemeMode = usePrefsStore((s) => s.setThemeMode);

  // Auto-load project on start (packaged app only; harmless elsewhere).
  const [autoLoadProject, setAutoLoadProject] = useState(true);

  // Collaboration sync cadence (1 min default; Settings → Sync).
  const [syncIntervalSecs, setSyncIntervalSecs] = useState(60);

  // Pseudonyms
  const [pseudonyms, setPseudonyms] = useState<Pseudonym[]>([]);
  const [pseudoOriginal, setPseudoOriginal] = useState("");
  const [pseudoName, setPseudoName] = useState("");
  const [pseudoError, setPseudoError] = useState<string | null>(null);

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
    void loadPseudonyms();
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

  const loadPseudonyms = async () => {
    try {
      const res = await api.pseudonyms();
      setPseudonyms(res.pseudonyms);
      setPseudoError(null);
    } catch (e) {
      setPseudoError(errorDetail(e, "Could not load pseudonyms"));
    }
  };

  async function addPseudonym(e: FormEvent) {
    e.preventDefault();
    setPseudoError(null);
    try {
      await api.addPseudonym(pseudoOriginal, pseudoName);
      setPseudoOriginal("");
      setPseudoName("");
      await loadPseudonyms();
    } catch (err) {
      setPseudoError(errorDetail(err, "Could not add pseudonym"));
    }
  }

async function removePseudonym(original: string) {
    try {
      await api.deletePseudonym(original);
      await loadPseudonyms();
    } catch (err) {
      setPseudoError(errorDetail(err, "Could not delete pseudonym"));
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
        <div className="grid grid-cols-2 gap-4">
          <div>
            <SectionLabel>{t("settings.appearance")}</SectionLabel>
            <Toggle
              checked={themeMode === "dark"}
              onChange={() => setThemeMode(themeMode === "dark" ? "light" : "dark")}
              ariaLabel={t("theme.switchLabel", { theme: themeMode === "dark" ? "light" : "dark" })}
              label={
                <span className="flex items-center gap-1.5">
                  {themeMode === "dark" ? (
                    <Moon size={14} className="text-text-secondary" aria-hidden />
                  ) : (
                    <Sun size={14} className="text-text-secondary" aria-hidden />
                  )}
                  {themeMode === "dark" ? t("theme.dark") : t("theme.light")}
                </span>
              }
            />
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

      {/* Pseudonyms */}
      <section className="p-3">
        <h2 className="text-sm font-semibold text-text-primary">{t("ai.pseudonymsSection")}</h2>
        <form onSubmit={(e) => void addPseudonym(e)} className="mt-2 flex flex-wrap items-end gap-2">
          <Field label={t("ai.pseudonymOriginal")} className="min-w-0 flex-1">
            <Input
              value={pseudoOriginal}
              onChange={(e) => setPseudoOriginal(e.target.value)}
              placeholder={t("ai.pseudonymOriginalPlaceholder")}
              className="w-full"
            />
          </Field>
          <Field label={t("ai.pseudonymPseudonym")} className="min-w-0 flex-1">
            <Input
              value={pseudoName}
              onChange={(e) => setPseudoName(e.target.value)}
              placeholder={t("ai.pseudonymPseudonymPlaceholder")}
              className="w-full"
            />
          </Field>
          <Button variant="primary" type="submit" disabled={pseudoOriginal.trim().length < 2}>
            {t("ai.pseudonymAdd")}
          </Button>
        </form>
        {pseudoError && <p className="mt-2 text-xs text-danger">{pseudoError}</p>}
        {pseudonyms.length === 0 ? (
          <p className="mt-2 text-xs text-text-secondary">{t("ai.pseudonymNone")}</p>
        ) : (
          <div className="mt-3 max-h-48 overflow-auto rounded-sm border border-border bg-bg">
            <table className="w-full border-collapse">
              <tbody>
                {pseudonyms.map((p) => (
                  <tr key={p.original} className="border-b border-border last:border-0">
                    <td className="px-2 py-1.5 text-sm">{p.original}</td>
                    <td className="px-2 py-1.5 text-sm text-text-secondary">→ {p.pseudonym}</td>
                    <td className="px-2 py-1.5 text-right">
                      <IconButton
                        label={t("ai.pseudonymDelete")}
                        title={t("ai.pseudonymDelete")}
                        size="row"
                        onClick={() => void removePseudonym(p.original)}
                        className="hover:bg-danger/10 hover:text-danger"
                      >
                        <Trash2 size={13} aria-hidden />
                      </IconButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}


