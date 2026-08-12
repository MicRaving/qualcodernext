/**
 * AiChatPanel — chat with the project AI assistant. The chat mode and
 * prompt-library selection live in the pane's top bar (AiView).
 */
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Eraser, LoaderCircle, Send } from "lucide-react";
import { api, type AiStatus } from "@/lib/api";
import { errorDetail, welcomeMessage } from "@/features/ai/format";
import { useI18n } from "@/lib/i18n";
import { ErrorBanner, IconButton, Textarea } from "@/components/ui/orchestrator";
import type { AiMode } from "@/features/ai/aiModes";

type ChatRole = "user" | "assistant" | "error";

interface ChatMessage {
  role: ChatRole;
  text: string;
}

export function AiChatPanel({
  mode,
  promptId,
}: {
  mode: AiMode;
  promptId: string;
}) {
  const { t } = useI18n();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [status, setStatus] = useState<AiStatus | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .aiStatus()
      .then((s) => {
        if (cancelled) return;
        setStatus(s);
        if (s.enabled) setMessages([{ role: "assistant", text: welcomeMessage(true) }]);
      })
      .catch(() => {
        if (!cancelled) setStatus(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, waiting]);

  const disabled = !status?.enabled;

  async function send() {
    const text = input.trim();
    if (!text || waiting || disabled) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setWaiting(true);
    try {
      const res = await api.aiChat(text, "", mode, promptId || undefined);
      setMessages((m) => [...m, { role: "assistant", text: res.reply }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "error", text: errorDetail(e) }]);
    } finally {
      setWaiting(false);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-bg">
      {disabled && (
        <ErrorBanner tone="warning">{welcomeMessage(false)}</ErrorBanner>
      )}

      {/* Messages */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto p-3">
        <div className="mx-auto flex max-w-2xl flex-col gap-2">
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[80%] rounded-lg bg-accent px-3 py-1.5 text-sm text-[var(--qc-bg)]">
                  {m.text}
                </div>
              </div>
            ) : m.role === "error" ? (
              <div key={i} className="flex justify-start">
                <div className="max-w-[80%] rounded-lg border border-danger bg-danger/10 px-3 py-1.5 text-sm text-danger">
                  {m.text}
                </div>
              </div>
            ) : (
              <div key={i} className="flex justify-start">
                <div className="max-w-[80%] rounded-lg bg-surface px-3 py-1.5 text-sm">
                  <span className="mb-0.5 block text-xs font-medium text-text-secondary">
                    {t("ai.assistantLabel")}
                  </span>
                  {m.text}
                </div>
              </div>
            ),
          )}
          {waiting && (
            <div className="flex justify-start">
              <div className="flex items-center gap-2 rounded-lg bg-surface px-3 py-1.5 text-sm text-text-secondary">
                <LoaderCircle size={14} className="animate-spin" aria-hidden />
                {t("ai.thinking")}
              </div>
            </div>
          )}
          {messages.length === 0 && !waiting && (
            <p className="py-4 text-center text-xs text-text-secondary">{t("ai.noMessages")}</p>
          )}
        </div>
      </div>

      {/* Input row */}
      <div className="shrink-0 border-t border-border bg-surface p-3">
        <div className="mx-auto flex max-w-2xl items-end gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
            placeholder={t("ai.chatPlaceholder")}
            aria-label={t("ai.messageAria")}
            disabled={disabled}
            className="min-h-0 flex-1 resize-none px-2 py-1.5"
          />
          <button
            type="button"
            onClick={() => void send()}
            disabled={disabled || waiting || input.trim() === ""}
            aria-label={t("ai.sendAria")}
            title={t("ai.sendTitle")}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm bg-accent text-[var(--qc-bg)] hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Send size={14} aria-hidden />
          </button>
          <IconButton
            label={t("ai.clearAria")}
            title={t("ai.clearTitle")}
            className="h-8 w-8 border border-border bg-bg"
            onClick={() => setMessages(status?.enabled ? [{ role: "assistant", text: welcomeMessage(true) }] : [])}
          >
            <Eraser size={14} aria-hidden />
          </IconButton>
        </div>
      </div>
    </div>
  );
}
