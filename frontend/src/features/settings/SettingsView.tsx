/**
 * Settings (right-bar pane) - appearance, language, AI assistant (incl. MCP
 * permissions + the semantic index), pseudonyms and Import/Export.
 *
 * Auto-saves: AI settings are persisted on change (debounced), no Save
 * button. Sections are separated by simple dividers, not cards.
 */
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  Check,
  CircleAlert,
  CircleCheck,
  HelpCircle,
  LoaderCircle,
  Moon,
  RotateCw,
  Sun,
  Trash2,
} from "lucide-react";
import { api, type AiIndexStatus, type Pseudonym } from "@/lib/api";
import { errorDetail } from "@/features/ai/format";
import { InterchangeView } from "@/features/interchange/InterchangeView";
import { useI18n, LOCALE_NAMES, type Locale } from "@/lib/i18n";
import {
  BarHeader,
  Button,
  ErrorBanner,
  Field,
  HelpFlyout,
  IconButton,
  Input,
  LeftBar,
  SectionLabel,
  Select,
} from "@/components/ui/orchestrator";
import { useProjectStore } from "@/stores/project";
import { useUpdatesStore } from "@/stores/updates";
import type { UpdatesSettings } from "@/lib/api";
import { Download } from "lucide-react";

export function SettingsView() {
  const { t, locale, setLocale } = useI18n();
  const themeMode = useProjectStore((s) => s.themeMode);
  const setThemeMode = useProjectStore((s) => s.setThemeMode);

  // App updates (desktop only — harmless no-op in the plain browser).
  const updatesStatus = useUpdatesStore((s) => s.status);
  const updatesInfo = useUpdatesStore((s) => s.info);
  const updatesProgress = useUpdatesStore((s) => s.progress);
  const updatesError = useUpdatesStore((s) => s.error);
  const updatesSettings = useUpdatesStore((s) => s.settings);
  const [checkInterval, setCheckInterval] = useState<UpdatesSettings["check_interval"]>("daily");
  const [autoUpdate, setAutoUpdate] = useState(false);

  useEffect(() => {
    const store = useUpdatesStore.getState();
    if (!updatesSettings) void store.loadSettings();
  }, [updatesSettings]);

  useEffect(() => {
    if (updatesSettings) {
      setCheckInterval(updatesSettings.check_interval);
      setAutoUpdate(updatesSettings.auto_update);
    }
  }, [updatesSettings]);

  async function toggleAutoUpdate() {
    const next = !autoUpdate;
    setAutoUpdate(next);
    const settings = { check_interval: checkInterval, auto_update: next };
    try {
      await useUpdatesStore.getState().saveSettings(settings);
      if (next) {
        // Enabling auto-update checks immediately (matches the scheduler).
        void useUpdatesStore.getState().checkNow();
      }
    } catch {
      /* keep the local toggle; the backend error surfaces on the next load */
    }
  }

  async function setIntervalAndSave(interval: UpdatesSettings["check_interval"]) {
    setCheckInterval(interval);
    try {
      await useUpdatesStore
        .getState()
        .saveSettings({ check_interval: interval, auto_update: autoUpdate });
    } catch {
      /* same as above */
    }
  }

  const [enabled, setEnabled] = useState(false);
  const [provider, setProvider] = useState("ollama");
  const [apiBase, setApiBase] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [mcpPermissions, setMcpPermissions] = useState("read");
  const [models, setModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  /** Service-status check button: "checking" → "ok"/"broken" for 3s. */
  const [serviceCheck, setServiceCheck] = useState<"idle" | "checking" | "ok" | "broken">("idle");
  const [serviceProbeError, setServiceProbeError] = useState<string | null>(null);
  const serviceCheckTimer = useRef<number | null>(null);

  // Semantic index
  const [indexStatus, setIndexStatus] = useState<AiIndexStatus | null>(null);
  const [indexBusy, setIndexBusy] = useState(false);
  const [indexError, setIndexError] = useState<string | null>(null);

  // Pseudonyms
  const [pseudonyms, setPseudonyms] = useState<Pseudonym[]>([]);
  const [pseudoOriginal, setPseudoOriginal] = useState("");
  const [pseudoName, setPseudoName] = useState("");
  const [pseudoError, setPseudoError] = useState<string | null>(null);


  // Help popovers (anchored for the shared HelpFlyout)
  const [helpOpen, setHelpOpen] = useState<"interchange" | "index" | null>(null);
  const [indexHintAnchorEl, setIndexHintAnchorEl] = useState<HTMLElement | null>(null);

  const PROVIDER_PRESETS: Record<string, { url: string; model: string }> = {
    ollama: { url: "http://localhost:11434/v1", model: "llama3.2" },
    lmstudio: { url: "http://localhost:1234/v1", model: "" },
    "opencode-go": { url: "https://opencode.ai/zen/go/v1", model: "deepseek-v4-flash" },
    gemini: {
      url: "https://generativelanguage.googleapis.com/v1beta/openai",
      model: "gemini-3.6-flash",
    },
    gpt: { url: "https://api.openai.com/v1", model: "gpt-5.6" },
    claude: { url: "https://api.anthropic.com/v1", model: "claude-sonnet-4-6" },
  };

  // Track whether the user has touched a field: the initial status fetch
  // must NOT overwrite an edit made while it was still in flight.
  const touchedRef = useRef(false);
  const markTouched = () => {
    touchedRef.current = true;
  };

  const loadStatus = useCallback(async () => {
    try {
      const s = await api.aiStatus();
      if (touchedRef.current) return;
      setEnabled(s.enabled);
      setProvider(s.provider);
      setApiBase(s.base_url);
      setModel(s.model);
      setMcpPermissions(s.mcp_permissions ?? "read");
    } catch {
      /* fields keep their defaults when the backend is unreachable */
    }
  }, []);

  const loadModels = useCallback(async () => {
    setModelsLoading(true);
    try {
      const res = await api.aiModels();
      setModels(res.models);
    } catch {
      setModels([]);
    } finally {
      setModelsLoading(false);
    }
  }, []);

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


  useEffect(() => {
    void loadStatus();
    void loadIndex();
    void loadPseudonyms();
  }, [loadStatus, loadIndex, loadPseudonyms]);

  // Model polling: fetch whenever the provider or base URL changes (with the
  // previous list cleared — no leftover models from other providers), and
  // refresh periodically while the pane is mounted so newly pulled models
  // (Ollama/LM Studio) appear on their own.
  useEffect(() => {
    setModels([]);
    void loadModels();
  }, [provider, apiBase, loadModels]);

  useEffect(() => {
    void loadModels();
    const timer = window.setInterval(() => void loadModels(), 60_000);
    return () => window.clearInterval(timer);
  }, [loadModels]);

  /** Probe the configured provider; the button shows OK/broken for 3s. */
  async function checkService() {
    if (serviceCheck === "checking") return;
    setServiceCheck("checking");
    setServiceProbeError(null);
    try {
      const s = await api.aiStatus(true);
      const ok = s.reachable === true;
      setServiceCheck(ok ? "ok" : "broken");
      if (!ok && s.probe_error) setServiceProbeError(s.probe_error);
    } catch (e) {
      setServiceCheck("broken");
      setServiceProbeError(errorDetail(e, t("settings.aiLoadError")));
    }
    if (serviceCheckTimer.current !== null) window.clearTimeout(serviceCheckTimer.current);
    serviceCheckTimer.current = window.setTimeout(() => setServiceCheck("idle"), 3000);
  }

  useEffect(
    () => () => {
      if (serviceCheckTimer.current !== null) window.clearTimeout(serviceCheckTimer.current);
    },
    [],
  );

  /** Auto-save the AI settings (debounced) — no Save button, no "Saved"
   *  flash; only errors surface. */
  const saveTimer = useRef<number | null>(null);
  useEffect(() => {
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      setSaveError(null);
      void api
        .aiSaveSettings({
          enabled,
          provider,
          api_base: apiBase.trim(),
          model: model.trim(),
          api_key: apiKey,
          mcp_permissions: mcpPermissions,
        })
        .catch((e) => setSaveError(errorDetail(e, t("settings.aiSaveError"))));
    }, 600);
    return () => {
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    };
  }, [enabled, provider, apiBase, model, apiKey, mcpPermissions, t]);


  function handleProviderChange(next: string) {
    markTouched();
    setProvider(next);
    const preset = PROVIDER_PRESETS[next];
    if (preset) {
      setApiBase(preset.url);
      if (preset.model) setModel(preset.model);
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

  const indexHintAnchor = helpOpen === "index" ? indexHintAnchorEl : null;

  return (
    <LeftBar
      borderSide="l"
      width="lg"
      header={<BarHeader title={t("settings.title")} />}
    >
      {saveError && <ErrorBanner>{saveError}</ErrorBanner>}

      <div className="divide-y divide-border">
        {/* General: appearance | language, then import/export */}
        <section className="p-3">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <SectionLabel>{t("settings.appearance")}</SectionLabel>
              <button
                type="button"
                role="switch"
                aria-checked={themeMode === "dark"}
                aria-label={t("theme.switchLabel", { theme: themeMode === "dark" ? "light" : "dark" })}
                onClick={() => setThemeMode(themeMode === "dark" ? "light" : "dark")}
                className="mt-2 flex items-center gap-2"
              >
                <span
                  className={`relative h-4 w-8 rounded-full transition-colors ${
                    themeMode === "dark" ? "bg-accent" : "bg-border"
                  }`}
                >
                  <span
                    className="absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all"
                    style={{ left: themeMode === "dark" ? 18 : 2 }}
                  />
                </span>
                {themeMode === "dark" ? (
                  <Moon size={14} className="text-text-secondary" aria-hidden />
                ) : (
                  <Sun size={14} className="text-text-secondary" aria-hidden />
                )}
                <span className="text-xs text-text-primary">
                  {themeMode === "dark" ? t("theme.dark") : t("theme.light")}
                </span>
              </button>
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

          <div className="mt-2">
            <InterchangeView embedded />
          </div>
        </section>

        {/* AI assistant */}
        <section className="p-3">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-text-primary">{t("settings.aiAssistant")}</h2>
            {/* Enable switch, styled like the status toggle */}
            <button
              type="button"
              role="switch"
              aria-checked={enabled}
              aria-label={t("settings.aiEnable")}
              onClick={() => {
                markTouched();
                setEnabled((v) => !v);
              }}
              className={`flex items-center gap-1 rounded-sm border border-border bg-bg px-2 py-1 text-xs hover:bg-surface-higher ${
                enabled ? "border-accent text-accent" : "text-text-secondary"
              }`}
            >
              <span
                className={`relative h-3.5 w-7 rounded-full transition-colors ${
                  enabled ? "bg-accent" : "bg-border"
                }`}
              >
                <span
                  className="absolute top-0.5 h-2.5 w-2.5 rounded-full bg-white transition-all"
                  style={{ left: enabled ? 16 : 2 }}
                />
              </span>
              {t("settings.aiEnable")}
            </button>
          </div>

          <div className="mt-3 grid grid-cols-1 gap-3">
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("settings.aiProvider")}>
                <Select
                  value={provider}
                  onChange={(e) => handleProviderChange(e.target.value)}
                  className="w-full"
                >
                  <option value="ollama">{t("settings.aiProviderOllama")}</option>
                  <option value="lmstudio">{t("settings.aiProviderLmStudio")}</option>
                  <option value="opencode-go">{t("settings.aiProviderOpencodeGo")}</option>
                  <option value="gemini">{t("settings.aiProviderGemini")}</option>
                  <option value="gpt">{t("settings.aiProviderGpt")}</option>
                  <option value="claude">{t("settings.aiProviderClaude")}</option>
                  <option value="custom">{t("settings.aiProviderCustom")}</option>
                </Select>
              </Field>
              <Field label={t("settings.model")}>
                <Select
                  value={model}
                  onChange={(e) => {
                    markTouched();
                    setModel(e.target.value);
                  }}
                  className="w-full"
                  disabled={models.length === 0}
                >
                  {model && !models.includes(model) && <option value={model}>{model}</option>}
                  {models.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </Select>
                {modelsLoading ? (
                  <span className="mt-1 flex items-center gap-1.5 text-xs text-text-secondary">
                    <LoaderCircle size={11} className="animate-spin" aria-hidden />
                    {t("settings.aiModelsLoading")}
                  </span>
                ) : (
                  models.length === 0 &&
                  enabled && (
                    <span className="mt-1 block text-xs text-warning">
                      {t("settings.aiModelsUnavailable")}
                    </span>
                  )
                )}
              </Field>
            </div>
            <Field label={t("settings.apiBaseUrl")}>
              <Input
                type="text"
                value={apiBase}
                onChange={(e) => {
                  markTouched(); setApiBase(e.target.value);
                  setProvider((p) =>
                    p in PROVIDER_PRESETS && PROVIDER_PRESETS[p].url !== e.target.value
                      ? "custom"
                      : p,
                  );
                }}
                placeholder="https://api.openai.com/v1"
                className="w-full"
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("settings.apiKey")}>
                <Input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={t("settings.optional")}
                  className="w-full"
                />
                {["gemini", "gpt", "claude"].includes(provider) && !apiKey.trim() && (
                  <span className="mt-1 block text-xs text-warning">
                    {t("settings.aiKeyRequired")}
                  </span>
                )}
              </Field>
              <Field label={t("ai.mcpPermissions")}>
                <Select
                  value={mcpPermissions}
                  onChange={(e) => { markTouched(); setMcpPermissions(e.target.value); }}
                  className="w-full"
                >
                  <option value="read">{t("ai.mcpRead")}</option>
                  <option value="write">{t("ai.mcpWrite")}</option>
                  <option value="full">{t("ai.mcpFull")}</option>
                </Select>
              </Field>
            </div>
          </div>

          {/* Service status | Semantic index — side by side */}
          <div className="mt-3 grid grid-cols-1 gap-3 border-t border-border pt-3 sm:grid-cols-2">
            {/* Service status — the Check button turns into a transient
                OK/broken indicator for 3s after probing the provider. */}
            <div>
              <div className="flex items-center gap-1.5">
                <h3 className="text-xs font-semibold text-text-primary">{t("settings.aiServiceStatus")}</h3>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <Button
                  variant="secondary"
                  onClick={() => void checkService()}
                  disabled={serviceCheck === "checking"}
                  icon={
                    serviceCheck === "checking" ? (
                      <LoaderCircle size={12} className="animate-spin" aria-hidden />
                    ) : serviceCheck === "ok" ? (
                      <CircleCheck size={12} aria-hidden />
                    ) : serviceCheck === "broken" ? (
                      <CircleAlert size={12} aria-hidden />
                    ) : (
                      <RotateCw size={12} aria-hidden />
                    )
                  }
                  className={
                    serviceCheck === "ok"
                      ? "border-success text-success hover:bg-success/10"
                      : serviceCheck === "broken"
                        ? "border-danger text-danger hover:bg-danger/10"
                        : ""
                  }
                >
                  {serviceCheck === "checking"
                    ? t("settings.aiChecking")
                    : serviceCheck === "ok"
                      ? t("settings.aiStatusOk")
                      : serviceCheck === "broken"
                        ? t("settings.aiStatusBroken")
                        : t("settings.aiCheckStatus")}
                </Button>
              </div>
              {serviceCheck === "broken" && serviceProbeError && (
                <p className="mt-1.5 break-words text-xs text-danger">{serviceProbeError}</p>
              )}
            </div>

            {/* Semantic index */}
            <div>
              <div className="flex items-center gap-1.5">
                <h3 className="text-xs font-semibold text-text-primary">{t("ai.indexSection")}</h3>
                <IconButton
                  label={t("ai.indexHint")}
                  title={t("ai.indexHint")}
                  size="sm"
                  aria-expanded={helpOpen === "index"}
                  onClick={(e) => {
                    setIndexHintAnchorEl(e.currentTarget);
                    setHelpOpen(helpOpen === "index" ? null : "index");
                  }}
                >
                  <HelpCircle size={12} aria-hidden />
                </IconButton>
                {helpOpen === "index" && indexHintAnchor && (
                  <HelpFlyout anchor={indexHintAnchor} onClose={() => setHelpOpen(null)}>
                    <p className="text-xs leading-relaxed text-text-secondary">{t("ai.indexHint")}</p>
                  </HelpFlyout>
                )}
              </div>
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
                <Button
                  variant="secondary"
                  onClick={() => void buildIndex()}
                  disabled={indexBusy}
                  icon={
                    indexBusy ? (
                      <LoaderCircle size={12} className="animate-spin" aria-hidden />
                    ) : (
                      <RotateCw size={12} aria-hidden />
                    )
                  }
                >
                  {indexStatus?.indexed ? t("ai.indexRebuild") : t("ai.indexBuild")}
                </Button>
                {indexStatus?.indexed && (
                  <Button
                    variant="danger"
                    onClick={() => void deleteIndex()}
                    icon={<Trash2 size={12} aria-hidden />}
                  >
                    {t("ai.indexDelete")}
                  </Button>
                )}
              </div>
            </div>
          </div>
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

        {/* App updates */}
        <section className="p-3">
          <h2 className="text-sm font-semibold text-text-primary">{t("settings.updatesSection")}</h2>
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              role="switch"
              aria-checked={autoUpdate}
              aria-label={t("settings.updatesAuto")}
              onClick={() => void toggleAutoUpdate()}
              className="flex items-center gap-2"
            >
              <span
                className={`relative h-4 w-8 rounded-full transition-colors ${
                  autoUpdate ? "bg-accent" : "bg-border"
                }`}
              >
                <span
                  className="absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all"
                  style={{ left: autoUpdate ? 18 : 2 }}
                />
              </span>
              <span className="text-xs text-text-primary">{t("settings.updatesAuto")}</span>
            </button>
          </div>
          <div className="mt-2 flex flex-wrap items-end gap-3">
            <Field label={t("settings.updatesInterval")} className="w-40">
              <Select
                value={checkInterval}
                onChange={(e) => void setIntervalAndSave(e.target.value as UpdatesSettings["check_interval"])}
                className="w-full"
              >
                <option value="daily">{t("settings.updatesIntervalDaily")}</option>
                <option value="weekly">{t("settings.updatesIntervalWeekly")}</option>
                <option value="never">{t("settings.updatesIntervalNever")}</option>
              </Select>
            </Field>
            <Button
              variant="secondary"
              icon={
                updatesStatus === "checking" ? (
                  <LoaderCircle size={12} className="animate-spin" aria-hidden />
                ) : (
                  <RotateCw size={12} aria-hidden />
                )
              }
              disabled={updatesStatus === "checking" || updatesStatus === "downloading"}
              onClick={() => void useUpdatesStore.getState().checkNow()}
            >
              {t("settings.updatesCheckNow")}
            </Button>
            {updatesStatus === "available" && updatesInfo && (
              <Button
                variant="primary"
                icon={<Download size={12} aria-hidden />}
                onClick={() => void useUpdatesStore.getState().install()}
              >
                {t("settings.updatesInstall")}
              </Button>
            )}
          </div>
          {updatesStatus === "checking" && (
            <p className="mt-2 text-xs text-text-secondary">{t("settings.updatesChecking")}</p>
          )}
          {updatesStatus === "up-to-date" && (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-success" role="status">
              <Check size={12} aria-hidden />
              {t("settings.updatesUpToDate")}
            </p>
          )}
          {updatesStatus === "available" && updatesInfo && (
            <p className="mt-2 text-xs text-text-primary">
              {t("settings.updatesAvailable", { version: updatesInfo.version })}
            </p>
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
                : t("settings.updatesError", { detail: updatesError ?? "" })}
            </p>
          )}
        </section>

        {/* About */}
        <section className="p-3">
          <h2 className="text-sm font-semibold text-text-primary">{t("settings.about")}</h2>
          <p className="mt-1 text-xs text-text-secondary">{t("settings.aboutText")}</p>
        </section>
      </div>
    </LeftBar>
  );
}
