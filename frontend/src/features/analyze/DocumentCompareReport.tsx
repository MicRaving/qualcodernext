/**
 * Document comparison chart (MAXQDA-style).
 *
 * Picks two documents and aligns their code sequences side by side:
 *  - a two-column chart of code-colored blocks with position-proportional
 *    heights and SVG connector lines between the LCS-aligned rows;
 *  - a stats card with the Dice (code-set) similarity and the sequence
 *    alignment ratio (2·LCS/(n1+n2));
 *  - per-code co-occurrence counts;
 *  - CSV export of the per-position alignment table.
 *
 * Clicking a block jumps to the segment in the coder (same store pattern
 * as the Inspector's "recent segments" list).
 *
 * The /compare endpoint is not in lib/api.ts, so it follows the local-fetch
 * pattern from statsApi.ts (initApiBase + fetchWithTimeout, single retry on
 * network-level failure for the packaged-backend restart case).
 */
import { useMemo, useRef, useState } from "react";
import {
  CircleAlert,
  FileText,
  GitCompareArrows,
  LoaderCircle,
  MousePointerClick,
} from "lucide-react";
import { localRequest } from "@/lib/api";
import { cn, errorMessage } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace";
import { useInspectorStore } from "@/stores/inspector";
import { useProjectStore } from "@/stores/project";
import { useI18n } from "@/lib/i18n";
import { Button, EmptyState, Input, SectionLabel } from "@/components/ui/orchestrator";
import { cardCls, tdCls, thCls } from "@/features/analyze/reportData";
import {
  ColorSwatch,
  ReportCsvButton,
  ReportMenuBar,
} from "@/features/analyze/reportKit";

export interface ComparePosition {
  ctid: number;
  cid: number;
  code_name: string;
  color: string;
  pos0: number;
  pos1: number;
  seltext: string;
  aligned: boolean;
}

export interface CompareRow {
  a: ComparePosition | null;
  b: ComparePosition | null;
  aligned: boolean;
}

export interface CompareResult {
  fid1: number;
  fid2: number;
  file1: string;
  file2: string;
  seq1: ComparePosition[];
  seq2: ComparePosition[];
  rows: CompareRow[];
  similarity: {
    dice: number;
    sequence: number;
    lcs: number;
    n1: number;
    n2: number;
  };
  cooccurrence: {
    cid: number;
    name: string;
    color: string;
    count1: number;
    count2: number;
    matched: number;
  }[];
}

async function fetchCompare(fid1: number, fid2: number): Promise<CompareResult> {
  return localRequest<CompareResult>(`/compare?fid1=${fid1}&fid2=${fid2}`);
}

/** Readable label color on a code's block background. */
function readableTextOn(hex: string): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return "rgba(0, 0, 0, 0.65)";
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16) / 255);
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return lum > 0.55 ? "rgba(0, 0, 0, 0.7)" : "rgba(255, 255, 255, 0.9)";
}

interface ChartItem {
  row: CompareRow;
  aH: number;
  bH: number;
  h: number;
  y: number;
}

/** Position-proportional block heights over the longer document, with a
 *  minimum so tiny segments stay clickable. Returns each row's pixel
 *  geometry — the DOM rows and the SVG connector overlay derive from it,
 *  so the lines always land on the block centers. */
function layoutChart(rows: CompareRow[], span1: number, span2: number): { items: ChartItem[]; total: number } {
  const pxPerChar = 520 / Math.max(1, Math.max(span1, span2));
  const minH = 6;
  let y = 0;
  const items = rows.map((row) => {
    const aH = row.a ? Math.max(minH, (row.a.pos1 - row.a.pos0) * pxPerChar) : 0;
    const bH = row.b ? Math.max(minH, (row.b.pos1 - row.b.pos0) * pxPerChar) : 0;
    const h = Math.max(aH, bH, minH);
    const item: ChartItem = { row, aH, bH, h, y };
    y += h + 2;
    return item;
  });
  return { items, total: Math.max(1, y - 2) };
}

