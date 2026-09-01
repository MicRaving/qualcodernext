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
 *  header. Coding works DIRECTLY in the table: selecting text inside a
 *  cell opens the shared SelectionToolbar (code / annotate / in-vivo /
 *  links / QTT), and ONLY the marked characters get the code tint plus a
 *  code badge (annotated spans get a dashed underline) — a coding never
 *  tints the whole cell. Clicking a coded cell or badge opens the shared
 *  CodingDetailsBar / AnnotationDetailsBar below the table. Cell spans
 *  map 1:1 onto the source text via the parser's per-cell raw offsets.
 *
 *  Plain-text side: the embedded TextCoder runs in controlled mode
 *  (bare + forceText), the parent owning codings/annotations/codes — the
 *  exact pattern PdfCoder/HtmlCoder use — so text codings on the source
 *  keep working unchanged.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import { useAsyncEffect } from "@/lib/useAsync";
import { FileText, Table2, Undo2 } from "lucide-react";
import {
  Button,
  ErrorBanner,
  LoadError,
  LoadingState,
  ViewHeader,
} from "@/components/ui/orchestrator";
import { api, type Annotation, type CodeTreeItem, type Coding, type Source } from "@/lib/api";
import { TextCoder } from "@/features/coding/TextCoder";
import { SelectionToolbar } from "@/features/coding/SelectionToolbar";
import {
  AnnotationDetailsBar,
  CodingDetailsBar,
} from "@/features/coding/DetailsBars";
import { useCodeIndex } from "@/features/coding/codingApi";
import { useSegmentActions } from "@/features/coding/shared/useSegmentActions";
import { clampToolbarAnchor } from "@/features/coding/shared/toolbarAnchor";
import { parseCsv } from "@/lib/csv";
import { tdCls, thCls } from "@/features/analyze/reportData";
import { getSelectionOffsets } from "@/features/coding/selection";
import { FALLBACK_CODE_COLOR, codeTint } from "@/features/coding/tint";
import { cn, errorMessage } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";
import { useCoderStore } from "@/stores/coder";

/** Which view is active — a single state so the two toggles can never be
 *  both off (mirrors the HtmlCoder/PdfCoder never-both-off rule). */
type CsvView = "table" | "plain";

/** Fallback badge/tint color when a code carries none. */

/** A cell's text range in the raw source (row/col resolved via spans). */
interface CellSpan {
  start: number;
  end: number;
  ri: number;
  ci: number;
  /** Field-char → raw-char map (for sub-span highlights). */
  toRaw: number[];
}

/** A field-char range carrying a visual mark. */
interface MarkSeg {
  start: number;
  end: number;
  /** Background tint (coded span); null = no tint. */
  color: string | null;
  /** Dashed underline (annotated span). */
  underline: boolean;
}

/** Everything derived for one cell (key `${ri}:${ci}`). */
interface CellInfo {
  codings: Coding[];
  annotations: Annotation[];
  /** Distinct codes (by id, first-appearance order) for the badge cluster. */
  badges: CodeTreeItem[];
  /** Field-char ranges covered by codings (disjoint, first code's color). */
  highlights: MarkSeg[];
  /** Field-char ranges covered by annotations (disjoint). */
  annHighlights: MarkSeg[];
}

/** Shared empty cell — read-only fallback for cells without any codings. */
const EMPTY_CELL_INFO: CellInfo = {
  codings: [],
  annotations: [],
  badges: [],
  highlights: [],
  annHighlights: [],
};

/** Field chars of a cell whose raw offset lies inside [pos0, pos1), or
 *  null when the span does not reach the cell. ``toRaw`` is ascending. */
function fieldRangeInRaw(toRaw: number[], pos0: number, pos1: number): [number, number] | null {
  let lo = 0;
  let hi = toRaw.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (toRaw[mid] < pos0) lo = mid + 1;
    else hi = mid;
  }
  const start = lo;
  if (start >= toRaw.length || toRaw[start] >= pos1) return null;
  let end = start;
  while (end < toRaw.length && toRaw[end] < pos1) end++;
  return [start, end];
}

