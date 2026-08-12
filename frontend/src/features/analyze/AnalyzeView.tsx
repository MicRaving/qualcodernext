/**
 * AnalyzeView — the Analysis area's CENTER view: renders the report
 * selected in the reports left bar (ReportsList). The left bar itself is
 * a workspace slot filled by ProjectShell; this view never builds bars.
 */
import { ANALYSIS, TOOLS, REPORT_COMPONENTS } from "@/features/analyze/registry";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";
import { ViewHeader } from "@/components/ui/orchestrator";

export function AnalyzeView() {
  const { t } = useI18n();
  const selectedId = useProjectStore((s) => s.analyzeUi.selectedId);
  const meta = [...ANALYSIS, ...TOOLS].find((r) => r.id === selectedId);
  const ReportComponent = selectedId ? REPORT_COMPONENTS[selectedId] : null;

  if (!ReportComponent) return null;

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col bg-bg">
      <ViewHeader
        back={false}
        title={t("analyze.title")}
        meta={meta ? <span>· {t(meta.titleKey)}</span> : undefined}
      />
      <div className="qc-scroll min-h-0 flex-1 overflow-y-auto p-4">
        <ReportComponent />
      </div>
    </section>
  );
}
