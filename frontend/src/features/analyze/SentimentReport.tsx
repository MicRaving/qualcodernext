/**
 * SentimentReportView — sentiment analysis of coded segments and whole
 * text sources.
 *
 * Offline mode scores with the VADER lexicon (backend, run in a worker
 * thread); AI mode classifies coded segments through the configured chat
 * provider and is disabled when the AI feature is not configured. Data
 * comes through the local-fetch pattern (initApiBase + fetchWithTimeout,
 * as in statsApi.ts), with a single retry on network-level failure.
 *
 * Registered by the analysis registry (suggested id: "sentiment").
 */
import { useEffect, useState } from "react";
import { api, ApiError, fetchWithTimeout, initApiBase, type AiStatus } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { EmptyState, Select } from "@/components/ui/orchestrator";
import { cardCls, tdCls, thCls, useReport } from "@/features/analyze/reportData";
import { ReportCsvButton, ReportMenuBar, ReportStatus } from "@/features/analyze/reportKit";
import { useProjectStore } from "@/stores/project";

export type SentimentScope = "segments" | "sources";
export type SentimentMode = "lexicon" | "ai";

export interface SentimentRow {
  fid: number;
  file_name: string;
  cid?: number;
  code_name?: string;
  seltext?: string;
  neg?: number;
  neu?: number;
  pos?: number;
  compound?: number | null;
  sentiment?: string;
  reason?: string;
}

export interface SentimentSummary {
  positive: number;
  negative: number;
  neutral: number;
  total: number;
  avg_compound: number | null;
}

export interface SentimentResult {
  mode: SentimentMode;
  scope: SentimentScope;
  rows: SentimentRow[];
  summary: SentimentSummary;
}

/** Compound thresholds mirroring the backend (VADER convention). */
const POSITIVE_COMPOUND = 0.05;
const NEGATIVE_COMPOUND = -0.05;

async function requestJson<T>(path: string): Promise<T> {
  const doFetch = async (): Promise<T> => {
    const base = await initApiBase();
    const res = await fetchWithTimeout(`${base}${path}`);
    if (!res.ok) {
      let detail: unknown;
      try {
        detail = (await res.json()).detail;
      } catch {
        /* non-JSON error body */
      }
      const suffix = typeof detail === "string" && detail ? `: ${detail}` : "";
      throw new ApiError(res.status, `API error ${res.status} on ${path}${suffix}`, detail);
    }
    return (await res.json()) as T;
  };
  try {
    return await doFetch();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    // Network-level failure (packaged backend restarted): retry once so the
    // base URL is resolved afresh.
    return doFetch();
  }
}

function fetchSentiment(opts: {
  scope: SentimentScope;
  mode: SentimentMode;
  fid?: number;
  limit?: number;
}): Promise<SentimentResult> {
  const params = new URLSearchParams({ scope: opts.scope, mode: opts.mode });
  if (opts.fid !== undefined) params.set("fid", String(opts.fid));
  if (opts.mode === "ai") params.set("limit", String(opts.limit ?? 100));
  return requestJson<SentimentResult>(`/reports/sentiment?${params.toString()}`);
}

/** Sentiment label for a row: AI rows carry it, lexicon rows derive it
 *  from the compound score (same thresholds as the backend summary). */
function sentimentOf(row: SentimentRow): string {
  if (row.sentiment) return row.sentiment;
  if (row.compound == null) return "neutral";
  return row.compound >= POSITIVE_COMPOUND
    ? "positive"
    : row.compound <= NEGATIVE_COMPOUND
      ? "negative"
      : "neutral";
}

function SentimentChip({ sentiment }: { sentiment: string }) {
  const { t } = useI18n();
  const tone =
    sentiment === "positive"
      ? "bg-success/10 text-success"
      : sentiment === "negative"
        ? "bg-danger/10 text-danger"
        : "bg-surface-higher text-text-secondary";
  return (
    <span
      className={cn(
        "inline-block whitespace-nowrap rounded-sm px-1.5 py-px text-[10px] font-medium",
        tone,
      )}
    >
      {t(`analyze.sentiment.${sentiment}`)}
    </span>
  );
}

