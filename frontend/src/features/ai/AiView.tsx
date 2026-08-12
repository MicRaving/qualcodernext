/**
 * AiView — the AI assistant as a toggleable right-bar pane with a
 * Chat / Search tab toggle; the chat mode and prompt library live in the
 * pane's top bar.
 */
import { useEffect, useState } from "react";
import { MessageSquare, Search } from "lucide-react";
import { api, type AiPromptInfo } from "@/lib/api";
import { BarHeader, LeftBar, Select } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { AI_MODES, AI_MODE_LABELS, type AiMode } from "@/features/ai/aiModes";
import { AiChatPanel } from "@/features/ai/AiChatPanel";
import { AiSearchPanel } from "@/features/ai/AiSearchPanel";

type AiTab = "chat" | "search";

const TABS: { kind: AiTab; label: string; icon: typeof MessageSquare }[] = [
  { kind: "chat", label: "Chat", icon: MessageSquare },
  { kind: "search", label: "Search", icon: Search },
];

export function AiView() {
  const { t } = useI18n();
  const [tab, setTab] = useState<AiTab>("chat");
  const [mode, setMode] = useState<AiMode>("general");
  const [prompts, setPrompts] = useState<AiPromptInfo[]>([]);
  const [promptId, setPromptId] = useState<string>("");

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

  const modePrompts = prompts.filter((p) => p.mode === mode);

  return (
    <LeftBar
      borderSide="l"
      scroll={false}
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
                  >
                    {AI_MODES.map((m) => (
                      <option key={m} value={m}>
                        {t(AI_MODE_LABELS[m])}
                      </option>
                    ))}
                  </Select>
                  {modePrompts.length > 0 && (
                    <Select
                      value={promptId}
                      onChange={(e) => setPromptId(e.target.value)}
                      aria-label={t("ai.promptLabel")}
                      title={t("ai.promptLabel")}
                      className="max-w-20"
                    >
                      <option value="">{t("ai.promptNone")}</option>
                      {modePrompts.map((p) => (
                        <option key={p.id} value={p.id} title={p.description}>
                          {p.name}
                        </option>
                      ))}
                    </Select>
                  )}
                </>
              )}
              <div className="flex items-center gap-0.5 rounded-sm border border-border bg-bg p-0.5">
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
