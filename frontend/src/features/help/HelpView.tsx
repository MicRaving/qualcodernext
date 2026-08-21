/**
 * HelpView — the in-app help bar as a toggleable right-bar pane.
 *
 * Two modes: Browse (bundled markdown docs with a regex-capable search) and
 * Ask AI (single-turn Q&A through the "help" chat mode — needs an open
 * project with AI enabled). The docs ship with the packaged app and work
 * offline.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, BookOpen, Bug, LoaderCircle, Send, Sparkles, X } from "lucide-react";
import { api, type AiStatus, type HelpSearchResult, type HelpTopic, type HelpTopicDetail } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { errorMessage } from "@/lib/utils";
import { Markdown } from "@/components/ui/Markdown";
import { BarHeader, EmptyState, ErrorBanner, IconButton, Input, LeftBar, Textarea } from "@/components/ui/orchestrator";
import { useProjectStore } from "@/stores/project";

type Mode = "browse" | "ask";

type ChatMsg = { role: "user" | "assistant" | "error"; text: string };

/** Highlight the matched span of a help search snippet (like the flyout). */
function HighlightedSnippet({
  snippet,
  rel0,
  rel1,
}: {
  snippet: string;
  rel0?: number;
  rel1?: number;
}) {
  const a = Math.max(0, Math.min(rel0 ?? 0, snippet.length));
  const b = Math.max(a, Math.min(rel1 ?? 0, snippet.length));
  if (a === b) return <>{snippet}</>;
  return (
    <>
      {snippet.slice(0, a)}
      <mark className="rounded-sm bg-accent/30 px-px text-text-primary">
        {snippet.slice(a, b)}
      </mark>
      {snippet.slice(b)}
    </>
  );
}

