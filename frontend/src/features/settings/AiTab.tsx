/**
 * AiTab — Settings "AI" tab: the AI assistant toggle, provider / model /
 * base URL / API key / MCP permissions and the live service-status row.
 * All settings auto-save (debounced); the semantic index lives on the
 * Maintenance tab.
 *
 * Module-level draft: SettingsView unmounts whenever the right pane
 * switches, so plain local state would lose a typed API key (and remount
 * auto-save would wipe the stored one). The draft survives the pane
 * lifetime and is re-used on reopen; it dies with the app session.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { LoaderCircle, RotateCw } from "lucide-react";
import { api } from "@/lib/api";
import { errorDetail } from "@/features/ai/format";
import { useI18n } from "@/lib/i18n";
import { ErrorBanner, Field, IconButton, Input, Select } from "@/components/ui/orchestrator";

interface AiDraft {
  enabled: boolean;
  provider: string;
  apiBase: string;
  model: string;
  apiKey: string;
  mcpPermissions: string;
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

export function AiTab() {
  const { t } = useI18n();

  const [enabled, setEnabled] = useState(() => aiDraftCache?.enabled ?? false);
  const [provider, setProvider] = useState(() => aiDraftCache?.provider ?? "ollama");
  const [apiBase, setApiBase] = useState(() => aiDraftCache?.apiBase ?? "");
  const [model, setModel] = useState(() => aiDraftCache?.model ?? "");
  const [apiKey, setApiKey] = useState(() => aiDraftCache?.apiKey ?? "");
  const [mcpPermissions, setMcpPermissions] = useState(
    () => aiDraftCache?.mcpPermissions ?? "read",
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

  useEffect(() => {
    // A restored draft (pane reopen) wins over the status fetch — the draft
    // already holds the values the user last saw and edited.
    if (aiDraftCache) touchedRef.current = true;
    void loadStatus();
  }, [loadStatus]);

  // Keep the module-level draft in sync so a typed API key etc. survives a
  // pane close/reopen (the AI tab unmounts on right-pane switches).
  useEffect(() => {
    aiDraftCache = {
      enabled,
      provider,
      apiBase,
      model,
      apiKey,
      mcpPermissions,
    };
  }, [enabled, provider, apiBase, model, apiKey, mcpPermissions]);

  // Model polling: fetch whenever the provider or base URL changes (with the
  // previous list cleared — no leftover models from other providers), and
  // refresh periodically while the tab is mounted so newly pulled models
  // (Ollama/LM Studio) appear on their own. Skipped entirely while the AI
  // assistant is disabled — one effect owns both behaviours, so a provider
  // change never double-fetches.
  useEffect(() => {
    if (!enabled) {
      setModels([]);
      return;
    }
    setModels([]);
    void loadModels();
    const timer = window.setInterval(() => void loadModels(), 60_000);
    return () => window.clearInterval(timer);
  }, [provider, apiBase, loadModels, enabled]);

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
      const body = {
        enabled,
        provider,
        api_base: apiBase.trim(),
        model: model.trim(),
        api_key: apiKey,
        mcp_permissions: mcpPermissions,
      };
      void api.aiSaveSettings(body).catch((e) => setSaveError(errorDetail(e, t("settings.aiSaveError"))));
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

  return (
    <div className="p-3">
      {saveError && <ErrorBanner>{saveError}</ErrorBanner>}
      <div className="p-3">
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

        {enabled && (
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
                  markTouched();
                  setApiBase(e.target.value);
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
                  onChange={(e) => {
                    markTouched();
                    setMcpPermissions(e.target.value);
                  }}
                  className="w-full"
                >
                  <option value="read">{t("ai.mcpRead")}</option>
                  <option value="write">{t("ai.mcpWrite")}</option>
                  <option value="full">{t("ai.mcpFull")}</option>
                </Select>
              </Field>
            </div>
          </div>
        )}

        {/* Service status — a fixed-height inline row: a status dot + short
            label and a small re-probe button. The dot stays success/danger/
            warning-colored; no banners, no height jumps. */}
        {enabled && (
          <div className="mt-3 border-t border-border pt-3">
            <div className="flex items-center gap-1.5">
              <h3 className="text-xs font-semibold text-text-primary">{t("settings.aiServiceStatus")}</h3>
            </div>
            <div className="mt-2 flex h-6 items-center gap-1.5" title={serviceProbeError ?? undefined}>
              <span
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                  serviceCheck === "ok"
                    ? "bg-success"
                    : serviceCheck === "broken"
                      ? "bg-danger"
                      : serviceCheck === "checking"
                        ? "bg-warning"
                        : "bg-border"
                }`}
                aria-hidden
              />
              <span className="min-w-0 truncate text-xs text-text-secondary">
                {serviceCheck === "checking"
                  ? t("settings.aiChecking")
                  : serviceCheck === "ok"
                    ? t("settings.aiStatusConnected")
                    : serviceCheck === "broken"
                      ? t("settings.aiStatusUnreachable")
                      : t("settings.aiCheckStatus")}
              </span>
              <IconButton
                label={t("settings.aiCheckStatus")}
                title={t("settings.aiCheckStatus")}
                size="sm"
                disabled={serviceCheck === "checking"}
                onClick={() => void checkService()}
                className="ml-auto"
              >
                {serviceCheck === "checking" ? (
                  <LoaderCircle size={12} className="animate-spin" aria-hidden />
                ) : (
                  <RotateCw size={12} aria-hidden />
                )}
              </IconButton>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

