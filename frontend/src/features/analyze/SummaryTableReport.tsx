/**
 * Summary table view — a document/case × code grid whose cells hold the
 * coding memos. Cells are editable: each coding memo can be saved through
 * the regular coding PATCH endpoints (local-fetch pattern).
 *
 * Registered by the analysis registry.
 */
import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Button, EmptyState, Pill, Select } from "@/components/ui/orchestrator";
import { cardCls, tdCls, thCls, useReport } from "@/features/analyze/reportData";
import { ColorSwatch, ReportCsvButton, ReportMenuBar, ReportStatus } from "@/features/analyze/reportKit";
import {
  fetchSummaryTable,
  patchCodingMemo,
  type SummaryCellItem,
  type SummaryTableResult,
} from "@/features/analyze/statsApi";

const cellKey = (rowIndex: number, colIndex: number) => `${rowIndex}|${colIndex}`;
const itemKey = (item: SummaryCellItem) => `${item.kind}:${item.id}`;

function recomputeMemo(items: SummaryCellItem[]): { memo: string; memo_count: number } {
  const memos = items.filter((item) => item.memo).map((item) => item.memo);
  return { memo: memos.join(" — "), memo_count: memos.length };
}

export function SummaryTableReportView() {
  const { t } = useI18n();
  const [scope, setScope] = useState<"file" | "case">("file");
  const { data, loading, error, retry } = useReport(
    () => fetchSummaryTable(scope),
    [scope],
  );
  // Local copy so saved memo edits can be reflected without a refetch.
  const [localData, setLocalData] = useState<SummaryTableResult | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    setLocalData(data);
  }, [data]);

  if (loading || error) return <ReportStatus loading={loading} error={error} onRetry={retry} />;

  const grid = localData ?? data;
  if (!grid || grid.rows.length === 0 || grid.codes.length === 0) {
    return (
      <div className="space-y-2">
        <ReportMenuBar>
          <ScopePicker value={scope} onChange={setScope} />
        </ReportMenuBar>
        <div className="h-48">
          <EmptyState>{t("analyze.summaryNoMemos")}</EmptyState>
        </div>
      </div>
    );
  }

  const saveItem = async (
    item: SummaryCellItem,
    rowIndex: number,
    colIndex: number,
  ) => {
    const key = itemKey(item);
    setSavingKey(key);
    setSaveError(null);
    try {
      await patchCodingMemo(item.kind, item.id, drafts[key] ?? item.memo);
      setLocalData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          rows: prev.rows.map((row, ri) =>
            ri === rowIndex
              ? {
                  ...row,
                  cells: row.cells.map((cell, ci) => {
                    if (ci !== colIndex) return cell;
                    const items = cell.items.map((it) =>
                      it.kind === item.kind && it.id === item.id
                        ? { ...it, memo: drafts[key] ?? item.memo }
                        : it,
                    );
                    return { ...cell, items, ...recomputeMemo(items) };
                  }),
                }
              : row,
          ),
        };
      });
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingKey(null);
    }
  };

  return (
    <div className="space-y-2">
      <ReportMenuBar>
        <ScopePicker value={scope} onChange={setScope} />
        <ReportCsvButton
          filename={`summary-table-${scope}.csv`}
          headers={[t("analyze.summaryEntity"), ...grid.codes.map((c) => c.name)]}
          rows={grid.rows.map((row) => [
            row.name,
            ...row.cells.map((cell) =>
              cell.memo_count > 1 ? `${cell.memo} (${cell.memo_count})` : cell.memo,
            ),
          ])}
        />
      </ReportMenuBar>

      <p className="text-xs text-text-secondary">{t("analyze.summaryClickHint")}</p>
      {saveError && <p className="text-xs text-danger">{saveError}</p>}

      <div className={cn(cardCls, "max-h-[70vh]")}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className={cn(thCls, "min-w-40")}>{t("analyze.summaryEntity")}</th>
              {grid.codes.map((c) => (
                <th key={c.cid} className={cn(thCls, "min-w-44")}>
                  <span className="flex items-center gap-1.5">
                    <ColorSwatch color={c.color} />
                    <span className="truncate">{c.name}</span>
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.rows.map((row, ri) => (
              <tr key={row.id} className="align-top hover:bg-surface-higher">
                <td className={cn(tdCls, "max-w-48")}>
                  <span className="block truncate font-medium">{row.name}</span>
                </td>
                {row.cells.map((cell, ci) => {
                  const key = cellKey(ri, ci);
                  if (editing === key) {
                    return (
                      <td key={ci} className={cn(tdCls, "min-w-44")}>
                        <div className="space-y-1.5">
                          {cell.items.length === 0 && (
                            <span className="text-xs italic text-text-secondary">—</span>
                          )}
                          {cell.items.map((item) => {
                            const k = itemKey(item);
                            if (item.kind === "av") {
                              return (
                                <p key={k} className="text-xs text-text-secondary">
                                  {item.memo || "—"}
                                </p>
                              );
                            }
                            return (
                              <div key={k} className="space-y-1">
                                <textarea
                                  value={drafts[k] ?? item.memo}
                                  onChange={(e) =>
                                    setDrafts((prev) => ({ ...prev, [k]: e.target.value }))
                                  }
                                  rows={2}
                                  className="w-full resize-y rounded-sm border border-border bg-bg px-1.5 py-1 text-xs text-text-primary"
                                  aria-label={t("analyze.memo")}
                                />
                                <Button
                                  variant="toolbarPrimary"
                                  disabled={savingKey === k}
                                  onClick={() => void saveItem(item, ri, ci)}
                                >
                                  {savingKey === k ? t("analyze.computing") : t("analyze.summarySave")}
                                </Button>
                              </div>
                            );
                          })}
                          <div>
                            <Button
                              variant="toolbar"
                              onClick={() => setEditing(null)}
                            >
                              {t("analyze.summaryDone")}
                            </Button>
                          </div>
                        </div>
                      </td>
                    );
                  }
                  return (
                    <td key={ci} className={cn(tdCls, "min-w-44")}>
                      <button
                        type="button"
                        className="block w-full text-left"
                        title={t("analyze.summaryEdit")}
                        onClick={() => {
                          setEditing(key);
                          setSaveError(null);
                        }}
                      >
                        <span className="block text-xs text-text-primary">
                          {cell.memo || <span className="italic text-text-secondary">—</span>}
                        </span>
                        {cell.memo_count > 1 && (
                          <Pill className="mt-0.5 tabular-nums">{t("analyze.summaryMemos", { n: cell.memo_count })}</Pill>
                        )}
                      </button>
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

function ScopePicker({
  value,
  onChange,
}: {
  value: "file" | "case";
  onChange: (v: "file" | "case") => void;
}) {
  const { t } = useI18n();
  return (
    <Select
      value={value}
      onChange={(e) => onChange(e.target.value as "file" | "case")}
      aria-label={t("analyze.summaryScope")}
    >
      <option value="file">{t("analyze.summaryFiles")}</option>
      <option value="case">{t("analyze.summaryCases")}</option>
    </Select>
  );
}
