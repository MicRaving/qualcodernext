/**
 * Settings - appearance, language, AI assistant (incl. MCP permissions and
 * the semantic index), pseudonyms and Import/Export.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Check, LoaderCircle, RotateCw, Save, Trash2 } from "lucide-react";
import { api, type AiIndexStatus, type AiStatus, type Pseudonym } from "@/lib/api";
import { errorDetail } from "@/features/ai/format";
import { InterchangeView } from "@/features/interchange/InterchangeView";
import { useI18n, LOCALE_NAMES, type Locale } from "@/lib/i18n";
import { ViewHeader } from "@/components/ui/orchestrator";
import { useProjectStore } from "@/stores/project";

const inputCls =
  "h-8 w-full rounded-sm border border-border bg-bg px-2 text-sm outline-none focus:border-accent";

export function SettingsView() {
  const { t, locale, setLocale } = useI18n();
  const themeMode = useProjectStore((s) => s.themeMode);
  const setThemeMode = useProjectStore((s) => s.setThemeMode);

  const [status, setStatus] = useState<AiStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);

  const [enabled, setEnabled] = useState(false);
  const [provider, setProvider] = useState("ollama");
  const [apiBase, setApiBase] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [mcpPermissions, setMcpPermissions] = useState("read");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Semantic index
  const [indexStatus, setIndexStatus] = useState<AiIndexStatus | null>(null);
  const [indexBusy, setIndexBusy] = useState(false);
  const [indexError, setIndexError] = useState<string | null>(null);

  // Pseudonyms
  const [pseudonyms, setPseudonyms] = useState<Pseudonym[]>([]);
  const [pseudoOriginal, setPseudoOriginal] = useState("");
  const [pseudoName, setPseudoName] = useState("");
  const [pseudoError, setPseudoError] = useState<string | null>(null);

  // Colour scheme
  const [palette, setPalette] = useState<string[]>([]);
  const [paletteSaved, setPaletteSaved] = useState(false);
  const [paletteError, setPaletteError] = useState<string | null>(null);

  const PROVIDER_PRESETS: Record<string, { url: string; model: string }> = {
    ollama: { url: "http://localhost:11434/v1", model: "llama3.2" },
    lmstudio: { url: "http://localhost:1234/v1", model: "" },
    "opencode-go": { url: "http://localhost:8080/v1", model: "deepseek-v4-flash" },
    gemini: {
      url: "https://generativelanguage.googleapis.com/v1beta/openai",
      model: "gemini-3.6-flash",
    },
    gpt: { url: "https://api.openai.com/v1", model: "gpt-5.6" },
    claude: { url: "https://api.anthropic.com/v1", model: "claude-sonnet-4-6" },
  };

  const loadStatus = useCallback(async () => {
    setStatusLoading(true);
    setStatusError(null);
    try {
      const s = await api.aiStatus();
      setStatus(s);
      setEnabled(s.enabled);
      setProvider(s.provider);
      setApiBase(s.base_url);
      setModel(s.model);
      setMcpPermissions(s.mcp_permissions ?? "read");
    } catch (e) {
      setStatusError(errorDetail(e, t("settings.aiLoadError")));
    } finally {
      setStatusLoading(false);
    }
  }, [t]);

  const loadIndex = useCallback(async () => {
    try {
      setIndexStatus(await api.aiIndexStatus());
      setIndexError(null);
    } catch (e) {
      setIndexError(errorDetail(e, t("settings.aiLoadError")));
    }
  }, [t]);

  const loadPseudonyms = useCallback(async () => {
    try {
      const res = await api.pseudonyms();
      setPseudonyms(res.pseudonyms);
      setPseudoError(null);
    } catch (e) {
      setPseudoError(errorDetail(e, "Could not load pseudonyms"));
    }
  }, []);

  const loadPalette = useCallback(async () => {
    try {
      const scheme = await api.colorScheme();
      setPalette(scheme.colors);
      setPaletteError(null);
    } catch (e) {
      setPaletteError(errorDetail(e, t("settings.colourSchemeSaveError")));
    }
  }, [t]);

  useEffect(() => {
    void loadStatus();
    void loadIndex();
    void loadPseudonyms();
    void loadPalette();
  }, [loadStatus, loadIndex, loadPseudonyms, loadPalette]);

  async function savePalette() {
    try {
      await api.saveColorScheme(palette);
      setPaletteSaved(true);
      window.setTimeout(() => setPaletteSaved(false), 2000);
      setPaletteError(null);
    } catch (e) {
      setPaletteError(errorDetail(e, t("settings.colourSchemeSaveError")));
    }
  }

  async function resetPalette() {
    try {
      const scheme = await api.resetColorScheme();
      setPalette(scheme.colors);
      setPaletteError(null);
    } catch (e) {
      setPaletteError(errorDetail(e, t("settings.colourSchemeSaveError")));
    }
  }

  function handleProviderChange(next: string) {
    setProvider(next);
    const preset = PROVIDER_PRESETS[next];
    if (preset) {
      setApiBase(preset.url);
      if (preset.model) setModel(preset.model);
    }
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (saving) return;
    setSaving(true);
    setSaved(false);
    setSaveError(null);
    try {
      await api.aiSaveSettings({
        enabled,
        provider,
        api_base: apiBase.trim(),
        model: model.trim(),
        api_key: apiKey,
        mcp_permissions: mcpPermissions,
      });
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
      await loadStatus();
    } catch (err) {
      setSaveError(errorDetail(err, t("settings.aiSaveError")));
    } finally {
      setSaving(false);
    }
  }

  async function buildIndex() {
    if (indexBusy) return;
    setIndexBusy(true);
    setIndexError(null);
    try {
      setIndexStatus(await api.aiIndexBuild());
    } catch (err) {
      setIndexError(errorDetail(err, "Index build failed"));
    } finally {
      setIndexBusy(false);
    }
  }

  async function deleteIndex() {
    try {
      await api.aiIndexDelete();
      await loadIndex();
    } catch (err) {
      setIndexError(errorDetail(err, "Could not delete index"));
    }
  }

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

  const themeBtn = (mode: "light" | "dark", label: string) => (
    <button
      type="button"
      onClick={() => setThemeMode(mode)}
      className={`rounded-sm border px-3 py-1.5 text-xs font-medium ${
        themeMode === mode
          ? "border-accent bg-accent text-[var(--qc-bg)]"
          : "border-border bg-bg hover:bg-surface-higher"
      }`}
      aria-pressed={themeMode === mode}
    >
      {label}
    </button>
  );

  return (
    <div className="flex h-full flex-col bg-bg">
      <ViewHeader back={false} title={t("settings.title")} />

      {saveError && (
        <div className="flex shrink-0 items-center gap-2 border-b border-danger bg-danger/10 px-3 py-1.5 text-sm text-danger">
          <span className="min-w-0 flex-1 truncate">{saveError}</span>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="max-w-3xl space-y-4">
          {/* General: appearance + import/export */}
          <section className="rounded-lg border border-border bg-surface p-4">
            <h2 className="text-sm font-semibold text-text-primary">{t("settings.general")}</h2>
            <p className="mt-1 text-xs text-text-secondary">{t("settings.generalHint")}</p>

            <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div>
                <h3 className="text-xs font-medium uppercase tracking-wide text-text-secondary">
                  {t("settings.appearance")}
                </h3>
                <div className="mt-2 flex items-center gap-2">
                  {themeBtn("light", t("theme.light"))}
                  {themeBtn("dark", t("theme.dark"))}
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <span className="text-xs text-text-secondary">{t("ai.language")}</span>
                  <select
                    value={locale}
                    onChange={(e) => setLocale(e.target.value as Locale)}
                    className={inputCls + " !w-40"}
                  >
                    {(Object.keys(LOCALE_NAMES) as Locale[]).map((l) => (
                      <option key={l} value={l}>
                        {LOCALE_NAMES[l]}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <h3 className="text-xs font-medium uppercase tracking-wide text-text-secondary">
                  {t("settings.interchange")}
                </h3>
                <p className="mt-1 text-xs text-text-secondary">{t("settings.interchangeHint")}</p>
                <div className="mt-2">
                  <InterchangeView embedded />
                </div>
              </div>
            </div>
          </section>

          {/* AI assistant */}
          <section className="rounded-lg border border-border bg-surface p-4">
            <h2 className="text-sm font-semibold text-text-primary">{t("settings.aiAssistant")}</h2>
            <div className="mt-2 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs text-text-secondary">{t("settings.aiStatus")}</p>
                {statusLoading ? (
                  <p className="mt-0.5 flex items-center gap-1.5 text-xs text-text-secondary">
                    <LoaderCircle size={12} className="animate-spin" aria-hidden />
                    {t("settings.aiChecking")}
                  </p>
                ) : status ? (
                  <p className="mt-0.5 text-xs text-text-primary">
                    {status.configured
                      ? t("settings.aiStatusConfigured", {
                          provider: status.provider || t("settings.aiFallbackName"),
                          model: status.model || t("settings.aiNoModel"),
                          enabled: status.enabled ? t("settings.aiYes") : t("settings.aiNo"),
                        })
                      : t("settings.aiStatusNotConfigured", {
                          provider: status.provider || t("settings.aiFallbackName"),
                        })}
                  </p>
                ) : (
                  <p className="mt-0.5 text-xs text-danger">{statusError ?? t("settings.aiStatusUnknown")}</p>
                )}
                {status && !status.configured && status.reason && (
                  <p className="mt-0.5 text-xs text-text-secondary">{status.reason}</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => void loadStatus()}
                disabled={statusLoading}
                className="flex shrink-0 items-center gap-1 rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher disabled:opacity-50"
              >
                <RotateCw size={12} aria-hidden />
                {t("settings.aiCheckStatus")}
              </button>
            </div>

            <form onSubmit={(e) => void handleSave(e)} className="mt-4 space-y-3">
              <label className="flex h-8 items-center gap-2 text-sm text-text-primary">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                  className="accent-accent"
                />
                {t("settings.aiEnable")}
              </label>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className="mb-1 block text-xs text-text-secondary">{t("settings.aiProvider")}</span>
                  <select
                    value={provider}
                    onChange={(e) => handleProviderChange(e.target.value)}
                    className={inputCls}
                  >
                    <option value="ollama">{t("settings.aiProviderOllama")}</option>
                    <option value="lmstudio">{t("settings.aiProviderLmStudio")}</option>
                    <option value="opencode-go">{t("settings.aiProviderOpencodeGo")}</option>
                    <option value="gemini">{t("settings.aiProviderGemini")}</option>
                    <option value="gpt">{t("settings.aiProviderGpt")}</option>
                    <option value="claude">{t("settings.aiProviderClaude")}</option>
                    <option value="custom">{t("settings.aiProviderCustom")}</option>
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs text-text-secondary">{t("settings.model")}</span>
                  <input
                    type="text"
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    placeholder="llama3.2"
                    className={inputCls}
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs text-text-secondary">{t("settings.apiBaseUrl")}</span>
                  <input
                    type="text"
                    value={apiBase}
                    onChange={(e) => {
                      setApiBase(e.target.value);
                      setProvider((p) =>
                        p in PROVIDER_PRESETS && PROVIDER_PRESETS[p].url !== e.target.value
                          ? "custom"
                          : p,
                      );
                    }}
                    placeholder="https://api.openai.com/v1"
                    className={inputCls}
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs text-text-secondary">{t("settings.apiKey")}</span>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={t("settings.optional")}
                    className={inputCls}
                  />
                  {["gemini", "gpt", "claude"].includes(provider) && !apiKey.trim() && (
                    <span className="mt-1 block text-xs text-warning">
                      {t("settings.aiKeyRequired")}
                    </span>
                  )}
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs text-text-secondary">{t("ai.mcpPermissions")}</span>
                  <select
                    value={mcpPermissions}
                    onChange={(e) => setMcpPermissions(e.target.value)}
                    className={inputCls}
                  >
                    <option value="read">{t("ai.mcpRead")}</option>
                    <option value="write">{t("ai.mcpWrite")}</option>
                    <option value="full">{t("ai.mcpFull")}</option>
                  </select>
                </label>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="submit"
                  disabled={saving}
                  className="flex items-center gap-1.5 rounded-sm bg-accent px-2.5 py-1 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-50"
                >
                  {saving ? (
                    <LoaderCircle size={14} className="animate-spin" aria-hidden />
                  ) : (
                    <Save size={14} aria-hidden />
                  )}
                  {t("settings.save")}
                </button>
                {saved && (
                  <span
                    role="status"
                    className="flex items-center gap-1 text-xs font-medium text-success"
                  >
                    <Check size={12} aria-hidden />
                    {t("settings.saved")}
                  </span>
                )}
              </div>
            </form>

            {/* Semantic index */}
            <div className="mt-4 border-t border-border pt-3">
              <h3 className="text-xs font-semibold text-text-primary">{t("ai.indexSection")}</h3>
              <p className="mt-0.5 text-xs text-text-secondary">{t("ai.indexHint")}</p>
              {indexStatus?.indexed ? (
                <p className="mt-1 text-xs text-text-primary">
                  {t("ai.indexStatusReady", {
                    chunks: String(indexStatus.chunks),
                    model: indexStatus.model,
                  })}
                </p>
              ) : (
                <p className="mt-1 text-xs text-text-secondary">{t("ai.indexStatusNone")}</p>
              )}
              {indexError && <p className="mt-1 text-xs text-danger">{indexError}</p>}
              <div className="mt-2 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void buildIndex()}
                  disabled={indexBusy}
                  className="flex items-center gap-1.5 rounded-sm border border-border bg-bg px-2.5 py-1 text-xs hover:bg-surface-higher disabled:opacity-50"
                >
                  {indexBusy ? (
                    <LoaderCircle size={12} className="animate-spin" aria-hidden />
                  ) : (
                    <RotateCw size={12} aria-hidden />
                  )}
                  {indexStatus?.indexed ? t("ai.indexRebuild") : t("ai.indexBuild")}
                </button>
                {indexStatus?.indexed && (
                  <button
                    type="button"
                    onClick={() => void deleteIndex()}
                    className="flex items-center gap-1 rounded-sm border border-border bg-bg px-2 py-1 text-xs text-danger hover:bg-danger/10"
                  >
                    <Trash2 size={12} aria-hidden />
                    {t("ai.indexDelete")}
                  </button>
                )}
              </div>
            </div>
          </section>

          {/* Pseudonyms */}
          <section className="rounded-lg border border-border bg-surface p-4">
            <h2 className="text-sm font-semibold text-text-primary">{t("ai.pseudonymsSection")}</h2>
            <p className="mt-1 text-xs text-text-secondary">{t("ai.pseudonymsHint")}</p>            <form onSubmit={(e) => void addPseudonym(e)} className="mt-3 flex flex-wrap items-end gap-2">
              <label className="block flex-1">
                <span className="mb-1 block text-xs text-text-secondary">{t("ai.pseudonymOriginal")}</span>
                <input
                  value={pseudoOriginal}
                  onChange={(e) => setPseudoOriginal(e.target.value)}
                  placeholder={t("ai.pseudonymOriginalPlaceholder")}
                  className={inputCls}
                />
              </label>
              <label className="block flex-1">
                <span className="mb-1 block text-xs text-text-secondary">{t("ai.pseudonymPseudonym")}</span>
                <input
                  value={pseudoName}
                  onChange={(e) => setPseudoName(e.target.value)}
                  placeholder={t("ai.pseudonymPseudonymPlaceholder")}
                  className={inputCls}
                />
              </label>
              <button
                type="submit"
                disabled={pseudoOriginal.trim().length < 2}
                className="rounded-sm bg-accent px-2.5 py-1 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-40"
              >
                {t("ai.pseudonymAdd")}
              </button>
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
                          <button
                            type="button"
                            title={t("ai.pseudonymDelete")}
                            onClick={() => void removePseudonym(p.original)}
                            className="rounded-sm p-1 text-text-secondary hover:bg-danger/10 hover:text-danger"
                          >
                            <Trash2 size={13} aria-hidden />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* Colour scheme */}
          <section className="rounded-lg border border-border bg-surface p-4">
            <h2 className="text-sm font-semibold text-text-primary">{t("settings.colourScheme")}</h2>
            <p className="mt-1 text-xs text-text-secondary">{t("settings.colourSchemeHint")}</p>
            {paletteError && <p className="mt-1 text-xs text-danger">{paletteError}</p>}
            <div className="mt-3 grid grid-cols-12 gap-1">
              {palette.map((color, i) => (
                <label
                  key={i}
                  className="relative h-6 cursor-pointer overflow-hidden rounded-sm border border-border"
                  style={{ backgroundColor: color }}
                  title={color}
                >
                  <input
                    type="color"
                    value={color}
                    onChange={(e) =>
                      setPalette((p) => p.map((c, j) => (j === i ? e.target.value : c)))
                    }
                    className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                    aria-label={`Colour ${i + 1}`}
                  />
                </label>
              ))}
            </div>
            <div className="mt-3 flex items-center gap-2">
              <button
                type="button"
                onClick={() => void savePalette()}
                className="rounded-sm bg-accent px-2.5 py-1 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover"
              >
                {t("settings.colourSchemeSave")}
              </button>
              <button
                type="button"
                onClick={() => void resetPalette()}
                className="rounded-sm border border-border bg-bg px-2.5 py-1 text-xs hover:bg-surface-higher"
              >
                {t("settings.colourSchemeReset")}
              </button>
              {paletteSaved && (
                <span role="status" className="flex items-center gap-1 text-xs font-medium text-success">
                  <Check size={12} aria-hidden />
                  {t("settings.colourSchemeSaved")}
                </span>
              )}
            </div>
          </section>

          {/* About */}
          <section className="rounded-lg border border-border bg-surface p-4">
            <h2 className="text-sm font-semibold text-text-primary">{t("settings.about")}</h2>
            <p className="mt-1 text-xs text-text-secondary">{t("settings.aboutText")}</p>
          </section>
        </div>
      </div>
    </div>
  );
}
