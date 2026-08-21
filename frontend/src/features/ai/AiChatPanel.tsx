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
import { Check, ChevronDown, ChevronRight, LoaderCircle, Send, Wrench, X } from "lucide-react";
import { api, type AiPendingTool, type AiStatus, type AiToolCallEvent } from "@/lib/api";
import { describePendingTool, describeToolCall, errorDetail, welcomeMessage } from "@/features/ai/format";
import { useI18n } from "@/lib/i18n";
import { ErrorBanner, IconButton, Textarea } from "@/components/ui/orchestrator";
import { Markdown } from "@/components/ui/Markdown";
import { AI_MODE_LABELS, CONTEXT_PICKER_KINDS, deriveModeLabel } from "@/features/ai/aiModes";
import { ContextPickerArea } from "@/features/ai/ContextPickers";
import { useContextPickers } from "@/features/ai/contextPickerData";
import { useWorkspaceStore } from "@/stores/workspace";

interface McpTool {
  name: string;
  description: string;
}

type ChatRole = "user" | "assistant" | "error";

interface ChatMessage {
  role: ChatRole;
  text: string;
  /** Agentic chat: the MCP tools the model executed in this turn. */
  toolCalls?: AiToolCallEvent[];
}

function parseToolCalls(requestJson: string): AiToolCallEvent[] {
  if (!requestJson) return [];
  try {
    const parsed: unknown = JSON.parse(requestJson);
    const calls = (parsed as { tool_calls?: unknown } | null)?.tool_calls;
    return Array.isArray(calls) ? (calls as AiToolCallEvent[]) : [];
  } catch {
    return [];
  }
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
  const [agentic, setAgentic] = useState(true);
  const [confirmWrites, setConfirmWrites] = useState(true);
  const [configExpanded, setConfigExpanded] = useState(true);
  const [pending, setPending] = useState<{
    token: string;
    tools: AiPendingTool[];
    chatId?: number;
  } | null>(null);
  const [toolsOpen, setToolsOpen] = useState(true);
  const [mcpTools, setMcpTools] = useState<{
    read_tools: McpTool[];
    write_tools: McpTool[];
    write_enabled: boolean;
  } | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useAsyncEffect(async (signal) => {
    try {
      const res = await api.aiMcpTools();
      signal.throwIfAborted();
      setMcpTools(res);
    } catch {
      signal.throwIfAborted();
      setMcpTools(null);
    }
  }, []);

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
            toolCalls: parseToolCalls(m.request_json),
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

  async function updateMcpPermissions(value: string) {
    if (!status) return;
    setStatus((s) => (s ? { ...s, mcp_permissions: value } : s));
    try {
      const res = await api.aiSetMcpPermissions(value);
      setStatus((s) => (s ? { ...s, mcp_permissions: res.mcp_permissions } : s));
      const tools = await api.aiMcpTools();
      setMcpTools(tools);
    } catch {
      // Revert to the known value on failure by refetching.
      try {
        const s = await api.aiStatus();
        setStatus(s);
      } catch {
        /* leave the optimistic value; the next open refreshes it */
      }
    }
  }

  async function sendWith() {
    const text = input.trim();
    if (!text || waiting || disabled) return;
    setInput("");
    setPending(null);
    setMessages((m) => [...m, { role: "user", text }]);
    setWaiting(true);
    try {
      const res = await api.aiChat(
        text,
        "",
        "auto",
        promptId || undefined,
        {
          memoIds: kinds.includes("memos") ? pickers.selectedMemoIds : undefined,
          codeIds: kinds.includes("codes") ? pickers.selectedCodeIds : undefined,
          sourceIds: kinds.includes("files") ? pickers.selectedSourceIds : undefined,
          chatId: chatId ?? undefined,
        },
        agentic,
        confirmWrites,
      );
      if (res.chat_id != null && res.chat_id !== chatId) {
        setLoadedChatId(res.chat_id);
        onChatId?.(res.chat_id);
      }
      if (res.status === "awaiting_approval" && res.token && res.pending_tools) {
        setPending({ token: res.token, tools: res.pending_tools, chatId: res.chat_id });
        return;
      }
      setMessages((m) => [
        ...m,
        { role: "assistant", text: res.reply, toolCalls: res.tool_calls ?? [] },
      ]);
    } catch (e) {
      setMessages((m) => [...m, { role: "error", text: errorDetail(e) }]);
    } finally {
      setWaiting(false);
    }
  }

  async function handleApprove(approve: boolean) {
    if (!pending) return;
    const p = pending;
    setPending(null);
    setWaiting(true);
    try {
      const res = await api.aiChatApprove(p.token, approve, p.chatId);
      if (res.chat_id != null && res.chat_id !== chatId) {
        setLoadedChatId(res.chat_id);
        onChatId?.(res.chat_id);
      }
      setMessages((m) => [
        ...m,
        { role: "assistant", text: res.reply, toolCalls: res.tool_calls ?? [] },
      ]);
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
      {disabled && (
        <button
          type="button"
          onClick={() => useWorkspaceStore.getState().setRightPane("settings")}
          title={t("ai.openSettingsTitle")}
          className="block w-full text-left"
        >
          <ErrorBanner tone="warning">{welcomeMessage(false)}</ErrorBanner>
        </button>
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
                  {m.toolCalls && m.toolCalls.length > 0 && (
                    <div className="mb-1.5 flex min-w-0 flex-col gap-1">
                      <span className="text-[10px] font-semibold uppercase tracking-wide text-text-secondary">
                        {t("ai.toolsRan")}
                      </span>
                      {m.toolCalls.map((tc, j) => (
                        <div
                          key={j}
                          className="flex min-w-0 items-center gap-1.5 rounded-sm border border-border bg-bg px-2 py-1 text-xs"
                        >
                          <Wrench size={12} className="shrink-0 text-text-secondary" aria-hidden />
                          <span className="min-w-0 flex-1 break-words">{describeToolCall(tc)}</span>
                          {tc.approved === true && (
                            <span className="flex shrink-0 items-center gap-1 text-success">
                              <Check size={12} aria-hidden />
                              {t("ai.toolsApprovedTag")}
                            </span>
                          )}
                          {tc.approved === false && (
                            <span className="flex shrink-0 items-center gap-1 text-danger">
                              <X size={12} aria-hidden />
                              {t("ai.toolsRejectedTag")}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  <Markdown text={m.text} size="sm" />
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

      {/* Context data config — collapsible via the arrow in its header */}
      {kinds.length > 0 && (
        <div className="min-w-0 shrink-0">
          <button
            type="button"
            onClick={() => setConfigExpanded((v) => !v)}
            aria-expanded={configExpanded}
            title={configExpanded ? t("ai.contextCollapse") : t("ai.contextExpand")}
            className="flex w-full min-w-0 items-center gap-1.5 px-3 py-1.5 text-left hover:bg-surface-higher"
          >
            {configExpanded ? (
              <ChevronDown size={12} className="shrink-0 text-text-secondary" aria-hidden />
            ) : (
              <ChevronRight size={12} className="shrink-0 text-text-secondary" aria-hidden />
            )}
            <span className="text-[10px] font-semibold uppercase tracking-wide text-text-secondary">
              {t("ai.modeLabel")}
            </span>
            <span className="normal-case text-[10px] font-normal text-text-secondary">
              {t(AI_MODE_LABELS[modeLabelKey])}
            </span>
          </button>
          {configExpanded && <ContextPickerArea pickers={pickers} />}
        </div>
      )}

      {/* Pending write approval (agentic chat paused) */}
      {pending && (
        <div className="min-w-0 shrink-0 border-t border-border bg-surface p-3">
          <div className="mx-auto flex w-full max-w-2xl flex-col gap-2">
            <p className="text-xs font-semibold text-text-secondary">
              {t("ai.toolsPendingTitle")}
            </p>
            <ul className="flex flex-col gap-1">
              {pending.tools.map((tool, j) => (
                <li
                  key={j}
                  className="flex min-w-0 items-center gap-1.5 rounded-sm border border-border bg-bg px-2 py-1 text-xs"
                >
                  <Wrench size={12} className="shrink-0 text-text-secondary" aria-hidden />
                  <span className="min-w-0 flex-1 break-words">
                    {describePendingTool(tool)}
                  </span>
                </li>
              ))}
            </ul>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => void handleApprove(true)}
                disabled={waiting}
                className="flex h-7 items-center gap-1 rounded-sm bg-accent px-2.5 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Check size={12} aria-hidden />
                {t("ai.toolsApprove")}
              </button>
              <button
                type="button"
                onClick={() => void handleApprove(false)}
                disabled={waiting}
                className="flex h-7 items-center gap-1 rounded-sm border border-border bg-bg px-2.5 text-xs text-text-secondary hover:bg-surface-higher disabled:cursor-not-allowed disabled:opacity-50"
              >
                <X size={12} aria-hidden />
                {t("ai.toolsReject")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tools & permissions — MCP tool list + access level */}
      {!disabled && (
        <div className="min-w-0 shrink-0">
          <div className="flex items-center gap-1.5 border-t border-border px-3 py-1.5">
            <button
              type="button"
              onClick={() => setToolsOpen((v) => !v)}
              aria-expanded={toolsOpen}
              className="flex min-w-0 flex-1 items-center gap-1.5 text-left hover:bg-surface-higher"
            >
              {toolsOpen ? (
                <ChevronDown size={12} className="shrink-0 text-text-secondary" aria-hidden />
              ) : (
                <ChevronRight size={12} className="shrink-0 text-text-secondary" aria-hidden />
              )}
              <span className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-text-secondary">
                <Wrench size={11} aria-hidden />
                {t("ai.toolsTitle")}
              </span>
            </button>
            {status?.mcp_mode === "external" ? (
              <span className="shrink-0 rounded-sm bg-accent/10 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
                {t("ai.mcpExternal")}
              </span>
            ) : (
              <label className="flex shrink-0 items-center gap-1 text-[11px] text-text-secondary">
                <span>{t("ai.mcpPermissions")}</span>
                <select
                  value={status?.mcp_permissions ?? "read"}
                  onChange={(e) => void updateMcpPermissions(e.target.value)}
                  aria-label={t("ai.mcpPermissions")}
                  className="h-6 rounded-sm border border-border bg-bg px-1 text-[11px] text-text-secondary focus:border-accent focus:outline-none"
                >
                  <option value="read">{t("ai.mcpRead")}</option>
                  <option value="write">{t("ai.mcpWrite")}</option>
                  <option value="full">{t("ai.mcpFull")}</option>
                </select>
              </label>
            )}
          </div>
          {toolsOpen && mcpTools && (
            <div className="max-h-40 overflow-y-auto border-t border-border px-3 py-1.5">
              <p className="text-[10px] font-medium uppercase tracking-wide text-text-secondary">
                {t("ai.toolsReadTitle")}
              </p>
              <ul className="mt-0.5 space-y-0.5">
                {mcpTools.read_tools.map((tool) => (
                  <li key={tool.name} className="flex items-baseline gap-1.5 text-[11px] leading-snug">
                    <span className="shrink-0 font-medium text-text-primary">{tool.name}</span>
                    <span className="min-w-0 truncate text-text-secondary" title={tool.description}>
                      {tool.description}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-1.5 flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-text-secondary">
                <span className={mcpTools.write_enabled ? "" : "text-text-secondary/60"}>
                  {t("ai.toolsWriteTitle")}
                </span>
                {!mcpTools.write_enabled && (
                  <span className="normal-case font-normal text-warning">{t("ai.toolsWriteLocked")}</span>
                )}
              </p>
              <ul className="mt-0.5 space-y-0.5">
                {mcpTools.write_tools.map((tool) => (
                  <li
                    key={tool.name}
                    className={`flex items-baseline gap-1.5 text-[11px] leading-snug ${
                      mcpTools.write_enabled ? "" : "opacity-50"
                    }`}
                  >
                    <span className="shrink-0 font-medium text-text-primary">{tool.name}</span>
                    <span className="min-w-0 truncate text-text-secondary" title={tool.description}>
                      {tool.description}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Input row */}
      <div className="min-w-0 shrink-0 border-t border-border bg-surface p-3">
        <div className="mx-auto flex min-w-0 w-full max-w-2xl flex-col gap-1.5">
          <div className="flex min-w-0 items-center gap-3 text-[11px] text-text-secondary">
            <label className="flex items-center gap-1.5" title={t("ai.agenticTitle")}>
              <input
                type="checkbox"
                checked={agentic}
                onChange={(e) => setAgentic(e.target.checked)}
                disabled={disabled}
                className="accent-accent"
              />
              {t("ai.agenticToggle")}
            </label>
            <label className="flex items-center gap-1.5" title={t("ai.confirmWritesTitle")}>
              <input
                type="checkbox"
                checked={confirmWrites}
                onChange={(e) => setConfirmWrites(e.target.checked)}
                disabled={disabled || !agentic}
                className="accent-accent"
              />
              {t("ai.confirmWritesToggle")}
            </label>
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