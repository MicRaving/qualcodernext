/**
 * SearchDialog — the full-text search UI as a flyout anchored under the
 * ribbon's native search box.
 *
 * The query itself lives in the ribbon input; this flyout hosts everything
 * else: the Exact/Semantic mode toggle, the entity-scope multi-select (files,
 * codes, categories, cases, journal, memos, attributes, comments — all
 * preselected), the semantic index controls, and the live results. Two modes:
 *
 * * Exact — the query is treated as a regular expression natively (no toggle);
 *   every result carries a ``kind`` so the list can label it and clicking
 *   navigates to the matching view. The match preview highlights the exact
 *   matched part in yellow.
 * * Semantic — AI embedding search over text sources. Requires a configured
 *   LLM; when no model is loaded the mode is disabled entirely.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { FileText, Sparkles } from "lucide-react";
import {
  api,
  type AiIndexStatus,
  type AiSearchResult,
  type SearchEntityKind,
  type SearchEntityType,
  type SearchHit,
  type SearchResultItem,
  SEARCH_ENTITY_TYPES,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { errorMessage } from "@/lib/utils";
import { Button, EmptyState } from "@/components/ui/orchestrator";
import { useWorkspaceStore } from "@/stores/workspace";

type Mode = "exact" | "semantic";

/** Singular result ``kind`` → plural entity scope name (for the badge). */
const KIND_TO_ENTITY: Record<SearchEntityKind, SearchEntityType> = {
  file: "files",
  code: "codes",
  category: "categories",
  case: "cases",
  journal: "journal",
  memo: "memos",
  attribute: "attributes",
  comment: "comments",
};

/** i18n key for an entity type's display label. */
function entityLabelKey(entity: SearchEntityType): string {
  return `search.entity.${entity}`;
}

/** The match context with the exact matched span marked in yellow. */
function HighlightedContext({ hit }: { hit: SearchHit }) {
  const a = Math.max(0, Math.min(hit.rel0, hit.context.length));
  const b = Math.max(a, Math.min(hit.rel1, hit.context.length));
  return (
    <>
      {hit.context.slice(0, a)}
      <mark className="rounded-sm bg-accent/30 px-px text-text-primary">
        {hit.context.slice(a, b)}
      </mark>
      {hit.context.slice(b)}
    </>
  );
}