export function HelpView() {
  const { t } = useI18n();
  const projectOpen = useProjectStore((s) => s.projectOpen);
  const [mode, setMode] = useState<Mode>("browse");
  const [query, setQuery] = useState("");
  const [topics, setTopics] = useState<HelpTopic[]>([]);
  const [results, setResults] = useState<HelpSearchResult[] | null>(null);
  const [detail, setDetail] = useState<HelpTopicDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<number | undefined>(undefined);

  const [status, setStatus] = useState<AiStatus | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [askInput, setAskInput] = useState("");
  const [waiting, setWaiting] = useState(false);

  useEffect(() => {
    void api.helpTopics().then((res) => setTopics(res.topics)).catch(() => {});
  }, []);

  // Debounce the doc search; an empty query shows the topic list again.
  // The query is treated as a regular expression natively (no toggle).
  useEffect(() => {
    window.clearTimeout(timerRef.current);
    const q = query.trim();
    if (!q) {
      setResults(null);
      setError(null);
      return;
    }
    timerRef.current = window.setTimeout(() => {
      setBusy(true);
      void api
        .helpSearch(q, true)
        .then((res) => {
          setResults(res.results);
          setError(null);
        })
        .catch((e) => setError(errorMessage(e)))
        .finally(() => setBusy(false));
    }, 250);
    return () => window.clearTimeout(timerRef.current);
  }, [query]);

  const openTopic = useCallback(async (id: string) => {
    try {
      const res = await api.helpTopic(id);
      setDetail(res.topic);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  async function ask() {
    const text = askInput.trim();
    if (!text || waiting) return;
    setAskInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setWaiting(true);
    try {
      const res = await api.aiChat(text, "", "help");
      setMessages((m) => [...m, { role: "assistant", text: res.reply }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "error", text: errorMessage(e) }]);
    } finally {
      setWaiting(false);
    }
  }

  useEffect(() => {
    if (mode !== "ask") return;
    api.aiStatus().then(setStatus).catch(() => setStatus(null));
  }, [mode]);

  const aiDisabled = !projectOpen || !status?.enabled;

  return (
    <LeftBar
      borderSide="l"
      scroll={false}
      className="h-full min-h-0 max-w-full"
      header={
        <BarHeader
          title={t("nav.help")}
          actions={
            <IconButton
              label={t("nav.bugReport")}
              title={t("nav.bugReport")}
              onClick={() => void useProjectStore.getState().openBugReport()}
            >
              <Bug size={14} aria-hidden />
            </IconButton>
          }
        />
      }
    >
      {/* The pane is its own flex column (scroll={false}) so only the content
          area scrolls — the mode bar and search row stay fixed and the
          scrollbar never extends over them. */}
      <div className="flex min-h-0 flex-1 flex-col">
        {/* Mode switch */}
        <div className="flex shrink-0 border-b border-border">
          {(["browse", "ask"] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              aria-pressed={mode === m}
              className={`flex flex-1 items-center justify-center gap-1.5 px-2 py-1.5 text-xs font-medium ${
                mode === m ? "bg-surface-higher text-accent" : "text-text-secondary hover:bg-surface-higher"
              }`}
            >
              {m === "browse" ? <BookOpen size={14} aria-hidden /> : <Sparkles size={14} aria-hidden />}
              {m === "browse" ? t("help.browseMode") : t("help.askMode")}
            </button>
          ))}
        </div>

        {mode === "browse" ? (
          <>
            {/* Search row (regex is native — no toggle button) */}
            <div className="flex shrink-0 items-center gap-2 border-b border-border p-2">
              <div className="relative min-w-0 flex-1">
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t("help.searchPlaceholder")}
                  aria-label={t("help.searchPlaceholder")}
                  className="w-full px-2 py-1 pr-7 text-xs"
                />
                {query !== "" && (
                  <button
                    type="button"
                    onClick={() => {
                      setQuery("");
                      setDetail(null);
                    }}
                    aria-label={t("search.clear")}
                    title={t("search.clear")}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-sm p-0.5 text-text-secondary hover:bg-surface-higher hover:text-text-primary"
                  >
                    <X size={13} aria-hidden />
                  </button>
                )}
              </div>
              {busy && <span className="h-3 w-3 shrink-0 animate-spin rounded-full border border-b-transparent border-accent" />}
            </div>

            <div className="qc-scroll min-h-0 flex-1 overflow-y-auto">
              {error ? (
                <div className="p-3 text-xs text-danger">{error}</div>
              ) : detail ? (
                <div className="space-y-1 p-3">
                  <button
                    type="button"
                    onClick={() => setDetail(null)}
                    className="mb-2 flex items-center gap-1 text-xs text-text-secondary hover:text-text-primary"
                  >
                    <ArrowLeft size={13} aria-hidden />
                    {t("help.back")}
                  </button>
                  <Markdown text={detail.content} />
                </div>
              ) : results ? (
                results.length === 0 ? (
                  <EmptyState>{t("help.noResults")}</EmptyState>
                ) : (
                  <ul className="divide-y divide-border">
                    {results.map((r) => (
                      <li key={r.id}>
                        <button
                          type="button"
                          onClick={() => void openTopic(r.id)}
                          className="block w-full px-3 py-2 text-left hover:bg-surface-higher"
                        >
                          <span className="block truncate text-sm font-medium text-text-primary">{r.title}</span>
                          <span className="mt-0.5 block line-clamp-2 break-words whitespace-pre-wrap text-xs text-text-secondary">
                            <HighlightedSnippet snippet={r.snippet} rel0={r.rel0} rel1={r.rel1} />
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )
              ) : (
                <ul className="divide-y divide-border">
                  {topics.map((tp) => (
                    <li key={tp.id}>
                      <button
                        type="button"
                        onClick={() => void openTopic(tp.id)}
                        className="block w-full px-3 py-2 text-left hover:bg-surface-higher"
                      >
                        <span className="block truncate text-sm font-medium text-text-primary">{tp.title}</span>
                        {tp.description && (
                          <span className="mt-0.5 block line-clamp-2 text-xs text-text-secondary">{tp.description}</span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </>
        ) : (
          <>
            {!projectOpen && <ErrorBanner tone="warning">{t("help.askNoProject")}</ErrorBanner>}
            {projectOpen && !status?.enabled && <ErrorBanner tone="warning">{t("help.askAiDisabled")}</ErrorBanner>}
            {!aiDisabled && <p className="shrink-0 px-3 pt-2 text-xs text-text-secondary">{t("help.askHint")}</p>}
            <div className="qc-scroll min-h-0 flex-1 overflow-y-auto p-3">
              <div className="flex flex-col gap-2">
                {messages.map((m, i) =>
                  m.role === "user" ? (
                    <div key={i} className="flex justify-end">
                      <div className="max-w-[85%] break-words rounded-lg bg-accent px-3 py-1.5 text-sm text-[var(--qc-bg)]">
                        {m.text}
                      </div>
                    </div>
                  ) : m.role === "error" ? (
                    <div key={i} className="flex justify-start">
                      <div className="max-w-[85%] break-words rounded-lg border border-danger bg-danger/10 px-3 py-1.5 text-sm text-danger">
                        {m.text}
                      </div>
                    </div>
                  ) : (
                    <div key={i} className="flex justify-start">
                      <div className="max-w-[85%] break-words rounded-lg bg-surface px-3 py-1.5 text-sm text-text-primary">
                        {m.text}
                      </div>
                    </div>
                  ),
                )}
                {waiting && (
                  <div className="flex items-center gap-2 text-xs text-text-secondary">
                    <LoaderCircle size={14} className="animate-spin" aria-hidden />
                    {t("help.thinking")}
                  </div>
                )}
              </div>
            </div>
            <div className="flex shrink-0 items-end gap-2 border-t border-border p-3">
              <Textarea
                value={askInput}
                onChange={(e) => setAskInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void ask();
                  }
                }}
                rows={2}
                placeholder={t("help.askPlaceholder")}
                aria-label={t("help.askPlaceholder")}
                disabled={aiDisabled}
                className="min-h-0 min-w-0 flex-1 resize-none px-2 py-1.5"
              />
              <button
                type="button"
                onClick={() => void ask()}
                disabled={aiDisabled || waiting || askInput.trim() === ""}
                aria-label={t("help.send")}
                title={t("help.send")}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm bg-accent text-[var(--qc-bg)] hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Send size={14} aria-hidden />
              </button>
            </div>
          </>
        )}
      </div>
    </LeftBar>
  );
}
