/**
 * AiSearchPanel — semantic search over project text sources, shown when the
 * "Semantic search" mode is active. Mirrors the chat composer layout: the
 * results scroll in the flex area on top, the context pickers and the query
 * input are pinned at the bottom; the selected files restrict the search to
 * those sources.
 */
import { useEffect, useState, type FormEvent } from "react";
import { CircleAlert, LoaderCircle, Search } from "lucide-react";
import {
  ApiError,
  api,
  fetchWithTimeout,
  initApiBase,
  type AiIndexStatus,
  type AiSearchResult,
  type AiStatus,
} from "@/lib/api";
import { errorDetail, formatScore, welcomeMessage } from "@/features/ai/format";
import { Button, ErrorBanner, Input } from "@/components/ui/orchestrator";
import { useProjectStore } from "@/stores/project";
import { useI18n } from "@/lib/i18n";
import { ContextPickerArea } from "@/features/ai/ContextPickers";
import { useContextPickers } from "@/features/ai/contextPickerData";
type SearchState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; detail: string }
  | { kind: "done"; results: AiSearchResult[] };

async function runSearch(
  query: string,
  sourceIds: number[],
): Promise<{ results: AiSearchResult[]; indexed?: boolean }> {
  const base = await initApiBase();
  const res = await fetchWithTimeout(`${base}/ai/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      limit: 10,
      source_ids: sourceIds.length > 0 ? sourceIds : undefined,
    }),
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, `API error ${res.status} on /ai/search`, detail);
  }
  return (await res.json()) as { results: AiSearchResult[]; indexed?: boolean };
}

export function AiSearchPanel() {
  const { t } = useI18n();
  const pickers = useContextPickers("search");
  const [query, setQuery] = useState("");
  const [state, setState] = useState<SearchState>({ kind: "idle" });
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [index, setIndex] = useState<AiIndexStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .aiStatus()
      .then((s) => {
        if (!cancelled) setStatus(s);
      })
      .catch(() => {
        if (!cancelled) setStatus(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .aiIndexStatus()
      .then((s) => {
        if (!cancelled) setIndex(s);
      })
      .catch(() => {
        if (!cancelled) setIndex(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const disabled = !status?.enabled;

  async function handleSearch(e: FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q || disabled || state.kind === "loading") return;
    setState({ kind: "loading" });
    try {
      const res = await runSearch(q, pickers.selectedSourceIds);
      setState({ kind: "done", results: res.results });
    } catch (err) {
      setState({ kind: "error", detail: errorDetail(err) });
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-bg">
      {disabled && (
        <ErrorBanner tone="warning">{welcomeMessage(false)}</ErrorBanner>
      )}

      {/* Results (scroll above the pinned input) */}
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <div className="mx-auto max-w-2xl">
          {state.kind === "idle" && (
            <p className="py-6 text-center text-xs text-text-secondary">
              {t("ai.searchHint")}
            </p>
          )}
          {state.kind === "error" && (
            <div className="flex items-center gap-2 rounded-lg border border-danger bg-danger/10 px-3 py-2 text-sm text-danger">
              <CircleAlert size={14} aria-hidden />
              <span className="min-w-0 flex-1">{state.detail}</span>
            </div>
          )}
          {state.kind === "done" && state.results.length === 0 && (
            <p className="py-6 text-center text-xs text-text-secondary">{t("ai.noResults")}</p>
          )}
          {state.kind === "done" && state.results.length > 0 && (
            <ul className="space-y-2">
              {state.results.map((r) => (
                <li key={`${r.source_id}-${r.text.slice(0, 40)}`}>
                  <button
                    type="button"
                    onClick={() =>
                      useProjectStore
                        .getState()
                        .setView({ kind: "coding", sourceId: r.source_id })
                    }
                    className="block w-full rounded-lg border border-border bg-surface p-3 text-left hover:border-accent"
                    title={t("ai.openSourceTitle")}
                  >
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm font-medium text-text-primary">
                        {r.file_name}
                      </span>
                      <span className="shrink-0 text-xs text-text-secondary">
                        {formatScore(r.score)}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-3 text-sm text-text-secondary">{r.text}</p>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {index && (
            <p className="mt-3 text-center text-[10px] text-text-secondary">
              {index.indexed
                ? t("ai.indexStatusReady", { chunks: index.chunks, model: index.model })
                : t("ai.indexStatusNone")}
            </p>
          )}
        </div>
      </div>

      {/* Context pickers: the selected files restrict the search */}
      <ContextPickerArea pickers={pickers} initialKind="files" />

      {/* Query input (pinned at the bottom, like the chat composer) */}
      <form
        onSubmit={(e) => void handleSearch(e)}
        className="min-w-0 shrink-0 border-t border-border bg-surface p-3"
      >
        <div className="mx-auto flex max-w-2xl items-center gap-2">
          <Input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("ai.searchPlaceholder")}
            aria-label={t("ai.searchQueryAria")}
            disabled={disabled}
            className="min-w-0 flex-1"
          />
          <Button
            variant="primary"
            type="submit"
            disabled={disabled || query.trim() === "" || state.kind === "loading"}
            icon={
              state.kind === "loading" ? (
                <LoaderCircle size={14} className="animate-spin" aria-hidden />
              ) : (
                <Search size={14} aria-hidden />
              )
            }
          >
            {t("ai.searchButton")}
          </Button>
        </div>
      </form>
    </div>
  );
}