export function SentimentReportView() {
  const { t } = useI18n();
  const sources = useProjectStore((state) => state.sources).filter(
    (s) => s.media_type === "text" || s.media_type === "pdf",
  );
  const [scope, setScope] = useState<SentimentScope>("segments");
  const [mode, setMode] = useState<SentimentMode>("lexicon");
  const [fid, setFid] = useState<number | "">("");
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .aiStatus()
      .then((status) => {
        if (!cancelled) setAiStatus(status);
      })
      .catch(() => {
        /* best-effort: the backend still guards AI mode with a 409 */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const aiAvailable = aiStatus === null ? true : aiStatus.enabled && aiStatus.configured;

  function changeMode(next: SentimentMode) {
    setMode(next);
    if (next === "ai" && scope !== "segments") setScope("segments");
  }

  const { data, loading, error, retry } = useReport(
    () => fetchSentiment({ scope, mode, fid: fid === "" ? undefined : fid }),
    [scope, mode, fid],
  );

  const isSegments = scope === "segments";
  const isAi = mode === "ai";

  const headers = [
    t("analyze.colFile"),
    ...(isSegments ? [t("analyze.colCode")] : []),
    ...(isSegments ? [t("analyze.colSegment")] : []),
    ...(isAi
      ? []
      : [t("analyze.colNeg"), t("analyze.colNeu"), t("analyze.colPos"), t("analyze.colCompound")]),
    t("analyze.colSentiment"),
    ...(isAi ? [t("analyze.colReason")] : []),
  ];
  const csvRows = (data?.rows ?? []).map((row) => [
    row.file_name,
    ...(isSegments ? [row.code_name ?? ""] : []),
    ...(isSegments ? [row.seltext ?? ""] : []),
    ...(isAi
      ? []
      : [row.neg ?? 0, row.neu ?? 0, row.pos ?? 0, row.compound ?? 0]),
    sentimentOf(row),
    ...(isAi ? [row.reason ?? ""] : []),
  ]);

  return (
    <div className="space-y-2">
      <ReportMenuBar>
        <Select
          value={scope}
          onChange={(e) => setScope(e.target.value as SentimentScope)}
          aria-label={t("analyze.summaryScope")}
        >
          <option value="segments">{t("analyze.sentimentSegments")}</option>
          <option value="sources" disabled={isAi}>
            {t("analyze.sentimentSources")}
          </option>
        </Select>
        <Select
          value={mode}
          onChange={(e) => changeMode(e.target.value as SentimentMode)}
          aria-label={t("analyze.sentimentMode")}
        >
          <option value="lexicon">{t("analyze.sentimentLexicon")}</option>
          <option value="ai" disabled={!aiAvailable}>
            {t("analyze.sentimentAi")}
            {!aiAvailable ? ` (${t("analyze.sentimentAiDisabled")})` : ""}
          </option>
        </Select>
        <Select
          value={fid}
          onChange={(e) => setFid(e.target.value === "" ? "" : Number(e.target.value))}
          aria-label={t("analyze.source")}
        >
          <option value="">{t("analyze.allTextSources")}</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </Select>
        <ReportCsvButton
          filename={`sentiment-${mode}-${scope}.csv`}
          headers={headers}
          rows={csvRows}
        />
      </ReportMenuBar>

      {loading || error ? (
        <ReportStatus loading={loading} error={error} onRetry={retry} />
      ) : !data || data.rows.length === 0 ? (
        <div className="h-48">
          <EmptyState>
            {isSegments ? t("analyze.sentimentEmptySegments") : t("analyze.sentimentEmptySources")}
          </EmptyState>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 rounded-sm border border-border bg-surface px-3 py-2 text-sm">
            <span className="text-xs font-medium tracking-wide text-text-secondary">
              {t("analyze.sentimentDistribution")}
            </span>
            <span className="flex items-center gap-1.5">
              <SentimentChip sentiment="positive" />
              <span className="tabular-nums">{data.summary.positive}</span>
            </span>
            <span className="flex items-center gap-1.5">
              <SentimentChip sentiment="negative" />
              <span className="tabular-nums">{data.summary.negative}</span>
            </span>
            <span className="flex items-center gap-1.5">
              <SentimentChip sentiment="neutral" />
              <span className="tabular-nums">{data.summary.neutral}</span>
            </span>
            <span className="ml-auto text-xs text-text-secondary">
              {t("analyze.sentimentAvg")}:{" "}
              <span className="font-medium tabular-nums text-text-primary">
                {data.summary.avg_compound ?? "—"}
              </span>
            </span>
          </div>
          <div className={cn(cardCls, "max-h-[65vh]")}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10">
                <tr>
                  <th className={cn(thCls, "min-w-36")}>{t("analyze.colFile")}</th>
                  {isSegments && <th className={cn(thCls, "min-w-28")}>{t("analyze.colCode")}</th>}
                  {isSegments && <th className={cn(thCls, "min-w-56")}>{t("analyze.colSegment")}</th>}
                  {!isAi && <th className={cn(thCls, "text-right")}>{t("analyze.colNeg")}</th>}
                  {!isAi && <th className={cn(thCls, "text-right")}>{t("analyze.colNeu")}</th>}
                  {!isAi && <th className={cn(thCls, "text-right")}>{t("analyze.colPos")}</th>}
                  {!isAi && <th className={cn(thCls, "text-right")}>{t("analyze.colCompound")}</th>}
                  <th className={cn(thCls, "min-w-24")}>{t("analyze.colSentiment")}</th>
                  {isAi && <th className={cn(thCls, "min-w-56")}>{t("analyze.colReason")}</th>}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, i) => (
                  <tr key={isSegments ? `${row.fid}-${i}` : String(row.fid)} className="hover:bg-surface-higher">
                    <td className={cn(tdCls, "max-w-40")}>
                      <span className="block truncate font-medium" title={row.file_name}>
                        {row.file_name}
                      </span>
                    </td>
                    {isSegments && (
                      <td className={cn(tdCls, "whitespace-nowrap")}>{row.code_name ?? ""}</td>
                    )}
                    {isSegments && (
                      <td className={cn(tdCls, "max-w-96 text-text-secondary")}>
                        <span className="block truncate" title={row.seltext}>
                          {row.seltext}
                        </span>
                      </td>
                    )}
                    {!isAi && (
                      <>
                        <td className={cn(tdCls, "text-right tabular-nums")}>
                          {row.neg?.toFixed(3)}
                        </td>
                        <td className={cn(tdCls, "text-right tabular-nums")}>
                          {row.neu?.toFixed(3)}
                        </td>
                        <td className={cn(tdCls, "text-right tabular-nums")}>
                          {row.pos?.toFixed(3)}
                        </td>
                        <td className={cn(tdCls, "text-right font-medium tabular-nums")}>
                          {row.compound?.toFixed(3)}
                        </td>
                      </>
                    )}
                    <td className={cn(tdCls, "whitespace-nowrap")}>
                      <SentimentChip sentiment={sentimentOf(row)} />
                    </td>
                    {isAi && (
                      <td className={cn(tdCls, "max-w-80 text-text-secondary")}>
                        <span className="block truncate" title={row.reason}>
                          {row.reason}
                        </span>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
