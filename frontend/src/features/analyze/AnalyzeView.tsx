/**
 * AnalyzeView — the Analysis area's CENTER view: renders the report
 * selected in the reports left bar (ReportsList). The left bar itself is
 * a workspace slot filled by ProjectShell; this view never builds bars.
 *
 * The ViewHeader's actions slot hosts the current report's buttons: reports
 * register them through <ReportMenuBar> (reportKit) and they appear here.
 */
import { useState, type ReactNode } from "react";
import { ANALYSIS, TOOLS, REPORT_COMPONENTS } from "@/features/analyze/registry";
import { PublishButton } from "@/features/analyze/PublishDialog";
import { useI18n } from "@/lib/i18n";
import { useWorkspaceStore } from "@/stores/workspace";
import { ViewHeader } from "@/components/ui/orchestrator";
import { ReportMenuBarProvider } from "@/features/analyze/reportKit";

export function AnalyzeView() {
  const { t } = useI18n();
  const selectedId = useWorkspaceStore((s) => s.analyzeUi.selectedId);
  const meta = [...ANALYSIS, ...TOOLS].find((r) => r.id === selectedId);
  const ReportComponent = selectedId ? REPORT_COMPONENTS[selectedId] : null;
  const [menuActions, setMenuActions] = useState<ReactNode>(null);

  if (!ReportComponent) return null;

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col bg-bg">
      <ViewHeader
        back={false}
        title={t("analyze.title")}
        meta={meta ? <span>· {t(meta.titleKey)}</span> : undefined}
        actions={
          <>
            <PublishButton />
            {menuActions}
          </>
        }
      />
      <div className="qc-scroll min-h-0 flex-1 overflow-y-auto p-4">
        <ReportMenuBarProvider actions={menuActions} setActions={setMenuActions}>
          <ReportComponent />
        </ReportMenuBarProvider>
      </div>
    </section>
  );
}
