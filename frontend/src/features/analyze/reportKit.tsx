/**
 * Shared report scaffolding — the uniform status/header/swatch cells used
 * by every report view (data loading lives in reportKit.ts).
 */
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { CircleAlert, Download } from "lucide-react";
import { Button, EmptyState, LoadingState } from "@/components/ui/orchestrator";
import { downloadCsv } from "@/lib/csv";
import { tdCls } from "@/features/analyze/reportData";

/** Center-view menu bar: reports register their action buttons here and they
 *  render in the AnalyzeView ViewHeader (actions slot) instead of floating in
 *  the report body. */
const ReportMenuBarContext = createContext<{
  actions: ReactNode;
  setActions: (actions: ReactNode) => void;
} | null>(null);

export function ReportMenuBarProvider({
  actions,
  setActions,
  children,
}: {
  actions: ReactNode;
  setActions: (actions: ReactNode) => void;
  children: ReactNode;
}) {
  return (
    <ReportMenuBarContext.Provider value={{ actions, setActions }}>
      {children}
    </ReportMenuBarContext.Provider>
  );
}

/** Renders its children into the center view's menu bar. A report places this
 *  anywhere in its tree; the buttons live in the ViewHeader. */
export function ReportMenuBar({ children }: { children: ReactNode }) {
  const ctx = useContext(ReportMenuBarContext);
  useEffect(() => {
    ctx?.setActions(children);
    return () => ctx?.setActions(null);
  }, [ctx, children]);
  return null;
}

export function ReportCsvButton({
  filename,
  headers,
  rows,
}: {
  filename: string;
  headers: string[];
  rows: unknown[][];
}) {
  return (
    <Button
      variant="secondary"
      className="text-text-secondary hover:text-text-primary"
      onClick={() => downloadCsv(filename, headers, rows)}
      icon={<Download size={12} aria-hidden />}
    >
      CSV
    </Button>
  );
}

export function ReportStatus({
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
      <div className="h-48">
        <LoadingState>Loading report…</LoadingState>
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
        <Button variant="secondary" onClick={onRetry}>
          Retry
        </Button>
      </div>
    );
  }
  return null;
}

export function ReportHeader({
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
        <Button
          variant="secondary"
          className="text-text-secondary hover:text-text-primary"
          onClick={() => downloadCsv(filename, headers, rows)}
          icon={<Download size={12} aria-hidden />}
        >
          CSV
        </Button>
      </div>
    </div>
  );
}

export function ColorSwatch({ color }: { color: string | null }) {
  return (
    <span
      className="inline-block h-3 w-3 shrink-0 rounded-sm"
      style={{ backgroundColor: color ?? "var(--qc-accent)" }}
      aria-hidden
    />
  );
}

export function CategoryCell({ category }: { category: string }) {
  return (
    <td className={`${tdCls} text-text-secondary`}>
      {category || <span className="italic">—</span>}
    </td>
  );
}

export function EmptyData() {
  return (
    <div className="h-48">
      <EmptyState>No data</EmptyState>
    </div>
  );
}
