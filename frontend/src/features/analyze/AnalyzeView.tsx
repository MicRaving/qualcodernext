import { useState, type ComponentType } from "react";
import { useI18n } from "@/lib/i18n";
import { Button, ViewHeader } from "@/components/ui/orchestrator";
import {
  AlignJustify,
  ArrowLeft,
  BarChart3,
  BookOpen,
  CloudSun,
  Files,
  FileCode2,
  Flame,
  GitBranch,
  GitCompareArrows,
  Grid3x3,
  SquareTerminal,
  Table,
  Tags,
  TrendingUp,
  Users,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import {
  AttributesReport,
  CodeFrequenciesReport,
  CodesBySegmentsReport,
  CoderComparisonReport,
  ComparisonTableReport,
  CooccurrenceReport,
  ExactMatchesReport,
  FileSummaryReport,
  InterraterReport,
} from "@/features/analyze/reports";
import {
  CodebookReport,
  CodeRelationsReport,
  CodeSegmentsReport,
  CodeSummaryReport,
  CoderFileComparisonReport,
  CumulativeChart,
  HeatmapReport,
  ReferencesReport,
  StackedChart,
  WordCloudReport,
} from "@/features/analyze/upstreamReports";
import { SqlReport } from "@/features/analyze/SqlReport";

export type ReportId =
  | "code-frequencies"
  | "codes-by-segments"
  | "comparison-table"
  | "co-occurrence"
  | "exact-matches"
  | "file-summary"
  | "coder-comparison"
  | "interrater"
  | "attributes"
  | "sql"
  | "code-segments"
  | "code-summary"
  | "coder-file-comparison"
  | "code-relations"
  | "word-cloud"
  | "cumulative"
  | "stacked"
  | "heatmap"
  | "codebook"
  | "references";

export interface ReportMeta {
  id: ReportId;
  title: string;
  description: string;
  icon: LucideIcon;
}

export const REPORT_META: ReportMeta[] = [
  {
    id: "code-frequencies",
    title: "Code frequencies",
    description: "How often each code is applied across the project, ranked by count.",
    icon: BarChart3,
  },
  {
    id: "codes-by-segments",
    title: "Codes by segments",
    description: "Every coded segment with its file, code, author and date.",
    icon: AlignJustify,
  },
  {
    id: "comparison-table",
    title: "Comparison table",
    description: "Code counts per file, laid out side by side.",
    icon: Table,
  },
  {
    id: "co-occurrence",
    title: "Co-occurrence",
    description: "How often pairs of codes appear together in the same file.",
    icon: GitBranch,
  },
  {
    id: "exact-matches",
    title: "Exact matches",
    description: "Identical text segments coded in more than one file.",
    icon: Grid3x3,
  },
  {
    id: "file-summary",
    title: "File summary",
    description: "Codes, segments, cases and word counts per file.",
    icon: Files,
  },
  {
    id: "coder-comparison",
    title: "Coder comparison",
    description: "Coding volume per coder across the project.",
    icon: Users,
  },
  {
    id: "interrater",
    title: "Interrater reliability",
    description: "Agreement between two coders (Cohen's Kappa, Krippendorff's Alpha, Gwet's AC1).",
    icon: GitCompareArrows,
  },
  {
    id: "attributes",
    title: "Attributes",
    description: "Attribute values recorded on cases and files.",
    icon: Tags,
  },
  {
    id: "sql",
    title: "SQL report",
    description: "Run ad-hoc read-only SQL queries",
    icon: SquareTerminal,
  },
  {
    id: "code-segments",
    title: "Code segments",
    description: "All coded segments of one code across text, image and AV (code-in-all-files).",
    icon: FileCode2,
  },
  {
    id: "code-summary",
    title: "Code summary",
    description: "Counts, files and memo of a single code.",
    icon: Files,
  },
  {
    id: "coder-file-comparison",
    title: "Coders by file",
    description: "Two coders' text segments, compared file by file.",
    icon: GitCompareArrows,
  },
  {
    id: "code-relations",
    title: "Code relations",
    description: "Crossover relations (overlapping segments) between codes of one coder.",
    icon: Workflow,
  },
  {
    id: "word-cloud",
    title: "Word cloud",
    description: "Most frequent words across the text sources.",
    icon: CloudSun,
  },
  {
    id: "cumulative",
    title: "Cumulative chart",
    description: "Cumulated coding counts across the codes.",
    icon: TrendingUp,
  },
  {
    id: "stacked",
    title: "Stacked bars",
    description: "Code share per file or per case as stacked bars.",
    icon: BarChart3,
  },
  {
    id: "heatmap",
    title: "Heatmap",
    description: "Coding density — file × code or case × code.",
    icon: Flame,
  },
  {
    id: "codebook",
    title: "Codebook",
    description: "Plain-text codebook export (category>>subcategory>>code).",
    icon: BookOpen,
  },
  {
    id: "references",
    title: "References",
    description: "Bibliographic references imported from RIS or Zotero.",
    icon: Table,
  },
];

const REPORT_COMPONENTS: Record<ReportId, ComponentType> = {
  "code-frequencies": CodeFrequenciesReport,
  "codes-by-segments": CodesBySegmentsReport,
  "comparison-table": ComparisonTableReport,
  "co-occurrence": CooccurrenceReport,
  "exact-matches": ExactMatchesReport,
  "file-summary": FileSummaryReport,
  "coder-comparison": CoderComparisonReport,
  "interrater": InterraterReport,
  attributes: AttributesReport,
  sql: SqlReport,
  "code-segments": CodeSegmentsReport,
  "code-summary": CodeSummaryReport,
  "coder-file-comparison": CoderFileComparisonReport,
  "code-relations": CodeRelationsReport,
  "word-cloud": WordCloudReport,
  cumulative: CumulativeChart,
  stacked: StackedChart,
  heatmap: HeatmapReport,
  codebook: CodebookReport,
  references: ReferencesReport,
};

export function AnalyzeView() {
  const { t } = useI18n();
  const [selected, setSelected] = useState<ReportId | null>(null);
  const meta = selected ? REPORT_META.find((r) => r.id === selected) : undefined;
  const ReportComponent = selected ? REPORT_COMPONENTS[selected] : null;

  return (
    <div className="flex h-full flex-col bg-bg">
      <ViewHeader
        title="Analysis"
        meta={meta ? <span>· {meta.title}</span> : undefined}
        actions={
          <>
            {selected && (
              <Button
                variant="secondary"
                icon={<ArrowLeft size={14} aria-hidden />}
                aria-label={t("analyze.backToReports")}
                onClick={() => setSelected(null)}
              >
                {t("analyze.backToReports")}
              </Button>
            )}
          </>
        }
      />

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {ReportComponent ? (
          <ReportComponent />
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {REPORT_META.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setSelected(r.id)}
                className="flex items-start gap-3 rounded-lg border border-border bg-surface p-4 text-left hover:bg-surface-higher"
              >
                <span className="rounded-sm bg-surface-higher p-2 text-accent">
                  <r.icon size={18} aria-hidden />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-text-primary">{r.title}</span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-text-secondary">
                    {r.description}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