/** Sort + merge overlapping ranges (first range's color wins). */
function mergeRanges(ranges: MarkSeg[]): MarkSeg[] {
  if (ranges.length === 0) return [];
  const sorted = [...ranges].sort((a, b) => a.start - b.start || b.end - a.end);
  const out: MarkSeg[] = [];
  for (const r of sorted) {
    const last = out[out.length - 1];
    if (last && r.start <= last.end) {
      if (r.end > last.end) last.end = r.end;
    } else {
      out.push({ ...r });
    }
  }
  return out;
}

/** Split the cell text at every mark boundary; coded chars get the code
 *  tint, annotated chars the dashed underline (spans add no text, so
 *  selection offsets stay intact). */
function renderMarkedText(text: string, segs: MarkSeg[]): ReactNode {
  if (segs.length === 0) return text;
  const out: ReactNode[] = [];
  let pos = 0;
  for (const s of segs) {
    if (s.start > pos) out.push(text.slice(pos, s.start));
    const inner = s.color ? (
      <span
        key={`c${s.start}`}
        className="rounded-sm"
        style={{ backgroundColor: codeTint(s.color) }}
      >
        {text.slice(s.start, s.end)}
      </span>
    ) : (
      text.slice(s.start, s.end)
    );
    out.push(
      s.underline ? (
        <span
          key={`u${s.start}`}
          className="underline decoration-dashed decoration-text-secondary underline-offset-2"
        >
          {inner}
        </span>
      ) : (
        inner
      ),
    );
    pos = s.end;
  }
  if (pos < text.length) out.push(text.slice(pos));
  return out;
}