export function DocumentCompareView() {
  const { t } = useI18n();
  const sources = useProjectStore((s) => s.sources);
  const setView = useWorkspaceStore((s) => s.setView);
  const setGotoSegment = useInspectorStore((s) => s.setGotoSegment);
  const [nameA, setNameA] = useState("");
  const [nameB, setNameB] = useState("");
  const [result, setResult] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestSeq = useRef(0);

  const textSources = useMemo(
    () =>
      sources
        .filter((s) => s.media_type === "text")
        .sort((x, y) => x.name.localeCompare(y.name)),
    [sources],
  );

  function handleCompare() {
    const a = textSources.find((s) => s.name === nameA);
    const b = textSources.find((s) => s.name === nameB);
    if (!a || !b) {
      setResult(null);
      setError(t("analyze.compareUnknownFile"));
      return;
    }
    if (a.id === b.id) {
      setResult(null);
      setError(t("analyze.compareSameFile"));
      return;
    }
    const seq = ++requestSeq.current;
    setLoading(true);
    setError(null);
    fetchCompare(a.id, b.id)
      .then((r) => {
        if (seq === requestSeq.current) setResult(r);
      })
      .catch((err) => {
        if (seq === requestSeq.current) {
          setResult(null);
          setError(errorMessage(err, "Failed to compare"));
        }
      })
      .finally(() => {
        if (seq === requestSeq.current) setLoading(false);
      });
  }

  function jumpTo(pos: ComparePosition, fid: number) {
    setView({ kind: "coding", sourceId: fid });
    setGotoSegment({ ctid: pos.ctid, pos0: pos.pos0, pos1: pos.pos1 });
  }

  if (textSources.length === 0) {
    return (
      <div className="space-y-4">
        <EmptyState icon={<FileText size={24} aria-hidden />}>
          {t("analyze.compareNoTextSources")}
        </EmptyState>
      </div>
    );
  }

  const pickers = (
    <div className="flex flex-wrap items-end gap-2">
      <label className="block min-w-52">
        <span className="mb-1 block text-xs text-text-secondary">{t("analyze.compareFileA")}</span>
        <Input
          list="compare-files-a"
          value={nameA}
          onChange={(e) => setNameA(e.target.value)}
          placeholder={t("analyze.compareFilePlaceholder")}
          aria-label={t("analyze.compareFileA")}
        />
        <datalist id="compare-files-a">
          {textSources.map((s) => (
            <option key={s.id} value={s.name} />
          ))}
        </datalist>
      </label>
      <label className="block min-w-52">
        <span className="mb-1 block text-xs text-text-secondary">{t("analyze.compareFileB")}</span>
        <Input
          list="compare-files-b"
          value={nameB}
          onChange={(e) => setNameB(e.target.value)}
          placeholder={t("analyze.compareFilePlaceholder")}
          aria-label={t("analyze.compareFileB")}
        />
        <datalist id="compare-files-b">
          {textSources.map((s) => (
            <option key={s.id} value={s.name} />
          ))}
        </datalist>
      </label>
      <Button
        variant="primary"
        icon={<GitCompareArrows size={13} aria-hidden />}
        onClick={handleCompare}
        disabled={loading || !nameA || !nameB}
      >
        {loading ? t("analyze.computing") : t("analyze.compare")}
      </Button>
    </div>
  );

  return (
    <div className="space-y-4">
      <ReportMenuBar>
        {result && (
          <ReportCsvButton
            filename={`compare-${result.file1.replace(/\.[^.]+$/, "")}-vs-${result.file2.replace(/\.[^.]+$/, "")}.csv`}
            headers={["#", t("analyze.compareFileA"), t("analyze.position"), t("analyze.colSegment"), t("analyze.compareFileB"), t("analyze.position"), t("analyze.colSegment"), t("analyze.aligned")]}
            rows={result.rows.map((r, i) => [
              i + 1,
              r.a ? r.a.code_name : "",
              r.a ? `${r.a.pos0}–${r.a.pos1}` : "",
              r.a?.seltext ?? "",
              r.b ? r.b.code_name : "",
              r.b ? `${r.b.pos0}–${r.b.pos1}` : "",
              r.b?.seltext ?? "",
              r.aligned ? t("analyze.aligned") : t("analyze.unaligned"),
            ])}
          />
        )}
      </ReportMenuBar>
      {pickers}
      {loading && (
        <div className="h-48">
          <LoadingSpinner label={t("analyze.computing")} />
        </div>
      )}
      {error && !loading && (
        <p className="flex items-center gap-1.5 text-xs text-danger">
          <CircleAlert size={13} aria-hidden />
          {error}
        </p>
      )}

      {result && !loading && (
        <>
          <div className={cn(cardCls, "p-4")}>
            <div className="flex flex-wrap gap-x-10 gap-y-3">
              <div>
                <p className="text-xs text-text-secondary">{t("analyze.dice")}</p>
                <p className="mt-0.5 font-mono text-3xl font-semibold tabular-nums text-accent">
                  {result.similarity.dice.toFixed(3)}
                </p>
              </div>
              <div>
                <p className="text-xs text-text-secondary">{t("analyze.sequenceRatio")}</p>
                <p className="mt-0.5 font-mono text-3xl font-semibold tabular-nums text-text-primary">
                  {result.similarity.sequence.toFixed(3)}
                </p>
              </div>
              <div>
                <p className="text-xs text-text-secondary">{t("analyze.aligned")}</p>
                <p className="mt-0.5 font-mono text-3xl font-semibold tabular-nums text-text-primary">
                  {result.similarity.lcs}
                </p>
              </div>
              <div>
                <p className="text-xs text-text-secondary">{t("analyze.segments")}</p>
                <p className="mt-0.5 text-sm tabular-nums text-text-primary">
                  {t("analyze.segmentsVs", { a: result.similarity.n1, b: result.similarity.n2 })}
                </p>
              </div>
            </div>
          </div>

          <section>
            <SectionLabel>{t("analyze.alignmentChart")}</SectionLabel>
            <Chart result={result} jumpTo={jumpTo} />
            <p className="mt-1.5 flex items-center gap-1.5 text-xs text-text-secondary">
              <MousePointerClick size={12} aria-hidden />
              {t("analyze.compareHint")}
            </p>
          </section>

          <section>
            <SectionLabel>{t("analyze.cooccurrenceTitle")}</SectionLabel>
            <div className={cn(cardCls, "mt-2")}>
              <table className="w-full border-collapse">
                <thead className="sticky top-0 z-10">
                  <tr>
                    <th className={thCls}>{t("analyze.colCode")}</th>
                    <th className={cn(thCls, "text-right")}>{t("analyze.colDocA")}</th>
                    <th className={cn(thCls, "text-right")}>{t("analyze.colDocB")}</th>
                    <th className={cn(thCls, "text-right")}>{t("analyze.colMatched")}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.cooccurrence.map((c) => (
                    <tr key={c.cid} className="hover:bg-surface-higher">
                      <td className={tdCls}>
                        <span className="flex items-center gap-2">
                          <ColorSwatch color={c.color} />
                          <span className="truncate font-medium">{c.name}</span>
                        </span>
                      </td>
                      <td className={cn(tdCls, "text-right tabular-nums")}>{c.count1}</td>
                      <td className={cn(tdCls, "text-right tabular-nums")}>{c.count2}</td>
                      <td className={cn(tdCls, "text-right tabular-nums")}>{c.matched}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      {!result && !loading && !error && (
        <EmptyState icon={<GitCompareArrows size={24} aria-hidden />}>
          {t("analyze.compareNoData")}
        </EmptyState>
      )}
    </div>
  );
}

function LoadingSpinner({ label }: { label: string }) {
  return (
    <div className="flex h-full items-center justify-center gap-2 text-text-secondary">
      <LoaderCircle size={16} className="animate-spin" aria-hidden />
      <span className="text-sm">{label}</span>
    </div>
  );
}

function Chart({
  result,
  jumpTo,
}: {
  result: CompareResult;
  jumpTo: (pos: ComparePosition, fid: number) => void;
}) {
  const lenA = result.seq1.length > 0 ? Math.max(...result.seq1.map((p) => p.pos1)) : 0;
  const lenB = result.seq2.length > 0 ? Math.max(...result.seq2.map((p) => p.pos1)) : 0;
  const { items, total } = layoutChart(result.rows, lenA, lenB);

  return (
    <div className={cn(cardCls, "mt-2 p-2")}>
      <div className="flex">
        <div className="w-[48%] truncate text-center text-xs font-medium text-text-primary">
          {result.file1}
        </div>
        <div className="w-[4%]" />
        <div className="w-[48%] truncate text-center text-xs font-medium text-text-primary">
          {result.file2}
        </div>
      </div>
      <div className="relative">
        <div className="flex flex-col" style={{ gap: 2 }}>
          {items.map((it, i) => (
            <div key={i} className="flex" style={{ height: it.h }}>
              <div className="flex w-[48%] items-center justify-end">
                {it.row.a && (
                  <Block pos={it.row.a} fid={result.fid1} h={it.aH} jumpTo={jumpTo} />
                )}
              </div>
              <div className="w-[4%]" />
              <div className="flex w-[48%] items-center justify-start">
                {it.row.b && (
                  <Block pos={it.row.b} fid={result.fid2} h={it.bH} jumpTo={jumpTo} />
                )}
              </div>
            </div>
          ))}
        </div>
        <svg
          className="pointer-events-none absolute inset-0 h-full w-full"
          viewBox={`0 0 100 ${total}`}
          preserveAspectRatio="none"
          aria-hidden
        >
          {items
            .filter((it) => it.row.aligned && it.row.a && it.row.b)
            .map((it, i) => (
              <line
                key={i}
                x1={24}
                y1={it.y + it.h / 2}
                x2={76}
                y2={it.y + it.h / 2}
                stroke="var(--qc-border)"
                strokeWidth={1.5}
                strokeDasharray="3 2"
              />
            ))}
        </svg>
      </div>
    </div>
  );
}

function Block({
  pos,
  fid,
  h,
  jumpTo,
}: {
  pos: ComparePosition;
  fid: number;
  h: number;
  jumpTo: (pos: ComparePosition, fid: number) => void;
}) {
  const { t } = useI18n();
  return (
    <button
      type="button"
      onClick={() => jumpTo(pos, fid)}
      title={`${pos.code_name} [${pos.pos0}–${pos.pos1}] · ${t("analyze.compareHint")}\n${pos.seltext}`}
      className={cn(
        "relative w-full overflow-hidden rounded-sm border",
        pos.aligned
          ? "border-black/20 hover:ring-1 hover:ring-accent"
          : "border-black/10 opacity-75 hover:opacity-100 hover:ring-1 hover:ring-accent",
      )}
      style={{ height: h, backgroundColor: pos.color }}
    >
      {h >= 18 && (
        <span
          className="pointer-events-none absolute inset-0 flex items-center justify-center truncate px-1 text-[10px] font-medium"
          style={{ color: readableTextOn(pos.color) }}
        >
          {pos.code_name}
        </span>
      )}
    </button>
  );
}
