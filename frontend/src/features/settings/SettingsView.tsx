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
import { api, type AiIndexStatus, type Pseudonym, type RStatus } from "@/lib/api";
import { DEFAULT_GITHUB_REPO } from "@/features/bugreport/github";
import { errorDetail } from "@/features/ai/format";
import { A11yControls } from "@/features/accessibility/A11yControls";
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
import { InterchangeView } from "@/features/interchange/InterchangeView";

/**
 * Module-level draft of the AI settings pane. SettingsView unmounts whenever
 * the right pane switches, so plain local state would lose a typed API key
 * (and remount auto-save would wipe the stored one). The draft survives the
 * pane lifetime and is re-used on reopen; it dies with the app session.
 */
interface AiDraft {
  enabled: boolean;
  provider: string;
  apiBase: string;
  model: string;
  apiKey: string;
  mcpPermissions: string;
  redditClientId: string;
  redditClientSecret: string;
}

let aiDraftCache: AiDraft | null = null;

const PROVIDER_ORDER = ["ollama", "lmstudio", "opencode-go", "gemini", "gpt", "claude", "custom"];
const PROVIDER_LABEL_KEYS: Record<string, string> = {
  ollama: "settings.aiProviderOllama",
  lmstudio: "settings.aiProviderLmStudio",
  "opencode-go": "settings.aiProviderOpencodeGo",
  gemini: "settings.aiProviderGemini",
  gpt: "settings.aiProviderGpt",
  claude: "settings.aiProviderClaude",
  custom: "settings.aiProviderCustom",
};

const PROVIDER_PRESETS: Record<string, { url: string; model: string }> = {
  ollama: { url: "http://localhost:11434/v1", model: "llama3.2" },
  lmstudio: { url: "http://127.0.0.1:1234/v1", model: "" },
  "opencode-go": { url: "https://opencode.ai/zen/go/v1", model: "deepseek-v4-flash" },
  gemini: {
    url: "https://generativelanguage.googleapis.com/v1beta/openai",
    model: "gemini-3.6-flash",
  },
  gpt: { url: "https://api.openai.com/v1", model: "gpt-5.6" },
  claude: { url: "https://api.anthropic.com/v1", model: "claude-sonnet-4-6" },
};

