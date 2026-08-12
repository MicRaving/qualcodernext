/**
 * AiSearchPanel — semantic search over project text sources.
 */
import { useEffect, useState, type FormEvent } from "react";
import { CircleAlert, LoaderCircle, Search } from "lucide-react";
import { api, type AiSearchResult, type AiStatus } from "@/lib/api";
import { errorDetail, formatScore, welcomeMessage } from "@/features/ai/format";
import { Button, ErrorBanner, Input } from "@/components/ui/orchestrator";
import { useProjectStore } from "@/stores/project";
import { useI18n } from "@/lib/i18n";

type SearchState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; detail: string }
  | { kind: "done"; results: AiSearchResult[] };

export function AiSearchPanel() {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [state, setState] = useState<SearchState>({ kind: "idle" });
  const [status, setStatus] = useState<AiStatus | null>(null);

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

  const disabled = !status?.enabled;

  async function handleSearch(e: FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q || disabled || state.kind === "loading") return;
    setState({ kind: "loading" });
    try {
      const res = await api.aiSearch(q);
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

      <form onSubmit={(e) => void handleSearch(e)} className="shrink-0 border-b border-border bg-surface p-3">
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
        </div>
      </div>
    </div>
  );
}
