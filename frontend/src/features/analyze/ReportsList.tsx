/**
 * ReportsList — the Analysis area's left bar (rendered in the LEFT BAR slot
 * of the workspace instead of the standard Sidebar).
 *
 * Follows the orchestrator: a `LeftBar` shell with a fixed `BarHeader`
 * (title + count + actions) and the report entries as canonical list rows
 * (border-b, selected bg-accent/10). The selection lives in the project
 * store so the center view stays in sync. "Graphs" is a pseudo-entry that
 * switches the center to the code-map editor.
 */
import { ANALYSIS, TOOLS, type NavEntry } from "@/features/analyze/registry";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";
import { BarHeader, LeftBar, SectionLabel } from "@/components/ui/orchestrator";
import { cn } from "@/lib/utils";
import { Network } from "lucide-react";

export function ReportsList() {
  const { t } = useI18n();
  const selectedId = useProjectStore((s) => s.analyzeUi.selectedId);
  const setAnalyzeUi = useProjectStore((s) => s.setAnalyzeUi);

  const renderRow = (entry: NavEntry) => {
    const active = selectedId === entry.id;
    return (
      <div
        key={entry.id}
        role="button"
        tabIndex={0}
        onClick={() => setAnalyzeUi({ selectedId: entry.id })}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") setAnalyzeUi({ selectedId: entry.id });
        }}
        aria-label={t(entry.titleKey)}
        aria-current={active ? "page" : undefined}
        className={cn(
          "flex cursor-pointer items-center gap-2 border-b border-border px-3 py-2 hover:bg-surface-higher",
          active && "bg-accent/10",
        )}
      >
        <entry.icon size={14} className="shrink-0 text-text-secondary" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{t(entry.titleKey)}</span>
          <span className="block truncate text-xs text-text-secondary">
            {t(entry.descriptionKey)}
          </span>
        </span>
      </div>
    );
  };

  const graphsActive = selectedId === "graphs";

  return (
    <LeftBar
      header={
        <BarHeader
          title={t("nav.analyze")}
          count={ANALYSIS.length + TOOLS.length}
        />
      }
    >
      <div className="border-b border-border" />
      {ANALYSIS.map(renderRow)}
      <div className="px-3 pb-1 pt-3">
        <SectionLabel>{t("analyze.tools")}</SectionLabel>
      </div>
      {TOOLS.map(renderRow)}
      <div className="px-3 pb-1 pt-3">
        <SectionLabel>{t("graphs.title")}</SectionLabel>
      </div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => setAnalyzeUi({ selectedId: "graphs" })}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") setAnalyzeUi({ selectedId: "graphs" });
        }}
        aria-label={t("graphs.title")}
        aria-current={graphsActive ? "page" : undefined}
        className={cn(
          "flex cursor-pointer items-center gap-2 border-b border-border px-3 py-2 hover:bg-surface-higher",
          graphsActive && "bg-accent/10",
        )}
      >
        <Network size={14} className="shrink-0 text-text-secondary" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{t("graphs.title")}</span>
          <span className="block truncate text-xs text-text-secondary">
            {t("graphs.subtitle")}
          </span>
        </span>
      </div>
    </LeftBar>
  );
}
