/**
 * Merged report views — the restructured Analysis area.
 *
 * Six analytical screens replace the old 20-tile grid; each merges the
 * reports that shared one underlying dataset:
 *  - Code frequencies   = code-frequencies + cumulative chart + code summary
 *  - Code segments      = codes-by-segments + code-in-all-files + coders-by-file
 *  - File × code        = comparison table + stacked bars + heatmap
 *  - Code relations     = co-occurrence + crossover relations
 *  - Interrater         = coder comparison + agreement measures
 *  - Text & corpus      = word cloud + exact matches + file summary + attributes
 * (Codebook / References / SQL live under the Tools group in the left bar.)
 */
import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { CircleAlert, FileImage, LoaderCircle } from "lucide-react";
import {
  api,
  ApiError,
  fetchWithTimeout,
  initApiBase,
  type ChartMatrix,
  type CodeFrequencyRow,
  type CodeRelation,
  type CodeSegmentRow,
  type CodesBySegmentRow,
  type CoderComparisonRow,
  type CooccurrenceTable,
  type InterraterResult,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useProjectStore } from "@/stores/project";
import { useI18n } from "@/lib/i18n";
import { downloadChartPng } from "@/features/analyze/chartPng";
import { barWidth, formatCount, matrixCell } from "@/features/analyze/reportHelpers";
import {
  AttributesReport,
  ExactMatchesReport,
  FileSummaryReport,
} from "@/features/analyze/reports";
import { WordCloudReport } from "@/features/analyze/upstreamReports";
import {
  Button,
  EmptyState,
  LoadingState,
  SectionLabel,
  Select,
} from "@/components/ui/orchestrator";
import {
  cardCls,
  thCls,
  tdCls,
  useReport,
} from "@/features/analyze/reportData";
import {
  ReportStatus,
  ReportMenuBar,
  ReportCsvButton,
  ColorSwatch,
  CategoryCell,
} from "@/features/analyze/reportKit";

function CodePickerSelect({ value, onChange }: { value: number | ""; onChange: (v: number | "") => void }) {
  const { t } = useI18n();
  const codeTree = useProjectStore((state) => state.codeTree);
  const options = codeTree
    .filter((item) => item.kind === "code")
    .map((item) => ({ cid: item.id, name: item.name }))
    .sort((a, b) => a.name.localeCompare(b.name));
  return (
    <Select value={value} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} className="w-full">
      <option value="">{t("analyze.allCodes")}</option>
      {options.map((c) => (
        <option key={c.cid} value={c.cid}>
          {c.name}
        </option>
      ))}
    </Select>
  );
}

/* --------------------------------------------------------- canvas charts */

function drawCumulativeChart(canvas: HTMLCanvasElement, rows: { name: string; color: string; count: number; cumulative: number }[]) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const dpr = window.devicePixelRatio > 0 ? window.devicePixelRatio : 1;
  const width = canvas.clientWidth || 800;
  const height = 340;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  const pad = { top: 28, right: 16, bottom: 56, left: 16 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const max = Math.max(1, ...rows.map((r) => r.cumulative));
  ctx.strokeStyle = "#d9d9dc";
  ctx.beginPath();
  ctx.moveTo(pad.left, pad.top);
  ctx.lineTo(pad.left, pad.top + plotH);
  ctx.lineTo(pad.left + plotW, pad.top + plotH);
  ctx.stroke();
  ctx.fillStyle = "#1d1d23";
  ctx.font = "bold 13px system-ui, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("Cumulative codings", pad.left, 16);
  const barW = plotW / Math.max(1, rows.length);
  rows.forEach((row, i) => {
    const h = (row.cumulative / max) * plotH;
    const x = pad.left + i * barW + barW * 0.2;
    const w = barW * 0.6;
    const y = pad.top + plotH - h;
    ctx.fillStyle = row.color || "#9a9ab0";
    ctx.fillRect(x, y, w, h);
    ctx.fillStyle = "#6b6b76";
    ctx.font = "10px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(row.name.length > 14 ? `${row.name.slice(0, 13)}…` : row.name, pad.left + i * barW + barW / 2, pad.top + plotH + 12);
    ctx.fillText(String(row.cumulative), pad.left + i * barW + barW / 2, Math.max(12, y - 4));
  });
}

function drawStackedChart(
  canvas: HTMLCanvasElement,
  names: string[],
  series: { name: string; color: string; count: number }[][],
) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const dpr = window.devicePixelRatio > 0 ? window.devicePixelRatio : 1;
  const width = canvas.clientWidth || 800;
  const height = Math.max(220, series.length * 34 + 70);
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  const pad = { top: 28, right: 16, bottom: 8, left: 180 };
  const plotW = width - pad.left - pad.right;
  const max = Math.max(
    1,
    ...series.map((s) => s.reduce((sum, c) => sum + c.count, 0)),
  );
  ctx.fillStyle = "#1d1d23";
  ctx.font = "bold 13px system-ui, sans-serif";
  ctx.fillText("Codings by source", pad.left, 16);
  series.forEach((row, i) => {
    const rowH = 26;
    const y = pad.top + i * (rowH + 8);
    let x = pad.left;
    ctx.fillStyle = "#6b6b76";
    ctx.font = "11px system-ui, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(names[i]?.length > 24 ? `${names[i].slice(0, 23)}…` : (names[i] ?? ""), pad.left - 6, y + rowH / 2 + 3);
    for (const seg of row) {
      const w = (seg.count / max) * plotW;
      if (w > 0) {
        ctx.fillStyle = seg.color || "#9a9ab0";
        ctx.fillRect(x, y, w, rowH);
      }
      x += w;
    }
    const total = row.reduce((sum, c) => sum + c.count, 0);
    ctx.textAlign = "left";
    ctx.fillStyle = "#1d1d23";
    ctx.fillText(String(total), x + 6, y + rowH / 2 + 3);
  });
}

