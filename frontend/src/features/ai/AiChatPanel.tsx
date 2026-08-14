/**
 * AiChatPanel — chat with the project AI assistant. The chat mode and
 * prompt-library selection live in the pane's top bar (AiView).
 *
 * Each analysis mode shows the matching context picker below the thread
 * (memos for memo analysis, codes for code analysis, files for text
 * analysis, all three for topic exploration) and sends the selection with
 * the chat request. The "Paraphrase" and "Sentiment" chips send the current
 * input text with the matching prompt-library id.
 */
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Eraser, LoaderCircle, Send } from "lucide-react";
import { ApiError, api, fetchWithTimeout, initApiBase, type AiStatus } from "@/lib/api";
import { errorDetail, welcomeMessage } from "@/features/ai/format";
import { useI18n } from "@/lib/i18n";
import { ErrorBanner, IconButton, Textarea } from "@/components/ui/orchestrator";
import { CONTEXT_PICKER_KINDS, type AiMode } from "@/features/ai/aiModes";
import { ContextPickerArea } from "@/features/ai/ContextPickers";
import { useContextPickers } from "@/features/ai/contextPickerData";

type ChatRole = "user" | "assistant" | "error";

interface ChatMessage {
  role: ChatRole;
  text: string;
}

const QUICK_ACTIONS = [
  { promptId: "paraphrase", labelKey: "ai.quickParaphrase" },
  { promptId: "sentiment", labelKey: "ai.quickSentiment" },
] as const;

async function chatWithContext(opts: {
  message: string;
  mode: AiMode;
  promptId?: string;
  memoIds?: number[];
  codeIds?: number[];
  sourceIds?: number[];
}): Promise<{ reply: string }> {
  const base = await initApiBase();
  const res = await fetchWithTimeout(`${base}/ai/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: opts.message,
      context: "",
      mode: opts.mode,
      prompt_id: opts.promptId,
      memo_ids: opts.memoIds,
      code_ids: opts.codeIds,
      source_ids: opts.sourceIds,
    }),
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, `API error ${res.status} on /ai/chat`, detail);
  }
  return (await res.json()) as { reply: string };
}

export function AiChatPanel({
  mode,
  promptId,
}: {
  mode: AiMode;
  promptId: string;
}) {
  const { t } = useI18n();
  const pickers = useContextPickers(mode);
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

  const kinds = useMemo(
    () => CONTEXT_PICKER_KINDS.filter((k) => pickers.required[k]),
    [pickers.required],
  );

  async function sendWith(promptOverride?: string) {
    const text = input.trim();
    if (!text || waiting || disabled) return;
    if (!promptOverride) setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setWaiting(true);
    try {
      const effectivePromptId = promptOverride ?? (promptId || undefined);
      const res =
        kinds.length > 0
          ? await chatWithContext({
              message: text,
              mode,
              promptId: effectivePromptId,
              memoIds: kinds.includes("memos") ? pickers.selectedMemoIds : undefined,
              codeIds: kinds.includes("codes") ? pickers.selectedCodeIds : undefined,
              sourceIds: kinds.includes("files") ? pickers.selectedSourceIds : undefined,
            })
          : await api.aiChat(text, "", mode, effectivePromptId);
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

  const chipsDisabled = disabled || waiting || input.trim() === "";

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-bg">
      {disabled && (
        <ErrorBanner tone="warning">{welcomeMessage(false)}</ErrorBanner>
      )}

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
          {messages.length === 0 && !waiting && (
            <p className="py-4 text-center text-xs text-text-secondary">{t("ai.noMessages")}</p>
          )}
        </div>
      </div>

      {/* Context picker (per mode: memos / codes / files) */}
      {kinds.length > 0 && <ContextPickerArea pickers={pickers} />}

      {/* Input row */}
      <div className="min-w-0 shrink-0 border-t border-border bg-surface p-3">
        <div className="mx-auto flex min-w-0 w-full max-w-2xl flex-col gap-1.5">
          <div className="flex min-w-0 flex-wrap gap-1">
            {QUICK_ACTIONS.map((action) => (
              <button
                key={action.promptId}
                type="button"
                onClick={() => void sendWith(action.promptId)}
                disabled={chipsDisabled}
                className="rounded-full border border-border bg-bg px-2 py-0.5 text-[11px] text-text-secondary hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t(action.labelKey)}
              </button>
            ))}
          </div>
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
    </div>
  );
}
