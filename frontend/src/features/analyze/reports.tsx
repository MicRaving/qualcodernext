import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { CircleAlert, Download, FileImage, LoaderCircle } from "lucide-react";
import {
  api,
  type AttributeReportRow,
  type CodeFrequencyRow,
  type CodesBySegmentRow,
  type CoderComparisonRow,
  type ComparisonTable,
  type CooccurrenceTable,
  type ExactMatchRow,
  type FileSummaryRow,
} from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";
import { downloadChartPng } from "@/features/analyze/chartPng";
import { barWidth, fileTypeLabel, formatCount, matrixCell } from "@/features/analyze/reportHelpers";

const thCls =
  "border-b border-border bg-surface px-2 py-1.5 text-left text-xs font-medium text-text-secondary";
const tdCls = "border-b border-border px-2 py-1.5 text-sm";
const cardCls = "overflow-auto rounded-sm border border-border bg-surface";

interface ReportState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  retry: () => void;
}

function useReport<T>(load: () => Promise<T>): ReportState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    loadRef
      .current()
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load report");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  return { data, loading, error, retry };
}

function ReportStatus({
  loading,
  error,
  onRetry,
}: {
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center gap-2 text-text-secondary">
        <LoaderCircle size={16} className="animate-spin" aria-hidden />
        Loading report…
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex h-48 flex-col items-center justify-center gap-3">
        <p className="flex items-center gap-1.5 text-sm text-danger">
          <CircleAlert size={16} aria-hidden />
          {error}
        </p>
        <button
          type="button"
          onClick={onRetry}
          className="rounded-sm border border-border bg-surface px-3 py-1.5 text-sm hover:bg-surface-higher"
        >
          Retry
        </button>
      </div>
    );
  }
  return null;
}

function EmptyState() {
  return (
    <div className="flex h-48 items-center justify-center">
      <p className="text-sm text-text-secondary">No data</p>
    </div>
  );
}

function ReportHeader({
  title,
  filename,
  headers,
  rows,
  actions,
}: {
  title: string;
  filename: string;
  headers: string[];
  rows: unknown[][];
  actions?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <h2 className="text-sm font-medium text-text-primary">{title}</h2>
      <div className="flex items-center gap-2">
        {actions}
        <button
          type="button"
          onClick={() => downloadCsv(filename, headers, rows)}
          className="flex items-center gap-1 rounded-sm border border-border bg-surface px-2 py-1 text-xs text-text-secondary hover:bg-surface-higher hover:text-text-primary"
        >
          <Download size={12} aria-hidden />
          CSV
        </button>
      </div>
    </div>
  );
}

function ColorSwatch({ color }: { color: string | null }) {
  return (
    <span
      className="inline-block h-3 w-3 shrink-0 rounded-sm"
      style={{ backgroundColor: color ?? "var(--qc-accent)" }}
      aria-hidden
    />
  );
}

function CategoryCell({ category }: { category: string }) {
  return (
    <td className={cn(tdCls, "text-text-secondary")}>
      {category || <span className="italic">—</span>}
    </td>
  );
}