export function SettingsView() {
  const { t, locale, setLocale } = useI18n();
  const themeMode = useProjectStore((s) => s.themeMode);
  const setThemeMode = useProjectStore((s) => s.setThemeMode);
  const autoShowSegmentDetails = useProjectStore((s) => s.autoShowSegmentDetails);
  const setAutoShowSegmentDetails = useProjectStore((s) => s.setAutoShowSegmentDetails);

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

  const [enabled, setEnabled] = useState(() => aiDraftCache?.enabled ?? false);
  const [provider, setProvider] = useState(() => aiDraftCache?.provider ?? "ollama");
  const [apiBase, setApiBase] = useState(() => aiDraftCache?.apiBase ?? "");
  const [model, setModel] = useState(() => aiDraftCache?.model ?? "");
  const [apiKey, setApiKey] = useState(() => aiDraftCache?.apiKey ?? "");
  const [mcpPermissions, setMcpPermissions] = useState(
    () => aiDraftCache?.mcpPermissions ?? "read",
  );
  const [redditClientId, setRedditClientId] = useState(() => aiDraftCache?.redditClientId ?? "");
  const [redditClientSecret, setRedditClientSecret] = useState(
    () => aiDraftCache?.redditClientSecret ?? "",
  );
  const [models, setModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  /** Service-status check button: "checking" → "ok"/"broken" for 3s. */
  const [serviceCheck, setServiceCheck] = useState<"idle" | "checking" | "ok" | "broken">("idle");
  const [serviceProbeError, setServiceProbeError] = useState<string | null>(null);
  const serviceCheckTimer = useRef<number | null>(null);

  /** Sequence guard for model fetches — a stale response (previous provider)
   *  must never overwrite the current provider's list. */
  const modelsReqId = useRef(0);

  // Semantic index
  const [indexStatus, setIndexStatus] = useState<AiIndexStatus | null>(null);
  const [indexBusy, setIndexBusy] = useState(false);
  const [indexError, setIndexError] = useState<string | null>(null);

  // Pseudonyms
  const [pseudonyms, setPseudonyms] = useState<Pseudonym[]>([]);
  const [pseudoOriginal, setPseudoOriginal] = useState("");
  const [pseudoName, setPseudoName] = useState("");
  const [pseudoError, setPseudoError] = useState<string | null>(null);

  // R integration status
  const [rStatus, setRStatus] = useState<RStatus | null>(null);

  // Auto-load project on start (packaged app only; harmless elsewhere).
  const [autoLoadProject, setAutoLoadProject] = useState(true);

  // GitHub bug-report integration (token + target repository). Defaults to
  // the repo the updater manifest points at (MicRaving/QCnext).
  const [githubToken, setGithubToken] = useState("");
  const [githubRepo, setGithubRepo] = useState(DEFAULT_GITHUB_REPO);
  const [githubSaving, setGithubSaving] = useState(false);
  const [githubSaved, setGithubSaved] = useState(false);
  const [githubError, setGithubError] = useState<string | null>(null);

  useEffect(() => {
    api
      .appSettings()
      .then((s) => setAutoLoadProject(s.auto_open_project))
      .catch(() => {
        /* backend unreachable — keep the default */
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

  // Load the stored GitHub config with the app settings on mount.
  useEffect(() => {
    api
      .appSettings()
      .then((s) => {
        if (s.github_token) setGithubToken(s.github_token);
        if (s.github_repo && s.github_repo.trim().includes("/")) {
          setGithubRepo(s.github_repo.trim());
        }
      })
      .catch(() => {
        /* backend unreachable — keep the defaults */
      });
  }, []);

  async function saveGithub() {
    if (githubSaving) return;
    setGithubSaving(true);
    setGithubError(null);
    setGithubSaved(false);
    try {
      await api.saveAppSettings({
        auto_open_project: autoLoadProject,
        github_token: githubToken.trim(),
        github_repo: githubRepo.trim() || DEFAULT_GITHUB_REPO,
      });
      setGithubSaved(true);
      window.setTimeout(() => setGithubSaved(false), 2500);
    } catch (e) {
      setGithubError(errorDetail(e, t("settings.githubSaveError")));
    } finally {
      setGithubSaving(false);
    }
  }


  // Help popovers (anchored for the shared HelpFlyout)
  const [helpOpen, setHelpOpen] = useState<"interchange" | "index" | null>(null);
  const [indexHintAnchorEl, setIndexHintAnchorEl] = useState<HTMLElement | null>(null);

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
    const reqId = ++modelsReqId.current;
    const opts = { provider, api_base: apiBase, api_key: apiKey };
    setModelsLoading(true);
    setModelsError(null);
    try {
      const res = await api.aiModels(opts);
      if (reqId !== modelsReqId.current) return; // superseded by a newer fetch
      setModels(res.models);
      // A key-less Gemini (or rejected key) surfaces as a friendly detail.
      setModelsError(res.error ?? null);
    } catch {
      if (reqId !== modelsReqId.current) return;
      setModels([]);
    } finally {
      if (reqId === modelsReqId.current) setModelsLoading(false);
    }
  }, [provider, apiBase, apiKey]);

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
    // A restored draft (pane reopen) wins over the status fetch — the draft
    // already holds the values the user last saw and edited.
    if (aiDraftCache) touchedRef.current = true;
    void loadStatus();
    void loadIndex();
    void loadPseudonyms();
    api
      .rStatus()
      .then(setRStatus)
      .catch(() => setRStatus(null));
  }, [loadStatus, loadIndex, loadPseudonyms]);

  // Keep the module-level draft in sync so a typed API key etc. survives a
  // pane close/reopen (SettingsView unmounts on right-pane switches).
  useEffect(() => {
    aiDraftCache = {
      enabled,
      provider,
      apiBase,
      model,
      apiKey,
      mcpPermissions,
      redditClientId,
      redditClientSecret,
    };
  }, [enabled, provider, apiBase, model, apiKey, mcpPermissions, redditClientId, redditClientSecret]);

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
   *  flash; only errors surface. Only runs after the user actually edited
   *  something: a bare mount must never write defaults over stored settings
   *  (the backend also refuses to overwrite the API key with a blank). */
  const saveTimer = useRef<number | null>(null);
  useEffect(() => {
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    if (!touchedRef.current) return;
    saveTimer.current = window.setTimeout(() => {
      setSaveError(null);
      // The Reddit API credentials ride the AI-settings request (the
      // pane's only auto-save mechanism); the backend persists them
      // separately in the settings JSON. Blank values are left unchanged
      // server-side, so a fresh mount can never wipe stored credentials.
      const body = {
        enabled,
        provider,
        api_base: apiBase.trim(),
        model: model.trim(),
        api_key: apiKey,
        mcp_permissions: mcpPermissions,
        reddit_client_id: redditClientId.trim(),
        reddit_client_secret: redditClientSecret.trim(),
      };
      void api.aiSaveSettings(body).catch((e) => setSaveError(errorDetail(e, t("settings.aiSaveError"))));
    }, 600);
    return () => {
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    };
  }, [enabled, provider, apiBase, model, apiKey, mcpPermissions, redditClientId, redditClientSecret, t]);


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
      className="h-full min-h-0"
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

          <div className="mt-3 border-t border-border pt-3">
            <button
              type="button"
              role="switch"
              aria-checked={autoLoadProject}
              aria-label={t("settings.autoLoadProject")}
              onClick={() => void toggleAutoLoadProject()}
              className="flex items-center gap-2"
            >
              <span
                className={`relative h-4 w-8 rounded-full transition-colors ${
                  autoLoadProject ? "bg-accent" : "bg-border"
                }`}
              >
                <span
                  className="absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all"
                  style={{ left: autoLoadProject ? 18 : 2 }}
                />
              </span>
              <span className="text-xs text-text-primary">{t("settings.autoLoadProject")}</span>
            </button>
            <p className="mt-1 text-xs text-text-secondary">{t("settings.autoLoadProjectHint")}</p>
          </div>

          <div className="mt-3 border-t border-border pt-3">
            <button
              type="button"
              role="switch"
              aria-checked={autoShowSegmentDetails}
              aria-label={t("settings.autoShowSegmentDetails")}
              onClick={() => setAutoShowSegmentDetails(!autoShowSegmentDetails)}
              className="flex items-center gap-2"
            >
              <span
                className={`relative h-4 w-8 rounded-full transition-colors ${
                  autoShowSegmentDetails ? "bg-accent" : "bg-border"
                }`}
              >
                <span
                  className="absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all"
                  style={{ left: autoShowSegmentDetails ? 18 : 2 }}
                />
              </span>
              <span className="text-xs text-text-primary">{t("settings.autoShowSegmentDetails")}</span>
            </button>
            <p className="mt-1 text-xs text-text-secondary">
              {t("settings.autoShowSegmentDetailsHint")}
            </p>
          </div>

          <div className="mt-3 border-t border-border pt-3">
            <A11yControls />
          </div>
        </section>

        {/* Import / Export — embedded in the General area (no ribbon entry) */}
        <section className="p-3">
          <InterchangeView />
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
                  {PROVIDER_ORDER.map((name) => (
                    <option key={name} value={name}>
                      {t(PROVIDER_LABEL_KEYS[name])}
                    </option>
                  ))}
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
                ) : modelsError ? (
                  <span className="mt-1 block text-xs text-danger" role="alert">
                    {modelsError}
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
                  onChange={(e) => {
                    markTouched();
                    setApiKey(e.target.value);
                  }}
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

          {/* Reddit API credentials — optional app-only OAuth for the
              Reddit scraper when anonymous access is blocked */}
          <div className="mt-3 border-t border-border pt-3">
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("settings.redditClientId")}>
                <Input
                  type="password"
                  value={redditClientId}
                  onChange={(e) => {
                    markTouched();
                    setRedditClientId(e.target.value);
                  }}
                  placeholder={t("settings.optional")}
                  className="w-full"
                />
              </Field>
              <Field label={t("settings.redditClientSecret")}>
                <Input
                  type="password"
                  value={redditClientSecret}
                  onChange={(e) => {
                    markTouched();
                    setRedditClientSecret(e.target.value);
                  }}
                  placeholder={t("settings.optional")}
                  className="w-full"
                />
              </Field>
            </div>
            <p className="mt-1 text-xs text-text-secondary">
              {t("settings.redditCredentialsHint")}{" "}
              <a
                href="https://www.reddit.com/prefs/apps"
                target="_blank"
                rel="noreferrer"
                className="inline-block text-accent underline"
              >
                reddit.com/prefs/apps
              </a>
            </p>
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

        {/* GitHub (bug reports) */}
        <section className="p-3">
          <h2 className="text-sm font-semibold text-text-primary">{t("settings.githubSection")}</h2>
          <p className="mt-1 text-xs text-text-secondary">{t("settings.githubHint")}</p>
          <div className="mt-2 flex flex-col gap-3">
            <Field label={t("settings.githubToken")}>
              <Input
                type="password"
                value={githubToken}
                onChange={(e) => setGithubToken(e.target.value)}
                placeholder={t("settings.optional")}
                autoComplete="off"
                className="w-full"
              />
            </Field>
            <Field label={t("settings.githubRepo")}>
              <Input
                value={githubRepo}
                onChange={(e) => setGithubRepo(e.target.value)}
                placeholder="owner/repo"
                className="w-full"
              />
            </Field>
            <div className="flex items-center gap-2">
              <Button
                variant="primary"
                disabled={githubSaving}
                icon={
                  githubSaving ? (
                    <LoaderCircle size={12} className="animate-spin" aria-hidden />
                  ) : (
                    <Check size={12} aria-hidden />
                  )
                }
                onClick={() => void saveGithub()}
              >
                {githubSaving ? t("settings.saving") : t("common.save")}
              </Button>
              {githubSaved && (
                <span className="flex items-center gap-1 text-xs text-success" role="status">
                  <Check size={12} aria-hidden />
                  {t("settings.saved")}
                </span>
              )}
            </div>
            {githubError && <p className="text-xs text-danger">{githubError}</p>}
          </div>
        </section>

        {/* R integration */}
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

        {/* About */}
        <section className="p-3">
          <h2 className="text-sm font-semibold text-text-primary">{t("settings.about")}</h2>
          <p className="mt-1 text-xs text-text-secondary">{t("settings.aboutText")}</p>
        </section>
      </div>
    </LeftBar>
  );
}
