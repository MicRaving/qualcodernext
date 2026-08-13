/**
 * AiChatPanel — chat with the project AI assistant. The chat mode and
 * prompt-library selection live in the pane's top bar (AiView).
 *
 * Memo mode ("memo_analysis") shows a memo picker (file + code memos from
 * GET /memos) and sends the selection with the chat request. The "Paraphrase"
 * and "Sentiment" chips send the current input text with the matching
 * prompt-library id.
 */
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Eraser, LoaderCircle, Search, Send } from "lucide-react";
import {
  ApiError,
  api,
  fetchWithTimeout,
  initApiBase,
  type AiStatus,
} from "@/lib/api";
import { errorDetail, welcomeMessage } from "@/features/ai/format";
import { useI18n } from "@/lib/i18n";
import {
  ErrorBanner,
  IconButton,
  Input,
  SectionLabel,
  Textarea,
} from "@/components/ui/orchestrator";
import type { AiMode } from "@/features/ai/aiModes";

type ChatRole = "user" | "assistant" | "error";

interface ChatMessage {
  role: ChatRole;
  text: string;
}

interface MemoEntry {
  kind: "file" | "code";
  id: number;
  name: string;
  memo: string;
  date: string;
  owner: string;
}

const QUICK_ACTIONS = [
  { promptId: "paraphrase", labelKey: "ai.quickParaphrase" },
  { promptId: "sentiment", labelKey: "ai.quickSentiment" },
] as const;

/** Modes that attach memo context to the chat request. */
const MEMO_MODES: ReadonlySet<AiMode> = new Set([
  "memo_analysis",
  "code_analysis",
  "text_analysis",
]);

async function fetchMemos(): Promise<MemoEntry[]> {
  const base = await initApiBase();
  const res = await fetchWithTimeout(`${base}/memos`);
  if (!res.ok) throw new ApiError(res.status, `API error ${res.status} on /memos`);
  const body = (await res.json()) as { memos: MemoEntry[] };
  return body.memos;
}

