/**
 * AiView — the AI assistant as a toggleable right-bar pane. The mode
 * dropdown (chat modes + semantic search) and the prompt library live in
 * the pane's top bar; the "Semantic search" mode renders the search panel
 * in the main area, every other mode renders the chat panel.
 */
import { useState } from "react";
import { useAsyncEffect } from "@/lib/useAsync";
import { HelpCircle } from "lucide-react";
import { api, type AiPromptInfo } from "@/lib/api";
import {
  BarHeader,
  HelpFlyout,
  IconButton,
  LeftBar,
  Select,
} from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { AI_MODES, AI_MODE_LABELS, type AiMode } from "@/features/ai/aiModes";
import { AiChatPanel } from "@/features/ai/AiChatPanel";
import { AiSearchPanel } from "@/features/ai/AiSearchPanel";

/**
 * Prompt catalog entries the backend may extend with ``label`` + ``hidden`` —
 * keep the old shape (name only) working until the new fields ship.
 */
type CatalogPrompt = AiPromptInfo & {
  /** Display name added by newer backends; falls back to ``name``. */
  label?: string;
  /** Backend mark for internal entries (e.g. ``_init``); never shown. */
  hidden?: boolean;
};

/**
 * Root prompts (``_init``, ``_bootstrap``, …) are resolved automatically by
 * the backend for each mode — they are scaffolding, not user-pickable
 * templates, so the dropdown skips them (newer backends also flag them via
 * ``hidden``).
 */
function isUsablePrompt(p: AiPromptInfo): boolean {
  const ext = p as CatalogPrompt;
  if (ext.hidden) return false;
  if (p.id === "_init" || p.id.endsWith("/_init")) return false;
  if (p.name.startsWith("_")) return false;
  return true;
}

function promptLabel(p: AiPromptInfo): string {
  return (p as CatalogPrompt).label ?? p.name;
}

export function AiView() {
  const { t } = useI18n();
  const [mode, setMode] = useState<AiMode>("general");
  const [prompts, setPrompts] = useState<AiPromptInfo[]>([]);
  const [promptId, setPromptId] = useState<string>("");
  const [helpAnchor, setHelpAnchor] = useState<HTMLElement | null>(null);

  useAsyncEffect(async (signal) => {
    const res = await api.aiPrompts();
    signal.throwIfAborted();
    setPrompts(res.prompts);
  }, []);

  const isSearch = mode === "search";
  const modePrompts = prompts.filter((p) => p.mode === mode && isUsablePrompt(p));

  return (
    <LeftBar
      borderSide="l"
      scroll={false}
      className="h-full min-h-0 max-w-full overflow-hidden"
      header={
        <>
          <BarHeader
            title="AI"
            actions={
              <>
                <Select
                  value={mode}
                  onChange={(e) => {
                    setMode(e.target.value as AiMode);
                    setPromptId("");
                  }}
                  aria-label={t("ai.modeLabel")}
                  title={t("ai.modeLabel")}
                  className="min-w-0 max-w-full"
                >
                  {AI_MODES.map((m) => (
                    <option key={m} value={m}>
                      {t(AI_MODE_LABELS[m])}
                    </option>
                  ))}
                </Select>
                {!isSearch && (
                  <>
                    {modePrompts.length > 0 ? (
                      <Select
                        value={promptId}
                        onChange={(e) => setPromptId(e.target.value)}
                        aria-label={t("ai.promptLabel")}
                        title={t("ai.promptLabel")}
                        className="min-w-0 max-w-20"
                      >
                        <option value="">{t("ai.promptNone")}</option>
                        {modePrompts.map((p) => (
                          <option key={p.id} value={p.id} title={p.description}>
                            {promptLabel(p)}
                          </option>
                        ))}
                      </Select>
                    ) : (
                      /* Same-size spacer so the bar layout does not jump
                       * when a mode has no prompt templates. */
                      <Select
                        value=""
                        disabled
                        aria-label={t("ai.promptLabel")}
                        className="min-w-0 max-w-20 opacity-60"
                      >
                        <option value="">{t("ai.promptNone")}</option>
                      </Select>
                    )}
                    <IconButton
                      label={t("ai.promptHelp")}
                      title={t("ai.promptHelp")}
                      size="sm"
                      aria-expanded={helpAnchor !== null}
                      onClick={(e) => setHelpAnchor(helpAnchor ? null : e.currentTarget)}
                    >
                      <HelpCircle size={12} aria-hidden />
                    </IconButton>
                    {helpAnchor && (
                      <HelpFlyout anchor={helpAnchor} onClose={() => setHelpAnchor(null)}>
                        <p className="text-xs leading-relaxed text-text-secondary">
                          {t("ai.promptHelp")}
                        </p>
                      </HelpFlyout>
                    )}
                  </>
                )}
              </>
            }
          />
          <p className="border-b border-border px-3 py-1 text-[10px] leading-snug text-text-secondary">
            {t("ai.modePipelineHelp")}
          </p>
        </>
      }
    >
      {isSearch ? <AiSearchPanel /> : <AiChatPanel mode={mode} promptId={promptId} />}
    </LeftBar>
  );
}
