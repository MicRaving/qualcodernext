/**
 * CsvCoder — tabular source coding workspace (CSV/TSV): a real table view
 * with the header row rendered as a sticky header (columns detected from
 * the parsed header) and a "Plain text" toggle that switches to the
 * embedded TextCoder, so coding always happens against the source's raw
 * text (the source is media_type "text").
 *
 *  Table side: the source's fulltext is parsed with the shared RFC-4180
 *  parser (lib/csv.ts — quoted fields, escaped quotes, embedded newlines,
 *  CRLF/LF, TSV auto-detection); the header row labels the columns and the
 *  body scrolls (vertical + horizontal for wide tables) under a sticky
 *  header. The toggle pair mirrors the HtmlCoder/PdfCoder split pattern:
 *  both buttons are always visible and exactly one view is active.
 *
 *  Plain-text side: the embedded TextCoder runs in controlled mode
 *  (bare + forceText), the parent owning codings/annotations/codes — the
 *  exact pattern PdfCoder/HtmlCoder use — so text codings on the source
 *  keep working unchanged.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { CircleAlert, FileText, Table2 } from "lucide-react";
import { Button, ErrorBanner, LoadingState, ViewHeader } from "@/components/ui/orchestrator";
import { api, type Annotation, type CodeTreeItem, type Coding, type Source } from "@/lib/api";
import { TextCoder } from "@/features/coding/TextCoder";
import { parseCsv } from "@/lib/csv";
import { tdCls, thCls } from "@/features/analyze/reportData";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";

/** Which view is active — a single state so the two toggles can never be
 *  both off (mirrors the HtmlCoder/PdfCoder never-both-off rule). */
type CsvView = "table" | "plain";

export function CsvCoder({ source }: { source: Source }) {
  const { t } = useI18n();
  const [view, setView] = useState<CsvView>("table");

  const [codings, setCodings] = useState<Coding[]>([]);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [codes, setCodes] = useState<CodeTreeItem[]>([]);
  const [fulltext, setFulltext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const refreshCodings = useCallback(async () => {
    setCodings(await api.sourceCoding(source.id));
  }, [source.id]);

  const refreshAnnotations = useCallback(async () => {
    setAnnotations(await api.fileAnnotations(source.id));
  }, [source.id]);

  const refreshCodes = useCallback(async () => {
    setCodes(await api.codesFlat());
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setCodings([]);
    setAnnotations([]);
    setCodes([]);
    setFulltext(null);
    void (async () => {
      try {
        const [cod, anns, flat, src] = await Promise.all([
          api.sourceCoding(source.id),
          api.fileAnnotations(source.id),
          api.codesFlat(),
          api.getSource(source.id),
        ]);
        if (cancelled) return;
        setCodings(cod);
        setAnnotations(anns);
        setCodes(flat);
        setFulltext(src.fulltext ?? source.fulltext ?? null);
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : t("csvCoder.loadCodingsError"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source.id, source.fulltext, reloadTick, t]);

  // History undo/redo: reload codings/annotations when the audit log
  // reverts a change (the shell only refreshes project metadata).
  useEffect(() => {
    const handle = () => {
      void refreshCodings();
      void refreshAnnotations();
      void refreshCodes();
    };
    window.addEventListener("qc:codings-changed", handle);
    return () => window.removeEventListener("qc:codings-changed", handle);
  }, [refreshCodings, refreshAnnotations, refreshCodes]);

  /** The parsed table — columns detected from the header row. */
  const parsed = useMemo(() => (fulltext != null ? parseCsv(fulltext) : null), [fulltext]);

  if (loading) {
    return <LoadingState>{t("csvCoder.loading")}</LoadingState>;
  }

  if (loadError) {
    return (
      <div className="flex h-full items-center justify-center bg-bg">
        <div className="max-w-md text-center">
          <p className="flex items-center justify-center gap-1.5 text-sm text-danger">
            <CircleAlert size={16} aria-hidden />
            {loadError}
          </p>
          <Button variant="secondary" className="mt-3" onClick={() => setReloadTick((v) => v + 1)}>
            {t("common.retry")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-bg">
      <ViewHeader
        wrap
        title={source.name}
        meta={source.memo}
        actions={
          <>
            {parsed && parsed.headers.length > 0 && (
              <span className="shrink-0 text-xs text-text-secondary">
                {t("csvCoder.columnsRows", {
                  columns: parsed.headers.length,
                  rows: parsed.rows.length,
                })}
              </span>
            )}
            <div className="flex flex-wrap items-center gap-1">
              <Button
                variant="secondary"
                className={cn(
                  "h-7 shrink-0",
                  view === "table" ? "border-accent text-accent" : "bg-bg text-text-secondary",
                )}
                onClick={() => setView("table")}
                aria-pressed={view === "table"}
                title={t("csvCoder.tableHint")}
                icon={<Table2 size={12} aria-hidden />}
              >
                {t("csvCoder.table")}
              </Button>
              <Button
                variant="secondary"
                className={cn(
                  "h-7 shrink-0",
                  view === "plain" ? "border-accent text-accent" : "bg-bg text-text-secondary",
                )}
                onClick={() => setView("plain")}
                aria-pressed={view === "plain"}
                title={t("csvCoder.plainTextHint")}
                icon={<FileText size={12} aria-hidden />}
              >
                {t("csvCoder.plainText")}
              </Button>
            </div>
          </>
        }
      />

      {errMsg && <ErrorBanner onClose={() => setErrMsg(null)}>{errMsg}</ErrorBanner>}

      {view === "plain" ? (
        <TextCoder
          sourceId={source.id}
          forceText
          bare
          codings={codings}
          annotations={annotations}
          codes={codes}
          onCodingsChange={setCodings}
          onAnnotationsChange={setAnnotations}
          onCodesChange={setCodes}
        />
      ) : parsed && parsed.headers.length > 0 ? (
        <div className="min-h-0 flex-1 overflow-auto bg-bg">
          <table className="w-max min-w-full border-collapse text-sm">
            <thead>
              <tr>
                {parsed.headers.map((header, col) => (
                  <th
                    key={`${col}-${header}`}
                    className={cn(thCls, "sticky top-0 z-10 whitespace-nowrap bg-surface")}
                  >
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {parsed.rows.map((row, ri) => (
                <tr key={ri} className="hover:bg-surface-higher">
                  {row.map((cell, ci) => (
                    <td
                      key={ci}
                      className={cn(tdCls, "max-w-96 truncate whitespace-nowrap")}
                      title={cell}
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center bg-bg">
          <p className="max-w-md px-6 text-center text-sm text-text-secondary">
            {t("csvCoder.noData")}
          </p>
        </div>
      )}
    </div>
  );
}