async function chatWithMemos(opts: {
  message: string;
  mode: AiMode;
  promptId?: string;
  memoIds: number[];
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

function MemoPicker({
  memos,
  query,
  onQuery,
  selected,
  onToggle,
  onSelectAll,
  onDeselectAll,
}: {
  memos: MemoEntry[];
  query: string;
  onQuery: (q: string) => void;
  selected: Set<string>;
  onToggle: (key: string) => void;
  onSelectAll: (keys: string[]) => void;
  onDeselectAll: () => void;
}) {
  const { t } = useI18n();
  const q = query.trim().toLowerCase();
  const visible = useMemo(
    () =>
      memos.filter(
        (m) =>
          !q || m.name.toLowerCase().includes(q) || m.memo.toLowerCase().includes(q),
      ),
    [memos, q],
  );
  const groups = useMemo(
    () => [
      {
        kind: "file",
        label: t("ai.memosFile"),
        items: visible.filter((m) => m.kind === "file"),
      },
      {
        kind: "code",
        label: t("ai.memosCode"),
        items: visible.filter((m) => m.kind === "code"),
      },
    ],
    [visible, t],
  );
  const visibleKeys = useMemo(() => visible.map((m) => `${m.kind}:${m.id}`), [visible]);
  const allVisibleSelected =
    visibleKeys.length > 0 && visibleKeys.every((key) => selected.has(key));

  return (
    <div className="shrink-0 border-t border-border bg-surface px-3 py-2">
      <div className="mx-auto flex max-w-2xl flex-col gap-1.5">
        <div className="flex items-center justify-between gap-1.5">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-text-secondary">
            {t("ai.contextMemos")}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onSelectAll(visibleKeys)}
              disabled={visibleKeys.length === 0 || allVisibleSelected}
              className="text-[11px] text-accent hover:underline disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t("ai.selectAll")}
            </button>
            <button
              type="button"
              onClick={onDeselectAll}
              disabled={selected.size === 0}
              className="text-[11px] text-accent hover:underline disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t("ai.deselectAll")}
            </button>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <Search size={12} className="shrink-0 text-text-secondary" aria-hidden />
          <Input
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            placeholder={t("ai.memosSearch")}
            aria-label={t("ai.memosSearch")}
            className="h-7 min-w-0 flex-1 px-2 py-1 text-xs"
          />
          <span className="shrink-0 text-[10px] text-text-secondary">
            {t("ai.memosSelected", { count: selected.size })}
          </span>
        </div>
        <div className="qc-scroll max-h-40 overflow-y-auto rounded-sm border border-border bg-bg p-1">
          {memos.length === 0 ? (
            <p className="px-2 py-3 text-center text-xs text-text-secondary">
              {t("ai.memosEmpty")}
            </p>
          ) : (
            groups.map((group) =>
              group.items.length === 0 ? null : (
                <div key={group.kind}>
                  <SectionLabel>{group.label}</SectionLabel>
                  {group.items.map((m) => {
                    const key = `${m.kind}:${m.id}`;
                    return (
                      <label
                        key={key}
                        className="flex cursor-pointer items-center gap-1.5 rounded-sm px-1.5 py-0.5 text-xs hover:bg-surface-higher"
                        title={m.memo}
                      >
                        <input
                          type="checkbox"
                          checked={selected.has(key)}
                          onChange={() => onToggle(key)}
                          className="accent-accent"
                        />
                        <span className="truncate">{m.name}</span>
                      </label>
                    );
                  })}
                </div>
              ),
            )
          )}
        </div>
      </div>
    </div>
  );
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
  const [memos, setMemos] = useState<MemoEntry[] | null>(null);
  const [memoQuery, setMemoQuery] = useState("");
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
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
    if (mode !== "memo_analysis") return;
    let cancelled = false;
    setMemos(null);
    fetchMemos()
      .then((items) => {
        if (!cancelled) setMemos(items);
      })
      .catch(() => {
        if (!cancelled) setMemos([]);
      });
    return () => {
      cancelled = true;
    };
  }, [mode]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, waiting]);

  const disabled = !status?.enabled;

  const memoById = useMemo(
    () => new Map<string, MemoEntry>((memos ?? []).map((m) => [`${m.kind}:${m.id}`, m])),
    [memos],
  );
  const selectedMemoIds = useMemo(
    () =>
      Array.from(
        new Set(
          [...selectedKeys]
            .map((key) => memoById.get(key)?.id)
            .filter((id): id is number => id != null),
        ),
      ),
    [selectedKeys, memoById],
  );

  function toggleMemo(key: string) {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function selectAllMemos(keys: string[]) {
    if (keys.length === 0) return;
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      for (const key of keys) next.add(key);
      return next;
    });
  }

  function deselectAllMemos() {
    setSelectedKeys(new Set());
  }

  async function sendWith(promptOverride?: string) {
    const text = input.trim();
    if (!text || waiting || disabled) return;
    if (!promptOverride) setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setWaiting(true);
    try {
      const effectivePromptId = promptOverride ?? (promptId || undefined);
      const res = MEMO_MODES.has(mode)
        ? await chatWithMemos({
            message: text,
            mode,
            promptId: effectivePromptId,
            memoIds: selectedMemoIds,
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
    <div className="flex min-h-0 flex-1 flex-col bg-bg">
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

      {/* Memo picker (memo/code/text analysis modes) */}
      {MEMO_MODES.has(mode) && memos !== null && (
        <MemoPicker
          memos={memos}
          query={memoQuery}
          onQuery={setMemoQuery}
          selected={selectedKeys}
          onToggle={toggleMemo}
          onSelectAll={selectAllMemos}
          onDeselectAll={deselectAllMemos}
        />
      )}
      {MEMO_MODES.has(mode) && memos === null && (
        <p className="shrink-0 border-t border-border bg-surface px-3 py-1.5 text-center text-xs text-text-secondary">
          {t("ai.memosLoading")}
        </p>
      )}

      {/* Input row */}
      <div className="shrink-0 border-t border-border bg-surface p-3">
        <div className="mx-auto flex max-w-2xl flex-col gap-1.5">
          <div className="flex flex-wrap gap-1">
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
          <div className="flex items-end gap-2">
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