export function CsvCoder({ source }: { source: Source }) {
  const { t } = useI18n();
  const [view, setView] = useState<CsvView>("table");

  const [codings, setCodings] = useState<Coding[]>([]);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [fulltext, setFulltext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  /** The code list is the project store's tree (the backend serves it flat;
   *  the sidebar refreshes it on every code change, so names stay fresh when
   *  a code is created while this coder is open). */
  /** The code list is the project store's tree (the backend serves it flat;
   *  the sidebar refreshes it on every code change, so names stay fresh when
   *  a code is created while this coder is open). Codes created inside the
   *  embedded TextCoder arrive via onCodesChange and take precedence until
   *  the next full reload folds them into the store tree. */
  const storeCodes = useProjectStore((s) => s.codeTree);
  const [embeddedCodes, setEmbeddedCodes] = useState<CodeTreeItem[] | null>(null);
  const codes = embeddedCodes ?? storeCodes;
  /** Codes hidden in the coder: their badges/highlights are dimmed out of
   *  the table (matching Text/PDF/AV/Image surfaces). */
  const hiddenCodes = useCoderStore((s) => s.hiddenCodes);

  /** The current text selection (in source coordinates) + popup position. */
  const [selection, setSelection] = useState<{ pos0: number; pos1: number; text: string } | null>(
    null,
  );
  const [toolbarAnchor, setToolbarAnchor] = useState<{ left: number; top: number } | null>(null);

  /** Codings/annotations of the cell the user clicked (details bars). */
  const [selectedCodings, setSelectedCodings] = useState<Coding[] | null>(null);
  const [selectedAnnotations, setSelectedAnnotations] = useState<Annotation[] | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);

  const refreshCodings = useCallback(async (): Promise<Coding[]> => {
    const next = await api.sourceCoding(source.id);
    setCodings(next);
    return next;
  }, [source.id]);

  const refreshAnnotations = useCallback(async () => {
    setAnnotations(await api.fileAnnotations(source.id));
  }, [source.id]);

  const refreshCodes = useCallback(async () => {
    await useProjectStore.getState().refreshProject();
  }, []);

  // NOTE: this coder deliberately does NOT use the shared `useCoder` hook —
  // its load fetches codings + annotations + source fulltext together and
  // the code tree comes from the project store (no codesFlat), so it stays
  // bespoke here.
  useAsyncEffect(async (signal) => {
    setLoading(true);
    setLoadError(null);
    setCodings([]);
    setAnnotations([]);
    setFulltext(null);
    setSelection(null);
    setToolbarAnchor(null);
    setEmbeddedCodes(null);
    try {
      const [cod, anns, src] = await Promise.all([
        api.sourceCoding(source.id),
        api.fileAnnotations(source.id),
        api.getSource(source.id),
      ]);
      signal.throwIfAborted();
      setCodings(cod);
      setAnnotations(anns);
      setFulltext(src.fulltext ?? source.fulltext ?? null);
    } catch (e) {
      signal.throwIfAborted();
      setLoadError(errorMessage(e, t("csvCoder.loadCodingsError")));
    } finally {
      signal.throwIfAborted();
      setLoading(false);
    }
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

  const { byId: codeById } = useCodeIndex(codes);

  /** All non-empty cells in text order (row-major) — enables binary-search
   *  overlap lookup, so big tables stay cheap when codings change. Empty
   *  fields (start === end) are skipped: a spanning coding must never tint
   *  a cell that holds no text. */
  const cellIndex = useMemo<CellSpan[]>(() => {
    if (!parsed) return [];
    const list: CellSpan[] = [];
    parsed.cells.forEach((row, ri) =>
      row.forEach((cell, ci) => {
        if (cell.start === cell.end) return;
        list.push({ start: cell.start, end: cell.end, ri, ci, toRaw: cell.toRaw });
      }),
    );
    list.sort((a, b) => a.start - b.start);
    return list;
  }, [parsed]);

  /** Overlapping codings/annotations, badges and sub-span highlights per
   *  cell (key `${ri}:${ci}`). Binary-search overlap lookup keeps big
   *  tables cheap. */
  const cellInfoMap = useMemo(() => {
    const map = new Map<string, CellInfo>();
    if (cellIndex.length === 0) return map;
    const ensure = (key: string): CellInfo => {
      const info = map.get(key);
      if (info) return info;
      const created: CellInfo = {
        codings: [],
        annotations: [],
        badges: [],
        highlights: [],
        annHighlights: [],
      };
      map.set(key, created);
      return created;
    };
    const assign = (start: number, end: number, item: Coding | Annotation) => {
      let lo = 0;
      let hi = cellIndex.length;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (cellIndex[mid].end <= start) lo = mid + 1;
        else hi = mid;
      }
      for (let k = lo; k < cellIndex.length && cellIndex[k].start < end; k++) {
        const info = ensure(`${cellIndex[k].ri}:${cellIndex[k].ci}`);
        if ("anid" in item) info.annotations.push(item as Annotation);
        else info.codings.push(item as Coding);
      }
    };
    for (const c of codings) assign(c.pos0, c.pos1, c);
    for (const a of annotations) assign(a.pos0, a.pos1, a);
    for (const span of cellIndex) {
      const info = map.get(`${span.ri}:${span.ci}`);
      if (!info) continue;
      // Distinct code badges per cell, in first-appearance order. Hidden
      // codes are dimmed out of the badges/highlights but stay on the cell
      // (clicking still opens their details).
      const seen = new Set<number>();
      for (const c of info.codings) {
        if (seen.has(c.cid)) continue;
        seen.add(c.cid);
        if (hiddenCodes.includes(c.cid)) continue;
        const code = codeById.get(c.cid);
        info.badges.push(
          code ?? { kind: "code", id: c.cid, name: "", color: null, parent_id: null, memo: "" },
        );
      }
      // Sub-span marks: only the marked characters are highlighted — a
      // coding must never tint the whole cell.
      info.highlights = mergeRanges(
        info.codings
          .filter((c) => !hiddenCodes.includes(c.cid))
          .map((c): MarkSeg | null => {
            const r = fieldRangeInRaw(span.toRaw, c.pos0, c.pos1);
            if (!r) return null;
            return {
              start: r[0],
              end: r[1],
              color: codeById.get(c.cid)?.color ?? FALLBACK_CODE_COLOR,
              underline: false,
            };
          })
          .filter((r): r is MarkSeg => r !== null),
      );
      info.annHighlights = mergeRanges(
        info.annotations
          .map((a): MarkSeg | null => {
            const r = fieldRangeInRaw(span.toRaw, a.pos0, a.pos1);
            if (!r) return null;
            return { start: r[0], end: r[1], color: null, underline: true };
          })
          .filter((r): r is MarkSeg => r !== null),
      );
    }
    return map;
  }, [cellIndex, codings, annotations, codeById, hiddenCodes]);

  const cellInfo = useCallback(
    (ri: number, ci: number): CellInfo => cellInfoMap.get(`${ri}:${ci}`) ?? EMPTY_CELL_INFO,
    [cellInfoMap],
  );

  /* ------------------------------------------------------------ selection */

  /** Hide only the floating popup — the selection survives (outside click). */
  const hideToolbar = useCallback(() => {
    setToolbarAnchor(null);
  }, []);

  function clearSelection() {
    window.getSelection()?.removeAllRanges();
    setSelection(null);
    setToolbarAnchor(null);
  }

  /** Drop every selection-owned UI state (view switches must not leak the
   *  table selection into the plain-text coder). */
  const resetSelectionUi = useCallback(() => {
    window.getSelection()?.removeAllRanges();
    setSelection(null);
    setToolbarAnchor(null);
    setSelectedCodings(null);
    setSelectedAnnotations(null);
  }, []);

  /** Open the details bars for the cell the user clicked. */
  function handleCellClick(cellEl: HTMLElement) {
    const td = cellEl.closest("td[data-row]") as HTMLElement | null;
    if (!td || !parsed) return;
    const ri = Number(td.dataset.row);
    const ci = Number(td.dataset.col);
    const cell = parsed.cells[ri]?.[ci];
    if (!cell) return;
    const info = cellInfo(ri, ci);
    setSelectedCodings(info.codings.length > 0 ? info.codings : null);
    setSelectedAnnotations(info.annotations.length > 0 ? info.annotations : null);
  }

  /** Select text inside a single cell → show the coding toolbar. Selections
   *  spanning multiple cells are ignored (cells map onto contiguous spans
   *  of the source text, so mixed-cell selections are not codeable). */
  function handleTableMouseUp(e: ReactMouseEvent) {
    const target = e.target as HTMLElement;
    if (target.closest("[data-qc-badge]")) return;
    const cellEl = target.closest("td[data-qc-cell]") as HTMLElement | null;
    if (!cellEl) return;
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
      handleCellClick(cellEl);
      return;
    }
    const span = target.closest("[data-qc-cell-text]") as HTMLElement | null;
    if (!span) return;
    const offsets = getSelectionOffsets(span, sel);
    if (!offsets) return;
    const ri = Number(span.dataset.row);
    const ci = Number(span.dataset.col);
    const cell = parsed?.cells[ri]?.[ci];
    if (!cell || cell.toRaw.length === 0) return;
    const pos0 = cell.toRaw[Math.min(offsets.start, cell.toRaw.length - 1)];
    const last = Math.min(offsets.end - 1, cell.toRaw.length - 1);
    const pos1 = pos0 !== undefined && last >= 0 ? cell.toRaw[last] + 1 : cell.start;
    if (pos1 <= pos0) return;
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    const scrollRect = scrollRef.current?.getBoundingClientRect();
    setToolbarAnchor(clampToolbarAnchor(rect, scrollRect));
    setSelection({ pos0, pos1, text: cell.text.slice(offsets.start, offsets.end) });
  }

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => hideToolbar();
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [hideToolbar]);

  useEffect(() => {
    const onBlur = () => hideToolbar();
    window.addEventListener("blur", onBlur);
    return () => window.removeEventListener("blur", onBlur);
  }, [hideToolbar]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      resetSelectionUi();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [resetSelectionUi]);

  /* ------------------------------------------------------------- mutations */

  /** Show the details bars for a freshly coded cell (parity with the text
   *  coder's auto-show-segment behavior). */
  function handleToolbarCoded(created: Coding, next: Coding[]) {
    void refreshCodes().catch(() => undefined);
    if (!parsed) return;
    for (let ri = 0; ri < parsed.cells.length; ri++) {
      for (let ci = 0; ci < parsed.cells[ri].length; ci++) {
        const cell = parsed.cells[ri][ci];
        if (created.pos0 < cell.end && created.pos1 > cell.start) {
          const cod = next.filter((c) => c.pos0 < cell.end && c.pos1 > cell.start);
          setSelectedCodings(cod.length > 0 ? cod : null);
          setSelectedAnnotations(null);
          return;
        }
      }
    }
  }

  /** Non-coding mutations (annotation, link, QTT): refresh the rest. */
  const handleToolbarChanged = useCallback(() => {
    void refreshAnnotations();
    void refreshCodes().catch(() => undefined);
  }, [refreshAnnotations, refreshCodes]);

  // Shared mutation actions — the undo stack replaces this coder's
  // hand-rolled copy; deletes confirm AND push (recoverable).
  const actions = useSegmentActions({
    kind: "text",
    rows: codings,
    idOf: (r) => r.ctid,
    deleteRow: (ctid) => api.deleteTextCoding(ctid),
    refresh: refreshCodings,
    onError: setErrMsg,
    onDeleted: () => setSelectedCodings(null),
  });
  const { undo } = actions;

  function deleteCoding(row: Coding) {
    actions.remove(row.ctid);
  }

  /** Stepper update of a segment's weight (0-100; 0 = no weight). */
  function updateCodingWeight(row: Coding, weight: number) {
    void actions.updateWeight(row.ctid, weight);
  }

  function updateAnnotationMemo(anid: number, memo: string) {
    void (async () => {
      try {
        await api.updateAnnotation(anid, memo);
        await refreshAnnotations();
      } catch (e) {
        setErrMsg(errorMessage(e, t("coder.annotationUpdateError")));
      }
    })();
  }

  function deleteAnnotation(ann: Annotation) {
    void (async () => {
      try {
        await api.deleteAnnotation(ann.anid);
        setSelectedAnnotations(null);
        await refreshAnnotations();
      } catch (e) {
        setErrMsg(errorMessage(e, t("coder.annotationDeleteError")));
      }
    })();
  }

  /* -------------------------------------------------------------- rendering */

  if (loading) {
    return <LoadingState>{t("csvCoder.loading")}</LoadingState>;
  }

  if (loadError) {
    return <LoadError message={loadError} onRetry={() => setReloadTick((v) => v + 1)} />;
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
                variant="toolbar"
                className={cn(
                  "shrink-0",
                  view === "table" ? "border-accent text-accent" : "bg-bg text-text-secondary",
                )}
                onClick={() => {
                  resetSelectionUi();
                  setView("table");
                }}
                aria-pressed={view === "table"}
                title={t("csvCoder.tableHint")}
                icon={<Table2 size={12} aria-hidden />}
              >
                {t("csvCoder.table")}
              </Button>
              <Button
                variant="toolbar"
                className={cn(
                  "shrink-0",
                  view === "plain" ? "border-accent text-accent" : "bg-bg text-text-secondary",
                )}
                onClick={() => {
                  resetSelectionUi();
                  setView("plain");
                }}
                aria-pressed={view === "plain"}
                title={t("csvCoder.plainTextHint")}
                icon={<FileText size={12} aria-hidden />}
              >
                {t("csvCoder.plainText")}
              </Button>
              <Button
                variant="toolbar"
                icon={<Undo2 size={12} aria-hidden />}
                onClick={undo.undoLast}
                disabled={!undo.canUndo}
                title={t("coder.unmarkTitle")}
              >
                {t("coder.unmarkLast")}
              </Button>
            </div>
          </>
        }
      />

      {errMsg && <ErrorBanner onClose={() => setErrMsg(null)}>{errMsg}</ErrorBanner>}

      {view === "plain" ? (
        <div className="min-h-0 flex-1 overflow-hidden bg-bg qc-enter">
          <TextCoder
            sourceId={source.id}
            forceText
            bare
            codings={codings}
            annotations={annotations}
            codes={codes}
            onCodingsChange={setCodings}
            onAnnotationsChange={setAnnotations}
            onCodesChange={setEmbeddedCodes}
          />
        </div>
      ) : parsed && parsed.headers.length > 0 ? (
        <div
          ref={scrollRef}
          onMouseUp={handleTableMouseUp}
          className="min-h-0 flex-1 overflow-auto bg-bg qc-enter"
        >
          <table className="qc-selectable w-max min-w-full border-collapse text-sm">
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
                  {row.map((cellText, ci) => {
                    const info = cellInfo(ri, ci);
                    const marks = mergeRanges([...info.highlights, ...info.annHighlights]);
                    return (
                      <td
                        key={ci}
                        data-qc-cell
                        data-row={ri}
                        data-col={ci}
                        className={cn(tdCls, "relative max-w-96 align-top")}
                      >
                        <span
                          data-qc-cell-text
                          data-row={ri}
                          data-col={ci}
                          className={cn(
                            "block truncate whitespace-nowrap",
                            info.codings.length > 0 && "pr-14",
                          )}
                          title={cellText}
                        >
                          {renderMarkedText(cellText, marks)}
                        </span>
                        {info.codings.length > 0 && (
                          <span className="absolute right-1 top-0.5 z-10 flex max-w-[80%] items-center gap-0.5">
                            {info.badges.slice(0, 2).map((c) => (
                              <button
                                key={c.id}
                                type="button"
                                data-qc-badge
                                title={badgeTitle(info.codings, codeById, t)}
                                aria-label={badgeTitle(info.codings, codeById, t)}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setSelectedCodings(info.codings);
                                  setSelectedAnnotations(
                                    info.annotations.length > 0 ? info.annotations : null,
                                  );
                                }}
                                className="flex h-4 max-w-28 items-center gap-1 truncate rounded-sm border border-border bg-surface px-1 text-[10px] text-text-primary hover:bg-surface-higher"
                              >
                                <span
                                  className="h-2 w-2 shrink-0 rounded-full"
                                  style={{ backgroundColor: c.color ?? FALLBACK_CODE_COLOR }}
                                  aria-hidden
                                />
                                <span className="truncate">
                                  {c.name || t("coder.fallbackCode", { id: c.id })}
                                </span>
                              </button>
                            ))}
                            {info.badges.length > 2 && (
                              <span className="shrink-0 rounded-sm bg-surface-higher px-1 text-[10px] text-text-secondary">
                                +{info.badges.length - 2}
                              </span>
                            )}
                          </span>
                        )}
                      </td>
                    );
                  })}
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

      {selectedCodings && selectedCodings.length > 0 && (
        <CodingDetailsBar
          rows={selectedCodings}
          codeById={codeById}
          onDelete={deleteCoding}
          onWeight={updateCodingWeight}
          onClose={() => setSelectedCodings(null)}
        />
      )}

      {selectedAnnotations && selectedAnnotations.length > 0 && (
        <AnnotationDetailsBar
          rows={selectedAnnotations}
          onUpdateMemo={updateAnnotationMemo}
          onDelete={deleteAnnotation}
          onClose={() => setSelectedAnnotations(null)}
        />
      )}

      <SelectionToolbar
        anchor={toolbarAnchor}
        selection={selection}
        fid={source.id}
        codes={codes}
        refreshCodings={refreshCodings}
        onCoded={handleToolbarCoded}
        onChanged={handleToolbarChanged}
        onHide={hideToolbar}
        onClose={clearSelection}
        onError={(msg) => setErrMsg(msg)}
      />
    </div>
  );
}

/** Tooltip of a cell's badge cluster: "Code A | Code B | …". */
function badgeTitle(
  cellCodes: Coding[],
  codeById: Map<number, CodeTreeItem>,
  t: (key: string, vars?: Record<string, string>) => string,
): string {
  const seen = new Set<number>();
  const names: string[] = [];
  for (const c of cellCodes) {
    if (seen.has(c.cid)) continue;
    seen.add(c.cid);
    names.push(codeById.get(c.cid)?.name ?? t("coder.fallbackCode", { id: String(c.cid) }));
  }
  return names.join(" | ");
}

