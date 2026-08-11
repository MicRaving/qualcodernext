/**
 * AiView — AI workspace with a Chat / Search tab toggle.
 */
import { useState } from "react";
import { MessageSquare, Search } from "lucide-react";
import { ViewHeader } from "@/components/ui/orchestrator";
import { AiChatPanel } from "@/features/ai/AiChatPanel";
import { AiSearchPanel } from "@/features/ai/AiSearchPanel";

type AiTab = "chat" | "search";

const TABS: { kind: AiTab; label: string; icon: typeof MessageSquare }[] = [
  { kind: "chat", label: "Chat", icon: MessageSquare },
  { kind: "search", label: "Search", icon: Search },
];

export function AiView() {
  const [tab, setTab] = useState<AiTab>("chat");

  return (
    <div className="flex h-full min-h-0 flex-col bg-bg">
      <ViewHeader
        title="AI"
        actions={
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
        }
      />
      {tab === "chat" ? <AiChatPanel /> : <AiSearchPanel />}
    </div>
  );
}