export function CodeFrequenciesReport() {
  const { data, loading, error, retry } = useReport(api.reports.codeFrequencies);
  if (loading || error) {
    return <ReportStatus loading={loading} error={error} onRetry={retry} />;
  }
  const rows = data?.rows ?? [];
  if (rows.length === 0) return <EmptyState />;
  const max = Math.max(0, ...rows.map((r) => r.count));
  return (
    <div className="space-y-4">
      <ReportHeader
        title="Code frequencies"
        filename="code-frequencies.csv"
        headers={["Code", "Category", "Count"]}
        rows={rows.map((row: CodeFrequencyRow) => [row.name, row.category, row.count])}
        actions={
          <button
            type="button"
            onClick={() => void downloadChartPng("code-frequencies.png", rows)}
            className="flex items-center gap-1 rounded-sm border border-border bg-surface px-2 py-1 text-xs text-text-secondary hover:bg-surface-higher hover:text-text-primary"
          >
            <FileImage size={12} aria-hidden />
            PNG
          </button>
        }
      />
      <section>
        <h2 className="text-xs font-medium uppercase tracking-wide text-text-secondary">
          Coding counts
        </h2>
        <div className={cn(cardCls, "mt-2 space-y-2 p-3")}>
          {rows.map((row: CodeFrequencyRow) => (
            <div key={row.cid} className="flex items-center gap-2">
              <span className="flex w-44 shrink-0 items-center gap-2 text-sm">
                <ColorSwatch color={row.color} />
                <span className="truncate">{row.name}</span>
              </span>
              <div className="h-2.5 flex-1 overflow-hidden rounded-sm bg-surface-higher">
                <div
                  className="h-full rounded-sm"
                  style={{
                    width: barWidth(row.count, max),
                    backgroundColor: row.color ?? "var(--qc-accent)",
                  }}
                />
              </div>
              <span className="w-12 shrink-0 text-right text-sm tabular-nums text-text-secondary">
                {row.count}
              </span>
            </div>
          ))}
        </div>
      </section>
      <section>
        <h2 className="text-xs font-medium uppercase tracking-wide text-text-secondary">Details</h2>
        <div className={cn(cardCls, "mt-2")}>
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10">
              <tr>
                <th className={thCls}>Code</th>
                <th className={thCls}>Category</th>
                <th className={cn(thCls, "text-right")}>Count</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row: CodeFrequencyRow) => (
                <tr key={row.cid} className="hover:bg-surface-higher">
                  <td className={tdCls}>
                    <span className="flex items-center gap-2">
                      <ColorSwatch color={row.color} />
                      <span className="truncate">{row.name}</span>
                    </span>
                  </td>
                  <CategoryCell category={row.category} />
                  <td className={cn(tdCls, "text-right tabular-nums")}>{row.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export function CodesBySegmentsReport() {
  const { data, loading, error, retry } = useReport(api.reports.codesBySegments);
  if (loading || error) {
    return <ReportStatus loading={loading} error={error} onRetry={retry} />;
  }
  const rows = data?.rows ?? [];
  if (rows.length === 0) return <EmptyState />;
  return (
    <div className="space-y-2">
      <ReportHeader
        title="Codes by segments"
        filename="codes-by-segments.csv"
        headers={["File", "Code", "Category", "Segment", "Owner", "Date"]}
        rows={rows.map((row: CodesBySegmentRow) => [
          row.file_name,
          row.code_name,
          row.category,
          row.seltext,
          row.owner,
          row.date,
        ])}
      />
      <div className={cardCls}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className={thCls}>File</th>
              <th className={thCls}>Code</th>
              <th className={thCls}>Category</th>
              <th className={thCls}>Segment</th>
              <th className={thCls}>Owner</th>
              <th className={thCls}>Date</th>
            </tr>
          </thead>
        <tbody>
          {rows.map((row: CodesBySegmentRow) => (
            <tr key={row.ctid} className="hover:bg-surface-higher">
              <td className={cn(tdCls, "max-w-48")}>
                <span className="block truncate">{row.file_name}</span>
              </td>
              <td className={cn(tdCls, "whitespace-nowrap")}>{row.code_name}</td>
              <CategoryCell category={row.category} />
              <td className={cn(tdCls, "max-w-md")}>
                <span className="block truncate" title={row.seltext}>
                  {row.seltext}
                </span>
              </td>
              <td className={cn(tdCls, "whitespace-nowrap text-text-secondary")}>{row.owner}</td>
              <td className={cn(tdCls, "whitespace-nowrap text-text-secondary")}>{row.date}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

export function ComparisonTableReport() {
  const { data, loading, error, retry } = useReport(api.reports.comparisonTable);
  if (loading || error) {
    return <ReportStatus loading={loading} error={error} onRetry={retry} />;
  }
  const table: ComparisonTable = {
    files: data?.files ?? [],
    codes: data?.codes ?? [],
    counts: data?.counts ?? [],
  };
  if (table.files.length === 0 || table.codes.length === 0) return <EmptyState />;
  return (
    <div className="space-y-2">
      <ReportHeader
        title="File × code comparison"
        filename="file-comparison.csv"
        headers={["File", ...table.codes.map((c) => c.name)]}
        rows={table.files.map((f, fi) => [
          f.name,
          ...(table.counts[fi] ?? []).map((n) => n),
        ])}
      />
      <div className={cn(cardCls, "max-h-96")}>
      <table className="w-full border-collapse">
        <thead className="sticky top-0 z-10">
          <tr>
            <th className={cn(thCls, "min-w-40")}>File</th>
            {table.codes.map((c) => (
              <th key={c.cid} className={cn(thCls, "min-w-32")}>
                <span className="flex items-center gap-1.5">
                  <ColorSwatch color={c.color} />
                  <span className="truncate">{c.name}</span>
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.files.map((f, fi) => (
            <tr key={f.fid} className="hover:bg-surface-higher">
              <td className={cn(tdCls, "max-w-48")}>
                <span className="block truncate font-medium">{f.name}</span>
              </td>
              {table.codes.map((c, ci) => (
                <td key={c.cid} className={cn(tdCls, "text-center tabular-nums text-text-secondary")}>
                  {matrixCell(table.counts[fi]?.[ci] ?? 0)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

export function CooccurrenceReport() {
  const { data, loading, error, retry } = useReport(api.reports.cooccurrence);
  if (loading || error) {
    return <ReportStatus loading={loading} error={error} onRetry={retry} />;
  }
  const table: CooccurrenceTable = { codes: data?.codes ?? [], counts: data?.counts ?? [] };
  if (table.codes.length === 0) return <EmptyState />;
  return (
    <div className="space-y-2">
      <ReportHeader
        title="Code co-occurrence"
        filename="co-occurrence.csv"
        headers={["", ...table.codes.map((c) => c.name)]}
        rows={table.codes.map((a, i) => [a.name, ...(table.counts[i] ?? []).map((n) => n)])}
      />
      <div className={cn(cardCls, "max-h-96")}>
      <table className="w-full border-collapse">
        <thead className="sticky top-0 z-10">
          <tr>
            <th className={cn(thCls, "min-w-40")}>Code</th>
            {table.codes.map((c) => (
              <th key={c.cid} className={cn(thCls, "min-w-24")}>
                <span className="flex items-center gap-1.5">
                  <ColorSwatch color={c.color} />
                  <span className="truncate">{c.name}</span>
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.codes.map((a, i) => (
            <tr key={a.cid} className="hover:bg-surface-higher">
              <td className={cn(tdCls, "max-w-48")}>
                <span className="flex items-center gap-2">
                  <ColorSwatch color={a.color} />
                  <span className="block truncate font-medium">{a.name}</span>
                </span>
              </td>
              {table.codes.map((b, j) => {
                const n = table.counts[i]?.[j] ?? 0;
                return (
                  <td
                    key={b.cid}
                    title={`${a.name} & ${b.name}: ${n} files`}
                    className={cn(
                      tdCls,
                      "text-center tabular-nums text-text-secondary",
                      i === j && "bg-surface-higher font-medium text-text-primary",
                    )}
                  >
                    {matrixCell(n)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

export function ExactMatchesReport() {
  const { data, loading, error, retry } = useReport(api.reports.exactMatches);
  if (loading || error) {
    return <ReportStatus loading={loading} error={error} onRetry={retry} />;
  }
  const rows = data?.rows ?? [];
  if (rows.length === 0) return <EmptyState />;
  return (
    <div className="space-y-2">
      <ReportHeader
        title="Exact matches"
        filename="exact-matches.csv"
        headers={["Segment", "Occurrences", "Files"]}
        rows={rows.map((row: ExactMatchRow) => [row.seltext, row.count, row.files.join(", ")])}
      />
      <div className={cardCls}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className={thCls}>Segment</th>
              <th className={cn(thCls, "text-right")}>Occurrences</th>
              <th className={thCls}>Files</th>
            </tr>
          </thead>
        <tbody>
          {rows.map((row: ExactMatchRow, i) => (
            <tr key={i} className="hover:bg-surface-higher">
              <td className={cn(tdCls, "max-w-xl")}>
                <span className="block truncate" title={row.seltext}>
                  {row.seltext}
                </span>
              </td>
              <td className={cn(tdCls, "text-right tabular-nums")}>{row.count}</td>
              <td className={cn(tdCls, "max-w-72 text-text-secondary")}>
                <span className="block truncate" title={row.files.join(", ")}>
                  {row.files.join(", ")}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

export function FileSummaryReport() {
  const { data, loading, error, retry } = useReport(api.reports.fileSummary);
  if (loading || error) {
    return <ReportStatus loading={loading} error={error} onRetry={retry} />;
  }
  const rows = data?.rows ?? [];
  if (rows.length === 0) return <EmptyState />;
  return (
    <div className="space-y-2">
      <ReportHeader
        title="File summary"
        filename="file-summary.csv"
        headers={["Name", "Type", "Codes", "Segments", "Cases", "Words"]}
        rows={rows.map((row: FileSummaryRow) => [
          row.name,
          fileTypeLabel(row.name, row.media_type),
          row.codes_count,
          row.segments_count,
          row.cases.join(", "),
          row.words,
        ])}
      />
      <div className={cardCls}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className={thCls}>Name</th>
              <th className={thCls}>Type</th>
              <th className={cn(thCls, "text-right")}>Codes</th>
              <th className={cn(thCls, "text-right")}>Segments</th>
              <th className={thCls}>Cases</th>
              <th className={cn(thCls, "text-right")}>Words</th>
            </tr>
          </thead>
        <tbody>
          {rows.map((row: FileSummaryRow) => (
            <tr key={row.fid} className="hover:bg-surface-higher">
              <td className={cn(tdCls, "max-w-56")}>
                <span className="block truncate font-medium">{row.name}</span>
              </td>
              <td className={cn(tdCls, "whitespace-nowrap")}>
                <span className="rounded-sm bg-surface-higher px-1.5 py-px text-xs font-medium text-text-secondary">
                  {fileTypeLabel(row.name, row.media_type)}
                </span>
              </td>
              <td className={cn(tdCls, "text-right tabular-nums")}>{row.codes_count}</td>
              <td className={cn(tdCls, "text-right tabular-nums")}>{row.segments_count}</td>
              <td className={cn(tdCls, "max-w-56 text-text-secondary")}>
                <span className="block truncate" title={row.cases.join(", ")}>
                  {row.cases.length > 0 ? row.cases.join(", ") : <span className="italic">—</span>}
                </span>
              </td>
              <td className={cn(tdCls, "text-right tabular-nums")}>{formatCount(row.words)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

export function CoderComparisonReport() {
  const { data, loading, error, retry } = useReport(api.reports.coderComparison);
  if (loading || error) {
    return <ReportStatus loading={loading} error={error} onRetry={retry} />;
  }
  const rows = data?.rows ?? [];
  if (rows.length === 0) return <EmptyState />;
  return (
    <div className="space-y-2">
      <ReportHeader
        title="Coder comparison"
        filename="coder-comparison.csv"
        headers={["Coder", "Codings", "Files"]}
        rows={rows.map((row: CoderComparisonRow) => [
          row.owner,
          row.codings_count,
          row.files_count,
        ])}
      />
      <div className={cardCls}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className={thCls}>Coder</th>
              <th className={cn(thCls, "text-right")}>Codings</th>
              <th className={cn(thCls, "text-right")}>Files</th>
            </tr>
          </thead>
        <tbody>
          {rows.map((row: CoderComparisonRow) => (
            <tr key={row.owner} className="hover:bg-surface-higher">
              <td className={cn(tdCls, "font-medium")}>{row.owner}</td>
              <td className={cn(tdCls, "text-right tabular-nums")}>
                {formatCount(row.codings_count)}
              </td>
              <td className={cn(tdCls, "text-right tabular-nums")}>{formatCount(row.files_count)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

export function AttributesReport() {
  const { data, loading, error, retry } = useReport(api.reports.attributes);
  if (loading || error) {
    return <ReportStatus loading={loading} error={error} onRetry={retry} />;
  }
  const rows = data?.rows ?? [];
  if (rows.length === 0) return <EmptyState />;
  return (
    <div className="space-y-2">
      <ReportHeader
        title="Attributes"
        filename="attributes.csv"
        headers={["Attribute", "Value", "Scope", "Entity"]}
        rows={rows.map((row: AttributeReportRow) => [
          row.name,
          row.value,
          row.entity_kind === "case" ? "Case" : "File",
          row.entity_name,
        ])}
      />
      <div className={cardCls}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className={thCls}>Attribute</th>
              <th className={thCls}>Value</th>
              <th className={thCls}>Scope</th>
              <th className={thCls}>Entity</th>
            </tr>
          </thead>
        <tbody>
          {rows.map((row: AttributeReportRow, i) => (
            <tr key={i} className="hover:bg-surface-higher">
              <td className={cn(tdCls, "whitespace-nowrap")}>
                <span className="font-medium">{row.name}</span>
                <span className="ml-1.5 text-xs text-text-secondary">({row.attr_type})</span>
              </td>
              <td className={cn(tdCls, "max-w-md")}>
                <span className="block truncate" title={row.value}>
                  {row.value}
                </span>
              </td>
              <td className={cn(tdCls, "whitespace-nowrap")}>
                <span className="rounded-sm bg-surface-higher px-1.5 py-px text-xs font-medium text-text-secondary">
                  {row.entity_kind === "case" ? "Case" : "File"}
                </span>
              </td>
              <td className={cn(tdCls, "max-w-56")}>
                <span className="block truncate text-text-secondary">{row.entity_name}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Interrater reliability
// ---------------------------------------------------------------------------

export interface InterraterResult {
  coder_a: string;
  coder_b: string;
  n_units: number;
  n_categories: number;
  n_pairs: number;
  both: number;
  only_a: number;
  only_b: number;
  neither: number;
  kappa: number | null;
  krippendorff: number | null;
  gwet_ac1: number | null;
}

export function InterraterReport() {
  const { t } = useI18n();
  const coders = useProjectStore((state) => state.coders);
  const coderNames = coders.map((c) => c.name);
  const [coderA, setCoderA] = useState("");
  const [coderB, setCoderB] = useState("");
  const [metric, setMetric] = useState<"kappa" | "krippendorff" | "gwet_ac1">("kappa");
  const [result, setResult] = useState<InterraterResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (coderNames.length >= 2 && !coderA && !coderB) {
      setCoderA(coderNames[0]);
      setCoderB(coderNames[1]);
    }
  }, [coderNames, coderA, coderB]);

  async function compute(e: FormEvent) {
    e.preventDefault();
    if (!coderA || !coderB || coderA === coderB) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await api.reports.interrater(coderA, coderB));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("analyze.loadError"));
    } finally {
      setLoading(false);
    }
  }

  const value =
    result == null ? null : metric === "kappa" ? result.kappa : metric === "krippendorff" ? result.krippendorff : result.gwet_ac1;

  const selectCls =
    "h-8 rounded-sm border border-border bg-bg px-2 text-sm outline-none focus:border-accent";

  return (
    <div className="space-y-2">
      <form onSubmit={(e) => void compute(e)} className="flex flex-wrap items-end gap-2">
        <label className="block">
          <span className="mb-1 block text-xs text-text-secondary">Coder A</span>
          <select value={coderA} onChange={(e) => setCoderA(e.target.value)} className={selectCls}>
            {coderNames.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-text-secondary">Coder B</span>
          <select value={coderB} onChange={(e) => setCoderB(e.target.value)} className={selectCls}>
            {coderNames.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-text-secondary">Measure</span>
          <select
            value={metric}
            onChange={(e) => setMetric(e.target.value as "kappa" | "krippendorff" | "gwet_ac1")}
            className={selectCls}
          >
            <option value="kappa">Cohen's Kappa</option>
            <option value="krippendorff">Krippendorff's Alpha</option>
            <option value="gwet_ac1">Gwet's AC1</option>
          </select>
        </label>
        <button
          type="submit"
          disabled={loading || !coderA || !coderB || coderA === coderB}
          className="rounded-sm bg-accent px-3 py-1.5 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-40"
        >
          {loading ? "Computing…" : "Compute"}
        </button>
      </form>

      {error && (
        <p className="flex items-center gap-1.5 text-xs text-danger">
          <CircleAlert size={13} aria-hidden />
          {error}
        </p>
      )}

      {result && (
        <div className={cardCls}>
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10">
              <tr>
                <th className={thCls}>Measure</th>
                <th className={cn(thCls, "text-right")}>Value</th>
                <th className={cn(thCls, "text-right")}>Units</th>
                <th className={cn(thCls, "text-right")}>Codes</th>
                <th className={cn(thCls, "text-right")}>Pairs</th>
                <th className={cn(thCls, "text-right")}>Both</th>
                <th className={cn(thCls, "text-right")}>A only</th>
                <th className={cn(thCls, "text-right")}>B only</th>
                <th className={cn(thCls, "text-right")}>Neither</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ["Cohen's Kappa", result.kappa],
                  ["Krippendorff's Alpha", result.krippendorff],
                  ["Gwet's AC1", result.gwet_ac1],
                ] as [string, number | null][]
              ).map(([label, v]) => (
                <tr
                  key={label}
                  className={v === value ? "bg-accent/10" : "hover:bg-surface-higher"}
                >
                  <td className={cn(tdCls, "font-medium")}>{label}</td>
                  <td className={cn(tdCls, "text-right font-mono")}>
                    {v == null ? "—" : v.toFixed(4)}
                  </td>
                  <td className={cn(tdCls, "text-right")}>{result.n_units}</td>
                  <td className={cn(tdCls, "text-right")}>{result.n_categories}</td>
                  <td className={cn(tdCls, "text-right")}>{result.n_pairs}</td>
                  <td className={cn(tdCls, "text-right")}>{result.both}</td>
                  <td className={cn(tdCls, "text-right")}>{result.only_a}</td>
                  <td className={cn(tdCls, "text-right")}>{result.only_b}</td>
                  <td className={cn(tdCls, "text-right")}>{result.neither}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="border-t border-border px-2 py-1.5 text-xs text-text-secondary">
            {result.coder_a} vs {result.coder_b} — agreement over source x code cells.
          </p>
        </div>
      )}
    </div>
  );
}