export function SearchDialog({
  open,
  anchor,
  query,
  onClose,
}: {
  open: boolean;
  /** The ribbon search input the flyout anchors under. */
  anchor: HTMLElement | null;
  /** The query lives in the ribbon input; the flyout only reads it. */
  query: string;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [mode, setMode] = useState<Mode>("exact");
  // Entity scopes to search, all preselected.
  const [entities, setEntities] = useState<SearchEntityType[]>([...SEARCH_ENTITY_TYPES]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [results, setResults] = useState<(SearchResultItem | AiSearchResult)[]>([]);
  const [indexStatus, setIndexStatus] = useState<AiIndexStatus | null>(null);
  const [indexBusy, setIndexBusy] = useState(false);
  // Semantic mode requires a loaded LLM — check the AI status once.
  const [aiEnabled, setAiEnabled] = useState<boolean | null>(null);
  const ref = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const timerRef = useRef<number | undefined>(undefined);

  const loadIndex = useCallback(async () => {
    try {
      setIndexStatus(await api.aiIndexStatus());
    } catch {
      setIndexStatus(null);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void api
      .aiStatus()
      .then((s) => setAiEnabled(s.enabled && s.configured))
      .catch(() => setAiEnabled(false));
  }, [open]);

  // Semantic is unavailable without a loaded LLM — force exact on open.
  useEffect(() => {
    if (open && aiEnabled === false && mode === "semantic") setMode("exact");
  }, [open, aiEnabled, mode]);

  // On mode switch to semantic, refresh the index status.
  useEffect(() => {
    if (open && mode === "semantic") void loadIndex();
  }, [open, mode, loadIndex]);

  const semanticDisabled = aiEnabled === false;

  // Position the flyout under the ribbon input (clamped to the window).
  useEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    const place = () => {
      const a = anchor?.getBoundingClientRect();
      const el = ref.current;
      if (!a || !el) return;
      const w = el.offsetWidth;
      const h = el.offsetHeight;
      // Center the flyout horizontally in the window.
      const left = Math.max(8, (window.innerWidth - w) / 2);
      let top = a.bottom + 6;
      if (top + h > window.innerHeight - 8) {
        top = Math.max(8, a.top - h - 6);
      }
      setPos({ left, top });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, anchor]);

  // Close on outside click / Escape (the ribbon input itself stays open).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (target && !ref.current?.contains(target) && !anchor?.contains(target)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, anchor, onClose]);

  const toggleEntity = (entity: SearchEntityType) => {
    setEntities((cur) =>
      cur.includes(entity) ? cur.filter((e) => e !== entity) : [...cur, entity],
    );
  };

  // Debounced live search on the ribbon query.
  useEffect(() => {
    if (!open) {
      window.clearTimeout(timerRef.current);
      return;
    }
    const run = async () => {
      const q = query.trim();
      if (!q) {
        setResults([]);
        setTotal(null);
        setError(null);
        return;
      }
      setBusy(true);
      setError(null);
      try {
        if (mode === "exact") {
          const res = await api.search({ query: q, regex: true, entities, limit: 50 });
          setResults(res.results);
          setTotal(res.total);
        } else {
          const res = await api.aiSearch({ query: q, limit: 20 });
          setResults(res.results);
          setTotal(res.results.length);
        }
      } catch (e) {
        setResults([]);
        setTotal(null);
        setError(errorMessage(e));
      } finally {
        setBusy(false);
      }
    };
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => void run(), 250);
    return () => window.clearTimeout(timerRef.current);
  }, [open, query, mode, entities]);

  function openResult(result: SearchResultItem | AiSearchResult) {
    onClose();
    const ws = useWorkspaceStore.getState();
    if ("kind" in result) {
      switch (result.kind) {
        case "file":
          ws.setView({ kind: "coding", sourceId: result.source_id ?? result.id });
          return;
        case "case":
          ws.setView({ kind: "cases" });
          ws.setCasesUi({ selectedId: result.id });
          return;
        case "journal":
          ws.setView({ kind: "notes" });
          ws.setNotesUi({ tab: "journal", selectedId: result.id, tick: 0 });
          return;
        case "code":
        case "category":
        case "memo": {
          ws.setView({ kind: "notes" });
          const refKind = result.kind === "memo" ? result.ref_kind : result.kind;
          ws.setNotesUi({
            tab: "memos",
            selectedId: result.ref_id ?? result.id,
            selectedKind: refKind === "file" ? "file" : refKind === "code" ? "code" : null,
            tick: 0,
          });
          return;
        }
        case "attribute":
          // Attributes belong to cases — open the cases view.
          ws.setView({ kind: "cases" });
          return;
        case "comment":
        default:
          // Comments attach to entities; open the notes view as a landing pad.
          ws.setView({ kind: "notes" });
          return;
      }
    }
    ws.setView({ kind: "coding", sourceId: result.source_id });
  }

  async function buildIndex() {
    if (indexBusy) return;
    setIndexBusy(true);
    try {
      setIndexStatus(await api.aiIndexBuild());
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setIndexBusy(false);
    }
  }

  async function deleteIndex() {
    if (indexBusy) return;
    setIndexBusy(true);
    try {
      await api.aiIndexDelete();
      setIndexStatus(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setIndexBusy(false);
    }
  }

  // Map a result row to a short kind label for the badge.
  const kindLabel = useCallback(
    (result: SearchResultItem | AiSearchResult): string => {
      if (!("kind" in result)) return t("search.kindSource");
      return t(entityLabelKey(KIND_TO_ENTITY[result.kind] ?? "files"));
    },
    [t],
  );

  if (!open) return null;

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={t("search.title")}
      className="fixed z-50 flex w-[44rem] max-w-[94vw] flex-col overflow-hidden rounded-md border border-border bg-surface shadow-qc-lg"
      style={
        pos
          ? { left: pos.left, top: pos.top, maxHeight: "min(70dvh, 30rem)" }
          : { visibility: "hidden" }
      }
    >
      {/* Controls */}
      <div className="flex shrink-0 space-y-2 border-b border-border p-3">
        <div className="flex shrink-0 overflow-hidden rounded-sm border border-border">
          {(["exact", "semantic"] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              aria-pressed={mode === m}
              disabled={m === "semantic" && semanticDisabled}
              title={m === "semantic" && semanticDisabled ? t("search.semanticDisabled") : undefined}
              className={`px-2.5 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50 ${
                mode === m
                  ? "bg-surface-higher text-accent"
                  : "bg-bg text-text-secondary hover:bg-surface-higher"
              }`}
            >
              {m === "exact" ? t("search.modeExact") : t("search.modeSemantic")}
            </button>
          ))}
        </div>

        {/* Entity scope multi-select — all preselected. */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-medium uppercase tracking-wide text-text-secondary">
            {t("search.scopeLabel")}
          </span>
          {SEARCH_ENTITY_TYPES.map((entity) => {
            const checked = entities.includes(entity);
            return (
              <label
                key={entity}
                className={`flex cursor-pointer items-center gap-1 rounded-sm border border-border px-1.5 py-0.5 text-xs ${
                  checked
                    ? "border-accent/50 bg-surface-higher text-text-primary"
                    : "text-text-secondary"
                }`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggleEntity(entity)}
                  className="h-3 w-3 accent-accent"
                />
                {t(entityLabelKey(entity))}
              </label>
            );
          })}
        </div>

        {/* Semantic explanation — below the "Search in" line. */}
        {mode === "semantic" && (
          <p className="flex items-start gap-1.5 text-xs leading-relaxed text-text-secondary">
            <Sparkles size={12} className="mt-0.5 shrink-0" aria-hidden />
            {t("search.semanticHint")}
          </p>
        )}

        {/* Semantic index status + build control — one line, aligned right. */}
        {mode === "semantic" && (
          <div className="flex items-center justify-end gap-2 text-xs text-text-secondary">
            <span className="min-w-0 truncate">
              {indexStatus?.indexed
                ? t("ai.indexStatusReady", {
                    chunks: String(indexStatus.chunks),
                    model: indexStatus.model,
                  })
                : t("ai.indexStatusNone")}
            </span>
            <Button variant="secondary" disabled={indexBusy} onClick={() => void buildIndex()}>
              {indexBusy
                ? t("search.indexBusy")
                : indexStatus?.indexed
                  ? t("ai.indexRebuild")
                  : t("ai.indexBuild")}
            </Button>
            {indexStatus?.indexed && (
              <Button variant="secondary" disabled={indexBusy} onClick={() => void deleteIndex()}>
                {t("ai.indexDelete")}
              </Button>
            )}
          </div>
        )}
      </div>

      {/* Results */}
      <div className="qc-scroll min-h-0 flex-1 overflow-y-auto">
        {busy && total === null ? (
          <EmptyState>
            <span className="mx-auto h-4 w-4 animate-spin rounded-full border-2 border-b-transparent border-accent" />
          </EmptyState>
        ) : error ? (
          <div className="p-3 text-xs text-danger">{error}</div>
        ) : total === 0 ? (
          <EmptyState>{t("search.empty")}</EmptyState>
        ) : total === null ? (
          <EmptyState>{t("search.enterQuery")}</EmptyState>
        ) : (
          <ul className="divide-y divide-border">
            {total != null && (
              <li className="px-3 py-1 text-[11px] font-medium uppercase tracking-wide text-text-secondary">
                {t("search.matches", { count: String(total) })}
              </li>
            )}
            {results.map((r, i) => (
              <li key={i}>
                <button
                  type="button"
                  onClick={() => openResult(r)}
                  className="block w-full px-3 py-2 text-left hover:bg-surface-higher"
                  title={t("search.openInCoder")}
                >
                  <div className="flex items-center gap-1.5">
                    <FileText size={13} className="shrink-0 text-text-secondary" aria-hidden />
                    <span className="shrink-0 rounded-sm bg-surface-higher px-1 text-[10px] uppercase tracking-wide text-text-secondary">
                      {kindLabel(r)}
                    </span>
                    <span className="truncate text-sm font-medium text-text-primary">
                      {"name" in r ? r.name : r.file_name}
                    </span>
                    {"match_count" in r && (
                      <span className="ml-auto shrink-0 rounded-sm bg-surface-higher px-1 text-[10px] text-text-secondary">
                        {r.match_count}
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 line-clamp-2 break-words whitespace-pre-wrap text-xs text-text-secondary">
                    {"hits" in r && r.hits.length > 0 ? (
                      <HighlightedContext hit={r.hits[0]} />
                    ) : "text" in r ? (
                      r.text
                    ) : (
                      "hits" in r ? r.hits[0]?.context : ""
                    )}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}