function drawHeatmap(
  canvas: HTMLCanvasElement,
  data: { rowName: string; colName: string; color: string; count: number }[][],
) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const dpr = window.devicePixelRatio > 0 ? window.devicePixelRatio : 1;
  const width = canvas.clientWidth || 800;
  const nRows = Math.max(1, data.length);
  const nCols = data[0]?.length ?? 1;
  const height = Math.max(200, nRows * 24 + 80);
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  const pad = { top: 64, right: 12, bottom: 12, left: 160 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const cellW = plotW / nCols;
  const cellH = plotH / nRows;
  const max = Math.max(
    1,
    ...data.flat().map((c) => c.count),
  );
  ctx.fillStyle = "#1d1d23";
  ctx.font = "bold 13px system-ui, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("Coding heatmap", pad.left, 16);
  data.forEach((row, ri) => {
    ctx.fillStyle = "#6b6b76";
    ctx.font = "10px system-ui, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(row[0]?.rowName?.length > 22 ? `${row[0].rowName.slice(0, 21)}…` : (row[0]?.rowName ?? ""), pad.left - 6, pad.top + ri * cellH + cellH / 2 + 3);
    row.forEach((cell, ci) => {
      const alpha = cell.count > 0 ? 0.15 + 0.85 * (cell.count / max) : 0.04;
      ctx.fillStyle = cell.color || "#7d26cd";
      ctx.globalAlpha = alpha;
      ctx.fillRect(pad.left + ci * cellW + 1, pad.top + ri * cellH + 1, cellW - 2, cellH - 2);
      ctx.globalAlpha = 1;
      if (ci === 0) {
        ctx.fillStyle = "#6b6b76";
        ctx.font = "9px system-ui, sans-serif";
        ctx.textAlign = "left";
        ctx.fillText(String(cell.count), pad.left + ci * cellW + 4, pad.top + ri * cellH + cellH / 2 + 3);
      }
    });
  });
  ctx.fillStyle = "#6b6b76";
  ctx.font = "10px system-ui, sans-serif";
  ctx.textAlign = "center";
  for (let ci = 0; ci < nCols; ci++) {
    const label = data[0]?.[ci]?.colName ?? "";
    ctx.fillText(label.length > 16 ? `${label.slice(0, 15)}…` : label, pad.left + ci * cellW + cellW / 2, pad.top - 10);
  }
}

/* ------------------------------------------------ 1. Code frequencies */

