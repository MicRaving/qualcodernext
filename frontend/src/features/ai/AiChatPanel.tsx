/**
 * AiChatPanel — chat with the project AI assistant. Supports the upstream
 * chat modes (help, topic exploration, code analysis, text analysis) and
 * prompt-library selection.
 */
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { CircleAlert, Eraser, LoaderCircle, Send } from "lucide-react";
import { api, type AiPromptInfo, type AiStatus } from "@/lib/api";
import { errorDetail, welcomeMessage } from "@/features/ai/format";
import { useI18n } from "@/lib/i18n";

type ChatRole = "user" | "assistant" | "error";

interface ChatMessage {
  role: ChatRole;
  text: string;
}

const MODES = ["general", "help", "topic_exploration", "code_analysis", "text_analysis"] as const;
type Mode = (typeof MODES)[number];

const MODE_LABELS: Record<Mode, string> = {
  general: "ai.modeGeneral",
  help: "ai.modeHelp",
  topic_exploration: "ai.modeTopic",
  code_analysis: "ai.modeCode",
  text_analysis: "ai.modeText",
};

export function AiChatPanel() {
  const { t } = useI18n();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [mode, setMode] = useState<Mode>("general");
  const [prompts, setPrompts] = useState<AiPromptInfo[]>([]);
  const [promptId, setPromptId] = useState<string>("");
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

  const modePrompts = prompts.filter((p) => p.mode === mode);

  return (
    <div className="flex h-full min-h-0 flex-col bg-bg">
      {disabled && (
        <div className="flex shrink-0 items-center gap-2 border-b border-warning bg-warning/10 px-3 py-1.5 text-sm text-warning">
          <CircleAlert size={14} aria-hidden />
          <span>{welcomeMessage(false)}</span>
        </div>
      )}

      {/* Mode + prompt pickers */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-surface px-3 py-1.5">
        <label className="flex items-center gap-1.5 text-xs text-text-secondary">
          {t("ai.modeLabel")}
          <select
            value={mode}
            onChange={(e) => {
              setMode(e.target.value as Mode);
              setPromptId("");
            }}
            className="h-7 rounded-sm border border-border bg-bg px-1.5 text-xs outline-none focus:border-accent"
          >
            {MODES.map((m) => (
              <option key={m} value={m}>
                {t(MODE_LABELS[m])}
              </option>
            ))}
          </select>
        </label>
        {modePrompts.length > 0 && (
          <label className="flex items-center gap-1.5 text-xs text-text-secondary">
            {t("ai.promptLabel")}
            <select
              value={promptId}
              onChange={(e) => setPromptId(e.target.value)}
              className="h-7 max-w-52 rounded-sm border border-border bg-bg px-1.5 text-xs outline-none focus:border-accent"
            >
              <option value="">{t("ai.promptNone")}</option>
              {modePrompts.map((p) => (
                <option key={p.id} value={p.id} title={p.description}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

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
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
            placeholder={t("ai.chatPlaceholder")}
            aria-label={t("ai.messageAria")}
            disabled={disabled}
            className="min-h-0 flex-1 resize-none rounded-sm border border-border bg-bg px-2 py-1.5 text-sm outline-none focus:border-accent disabled:opacity-50"
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
          <button
            type="button"
            onClick={() => setMessages(status?.enabled ? [{ role: "assistant", text: welcomeMessage(true) }] : [])}
            aria-label={t("ai.clearAria")}
            title={t("ai.clearTitle")}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm border border-border bg-bg text-text-secondary hover:bg-surface-higher hover:text-text-primary"
          >
            <Eraser size={14} aria-hidden />
          </button>
        </div>
      </div>
    </div>
  );
}
