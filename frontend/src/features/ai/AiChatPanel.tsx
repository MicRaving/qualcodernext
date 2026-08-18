/**
 * AiChatPanel — chat with the project AI assistant. The instruction picker
 * and the chat-history control live in the pane's top bar (AiView).
 *
 * The conversation is persisted in the project database: the panel loads
 * the messages of the selected chat session from the backend and appends
 * every new exchange to it. The mode is auto-derived by the backend from
 * the context picker selections ("auto"), so all three pickers are always
 * shown; the read-only mode badge mirrors the derivation client-side.
 */
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useAsyncEffect } from "@/lib/useAsync";
import { LoaderCircle, Send } from "lucide-react";
import { api, type AiStatus } from "@/lib/api";
import { errorDetail, welcomeMessage } from "@/features/ai/format";
import { useI18n } from "@/lib/i18n";
import { ErrorBanner, IconButton, Textarea } from "@/components/ui/orchestrator";
import { AI_MODE_LABELS, CONTEXT_PICKER_KINDS, deriveModeLabel } from "@/features/ai/aiModes";
import { ContextPickerArea } from "@/features/ai/ContextPickers";
import { useContextPickers } from "@/features/ai/contextPickerData";

type ChatRole = "user" | "assistant" | "error";

interface ChatMessage {
  role: ChatRole;
  text: string;
}

export function AiChatPanel({
  chatId,
  promptId,
  onChatId,
}: {
  /** The open chat session (null = a fresh, unsaved conversation). */
  chatId: number | null;
  /** Selected instruction template id ("" = backend default). */
  promptId: string;
  /** Called when the backend creates/opens a chat session for a turn. */
  onChatId?: (chatId: number) => void;
}) {
  const { t } = useI18n();
  const pickers = useContextPickers();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [loadedChatId, setLoadedChatId] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useAsyncEffect(async (signal) => {
    try {
      const s = await api.aiStatus();
      signal.throwIfAborted();
      setStatus(s);
    } catch {
      signal.throwIfAborted();
      setStatus(null);
    }
  }, []);

  // Load the messages of the selected chat session from the backend.
  useAsyncEffect(
    async (signal) => {
      if (chatId === null) {
        setMessages([]);
        setLoadedChatId(null);
        return;
      }
      if (chatId === loadedChatId) return;
      try {
        const detail = await api.aiChatGet(chatId);
        signal.throwIfAborted();
        setMessages(
          detail.messages.map((m) => ({
            role: m.role === "user" ? "user" : "assistant",
            text: m.text,
          })),
        );
        setLoadedChatId(chatId);
      } catch {
        signal.throwIfAborted();
        setMessages([]);
      }
    },
    [chatId],
  );

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, waiting]);

  const disabled = !status?.enabled;
  const kinds = useMemo(() => CONTEXT_PICKER_KINDS, []);
  const modeLabelKey = deriveModeLabel({
    memoIds: pickers.selectedMemoIds,
    codeIds: pickers.selectedCodeIds,
    sourceIds: pickers.selectedSourceIds,
  });

  async function sendWith() {
    const text = input.trim();
    if (!text || waiting || disabled) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setWaiting(true);
    try {
      const res = await api.aiChat(text, "", "auto", promptId || undefined, {
        memoIds: kinds.includes("memos") ? pickers.selectedMemoIds : undefined,
        codeIds: kinds.includes("codes") ? pickers.selectedCodeIds : undefined,
        sourceIds: kinds.includes("files") ? pickers.selectedSourceIds : undefined,
        chatId: chatId ?? undefined,
      });
      if (res.chat_id != null && res.chat_id !== chatId) {
        setLoadedChatId(res.chat_id);
        onChatId?.(res.chat_id);
      }
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
      void sendWith();
    }
  }

  const showWelcome = messages.length === 0 && !waiting;

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-bg">
      {disabled && <ErrorBanner tone="warning">{welcomeMessage(false)}</ErrorBanner>}

      {/* Messages */}
      <div ref={scrollRef} className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto p-3">
        <div className="mx-auto flex min-w-0 w-full max-w-2xl flex-col gap-2">
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="flex min-w-0 justify-end">
                <div className="max-w-[80%] min-w-0 break-words rounded-lg bg-accent px-3 py-1.5 text-sm text-[var(--qc-bg)]">
                  {m.text}
                </div>
              </div>
            ) : m.role === "error" ? (
              <div key={i} className="flex min-w-0 justify-start">
                <div className="max-w-[80%] min-w-0 break-words rounded-lg border border-danger bg-danger/10 px-3 py-1.5 text-sm text-danger">
                  {m.text}
                </div>
              </div>
            ) : (
              <div key={i} className="flex min-w-0 justify-start">
                <div className="max-w-[80%] min-w-0 break-words rounded-lg bg-surface px-3 py-1.5 text-sm">
                  <span className="mb-0.5 block text-xs font-medium text-text-secondary">
                    {t("ai.assistantLabel")}
                  </span>
                  {m.text}
                </div>
              </div>
            ),
          )}
          {waiting && (
            <div className="flex min-w-0 justify-start">
              <div className="flex min-w-0 items-center gap-2 rounded-lg bg-surface px-3 py-1.5 text-sm text-text-secondary">
                <LoaderCircle size={14} className="animate-spin" aria-hidden />
                {t("ai.thinking")}
              </div>
            </div>
          )}
          {showWelcome && (
            <p className="py-4 text-center text-xs text-text-secondary">
              {t("ai.welcomeReady")}
            </p>
          )}
        </div>
      </div>

      {/* Context pickers (additive: memos / codes / files) */}
      {kinds.length > 0 && (
        <div className="min-w-0 shrink-0">
          <p className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-text-secondary">
            {t("ai.modeLabel")}{" "}
            <span className="normal-case font-normal">{t(AI_MODE_LABELS[modeLabelKey])}</span>
          </p>
          <ContextPickerArea pickers={pickers} />
        </div>
      )}

      {/* Input row */}
      <div className="min-w-0 shrink-0 border-t border-border bg-surface p-3">
        <div className="mx-auto flex min-w-0 w-full max-w-2xl flex-col gap-1.5">
          <div className="flex min-w-0 items-end gap-2">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={2}
              placeholder={t("ai.chatPlaceholder")}
              aria-label={t("ai.messageAria")}
              disabled={disabled}
              className="min-h-0 min-w-0 flex-1 resize-none px-2 py-1.5"
            />
            <button
              type="button"
              onClick={() => void sendWith()}
              disabled={disabled || waiting || input.trim() === ""}
              aria-label={t("ai.sendAria")}
              title={t("ai.sendTitle")}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm bg-accent text-[var(--qc-bg)] hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Send size={14} aria-hidden />
            </button>
            {chatId === null && (
              <IconButton
                label={t("ai.clearAria")}
                title={t("ai.clearTitle")}
                className="h-8 w-8 border border-border bg-bg"
                onClick={() => setMessages([])}
              >
                <span aria-hidden>×</span>
              </IconButton>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}