export function CodeFrequenciesView() {
  const { t } = useI18n();
  const [mode, setMode] = useState<"ranked" | "cumulative">("ranked");
  const [selectedCid, setSelectedCid] = useState<number | null>(null);
  const { data, loading, error, retry } = useReport<
    { rows: CodeFrequencyRow[] } | ChartMatrix
  >(
    () =>
      mode === "ranked" ? api.reports.codeFrequencies() : api.reports.charts("cumulative"),
    [mode],
  );
  const { data: summary } = useReport(
    () => (selectedCid == null ? Promise.resolve(null) : api.reports.codeSummary(selectedCid)),
    [selectedCid],
  );

  if (loading || error) return <ReportStatus loading={loading} error={error} onRetry={retry} />;

  if (mode === "ranked") {
    const rows = (data as { rows: CodeFrequencyRow[] } | null)?.rows ?? [];
    if (rows.length === 0) return <div className="h-48"><EmptyState>No data</EmptyState></div>;
    const max = Math.max(0, ...rows.map((r) => r.count));
    return (
      <div className="space-y-4">
        <ReportMenuBar>
          <Button
            variant="primary"
            className="h-6 px-2 py-0"
            onClick={() => setMode("ranked")}
          >
            {t("analyze.ranked")}
          </Button>
          <Button
            variant="secondary"
            className="h-6 px-2 py-0"
            onClick={() => setMode("cumulative")}
          >
            {t("analyze.cumulative")}
          </Button>
          {selectedCid != null && (
            <Button variant="secondary" className="h-6 px-2 py-0 text-text-secondary" onClick={() => setSelectedCid(null)}>
              {t("analyze.clearCode")}
            </Button>
          )}
          <Button
            variant="secondary"
            className="text-text-secondary hover:text-text-primary"
            onClick={() => void downloadChartPng("code-frequencies.png", rows)}
            icon={<FileImage size={12} aria-hidden />}
          >
            PNG
          </Button>
          <ReportCsvButton
            filename="code-frequencies.csv"
            headers={[t("analyze.colCode"), t("analyze.colCategory"), t("analyze.colCount")]}
            rows={rows.map((row: CodeFrequencyRow) => [row.name, row.category, row.count])}
          />
        </ReportMenuBar>
        {selectedCid != null && summary && summary.cid === selectedCid && (
          <div className="rounded-sm border border-border bg-surface p-3">
            <div className="flex items-baseline justify-between gap-2">
              <h2 className="text-sm font-medium text-text-primary">{summary.name}</h2>
              <span className="text-xs text-text-secondary">{summary.categories.join(" › ")}</span>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
              {(
                [
                  [t("analyze.total"), summary.total],
                  [t("analyze.text"), summary.counts.text],
                  [t("analyze.image"), summary.counts.image],
                  [t("analyze.av"), summary.counts.av],
                  [t("analyze.files"), summary.file_count],
                ] as [string, number][]
              ).map(([label, n]) => (
                <div key={label} className="rounded-sm border border-border bg-bg p-2">
                  <p className="text-xs text-text-secondary">{label}</p>
                  <p className="mt-0.5 text-lg font-semibold tabular-nums text-text-primary">{n}</p>
                </div>
              ))}
            </div>
            {summary.memo && <p className="mt-2 text-xs text-text-secondary">{summary.memo}</p>}
          </div>
        )}
        <section>
          <SectionLabel>{t("analyze.codingCounts")}</SectionLabel>
          <div className={cn(cardCls, "mt-2 space-y-2 p-3")}>
            {rows.map((row: CodeFrequencyRow) => (
              <div key={row.cid} className="flex items-center gap-2">
                <span className="flex w-44 shrink-0 items-center gap-2 text-sm">
                  <ColorSwatch color={row.color} />
                  <span className="truncate">{row.name}</span>
                </span>
                <div className="h-2.5 flex-1 overflow-hidden rounded-sm bg-surface-higher">
                  <div
                    className="h-full rounded-sm"
                    style={{
                      width: barWidth(row.count, max),
                      backgroundColor: row.color ?? "var(--qc-accent)",
                    }}
                  />
                </div>
                <span className="w-12 shrink-0 text-right text-sm tabular-nums text-text-secondary">
                  {row.count}
                </span>
              </div>
            ))}
          </div>
        </section>
        <section>
          <SectionLabel>{t("analyze.detailsTitle")}</SectionLabel>
          <div className={cn(cardCls, "mt-2")}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10">
                <tr>
                  <th className={thCls}>{t("analyze.colCode")}</th>
                  <th className={thCls}>{t("analyze.colCategory")}</th>
                  <th className={cn(thCls, "text-right")}>{t("analyze.colCount")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row: CodeFrequencyRow) => (
                  <tr
                    key={row.cid}
                    className={cn(
                      "hover:bg-surface-higher",
                      selectedCid === row.cid && "bg-accent/10",
                    )}
                  >
                    <td className={tdCls}>
                      <button
                        type="button"
                        onClick={() => setSelectedCid(selectedCid === row.cid ? null : row.cid)}
                        title={t("analyze.codeSummaryTitle")}
                        className="flex items-center gap-2"
                      >
                        <ColorSwatch color={row.color} />
                        <span className="truncate hover:text-accent">{row.name}</span>
                      </button>
                    </td>
                    <CategoryCell category={row.category} />
                    <td className={cn(tdCls, "text-right tabular-nums")}>{row.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    );
  }

  const cum = (data as ChartMatrix | null);
  const rows = (cum?.codes ?? []).map((c) => ({ name: c.name, color: c.color, count: c.count ?? 0, cumulative: c.cumulative ?? 0 }));
  if (rows.length === 0) return <div className="h-48"><EmptyState>No data</EmptyState></div>;
  return (
    <div className="space-y-4">
      <ReportMenuBar>
        <Button variant="secondary" className="h-6 px-2 py-0" onClick={() => setMode("ranked")}>
          Ranked
        </Button>
        <Button variant="primary" className="h-6 px-2 py-0" onClick={() => setMode("cumulative")}>
          Cumulative
        </Button>
        <ReportCsvButton
          filename="cumulative.csv"
          headers={[t("analyze.colCode"), t("analyze.colCount"), t("analyze.cumulative")]}
          rows={rows.map((r) => [r.name, r.count, r.cumulative])}
        />
      </ReportMenuBar>
      <canvas
        ref={(el) => {
          if (el && rows.length > 0) drawCumulativeChart(el, rows);
        }}
        className="h-[340px] w-full rounded-sm border border-border bg-white"
      />
      <div className={cardCls}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className={thCls}>{t("analyze.colCode")}</th>
              <th className={cn(thCls, "text-right")}>{t("analyze.colCount")}</th>
              <th className={cn(thCls, "text-right")}>{t("analyze.cumulative")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="hover:bg-surface-higher">
                <td className={tdCls}>
                  <span className="flex items-center gap-2">
                    <ColorSwatch color={r.color} />
                    <span className="truncate">{r.name}</span>
                  </span>
                </td>
                <td className={cn(tdCls, "text-right tabular-nums")}>{r.count}</td>
                <td className={cn(tdCls, "text-right tabular-nums")}>{r.cumulative}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ---------------------------------------------------- 2. Code segments */

const KIND_LABEL: Record<CodeSegmentRow["kind"], string> = {
  text: "Text",
  image: "Image",
  av: "AV",
};

function segmentPosition(r: CodeSegmentRow): string {
  if (r.kind === "av") return `${r.pos0}–${r.pos1} ms`;
  if (r.kind === "image") return `(${r.x1}, ${r.y1}) ${r.width}×${r.height}`;
  return `${r.pos0}–${r.pos1}`;
}

export function CodeSegmentsView() {
  const { t } = useI18n();
  const coders = useProjectStore((state) => state.coders).map((c) => c.name);
  const [cid, setCid] = useState<number | "">("");
  const [owner, setOwner] = useState("");
  const [compare, setCompare] = useState(false);
  const [coderA, setCoderA] = useState("");
  const [coderB, setCoderB] = useState("");

  useEffect(() => {
    if (coders.length >= 2 && !coderA && !coderB) {
      setCoderA(coders[0]);
      setCoderB(coders[1]);
    }
  }, [coders, coderA, coderB]);

  // The flat dump (all codes / compare modes) is fetched once.
  const { data: all, loading: allLoading, error: allError, retry: retryAll } = useReport(
    () => (cid === "" || compare ? api.reports.codesBySegments() : Promise.resolve(null)),
    [cid, compare],
  );
  // A single picked code loads the rich endpoint (image/AV positions).
  const { data: rich, loading: richLoading, error: richError, retry: retryRich } = useReport(
    () => (cid !== "" && !compare ? api.reports.codeSegments(cid) : Promise.resolve(null)),
    [cid, compare],
  );

  if (compare) {
    const rows = (all?.rows ?? []).filter(
      (r) => (owner === "" || r.owner === owner) && (r.owner === coderA || r.owner === coderB),
    );
    if (allLoading) return <div className="h-48"><LoadingState>Loading report…</LoadingState></div>;
    if (allError) return <ReportStatus loading={false} error={allError} onRetry={retryAll} />;
    const byFile = new Map<string, { a: CodesBySegmentRow[]; b: CodesBySegmentRow[] }>();
    for (const r of rows) {
      const e = byFile.get(r.file_name) ?? { a: [], b: [] };
      if (r.owner === coderA) e.a.push(r);
      else e.b.push(r);
      byFile.set(r.file_name, e);
    }
    const files = [...byFile.entries()].sort(([x], [y]) => x.localeCompare(y));
    if (files.length === 0) return <div className="h-48"><EmptyState>No data</EmptyState></div>;
    return (
      <div className="space-y-2">
        <ReportMenuBar>
          <Button variant="secondary" className="h-7" onClick={() => setCompare(false)}>
            {t("analyze.flatList")}
          </Button>
          <ReportCsvButton
            filename="coder-file-comparison.csv"
            headers={[t("analyze.colFile"), `${coderA} ${t("analyze.colCount").toLowerCase()}`, `${coderB} ${t("analyze.colCount").toLowerCase()}`]}
            rows={files.map(([name, e]) => [name, e.a.length, e.b.length])}
          />
        </ReportMenuBar>
        <div className="flex flex-wrap items-end gap-2">
          <label className="block">
            <span className="mb-1 block text-xs text-text-secondary">{t("analyze.coderALabel")}</span>
            <Select value={coderA} onChange={(e) => setCoderA(e.target.value)}>
              {coders.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </Select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-text-secondary">{t("analyze.coderBLabel")}</span>
            <Select value={coderB} onChange={(e) => setCoderB(e.target.value)}>
              {coders.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </Select>
          </label>
        </div>
        <div className={cardCls}>
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10">
              <tr>
                <th className={thCls}>{t("analyze.colFile")}</th>
                <th className={thCls}>{coderA} segments</th>
                <th className={thCls}>{coderB} segments</th>
              </tr>
            </thead>
            <tbody>
              {files.map(([name, e]) => (
                <tr key={name} className="align-top hover:bg-surface-higher">
                  <td className={cn(tdCls, "max-w-40 font-medium")}>{name}</td>
                  <td className={cn(tdCls, "max-w-sm")}>
                    {e.a.map((s, i) => (
                      <span key={i} className="block truncate text-xs" title={s.seltext}>
                        {s.code_name}: {s.seltext}
                      </span>
                    ))}
                  </td>
                  <td className={cn(tdCls, "max-w-sm")}>
                    {e.b.map((s, i) => (
                      <span key={i} className="block truncate text-xs" title={s.seltext}>
                        {s.code_name}: {s.seltext}
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  if (cid === "") {
    const rows = (all?.rows ?? []).filter((r) => owner === "" || r.owner === owner);
    if (allLoading) return <div className="h-48"><LoadingState>Loading report…</LoadingState></div>;
    if (allError) return <ReportStatus loading={false} error={allError} onRetry={retryAll} />;
    if (rows.length === 0) return <div className="h-48"><EmptyState>No data</EmptyState></div>;
    return (
      <div className="space-y-2">
        <ReportMenuBar>
          <Button variant="secondary" className="h-7" onClick={() => setCompare(true)}>
            {t("analyze.compareTwoCoders")}
          </Button>
          <ReportCsvButton
            filename="codes-by-segments.csv"
            headers={[t("analyze.colFile"), t("analyze.colCode"), t("analyze.colCategory"), t("analyze.colSegment"), t("analyze.colOwner"), t("analyze.colDate")]}
            rows={rows.map((row: CodesBySegmentRow) => [
              row.file_name,
              row.code_name,
              row.category,
              row.seltext,
              row.owner,
              row.date,
            ])}
          />
        </ReportMenuBar>
        <div className="flex flex-wrap items-end gap-2">
          <label className="block min-w-40">
            <span className="mb-1 block text-xs text-text-secondary">Code</span>
            <CodePickerSelect value={cid} onChange={setCid} />
          </label>
          <label className="block min-w-40">
            <span className="mb-1 block text-xs text-text-secondary">Coder</span>
            <Select value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="">{t("analyze.allCoders")}</option>
              {coders.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </Select>
          </label>
        </div>
        <div className={cardCls}>
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10">
              <tr>
                <th className={thCls}>File</th>
                <th className={thCls}>Code</th>
                <th className={thCls}>{t("analyze.colCategory")}</th>
                <th className={thCls}>{t("analyze.colSegment")}</th>
                <th className={thCls}>{t("analyze.colOwner")}</th>
                <th className={thCls}>{t("analyze.colDate")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row: CodesBySegmentRow) => (
                <tr key={row.ctid} className="hover:bg-surface-higher">
                  <td className={cn(tdCls, "max-w-48")}>
                    <span className="block truncate">{row.file_name}</span>
                  </td>
                  <td className={cn(tdCls, "whitespace-nowrap")}>{row.code_name}</td>
                  <CategoryCell category={row.category} />
                  <td className={cn(tdCls, "max-w-md")}>
                    <span className="block truncate" title={row.seltext}>{row.seltext}</span>
                  </td>
                  <td className={cn(tdCls, "whitespace-nowrap text-text-secondary")}>{row.owner}</td>
                  <td className={cn(tdCls, "whitespace-nowrap text-text-secondary")}>{row.date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  const rows = (rich?.rows ?? []).filter((r) => owner === "" || r.owner === owner);
  if (richLoading) return <div className="h-48"><LoadingState>Loading report…</LoadingState></div>;
  if (richError) return <ReportStatus loading={false} error={richError} onRetry={retryRich} />;
  if (rows.length === 0) return <div className="h-48"><EmptyState>No data</EmptyState></div>;
  return (
    <div className="space-y-2">
      <ReportMenuBar>
        <ReportCsvButton
          filename="code-segments.csv"
          headers={[t("analyze.kind"), t("analyze.colFile"), t("analyze.position"), t("analyze.textGeometry"), t("analyze.colOwner"), t("analyze.memo")]}
          rows={rows.map((r) => [
            KIND_LABEL[r.kind],
            r.file_name,
            segmentPosition(r),
            r.seltext ?? `${r.width}×${r.height}@${r.x1},${r.y1}`,
            r.owner,
            r.memo,
          ])}
        />
      </ReportMenuBar>
      <div className="flex flex-wrap items-end gap-2">
        <label className="block min-w-40">
          <span className="mb-1 block text-xs text-text-secondary">Code</span>
          <CodePickerSelect value={cid} onChange={setCid} />
        </label>
        <label className="block min-w-40">
          <span className="mb-1 block text-xs text-text-secondary">Coder</span>
          <Select value={owner} onChange={(e) => setOwner(e.target.value)}>
            <option value="">All coders</option>
            {coders.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </Select>
        </label>
      </div>
      <div className={cardCls}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className={thCls}>{t("analyze.kind")}</th>
              <th className={thCls}>File</th>
              <th className={thCls}>{t("analyze.position")}</th>
              <th className={thCls}>Segment</th>
              <th className={thCls}>Owner</th>
              <th className={thCls}>{t("analyze.memo")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.kind}-${r.id}`} className="hover:bg-surface-higher">
                <td className={cn(tdCls, "whitespace-nowrap")}>
                  <span className="rounded-sm bg-surface-higher px-1.5 py-px text-xs font-medium text-text-secondary">
                    {KIND_LABEL[r.kind]}
                  </span>
                </td>
                <td className={cn(tdCls, "max-w-48")}>
                  <span className="block truncate">{r.file_name}</span>
                </td>
                <td className={cn(tdCls, "whitespace-nowrap text-text-secondary")}>{segmentPosition(r)}</td>
                <td className={cn(tdCls, "max-w-md")}>
                  <span className="block truncate" title={r.seltext}>{r.seltext}</span>
                </td>
                <td className={cn(tdCls, "whitespace-nowrap text-text-secondary")}>{r.owner}</td>
                <td className={cn(tdCls, "max-w-56 text-text-secondary")}>
                  <span className="block truncate" title={r.memo}>{r.memo}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ---------------------------------------------------- 3. File × code */

export function FileCodeView() {
  const { t } = useI18n();
  const [dim, setDim] = useState<"files" | "cases">("files");
  const [view, setView] = useState<"table" | "stacked" | "heatmap">("table");
  const { data, loading, error, retry } = useReport(() =>
    api.reports.charts(dim === "files" ? "heatmap-file-code" : "heatmap-case"),
    [dim],
  );
  const ref = useRef<HTMLCanvasElement | null>(null);
  const dimLabel = dim === "files" ? "File" : "Case";
  const entities = useMemo(
    () => (dim === "files" ? (data?.files ?? []) : (data?.cases ?? [])),
    [data, dim],
  );
  const counts = useMemo(() => data?.counts ?? [], [data]);
  const codes = useMemo(() => data?.codes ?? [], [data]);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !data) return;
    if (view === "stacked") {
      const labels = entities.map((e) => e.name);
      const series = counts.map((row) =>
        row.map((count, ci) => ({
          name: codes[ci]?.name ?? String(ci),
          color: codes[ci]?.color ?? "#9a9ab0",
          count,
        })),
      );
      drawStackedChart(canvas, labels, series);
    } else if (view === "heatmap") {
      const rows = counts.map((row, ri) =>
        row.map((count, ci) => ({
          rowName: entities[ri]?.name ?? "",
          colName: codes[ci]?.name ?? "",
          color: codes[ci]?.color ?? "#7d26cd",
          count,
        })),
      );
      drawHeatmap(canvas, rows);
    }
  }, [data, view, dim, entities, counts, codes]);

  if (loading || error) return <ReportStatus loading={loading} error={error} onRetry={retry} />;
  if (entities.length === 0 || codes.length === 0)
    return <div className="h-48"><EmptyState>No data</EmptyState></div>;

  return (
    <div className="space-y-2">
      <ReportMenuBar>
        <Select
          value={dim}
          onChange={(e) => setDim(e.target.value as typeof dim)}
          aria-label="Dimension"
          className="h-7"
        >
          <option value="files">{t("analyze.perFile")}</option>
          <option value="cases">{t("analyze.perCase")}</option>
        </Select>
        {(["table", "stacked", "heatmap"] as const).map((v) => (
          <Button
            key={v}
            variant={view === v ? "primary" : "secondary"}
            className="h-6 px-2 py-0 capitalize"
            onClick={() => setView(v)}
          >
            {v === "table" ? t("analyze.table") : v === "stacked" ? t("analyze.stacked") : t("analyze.heatmap")}
          </Button>
        ))}
        <ReportCsvButton
          filename={`${dimLabel.toLowerCase()}-code.csv`}
          headers={[dimLabel, ...codes.map((c) => c.name)]}
          rows={entities.map((e, ri) => [e.name, ...(counts[ri] ?? []).map((n) => n)])}
        />
      </ReportMenuBar>

      {view === "table" ? (
        <>
          <div className={cn(cardCls, "max-h-96")}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10">
                <tr>
                  <th className={cn(thCls, "min-w-40")}>{dimLabel}</th>
                  {codes.map((c) => (
                    <th key={c.cid} className={cn(thCls, "min-w-32")}>
                      <span className="flex items-center gap-1.5">
                        <ColorSwatch color={c.color} />
                        <span className="truncate">{c.name}</span>
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {entities.map((e, ri) => (
                  <tr key={ri} className="hover:bg-surface-higher">
                    <td className={cn(tdCls, "max-w-48")}>
                      <span className="block truncate font-medium">{e.name}</span>
                    </td>
                    {codes.map((c, ci) => (
                      <td key={c.cid} className={cn(tdCls, "text-center tabular-nums text-text-secondary")}>
                        {matrixCell(counts[ri]?.[ci] ?? 0)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <canvas ref={ref} className="w-full rounded-sm border border-border bg-white" />
      )}
    </div>
  );
}

/* ---------------------------------------------------- 4. Code relations */

export function CodeRelationsView() {
  const { t } = useI18n();
  const coders = useProjectStore((state) => state.coders).map((c) => c.name);
  const current = useProjectStore((state) => state.coderName);
  const [mode, setMode] = useState<"cooccurrence" | "crossover">("cooccurrence");
  const [owner, setOwner] = useState("");
  useEffect(() => {
    if (!owner && current) setOwner(current);
  }, [current, owner]);

  const { data, loading, error, retry } = useReport<CooccurrenceTable | { owner: string; relations: CodeRelation[] }>(
    () =>
      mode === "cooccurrence"
        ? api.reports.cooccurrence()
        : api.reports.codeRelations(owner || current || undefined),
    [mode, owner, current],
  );

  if (loading || error) return <ReportStatus loading={loading} error={error} onRetry={retry} />;

  if (mode === "crossover") {
    const rows = (data as { relations: CodeRelation[] } | null)?.relations ?? [];
    if (rows.length === 0) return <div className="h-48"><EmptyState>No data</EmptyState></div>;
    return (
      <div className="space-y-2">
        <ReportMenuBar>
          <Button variant="secondary" className="h-6 px-2 py-0" onClick={() => setMode("cooccurrence")}>
            {t("analyze.cooccurrence")}
          </Button>
          <Button variant="primary" className="h-6 px-2 py-0" onClick={() => setMode("crossover")}>
            {t("analyze.crossovers")}
          </Button>
          <Select value={owner} onChange={(e) => setOwner(e.target.value)} className="h-7" aria-label="Coder">
            {coders.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </Select>
          <ReportCsvButton
            filename="code-relations.csv"
            headers={[t("analyze.coderALabel"), t("analyze.coderBLabel"), t("analyze.crossovers")]}
            rows={rows.map((r) => [r.code_a, r.code_b, r.count])}
          />
        </ReportMenuBar>
        <div className={cardCls}>
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10">
              <tr>
                <th className={thCls}>{t("analyze.coderALabel")}</th>
                <th className={thCls}>{t("analyze.coderBLabel")}</th>
                <th className={cn(thCls, "text-right")}>{t("analyze.crossovers")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.code_a}|${r.code_b}`} className="hover:bg-surface-higher">
                  <td className={cn(tdCls, "font-medium")}>{r.code_a}</td>
                  <td className={tdCls}>{r.code_b}</td>
                  <td className={cn(tdCls, "text-right tabular-nums")}>{r.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  const cooc = data as CooccurrenceTable | null;
  const codes = cooc?.codes ?? [];
  const counts = cooc?.counts ?? [];
  if (codes.length === 0) return <div className="h-48"><EmptyState>No data</EmptyState></div>;
  return (
    <div className="space-y-2">
      <ReportMenuBar>
        <Button variant="primary" className="h-6 px-2 py-0" onClick={() => setMode("cooccurrence")}>
          Co-occurrence
        </Button>
        <Button variant="secondary" className="h-6 px-2 py-0" onClick={() => setMode("crossover")}>
          Crossovers
        </Button>
        <ReportCsvButton
          filename="co-occurrence.csv"
          headers={["", ...codes.map((c) => c.name)]}
          rows={codes.map((a, i) => [a.name, ...(counts[i] ?? []).map((n) => n)])}
        />
      </ReportMenuBar>
      <div className={cn(cardCls, "max-h-96")}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className={cn(thCls, "min-w-40")}>Code</th>
              {codes.map((c) => (
                <th key={c.cid} className={cn(thCls, "min-w-24")}>
                  <span className="flex items-center gap-1.5">
                    <ColorSwatch color={c.color} />
                    <span className="truncate">{c.name}</span>
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {codes.map((a, i) => (
              <tr key={a.cid} className="hover:bg-surface-higher">
                <td className={cn(tdCls, "max-w-48")}>
                  <span className="flex items-center gap-2">
                    <ColorSwatch color={a.color} />
                    <span className="block truncate font-medium">{a.name}</span>
                  </span>
                </td>
                {codes.map((b, j) => {
                  const n = counts[i]?.[j] ?? 0;
                  return (
                    <td
                      key={b.cid}
                      title={`${a.name} & ${b.name}: ${n} files`}
                      className={cn(
                        tdCls,
                        "text-center tabular-nums text-text-secondary",
                        i === j && "bg-surface-higher font-medium text-text-primary",
                      )}
                    >
                      {matrixCell(n)}
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

/* ---------------------------------------------------- 5. Interrater */

interface InterraterPair {
  coder_a: string;
  coder_b: string;
  n_units: number;
  n_categories: number;
  n_pairs: number;
  both: number;
  only_a: number;
  only_b: number;
  neither: number;
  kappa: number | null;
  krippendorff: number | null;
  gwet_ac1: number | null;
}

interface InterraterSummary {
  kappa: number | null;
  krippendorff: number | null;
  gwet_ac1: number | null;
}

/** Backend interrater response: the two-coder shape plus the multi-coder
 *  fields (alpha over all selected coders and the pairwise table). */
interface InterraterReport extends InterraterResult {
  coders: string[];
  n_coders: number;
  alpha: number | null;
  pairs: InterraterPair[];
  pairwise_mean: InterraterSummary | null;
  pairwise_min: InterraterSummary | null;
  pairwise_max: InterraterSummary | null;
}

/** POST the interrater request with an explicit coder selection. The
 *  report client's `interrater` helper only sends coder_a/coder_b; reuse
 *  the exported request primitives to send the `coders` list as well. */
async function postInterrater(body: {
  coder_a: string;
  coder_b: string;
  coders: string[];
}): Promise<InterraterReport> {
  const doPost = async (): Promise<InterraterReport> => {
    const base = await initApiBase();
    const res = await fetchWithTimeout(`${base}/reports/interrater`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      let detail: unknown;
      try {
        detail = (await res.json()).detail;
      } catch {
        /* non-JSON error body */
      }
      const suffix = typeof detail === "string" && detail ? `: ${detail}` : "";
      throw new ApiError(res.status, `API error ${res.status} on /reports/interrater${suffix}`, detail);
    }
    return (await res.json()) as InterraterReport;
  };
  try {
    return await doPost();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    // Network-level failure (the packaged backend restarted): retry once
    // so the base URL is resolved afresh.
    return doPost();
  }
}

const fmtValue = (v: number | null) => (v == null ? "—" : v.toFixed(4));

export function InterraterView() {
  const { t } = useI18n();
  const { data, loading, error, retry } = useReport(api.reports.coderComparison);
  const volume = data?.rows ?? [];
  const coders = useProjectStore((state) => state.coders).map((c) => c.name);
  const [selected, setSelected] = useState<string[]>([]);
  const [result, setResult] = useState<InterraterReport | null>(null);
  const [computing, setComputing] = useState(false);
  const [computeError, setComputeError] = useState<string | null>(null);
  const [showCoefs, setShowCoefs] = useState({
    kappa: true,
    alpha: true,
    gwet: true,
  });
  const initialized = useRef(false);
  const requestSeq = useRef(0);

  // Default: every project coder is selected.
  useEffect(() => {
    if (!initialized.current && coders.length > 0) {
      initialized.current = true;
      setSelected(coders);
    }
  }, [coders]);

  // Recompute whenever the selection settles on two or more coders.
  useEffect(() => {
    if (selected.length < 2) {
      setResult(null);
      return;
    }
    const seq = ++requestSeq.current;
    let cancelled = false;
    setComputing(true);
    setComputeError(null);
    postInterrater({ coder_a: selected[0], coder_b: selected[1], coders: selected })
      .then((r) => {
        if (!cancelled && seq === requestSeq.current) setResult(r);
      })
      .catch((err) => {
        if (!cancelled && seq === requestSeq.current) {
          setComputeError(err instanceof Error ? err.message : "Failed to compute");
        }
      })
      .finally(() => {
        if (seq === requestSeq.current) setComputing(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  function toggleCoder(name: string) {
    setSelected((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  }

  const hiddenCoefCount =
    3 - (showCoefs.kappa ? 1 : 0) - (showCoefs.alpha ? 1 : 0) - (showCoefs.gwet ? 1 : 0);

  return (
    <div className="space-y-4">
      {loading || error ? (
        <ReportStatus loading={loading} error={error} onRetry={retry} />
      ) : volume.length > 0 ? (
        <div className="space-y-2">
          <ReportMenuBar>
            <ReportCsvButton
              filename="coder-comparison.csv"
              headers={[t("analyze.colCoder"), t("analyze.colCodings"), t("analyze.colFiles")]}
              rows={volume.map((row: CoderComparisonRow) => [row.owner, row.codings_count, row.files_count])}
            />
          </ReportMenuBar>
          <div className={cardCls}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10">
                <tr>
                  <th className={thCls}>{t("analyze.colCoder")}</th>
                  <th className={cn(thCls, "text-right")}>{t("analyze.colCodings")}</th>
                  <th className={cn(thCls, "text-right")}>{t("analyze.colFiles")}</th>
                </tr>
              </thead>
              <tbody>
                {volume.map((row: CoderComparisonRow) => (
                  <tr key={row.owner} className="hover:bg-surface-higher">
                    <td className={cn(tdCls, "font-medium")}>{row.owner}</td>
                    <td className={cn(tdCls, "text-right tabular-nums")}>{formatCount(row.codings_count)}</td>
                    <td className={cn(tdCls, "text-right tabular-nums")}>{formatCount(row.files_count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-text-secondary">{t("analyze.coders")}:</span>
          {coders.map((n) => (
            <Button
              key={n}
              variant="secondary"
              onClick={() => toggleCoder(n)}
              className={cn(
                "h-6 px-2.5 text-xs",
                selected.includes(n) && "border-accent bg-accent/10 text-accent",
              )}
            >
              {n}
            </Button>
          ))}
          {computing && (
            <span className="ml-2 flex items-center gap-1 text-xs text-text-secondary">
              <LoaderCircle size={12} className="animate-spin" aria-hidden />
              {t("analyze.computing")}
            </span>
          )}
        </div>
        {selected.length < 2 && (
          <p className="flex items-center gap-1.5 text-xs text-danger">
            <CircleAlert size={13} aria-hidden />
            {t("analyze.atLeastTwoCoders")}
          </p>
        )}
        {computeError && (
          <p className="flex items-center gap-1.5 text-xs text-danger">
            <CircleAlert size={13} aria-hidden />
            {computeError}
          </p>
        )}
      </div>

      {result && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-text-secondary">{t("analyze.coefficients")}:</span>
            {(
              [
                ["kappa", t("analyze.kappa")],
                ["alpha", t("analyze.krippendorff")],
                ["gwet", t("analyze.gwet")],
              ] as const
            ).map(([key, label]) => (
              <Button
                key={key}
                variant="secondary"
                onClick={() => setShowCoefs((s) => ({ ...s, [key]: !s[key] }))}
                className={cn(
                  "h-6 px-2.5 text-xs",
                  showCoefs[key] && "border-accent bg-accent/10 text-accent",
                )}
              >
                {label}
              </Button>
            ))}
          </div>

          {showCoefs.alpha && (
            <div className={cardCls}>
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-3 py-2">
                <span className="font-mono text-2xl font-semibold text-accent">
                  {fmtValue(result.alpha)}
                </span>
                <span className="text-xs text-text-secondary">
                  {t("analyze.overallAlpha", { n: result.n_coders })}
                </span>
              </div>
            </div>
          )}

          <div className={cardCls}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10">
                <tr>
                  <th className={thCls}>{t("analyze.coderALabel")}</th>
                  <th className={thCls}>{t("analyze.coderBLabel")}</th>
                  {showCoefs.kappa && (
                    <th className={cn(thCls, "text-right")}>{t("analyze.kappa")}</th>
                  )}
                  {showCoefs.alpha && (
                    <th className={cn(thCls, "text-right")}>{t("analyze.krippendorff")}</th>
                  )}
                  {showCoefs.gwet && (
                    <th className={cn(thCls, "text-right")}>{t("analyze.gwet")}</th>
                  )}
                  <th className={cn(thCls, "text-right")}>{t("analyze.units")}</th>
                  <th className={cn(thCls, "text-right")}>{t("analyze.pairs")}</th>
                </tr>
              </thead>
              <tbody>
                {result.pairs.map((p) => (
                  <tr key={`${p.coder_a}|${p.coder_b}`} className="hover:bg-surface-higher">
                    <td className={cn(tdCls, "font-medium")}>{p.coder_a}</td>
                    <td className={tdCls}>{p.coder_b}</td>
                    {showCoefs.kappa && (
                      <td className={cn(tdCls, "text-right font-mono tabular-nums")}>
                        {fmtValue(p.kappa)}
                      </td>
                    )}
                    {showCoefs.alpha && (
                      <td className={cn(tdCls, "text-right font-mono tabular-nums")}>
                        {fmtValue(p.krippendorff)}
                      </td>
                    )}
                    {showCoefs.gwet && (
                      <td className={cn(tdCls, "text-right font-mono tabular-nums")}>
                        {fmtValue(p.gwet_ac1)}
                      </td>
                    )}
                    <td className={cn(tdCls, "text-right tabular-nums")}>{p.n_units}</td>
                    <td className={cn(tdCls, "text-right tabular-nums")}>{p.n_pairs}</td>
                  </tr>
                ))}
                {result.pairwise_mean && (
                  <tr className="bg-surface-higher font-medium">
                    <td className={cn(tdCls, "text-xs text-text-secondary")} colSpan={2}>
                      {t("analyze.mean")}
                    </td>
                    {showCoefs.kappa && (
                      <td className={cn(tdCls, "text-right font-mono tabular-nums")}>
                        {fmtValue(result.pairwise_mean.kappa)}
                      </td>
                    )}
                    {showCoefs.alpha && (
                      <td className={cn(tdCls, "text-right font-mono tabular-nums")}>
                        {fmtValue(result.pairwise_mean.krippendorff)}
                      </td>
                    )}
                    {showCoefs.gwet && (
                      <td className={cn(tdCls, "text-right font-mono tabular-nums")}>
                        {fmtValue(result.pairwise_mean.gwet_ac1)}
                      </td>
                    )}
                    <td className={cn(tdCls, "text-right")} colSpan={2 + hiddenCoefCount} />
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {result.n_coders === 2 && (
            <div className={cardCls}>
              <table className="w-full border-collapse">
                <thead className="sticky top-0 z-10">
                  <tr>
                    <th className={thCls}>{t("analyze.measure")}</th>
                    <th className={cn(thCls, "text-right")}>Value</th>
                    <th className={cn(thCls, "text-right")}>{t("analyze.units")}</th>
                    <th className={cn(thCls, "text-right")}>{t("analyze.colCodes")}</th>
                    <th className={cn(thCls, "text-right")}>{t("analyze.pairs")}</th>
                    <th className={cn(thCls, "text-right")}>{t("analyze.both")}</th>
                    <th className={cn(thCls, "text-right")}>{t("analyze.aOnly")}</th>
                    <th className={cn(thCls, "text-right")}>{t("analyze.bOnly")}</th>
                    <th className={cn(thCls, "text-right")}>{t("analyze.neither")}</th>
                  </tr>
                </thead>
                <tbody>
                  {(
                    [
                      [t("analyze.kappa"), result.kappa],
                      [t("analyze.krippendorff"), result.krippendorff],
                      [t("analyze.gwet"), result.gwet_ac1],
                    ] as [string, number | null][]
                  ).map(([label, v]) => (
                    <tr key={label} className="hover:bg-surface-higher">
                      <td className={cn(tdCls, "font-medium")}>{label}</td>
                      <td className={cn(tdCls, "text-right font-mono")}>{fmtValue(v)}</td>
                      <td className={cn(tdCls, "text-right")}>{result.n_units}</td>
                      <td className={cn(tdCls, "text-right")}>{result.n_categories}</td>
                      <td className={cn(tdCls, "text-right")}>{result.n_pairs}</td>
                      <td className={cn(tdCls, "text-right")}>{result.both}</td>
                      <td className={cn(tdCls, "text-right")}>{result.only_a}</td>
                      <td className={cn(tdCls, "text-right")}>{result.only_b}</td>
                      <td className={cn(tdCls, "text-right")}>{result.neither}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="border-t border-border px-2 py-1.5 text-xs text-text-secondary">
                {t("analyze.agreementNote", { a: result.coder_a, b: result.coder_b })}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------- 6. Text & corpus */

export function CorpusTextView() {
  const { t } = useI18n();
  const CORPUS_TABS = [
    { id: "word-cloud", label: t("analyze.wordCloudTab") },
    { id: "exact-matches", label: t("analyze.exactMatchesTab") },
    { id: "file-summary", label: t("analyze.fileSummaryTab") },
    { id: "attributes", label: t("analyze.attributesTab") },
  ] as const;
  const [tab, setTab] = useState<(typeof CORPUS_TABS)[number]["id"]>("word-cloud");
  return (
    <div className="space-y-3">
      <ReportMenuBar>
        {CORPUS_TABS.map((t) => (
          <Button
            key={t.id}
            variant={tab === t.id ? "primary" : "secondary"}
            className="h-6 px-2 py-0"
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </Button>
        ))}
      </ReportMenuBar>
      {tab === "word-cloud" && <WordCloudReport />}
      {tab === "exact-matches" && <ExactMatchesReport />}
      {tab === "file-summary" && <FileSummaryReport />}
      {tab === "attributes" && <AttributesReport />}
    </div>
  );
}

/* ------------------------------------------------------------------ */