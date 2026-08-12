/**
 * Analysis report registry — the single catalog of report screens.
 *
 * The six analytical entries each merge the legacy reports that shared one
 * dataset (see merged.tsx); Codebook / References / SQL live under Tools.
 * The registry drives BOTH the reports left bar (ReportsList) and the
 * center view (AnalyzeView) so they can never drift apart. Titles and
 * descriptions are i18n keys resolved through `t()` at render time.
 */
import type { ComponentType } from "react";
import {
  AlignJustify,
  BarChart3,
  BookOpen,
  CloudSun,
  GitBranch,
  GitCompareArrows,
  Paperclip,
  SquareTerminal,
  Table,
  type LucideIcon,
} from "lucide-react";
import {
  CodeFrequenciesView,
  CodeSegmentsView,
  CodeRelationsView,
  CorpusTextView,
  FileCodeView,
  InterraterView,
} from "@/features/analyze/merged";
import { CodebookReport, ReferencesReport } from "@/features/analyze/upstreamReports";
import { SqlReport } from "@/features/analyze/SqlReport";
import type { ReportId } from "@/stores/project";

export interface NavEntry {
  id: ReportId;
  titleKey: string;
  descriptionKey: string;
  icon: LucideIcon;
}

/** The six analytical screens. */
export const ANALYSIS: NavEntry[] = [
  {
    id: "code-frequencies",
    titleKey: "analyze.titleCodeFrequencies",
    descriptionKey: "analyze.descCodeFrequencies",
    icon: BarChart3,
  },
  {
    id: "code-segments",
    titleKey: "analyze.titleCodeSegments",
    descriptionKey: "analyze.descCodeSegments",
    icon: AlignJustify,
  },
  {
    id: "file-code",
    titleKey: "analyze.fileCodeTitle",
    descriptionKey: "analyze.fileCodeDescription",
    icon: Table,
  },
  {
    id: "code-relations",
    titleKey: "analyze.titleCodeRelations",
    descriptionKey: "analyze.descCodeRelations",
    icon: GitBranch,
  },
  {
    id: "interrater",
    titleKey: "analyze.titleInterrater",
    descriptionKey: "analyze.descInterrater",
    icon: GitCompareArrows,
  },
  {
    id: "text-corpus",
    titleKey: "analyze.titleTextCorpus",
    descriptionKey: "analyze.descTextCorpus",
    icon: CloudSun,
  },
];

/** Non-analytical tools, grouped under their own section in the left bar. */
export const TOOLS: NavEntry[] = [
  {
    id: "codebook",
    titleKey: "analyze.titleCodebook",
    descriptionKey: "analyze.descCodebook",
    icon: BookOpen,
  },
  {
    id: "references",
    titleKey: "analyze.titleReferences",
    descriptionKey: "analyze.descReferences",
    icon: Paperclip,
  },
  {
    id: "sql",
    titleKey: "analyze.titleSql",
    descriptionKey: "analyze.descSql",
    icon: SquareTerminal,
  },
];

export const REPORT_COMPONENTS: Record<ReportId, ComponentType> = {
  "code-frequencies": CodeFrequenciesView,
  "code-segments": CodeSegmentsView,
  "file-code": FileCodeView,
  "code-relations": CodeRelationsView,
  interrater: InterraterView,
  "text-corpus": CorpusTextView,
  codebook: CodebookReport,
  references: ReferencesReport,
  sql: SqlReport,
  graphs: () => null,
};
