/**
 * Upstream-parity reports: code segments (code-in-all-files), code summary,
 * coder-vs-file comparison, code relations, word cloud, charts (cumulative,
 * stacked, heatmap), codebook export and references.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { CircleAlert, Download, LoaderCircle, Paperclip, Trash2, X } from "lucide-react";
import { api, type CodeSegmentRow, type ReferenceEntry } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { cn } from "@/lib/utils";
import { useProjectStore } from "@/stores/project";

const thCls =
  "border-b border-border bg-surface px-2 py-1.5 text-left text-xs font-medium text-text-secondary";
const tdCls = "border-b border-border px-2 py-1.5 text-sm";
const cardCls = "overflow-auto rounded-sm border border-border bg-surface";
const selectCls =
  "h-8 rounded-sm border border-border bg-bg px-2 text-sm outline-none focus:border-accent";

function useReport<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    loadRef
      .current()
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load report");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);
  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  return { data, loading, error, retry };
}

function ReportStatus({
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
      <div className="flex h-48 items-center justify-center gap-2 text-text-secondary">
        <LoaderCircle size={16} className="animate-spin" aria-hidden />
        Loading report…
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
        <button
          type="button"
          onClick={onRetry}
          className="rounded-sm border border-border bg-surface px-3 py-1.5 text-sm hover:bg-surface-higher"
        >
          Retry
        </button>
      </div>
    );
  }
  return null;
}

function EmptyState({ label = "No data" }: { label?: string }) {
  return (
    <div className="flex h-48 items-center justify-center">
      <p className="text-sm text-text-secondary">{label}</p>
    </div>
  );
}

function CsvButton({ filename, headers, rows }: { filename: string; headers: string[]; rows: unknown[][] }) {
  return (
    <button
      type="button"
      onClick={() => downloadCsv(filename, headers, rows)}
      className="flex items-center gap-1 rounded-sm border border-border bg-surface px-2 py-1 text-xs text-text-secondary hover:bg-surface-higher hover:text-text-primary"
    >
      <Download size={12} aria-hidden />
      CSV
    </button>
  );
}

const KIND_LABEL: Record<CodeSegmentRow["kind"], string> = {
  text: "Text",
  image: "Image",
  av: "AV",
};

function CodePickerSelect({ value, onChange }: { value: number | ""; onChange: (v: number) => void }) {
  const codeTree = useProjectStore((state) => state.codeTree);
  const options = codeTree
    .filter((item) => item.kind === "code")
    .map((item) => ({ cid: item.id, name: item.name }))
    .sort((a, b) => a.name.localeCompare(b.name));
  return (
    <select value={value} onChange={(e) => onChange(Number(e.target.value))} className={selectCls}>
      <option value="" disabled>
        Pick a code…
      </option>
      {options.map((c) => (
        <option key={c.cid} value={c.cid}>
          {c.name}
        </option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
// Code segments (code-in-all-files)
// ---------------------------------------------------------------------------

export function CodeSegmentsReport() {
  const [cid, setCid] = useState<number | "">("");
  const [rows, setRows] = useState<CodeSegmentRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (cid === "") return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.reports
      .codeSegments(cid)
      .then((res) => {
        if (!cancelled) setRows(res.rows);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [cid]);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-sm text-text-secondary">Code:</span>
        <CodePickerSelect value={cid} onChange={setCid} />
      </div>
      {loading ? (
        <ReportStatus loading error={null} onRetry={() => {}} />
      ) : error ? (
        <ReportStatus loading={false} error={error} onRetry={() => setCid(cid)} />
      ) : rows == null ? (
        <EmptyState label="Pick a code to see all its coded segments." />
      ) : rows.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-text-primary">
              {rows.length} segment(s)
            </h2>
            <CsvButton
              filename="code-segments.csv"
              headers={["Kind", "File", "Position", "Text/Geometry", "Owner", "Memo"]}
              rows={rows.map((r) => [
                KIND_LABEL[r.kind],
                r.file_name,
                r.kind === "av"
                  ? `${r.pos0}–${r.pos1} ms`
                  : r.kind === "image"
                    ? `(${r.x1}, ${r.y1}) ${r.width}×${r.height}`
                    : `${r.pos0}–${r.pos1}`,
                r.seltext ?? `${r.width}×${r.height}@${r.x1},${r.y1}`,
                r.owner,
                r.memo,
              ])}
            />
          </div>
          <div className={cardCls}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10">
                <tr>
                  <th className={thCls}>Kind</th>
                  <th className={thCls}>File</th>
                  <th className={thCls}>Position</th>
                  <th className={thCls}>Segment</th>
                  <th className={thCls}>Owner</th>
                  <th className={thCls}>Memo</th>
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
                    <td className={cn(tdCls, "whitespace-nowrap text-text-secondary")}>
                      {r.kind === "av"
                        ? `${r.pos0}–${r.pos1} ms`
                        : r.kind === "image"
                          ? `(${r.x1}, ${r.y1}) ${r.width}×${r.height}`
                          : `${r.pos0}–${r.pos1}`}
                    </td>
                    <td className={cn(tdCls, "max-w-md")}>
                      <span className="block truncate" title={r.seltext}>
                        {r.seltext}
                      </span>
                    </td>
                    <td className={cn(tdCls, "whitespace-nowrap text-text-secondary")}>{r.owner}</td>
                    <td className={cn(tdCls, "max-w-56 text-text-secondary")}>
                      <span className="block truncate" title={r.memo}>
                        {r.memo}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Code summary
// ---------------------------------------------------------------------------

export function CodeSummaryReport() {
  const [cid, setCid] = useState<number | "">("");
  const [summary, setSummary] = useState<Awaited<ReturnType<typeof api.reports.codeSummary>> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (cid === "") return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.reports
      .codeSummary(cid)
      .then((d) => {
        if (!cancelled) setSummary(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [cid]);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-sm text-text-secondary">Code:</span>
        <CodePickerSelect value={cid} onChange={setCid} />
      </div>
      {loading ? (
        <ReportStatus loading error={null} onRetry={() => {}} />
      ) : error ? (
        <ReportStatus loading={false} error={error} onRetry={() => setCid(cid)} />
      ) : summary == null ? (
        <EmptyState label="Pick a code to see its summary." />
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {(
              [
                ["Total", summary.total],
                ["Text", summary.counts.text],
                ["Image", summary.counts.image],
                ["AV", summary.counts.av],
                ["Files", summary.file_count],
              ] as [string, number][]
            ).map(([label, n]) => (
              <div key={label} className="rounded-sm border border-border bg-surface p-3">
                <p className="text-xs text-text-secondary">{label}</p>
                <p className="mt-1 text-xl font-semibold tabular-nums text-text-primary">{n}</p>
              </div>
            ))}
          </div>
          {summary.memo && (
            <p className="rounded-sm border border-border bg-surface p-3 text-sm text-text-secondary">
              <span className="font-medium text-text-primary">Memo: </span>
              {summary.memo}
            </p>
          )}
          {summary.categories.length > 0 && (
            <p className="text-sm text-text-secondary">
              Categories: <span className="text-text-primary">{summary.categories.join(" › ")}</span>
            </p>
          )}
          <div className={cardCls}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10">
                <tr>
                  <th className={thCls}>Files coded with this code</th>
                </tr>
              </thead>
              <tbody>
                {summary.files.map((f) => (
                  <tr key={f} className="hover:bg-surface-higher">
                    <td className={tdCls}>{f}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Coder vs coder, file by file
// ---------------------------------------------------------------------------

export function CoderFileComparisonReport() {
  const coders = useProjectStore((state) => state.coders).map((c) => c.name);
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [data, setData] = useState<Awaited<ReturnType<typeof api.reports.coderFileComparison>> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (coders.length >= 2 && !a && !b) {
      setA(coders[0]);
      setB(coders[1]);
    }
  }, [coders, a, b]);

  async function run(e: FormEvent) {
    e.preventDefault();
    if (!a || !b || a === b) return;
    setLoading(true);
    setError(null);
    try {
      setData(await api.reports.coderFileComparison(a, b));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-2">
      <form onSubmit={(e) => void run(e)} className="flex flex-wrap items-end gap-2">
        <label className="block">
          <span className="mb-1 block text-xs text-text-secondary">Coder A</span>
          <select value={a} onChange={(e) => setA(e.target.value)} className={selectCls}>
            {coders.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-text-secondary">Coder B</span>
          <select value={b} onChange={(e) => setB(e.target.value)} className={selectCls}>
            {coders.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={loading || !a || !b || a === b}
          className="rounded-sm bg-accent px-3 py-1.5 text-xs font-medium text-[var(--qc-bg)] hover:bg-accent-hover disabled:opacity-40"
        >
          {loading ? "Loading…" : "Compare"}
        </button>
      </form>
      {error && (
        <p className="flex items-center gap-1.5 text-xs text-danger">
          <CircleAlert size={13} aria-hidden />
          {error}
        </p>
      )}
      {data && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-text-primary">
              {data.total_a} vs {data.total_b} segments across {data.files.length} files
            </h2>
            <CsvButton
              filename="coder-file-comparison.csv"
              headers={["File", `${a} count`, `${b} count`]}
              rows={data.files.map((f) => [f.file_name, f.coder_a_count, f.coder_b_count])}
            />
          </div>
          <div className={cardCls}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10">
                <tr>
                  <th className={thCls}>File</th>
                  <th className={thCls}>{a} segments</th>
                  <th className={thCls}>{b} segments</th>
                </tr>
              </thead>
              <tbody>
                {data.files.map((f) => (
                  <tr key={f.file_name} className="align-top hover:bg-surface-higher">
                    <td className={cn(tdCls, "max-w-40 font-medium")}>{f.file_name}</td>
                    <td className={cn(tdCls, "max-w-sm")}>
                      {f.segments_a.map((s, i) => (
                        <span key={i} className="block truncate text-xs" title={s.seltext}>
                          {s.code_name}: {s.seltext}
                        </span>
                      ))}
                    </td>
                    <td className={cn(tdCls, "max-w-sm")}>
                      {f.segments_b.map((s, i) => (
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
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Code relations (crossovers)
// ---------------------------------------------------------------------------

export function CodeRelationsReport() {
  const coders = useProjectStore((state) => state.coders).map((c) => c.name);
  const current = useProjectStore((state) => state.coderName);
  const [owner, setOwner] = useState("");
  const { data, loading, error, retry } = useReport(() =>
    api.reports.codeRelations(owner || current || undefined),
  );
  useEffect(() => {
    if (!owner && current) setOwner(current);
  }, [current, owner]);
  const rows = data?.relations ?? [];
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-sm text-text-secondary">Coder:</span>
        <select value={owner} onChange={(e) => setOwner(e.target.value)} className={selectCls}>
          {coders.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </div>
      {loading || error ? (
        <ReportStatus loading={loading} error={error} onRetry={retry} />
      ) : rows.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-text-primary">
              {rows.length} code pair(s) with overlapping segments
            </h2>
            <CsvButton
              filename="code-relations.csv"
              headers={["Code A", "Code B", "Crossovers"]}
              rows={rows.map((r) => [r.code_a, r.code_b, r.count])}
            />
          </div>
          <div className={cardCls}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10">
                <tr>
                  <th className={thCls}>Code A</th>
                  <th className={thCls}>Code B</th>
                  <th className={cn(thCls, "text-right")}>Crossovers</th>
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
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Word cloud
// ---------------------------------------------------------------------------

export function WordCloudReport() {
  const sources = useProjectStore((state) => state.sources).filter(
    (s) => s.media_type === "text" || s.media_type === "pdf",
  );
  const [sourceId, setSourceId] = useState<number | "">("");
  const [rows, setRows] = useState<Awaited<ReturnType<typeof api.reports.wordFrequencies>> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.reports
      .wordFrequencies(sourceId === "" ? null : sourceId, 120)
      .then((d) => {
        if (!cancelled) setRows(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sourceId]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !rows || rows.rows.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio > 0 ? window.devicePixelRatio : 1;
    const width = canvas.clientWidth || 800;
    const height = 360;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.textBaseline = "alphabetic";

    const max = Math.max(1, ...rows.rows.map((r) => r.count));
    // Deterministic pseudo-random placement.
    let seed = 42;
    const rand = () => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    };
    const placed: { x: number; y: number; w: number; h: number }[] = [];
    for (const row of rows.rows) {
      const fontSize = 12 + (row.count / max) * 44;
      ctx.font = `${fontSize}px system-ui, sans-serif`;
      const w = ctx.measureText(row.word).width;
      const h = fontSize;
      let attempts = 0;
      let x = width / 2 - w / 2;
      let y = height / 2;
      let collides = true;
      while (collides && attempts < 400) {
        collides = placed.some(
          (p) => x < p.x + p.w + 4 && x + w + 4 > p.x && y < p.y + p.h + 4 && y + h + 4 > p.y,
        );
        if (collides) {
          x = rand() * (width - w);
          y = 20 + rand() * (height - h - 40);
          attempts += 1;
        }
      }
      placed.push({ x, y, w, h });
      ctx.fillStyle = `hsl(${(row.word.length * 47 + 190) % 360} 45% 38%)`;
      ctx.fillText(row.word, x, y + fontSize);
    }
  }, [rows]);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-sm text-text-secondary">Source:</span>
        <select value={sourceId} onChange={(e) => setSourceId(e.target.value === "" ? "" : Number(e.target.value))} className={selectCls}>
          <option value="">All text sources</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>
      {loading ? (
        <ReportStatus loading error={null} onRetry={() => {}} />
      ) : error ? (
        <ReportStatus loading={false} error={error} onRetry={() => setSourceId(sourceId)} />
      ) : !rows || rows.rows.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          <canvas ref={canvasRef} className="h-[360px] w-full rounded-sm border border-border bg-white" />
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-text-primary">Top words</h2>
            <CsvButton
              filename="word-frequencies.csv"
              headers={["Word", "Count"]}
              rows={rows.rows.map((r) => [r.word, r.count])}
            />
          </div>
          <div className={cardCls}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10">
                <tr>
                  <th className={thCls}>Word</th>
                  <th className={cn(thCls, "text-right")}>Count</th>
                </tr>
              </thead>
              <tbody>
                {rows.rows.map((r) => (
                  <tr key={r.word} className="hover:bg-surface-higher">
                    <td className={cn(tdCls, "font-medium")}>{r.word}</td>
                    <td className={cn(tdCls, "text-right tabular-nums")}>{r.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Charts (canvas)
// ---------------------------------------------------------------------------

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

export function CumulativeChart() {
  const { data, loading, error, retry } = useReport(() => api.reports.charts("cumulative"));
  const ref = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    if (data && ref.current) {
      drawCumulativeChart(
        ref.current,
        (data.codes ?? []).map((c) => ({
          name: c.name,
          color: c.color,
          count: c.count ?? 0,
          cumulative: c.cumulative ?? 0,
        })),
      );
    }
  }, [data]);
  if (loading || error) return <ReportStatus loading={loading} error={error} onRetry={retry} />;
  return <canvas ref={ref} className="h-[340px] w-full rounded-sm border border-border bg-white" />;
}

export function StackedChart() {
  const [kind, setKind] = useState<"stacked-files" | "stacked-cases">("stacked-files");
  const { data, loading, error, retry } = useReport(() => api.reports.charts(kind));
  const ref = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    if (!data || !ref.current) return;
    const labels = (data.labels ?? []).map((l) => l.name);
    const series = (data.series ?? []).map((row) =>
      row.map((cell) => ({
        name: data.codes.find((c) => c.cid === cell.cid)?.name ?? String(cell.cid),
        color: data.codes.find((c) => c.cid === cell.cid)?.color ?? "#9a9ab0",
        count: cell.count,
      })),
    );
    drawStackedChart(ref.current, labels, series);
  }, [data, kind]);
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} className={selectCls}>
          <option value="stacked-files">Codings per file</option>
          <option value="stacked-cases">Codings per case</option>
        </select>
      </div>
      {loading || error ? <ReportStatus loading={loading} error={error} onRetry={retry} /> : null}
      <canvas ref={ref} className="w-full rounded-sm border border-border bg-white" />
    </div>
  );
}

export function HeatmapReport() {
  const [kind, setKind] = useState<"heatmap-file-code" | "heatmap-case">("heatmap-file-code");
  const { data, loading, error, retry } = useReport(() => api.reports.charts(kind));
  const ref = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    if (!data || !ref.current) return;
    const rows = (data.counts ?? []).map((counts, ri) =>
      counts.map((count, ci) => ({
        rowName: kind === "heatmap-file-code" ? (data.files?.[ri]?.name ?? "") : (data.cases?.[ri]?.name ?? ""),
        colName: data.codes[ci]?.name ?? "",
        color: data.codes[ci]?.color ?? "#7d26cd",
        count,
      })),
    );
    drawHeatmap(ref.current, rows);
  }, [data, kind]);
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} className={selectCls}>
          <option value="heatmap-file-code">File × code</option>
          <option value="heatmap-case">Case × code</option>
        </select>
      </div>
      {loading || error ? <ReportStatus loading={loading} error={error} onRetry={retry} /> : null}
      <canvas ref={ref} className="w-full rounded-sm border border-border bg-white" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Codebook
// ---------------------------------------------------------------------------

export function CodebookReport() {
  const [memos, setMemos] = useState(false);
  const { data, loading, error, retry } = useReport(() => api.reports.codebook(memos));
  const [copied, setCopied] = useState(false);

  async function download() {
    if (!data) return;
    const blob = new Blob([data.text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "codebook.txt";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  async function copy() {
    if (!data) return;
    await navigator.clipboard.writeText(data.text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  if (loading || error) return <ReportStatus loading={loading} error={error} onRetry={retry} />;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-sm text-text-secondary">
          <input type="checkbox" checked={memos} onChange={(e) => setMemos(e.target.checked)} />
          Include memos
        </label>
        <button
          type="button"
          onClick={() => void download()}
          className="flex items-center gap-1 rounded-sm border border-border bg-surface px-2.5 py-1 text-xs text-text-secondary hover:bg-surface-higher hover:text-text-primary"
        >
          <Download size={12} aria-hidden />
          Download codebook (.txt)
        </button>
        <button
          type="button"
          onClick={() => void copy()}
          className="rounded-sm border border-border bg-surface px-2.5 py-1 text-xs text-text-secondary hover:bg-surface-higher hover:text-text-primary"
        >
          {copied ? "Copied" : "Copy to clipboard"}
        </button>
      </div>
      <pre className="qc-selectable max-h-96 overflow-y-auto whitespace-pre-wrap break-words rounded-sm border border-border bg-surface p-3 text-xs leading-relaxed text-text-primary">
        {data?.text || "—"}
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------------------
// References
// ---------------------------------------------------------------------------

export function ReferencesReport() {  const [references, setReferences] = useState<ReferenceEntry[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .references()
      .then((res) => {
        if (!cancelled) setReferences(res.references);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  async function remove(risid: number) {
    await api.deleteReference(risid);
    setAttempt((a) => a + 1);
  }

  async function attach(risid: number) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".pdf,.epub";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        await api.attachReferenceFile(risid, file);
        setAttempt((a) => a + 1);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not attach file");
      }
    };
    input.click();
  }

  async function detach(risid: number, sourceId: number) {
    try {
      await api.detachReferenceFile(risid, sourceId);
      setAttempt((a) => a + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not detach file");
    }
  }

  if (loading || error) {
    return <ReportStatus loading={loading} error={error} onRetry={() => setAttempt((a) => a + 1)} />;
  }
  const rows = references ?? [];
  if (rows.length === 0) return <EmptyState label="No references yet — import a RIS file or pull from Zotero." />;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-text-primary">{rows.length} reference(s)</h2>
        <CsvButton
          filename="references.csv"
          headers={["Title", "Authors", "Year", "Type"]}
          rows={rows.map((r) => [r.title, r.authors.join("; "), r.year, r.type])}
        />
      </div>
      <div className={cardCls}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className={thCls}>Title</th>
              <th className={thCls}>Authors</th>
              <th className={thCls}>Year</th>
              <th className={thCls}>Type</th>
              <th className={thCls}>Sources</th>
              <th className={cn(thCls, "w-10")} />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.risid} className="hover:bg-surface-higher">
                <td className={cn(tdCls, "max-w-md font-medium")}>
                  <span className="block truncate" title={r.title}>
                    {r.title}
                  </span>
                </td>
                <td className={cn(tdCls, "max-w-56 text-text-secondary")}>
                  <span className="block truncate" title={r.authors.join(", ")}>
                    {r.authors.join(", ")}
                  </span>
                </td>
                <td className={cn(tdCls, "whitespace-nowrap")}>{r.year}</td>
                <td className={cn(tdCls, "whitespace-nowrap")}>{r.type}</td>
                <td className={cn(tdCls, "text-text-secondary")}>
                  {r.sources.length > 0 ? `${r.sources.length} linked` : "—"}
                </td>
                <td className={cn(tdCls, "text-right")}>
                  <div className="flex items-center justify-end gap-1">
                    {r.sources.map((s) => (
                      <span key={s.id} className="flex items-center gap-1">
                        <button
                          type="button"
                          title={`Open ${s.name} in the coder`}
                          onClick={() =>
                            useProjectStore.getState().setView({ kind: "coding", sourceId: s.id })
                          }
                          className="rounded-sm px-1 py-0.5 text-xs text-accent hover:bg-accent/10"
                        >
                          {s.name}
                        </button>
                        <button
                          type="button"
                          title="Detach"
                          onClick={() => void detach(r.risid, s.id)}
                          className="rounded-sm p-0.5 text-text-secondary hover:text-danger"
                        >
                          <X size={11} aria-hidden />
                        </button>
                      </span>
                    ))}
                    <button
                      type="button"
                      title="Attach PDF/EPUB…"
                      onClick={() => void attach(r.risid)}
                      className="flex items-center gap-1 rounded-sm border border-border bg-bg px-1.5 py-0.5 text-xs hover:bg-surface-higher"
                    >
                      <Paperclip size={11} aria-hidden />
                      Attach
                    </button>
                    <button
                      type="button"
                      title="Delete reference"
                      onClick={() => {
                        if (window.confirm(`Delete reference "${r.title}"?`)) void remove(r.risid);
                      }}
                      className="rounded-sm p-1 text-text-secondary hover:bg-danger/10 hover:text-danger"
                    >
                      <Trash2 size={13} aria-hidden />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
