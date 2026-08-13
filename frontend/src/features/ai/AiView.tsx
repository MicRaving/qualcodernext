/**
 * AiView — the AI assistant as a toggleable right-bar pane with a
 * Chat / Search tab toggle; the chat mode and prompt library live in the
 * pane's top bar.
 */
import { useEffect, useState } from "react";
import { HelpCircle, MessageSquare, Search } from "lucide-react";
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

type AiTab = "chat" | "search";

const TABS: { kind: AiTab; label: string; icon: typeof MessageSquare }[] = [
  { kind: "chat", label: "Chat", icon: MessageSquare },
  { kind: "search", label: "Search", icon: Search },
];

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
  const [tab, setTab] = useState<AiTab>("chat");
  const [mode, setMode] = useState<AiMode>("general");
  const [prompts, setPrompts] = useState<AiPromptInfo[]>([]);
  const [promptId, setPromptId] = useState<string>("");
  const [helpAnchor, setHelpAnchor] = useState<HTMLElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .aiPrompts()
      .then((res) => {
        if (!cancelled) setPrompts(res.prompts);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const modePrompts = prompts.filter((p) => p.mode === mode && isUsablePrompt(p));

  return (
    <LeftBar
      borderSide="l"
      scroll={false}
      className="h-full min-h-0 max-w-full overflow-hidden"
      header={
        <BarHeader
          title="AI"
          actions={
            <>
              {/* Chat mode lives in the top bar of the pane */}
              {tab === "chat" && (
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
                    <span title={t("ai.promptHelp")} className="text-[10px] text-text-secondary">
                      {t("ai.promptsEmptyHint")}
                    </span>
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
              <div className="flex shrink-0 items-center gap-0.5 rounded-sm border border-border bg-bg p-0.5">
                {TABS.map(({ kind, label, icon: Icon }) => (
                  <button
                    key={kind}
                    type="button"
                    onClick={() => setTab(kind)}
                    aria-pressed={tab === kind}
                    className={`flex items-center gap-1 rounded-sm px-2 py-1 text-xs font-medium ${
                      tab === kind
                        ? "bg-surface-higher text-accent"
                        : "text-text-secondary hover:text-text-primary"
                    }`}
                  >
                    <Icon size={12} aria-hidden />
                    {label}
                  </button>
                ))}
              </div>
            </>
          }
        />
      }
    >
      {tab === "chat" ? (
        <AiChatPanel mode={mode} promptId={promptId} />
      ) : (
        <AiSearchPanel />
      )}
    </LeftBar>
  );
}
