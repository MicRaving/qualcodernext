import {
  api,
  type AttributeReportRow,
  type ExactMatchRow,
  type FileSummaryRow,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { fileTypeLabel, formatCount } from "@/features/analyze/reportHelpers";
import { EmptyState } from "@/components/ui/orchestrator";
import {
  cardCls,
  thCls,
  tdCls,
  useReport,
} from "@/features/analyze/reportData";
import {
  ReportStatus,
  ReportHeader,
} from "@/features/analyze/reportKit";

export function ExactMatchesReport() {
  const { t } = useI18n();
  const { data, loading, error, retry } = useReport(api.reports.exactMatches);
  if (loading || error) {
    return <ReportStatus loading={loading} error={error} onRetry={retry} />;
  }
  const rows = data?.rows ?? [];
  if (rows.length === 0) return <div className="h-48"><EmptyState>No data</EmptyState></div>;
  return (
    <div className="space-y-2">
      <ReportHeader
        title={t("analyze.exactMatchesTitle")}
        filename="exact-matches.csv"
        headers={[t("analyze.colSegment"), t("analyze.colOccurrences"), t("analyze.colFiles")]}
        rows={rows.map((row: ExactMatchRow) => [row.seltext, row.count, row.files.join(", ")])}
      />
      <div className={cardCls}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className={thCls}>{t("analyze.colSegment")}</th>
              <th className={cn(thCls, "text-right")}>{t("analyze.colOccurrences")}</th>
              <th className={thCls}>{t("analyze.colFiles")}</th>
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
  const { t } = useI18n();
  const { data, loading, error, retry } = useReport(api.reports.fileSummary);
  if (loading || error) {
    return <ReportStatus loading={loading} error={error} onRetry={retry} />;
  }
  const rows = data?.rows ?? [];
  if (rows.length === 0) return <div className="h-48"><EmptyState>No data</EmptyState></div>;
  return (
    <div className="space-y-2">
      <ReportHeader
        title={t("analyze.fileSummaryTitle")}
        filename="file-summary.csv"
        headers={[t("analyze.colName"), t("analyze.colType"), t("analyze.colCodes"), t("analyze.colSegments"), t("analyze.colCases"), t("analyze.colWords")]}
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
              <th className={thCls}>{t("analyze.colName")}</th>
              <th className={thCls}>{t("analyze.colType")}</th>
              <th className={cn(thCls, "text-right")}>{t("analyze.colCodes")}</th>
              <th className={cn(thCls, "text-right")}>{t("analyze.colSegments")}</th>
              <th className={thCls}>{t("analyze.colCases")}</th>
              <th className={cn(thCls, "text-right")}>{t("analyze.colWords")}</th>
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

export function AttributesReport() {
  const { t } = useI18n();
  const { data, loading, error, retry } = useReport(api.reports.attributes);
  if (loading || error) {
    return <ReportStatus loading={loading} error={error} onRetry={retry} />;
  }
  const rows = data?.rows ?? [];
  if (rows.length === 0) return <div className="h-48"><EmptyState>No data</EmptyState></div>;
  return (
    <div className="space-y-2">
      <ReportHeader
        title={t("analyze.attributesTitle")}
        filename="attributes.csv"
        headers={[t("analyze.colAttribute"), t("analyze.colValue"), t("analyze.colScope"), t("analyze.colEntity")]}
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
              <th className={thCls}>{t("analyze.colAttribute")}</th>
              <th className={thCls}>{t("analyze.colValue")}</th>
              <th className={thCls}>{t("analyze.colScope")}</th>
              <th className={thCls}>{t("analyze.colEntity")}</th>
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
