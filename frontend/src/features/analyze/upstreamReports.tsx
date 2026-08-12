/**
 * Standalone analysis tools that survived the restructure: word cloud,
 * codebook export and the references manager. (The merged analytical
 * screens live in merged.tsx.)
 */
import { useEffect, useRef, useState } from "react";
import { Download, Paperclip, Trash2, X } from "lucide-react";
import { api, type ReferenceEntry } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";
import {
  Button,
  EmptyState,
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
} from "@/features/analyze/reportKit";

function CsvButton({ filename, headers, rows }: { filename: string; headers: string[]; rows: unknown[][] }) {
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

// ---------------------------------------------------------------------------
// Word cloud
// ---------------------------------------------------------------------------

export function WordCloudReport() {
  const { t } = useI18n();
  const sources = useProjectStore((state) => state.sources).filter(
    (s) => s.media_type === "text" || s.media_type === "pdf",
  );
  const [sourceId, setSourceId] = useState<number | "">("");
  const [attempt, setAttempt] = useState(0);
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
  }, [sourceId, attempt]);

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
        <span className="text-sm text-text-secondary">{t("analyze.source")}</span>
        <Select value={sourceId} onChange={(e) => setSourceId(e.target.value === "" ? "" : Number(e.target.value))} className="w-full">
          <option value="">{t("analyze.allTextSources")}</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </Select>
      </div>
      {loading ? (
        <ReportStatus loading error={null} onRetry={() => {}} />
      ) : error ? (
        <ReportStatus loading={false} error={error} onRetry={() => setAttempt((a) => a + 1)} />
      ) : !rows || rows.rows.length === 0 ? (
        <div className="h-48"><EmptyState>No data</EmptyState></div>
      ) : (
        <>
          <ReportMenuBar>
            <CsvButton
              filename="word-frequencies.csv"
              headers={[t("analyze.colWord"), t("analyze.colCount")]}
              rows={rows.rows.map((r) => [r.word, r.count])}
            />
          </ReportMenuBar>
          <canvas ref={canvasRef} className="h-[360px] w-full rounded-sm border border-border bg-white" />
          <div className={cardCls}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10">
                <tr>
                  <th className={thCls}>{t("analyze.colWord")}</th>
                  <th className={cn(thCls, "text-right")}>{t("analyze.colCount")}</th>
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
// Codebook
// ---------------------------------------------------------------------------

export function CodebookReport() {
  const { t } = useI18n();
  const [memos, setMemos] = useState(false);
  // The loader depends on `memos` — without the deps the toggle would show
  // stale text (the shared useReport re-runs whenever its deps change).
  const { data, loading, error, retry } = useReport(
    () => api.reports.codebook(memos),
    [memos],
  );
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
      <ReportMenuBar>
        <label className="flex items-center gap-1.5 text-sm text-text-secondary">
          <input type="checkbox" checked={memos} onChange={(e) => setMemos(e.target.checked)} />
          {t("analyze.withMemos")}
        </label>
        <Button
          variant="secondary"
          className="text-text-secondary hover:text-text-primary"
          onClick={() => void download()}
          icon={<Download size={12} aria-hidden />}
        >
          {t("analyze.downloadCodebook")}
        </Button>
        <Button
          variant="secondary"
          className="text-text-secondary hover:text-text-primary"
          onClick={() => void copy()}
        >
          {copied ? t("common.copied") : t("analyze.copyCodebook")}
        </Button>
      </ReportMenuBar>
      <pre className="qc-selectable max-h-96 overflow-y-auto whitespace-pre-wrap break-words rounded-sm border border-border bg-surface p-3 text-xs leading-relaxed text-text-primary">
        {data?.text || "—"}
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------------------
// References
// ---------------------------------------------------------------------------

export function ReferencesReport() {
  const { t } = useI18n();
  const [references, setReferences] = useState<ReferenceEntry[] | null>(null);
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
  if (rows.length === 0)
    return <div className="h-48"><EmptyState>{t("analyze.referencesEmpty")}</EmptyState></div>;
  return (
    <div className="space-y-2">
      <ReportMenuBar>
        <CsvButton
          filename="references.csv"
          headers={[t("analyze.colTitle"), t("analyze.colAuthors"), t("analyze.colYear"), t("analyze.colType")]}
          rows={rows.map((r) => [r.title, r.authors.join("; "), r.year, r.type])}
        />
      </ReportMenuBar>
      <h2 className="text-sm font-medium text-text-primary">{t("analyze.referencesCount", { n: rows.length })}</h2>
      <div className={cardCls}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className={thCls}>{t("analyze.colTitle")}</th>
              <th className={thCls}>{t("analyze.colAuthors")}</th>
              <th className={thCls}>{t("analyze.colYear")}</th>
              <th className={thCls}>{t("analyze.colType")}</th>
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
                  {r.sources.length > 0 ? t("analyze.linkedCount", { n: r.sources.length }) : "—"}
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
                        if (window.confirm(t("analyze.deleteReferenceConfirm", { title: r.title }))) void remove(r.risid);
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
