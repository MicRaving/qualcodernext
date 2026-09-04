/**
 * RConsoleView — the "R console" analysis report: script editor, background
 * R runs (through the shared task queue), saved scripts, output/artifact
 * display and report-data preparation.
 *
 * Backend contract (Rscript bridge):
 *   GET    /r/status                     → RStatus
 *   POST   /r/run                        → { job_id }  (starts immediately)
 *   GET    /r/jobs/{id}                  → RJob
 *   DELETE /r/jobs/{id}
 *   GET    /r/artifacts                  → { artifacts }
 *   GET    /r/artifacts/{name}           → bytes (PNG/CSV)
 *   GET    /r/scripts (+ POST/PATCH/DELETE)
 *   POST   /r/prepare-report             → { stub, files }
 *
 * R runs with QC_PORT / QC_PROJECT / QC_EXCHANGE set in its environment.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CircleAlert,
  CircleCheck,
  LoaderCircle,
  Play,
  RefreshCw,
  Save,
  Square,
  Trash2,
} from "lucide-react";
import {
  api,
  type RArtifact,
  type RJob,
  type RScript,
  type RStatus,
} from "@/lib/api";
import { localRequestBlob } from "@/lib/api/transport";
import { cn, errorMessage } from "@/lib/utils";
import { useAsyncEffect } from "@/lib/useAsync";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { useProjectStore } from "@/stores/project";
import {
  Button,
  EmptyState,
  ErrorBanner,
  Input,
  SectionLabel,
  Select,
  Textarea,
} from "@/components/ui/orchestrator";
import { cardCls, tdCls } from "@/features/analyze/reportData";

/** Embedded script templates (plain strings — no highlighting in v1). */
const TEMPLATES: Record<string, string> = {
  matrix: `# Code x document matrix — read-only RSQLite on the QCnext project
library(RSQLite)

con <- dbConnect(SQLite(), Sys.getenv("QC_PROJECT"), flags = SQLITE_RO)
m <- dbGetQuery(con,
  "SELECT fid, cid, COUNT(*) AS n FROM code_text_visible GROUP BY fid, cid")
d <- reshape(m, idvar = "fid", timevar = "cid", direction = "wide")
names(d) <- sub("^n\\\\.", "code_", names(d))
out <- file.path(Sys.getenv("QC_EXCHANGE"), "out", "matrix.csv")
dir.create(dirname(out), showWarnings = FALSE, recursive = TRUE)
write.csv(d, out, row.names = FALSE, fileEncoding = "UTF-8")
cat("Wrote", out, "\\n")
dbDisconnect(con)
`,
  http: `# HTTP example — run a read-only SQL query via QCnext's /sql/run API
library(httr)
library(jsonlite)

base <- sprintf("http://127.0.0.1:%s/api/v1", Sys.getenv("QC_PORT", "8765"))
res <- POST(paste0(base, "/sql/run"),
  body = list(sql = "SELECT cid, name FROM code_name ORDER BY name"),
  encode = "json")
stop_for_status(res)
rows <- fromJSON(content(res, "text", encoding = "UTF-8"))
print(rows)
`,
  irr: `# Interrater agreement (irr package) — reads the prepared segments CSV
# Prepare the data first via "Prepare report data" (Interrater report).
library(irr)

df <- read.csv(file.path(Sys.getenv("QC_EXCHANGE"), "in", "segments.csv"),
  fileEncoding = "UTF-8", check.names = FALSE)
w <- reshape(df, idvar = "segment_id", timevar = "coder", direction = "wide")
m <- w[, grepl("^code", names(w))]
m <- m[complete.cases(m), ]
if (nrow(m) < 2) stop("Need at least two coders with overlapping segments")
k <- kappa2(m)
cat("Cohen's kappa:", k$value, "\\n")
`,
  quanteda: `# Word frequencies (quanteda) — reads the prepared text sources CSV
# Prepare the data first via "Prepare report data" (Text & corpus report).
library(quanteda)

df <- read.csv(file.path(Sys.getenv("QC_EXCHANGE"), "in", "texts.csv"),
  fileEncoding = "UTF-8", check.names = FALSE)
corp <- corpus(df, text_field = "fulltext", docid_field = "name")
toks <- tokens(corp, remove_punct = TRUE, remove_numbers = TRUE)
dfm1 <- dfm(toks, remove = stopwords("en"))
freq <- textstat_frequency(dfm1, n = 20)
out <- file.path(Sys.getenv("QC_EXCHANGE"), "out", "word_frequencies.csv")
dir.create(dirname(out), showWarnings = FALSE, recursive = TRUE)
write.csv(freq, out, row.names = FALSE, fileEncoding = "UTF-8")
print(head(freq, 10))
`,
};

/** The four analytical reports the "prepare report data" action covers. */
const PREPARE_REPORTS: { id: string; labelKey: string }[] = [
  { id: "code-frequencies", labelKey: "analyze.titleCodeFrequencies" },
  { id: "code-segments", labelKey: "analyze.titleCodeSegments" },
  { id: "interrater", labelKey: "analyze.titleInterrater" },
  { id: "text-corpus", labelKey: "analyze.titleTextCorpus" },
];

/** Minimal RFC-4180-ish CSV parser for previews (header row included). */
function parseCsv(text: string, maxRows: number): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;
  for (let i = 0; i < text.length && rows.length <= maxRows; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        cell += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n") {
      row.push(cell);
      cell = "";
      rows.push(row);
      row = [];
    } else if (ch !== "\r") {
      cell += ch;
    }
  }
  if (cell !== "" || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows.slice(0, maxRows);
}

export function RConsoleView() {
  const { t } = useI18n();
  const toast = useToast();

  // The newest R task in the store queue drives what we poll/display.
  // NOTE: select the raw array here and derive the R-task list with useMemo —
  // a selector returning a fresh filter() array on every render makes
  // useSyncExternalStore re-render forever ("Maximum update depth exceeded").
  const allTasks = useProjectStore((s) => s.tasks);
  const { rTasks, running } = useMemo(() => {
    const list = allTasks.filter((j) => j.kind === "r");
    return {
      rTasks: list,
      running: list.find((j) => j.state === "running" || j.state === "queued") ?? null,
    };
  }, [allTasks]);
  const currentRTask = rTasks[rTasks.length - 1] ?? null;
  const removeTask = useProjectStore((s) => s.removeTask);

  const [status, setStatus] = useState<RStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [script, setScript] = useState(TEMPLATES.matrix);
  const [job, setJob] = useState<RJob | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [artifacts, setArtifacts] = useState<RArtifact[]>([]);
  const [pngUrls, setPngUrls] = useState<Record<string, string>>({});
  const [csvPreview, setCsvPreview] = useState<Record<string, string[][]>>({});
  const [scripts, setScripts] = useState<RScript[]>([]);
  const [scriptName, setScriptName] = useState("");
  const [prepareReportId, setPrepareReportId] = useState(PREPARE_REPORTS[0].id);
  const [preparing, setPreparing] = useState(false);
  const [preparedFiles, setPreparedFiles] = useState<string[]>([]);

  // Object URLs created for artifact PNGs; revoked on unmount.
  const createdUrlsRef = useRef<string[]>([]);

  // R installation status (console + the Settings card share this call).
  useAsyncEffect(async (signal) => {
    try {
      const s = await api.rStatus();
      signal.throwIfAborted();
      setStatus(s);
    } catch {
      signal.throwIfAborted();
      setStatus({ available: false, path: null, version: null, error: null });
    } finally {
      signal.throwIfAborted();
      setStatusLoading(false);
    }
  }, []);

  const loadScripts = useCallback(async () => {
    try {
      const res = await api.rScripts();
      setScripts(res.scripts);
    } catch {
      /* keep the last list */
    }
  }, []);

  const loadArtifacts = useCallback(async () => {
    try {
      const res = await api.rArtifacts();
      setArtifacts(res.artifacts);
    } catch {
      /* keep the last list */
    }
  }, []);

  useEffect(() => {
    void loadScripts();
    void loadArtifacts();
  }, [loadScripts, loadArtifacts]);

  // Poll the newest R job: live progress while running, one final fetch
  // when it settles; artifacts refresh on completion.
  const rTaskId = currentRTask?.id;
  const rTaskState = currentRTask?.state;
  useEffect(() => {
    if (!rTaskId) return;
    let cancelled = false;
    let timer: number | null = null;
    const fetchJob = async () => {
      try {
        const j = await api.rJob(rTaskId);
        if (cancelled) return;
        setJob(j);
        if (j.state === "done" || j.state === "error") void loadArtifacts();
      } catch {
        /* transient — the next poll retries */
      }
    };
    void fetchJob();
    if (rTaskState === "running") {
      timer = window.setInterval(() => void fetchJob(), 1500);
    }
    return () => {
      cancelled = true;
      if (timer !== null) window.clearInterval(timer);
    };
  }, [rTaskId, rTaskState, loadArtifacts]);

  // Revoke stale object URLs when the artifact list changes (refresh).
  const artifactNames = artifacts.map((a) => a.name).join("\u0000");
  useEffect(() => {
    const wanted = new Set(artifactNames.split("\u0000"));
    setPngUrls((prev) => {
      const stale = Object.keys(prev).filter((n) => !wanted.has(n));
      for (const n of stale) URL.revokeObjectURL(prev[n]);
      if (stale.length === 0) return prev;
      const next = { ...prev };
      for (const n of stale) delete next[n];
      return next;
    });
    setCsvPreview((prev) => {
      const stale = Object.keys(prev).filter((n) => !wanted.has(n));
      if (stale.length === 0) return prev;
      const next = { ...prev };
      for (const n of stale) delete next[n];
      return next;
    });
  }, [artifactNames]);

  // Fetch artifact bytes: PNG → object URL for <img>, CSV → preview rows.
  const targets = artifacts.filter((a) => a.kind === "png" || a.kind === "csv");
  const targetNames = targets.map((a) => a.name).join("\u0000");
  useEffect(() => {
    if (targetNames === "") return;
    const list = targetNames.split("\u0000");
    let cancelled = false;
    void (async () => {
      for (const name of list) {
        if (cancelled) break;
        const artifact = targets.find((a) => a.name === name);
        if (!artifact) continue;
        try {
          // Authenticated fetch (server mode needs the bearer header — a raw
          // <img src> URL cannot send it).
          const blob = await localRequestBlob(`/r/artifacts/${encodeURIComponent(name)}`);
          if (cancelled) continue;
          if (artifact.kind === "png") {
            const url = URL.createObjectURL(blob);
            createdUrlsRef.current.push(url);
            setPngUrls((prev) => {
              if (prev[name] && prev[name] !== url) URL.revokeObjectURL(prev[name]);
              return { ...prev, [name]: url };
            });
          } else {
            const text = await blob.text();
            if (cancelled) continue;
            setCsvPreview((prev) => ({ ...prev, [name]: parseCsv(text, 50) }));
          }
        } catch {
          /* the artifact may be gone — skip it */
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetNames]);

  useEffect(
    () => () => {
      for (const url of createdUrlsRef.current) URL.revokeObjectURL(url);
      createdUrlsRef.current = [];
    },
    [],
  );

  async function handleRun() {
    if (!status?.available || !script.trim() || running) return;
    setJobError(null);
    setPreparedFiles([]);
    try {
      const res = await api.rRun(script);
      useProjectStore.getState().enqueueRJob({
        id: res.job_id,
        sourceName: scriptName.trim() || t("r.scriptDefault"),
      });
      setJob(null);
    } catch (e) {
      setJobError(errorMessage(e, t("r.error")));
    }
  }

  async function handleSaveScript() {
    const name = scriptName.trim();
    if (!name || !script.trim()) return;
    setJobError(null);
    try {
      const existing = scripts.some((s) => s.name === name);
      if (existing) await api.rScriptPatch(name, script);
      else await api.rScriptCreate(name, script);
      setScriptName("");
      await loadScripts();
      toast.success(t("r.scriptSaved", { name }));
    } catch (e) {
      setJobError(errorMessage(e, t("r.error")));
    }
  }

  async function handleDeleteScript(name: string) {
    if (!window.confirm(t("r.deleteScriptConfirm", { name }))) return;
    try {
      await api.rScriptDelete(name);
      if (scriptName === name) setScriptName("");
      await loadScripts();
      toast.info(t("r.scriptDeleted", { name }));
    } catch (e) {
      setJobError(errorMessage(e, t("r.error")));
    }
  }

  function loadScript(s: RScript) {
    setScript(s.script);
    setScriptName(s.name);
  }

  async function handlePrepare() {
    if (preparing) return;
    setPreparing(true);
    setJobError(null);
    try {
      const res = await api.rPrepareReport(prepareReportId);
      setScript((prev) => (prev.trim() ? `${prev}\n\n${res.stub}` : res.stub));
      setPreparedFiles(res.files);
    } catch (e) {
      setJobError(errorMessage(e, t("r.error")));
    } finally {
      setPreparing(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* Status + prepare-report bar */}
      <div className="flex flex-wrap items-center gap-2">
        {status ? (
          status.available ? (
            <span className="flex items-center gap-1.5 rounded-sm border border-success/40 bg-success/10 px-2 py-1 text-xs text-success">
              <CircleCheck size={13} aria-hidden />
              {t("r.detected", { version: status.version ?? "?", path: status.path ?? "?" })}
            </span>
          ) : (
            <span className="flex items-center gap-1.5 rounded-sm border border-warning/40 bg-warning/10 px-2 py-1 text-xs text-warning">
              <CircleAlert size={13} aria-hidden />
              {t("r.notFound")}
              <a
                href="https://www.r-project.org/"
                target="_blank"
                rel="noreferrer"
                className="underline hover:text-accent"
              >
                {t("r.installHint")}
              </a>
            </span>
          )
        ) : statusLoading ? (
          <span className="flex items-center gap-1.5 text-xs text-text-secondary">
            <LoaderCircle size={12} className="animate-spin" aria-hidden />
            {t("r.checking")}
          </span>
        ) : null}
        <span className="flex-1" />
        <Select
          value={prepareReportId}
          onChange={(e) => setPrepareReportId(e.target.value)}
          aria-label={t("r.prepareReport")}
          disabled={!status?.available || preparing || !!running}
        >
          {PREPARE_REPORTS.map((r) => (
            <option key={r.id} value={r.id}>
              {t(r.labelKey)}
            </option>
          ))}
        </Select>
        <Button
          variant="toolbar"
          onClick={() => void handlePrepare()}
          disabled={!status?.available || preparing || !!running}
        >
          {preparing ? t("r.running") : t("r.prepareReport")}
        </Button>
        {preparedFiles.length > 0 && (
          <p className="w-full text-xs text-text-secondary">
            {t("r.preparedFiles", { files: preparedFiles.join(", ") })}
          </p>
        )}
      </div>

      {/* Saved scripts (Phase 2) */}
      <div className={cn(cardCls, "p-2")}>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-text-secondary">{t("r.savedScripts")}</span>
          {scripts.length === 0 ? (
            <span className="text-xs text-text-secondary/60">{t("r.noScripts")}</span>
          ) : (
            scripts.map((s) => (
              <span
                key={s.name}
                className="flex items-center gap-1 rounded-sm border border-border bg-bg px-2 py-0.5 text-xs"
              >
                <button
                  type="button"
                  onClick={() => loadScript(s)}
                  title={t("r.loadScript")}
                  className="max-w-48 truncate text-text-primary hover:text-accent"
                >
                  {s.name}
                </button>
                <button
                  type="button"
                  onClick={() => void handleDeleteScript(s.name)}
                  aria-label={t("r.deleteScript", { name: s.name })}
                  title={t("r.deleteScript", { name: s.name })}
                  className="rounded-sm p-0.5 text-text-secondary hover:bg-surface-higher hover:text-danger"
                >
                  <Trash2 size={11} aria-hidden />
                </button>
              </span>
            ))
          )}
          <span className="flex-1" />
          <Input
            value={scriptName}
            onChange={(e) => setScriptName(e.target.value)}
            placeholder={t("r.scriptName")}
            aria-label={t("r.scriptName")}
            className="w-40 text-xs"
          />
          <Button
            variant="toolbarPrimary"
            onClick={() => void handleSaveScript()}
            disabled={!scriptName.trim() || !script.trim()}
            icon={<Save size={12} aria-hidden />}
          >
            {t("r.saveScript")}
          </Button>
        </div>
      </div>

      {jobError && <ErrorBanner>{jobError}</ErrorBanner>}

      {/* Script editor + run bar */}
      <div className={cn(cardCls, "p-2")}>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value=""
            onChange={(e) => {
              if (e.target.value && TEMPLATES[e.target.value]) {
                setScript(TEMPLATES[e.target.value]);
              }
            }}
            aria-label={t("r.templates")}
            className="w-56"
          >
            <option value="">{t("r.templates")}…</option>
            <option value="matrix">{t("r.templateMatrix")}</option>
            <option value="http">{t("r.templateHttp")}</option>
            <option value="irr">{t("r.templateIrr")}</option>
            <option value="quanteda">{t("r.templateQuanteda")}</option>
          </Select>
          <span className="flex-1" />
          {running ? (
            <Button
              variant="toolbarDanger"
              onClick={() => removeTask(running.id)}
              disabled={!status?.available}
              icon={<Square size={13} aria-hidden />}
            >
              {t("r.cancel")}
            </Button>
          ) : (
            <Button
              variant="toolbarPrimary"
              onClick={() => void handleRun()}
              disabled={!status?.available || !script.trim()}
              icon={<Play size={13} aria-hidden />}
            >
              {t("r.run")}
            </Button>
          )}
        </div>
        <Textarea
          value={script}
          onChange={(e) => setScript(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              void handleRun();
            }
          }}
          rows={14}
          spellCheck={false}
          aria-label={t("r.editorAria")}
          placeholder={t("r.editorPlaceholder")}
          className="mt-2 w-full resize-y bg-bg p-2 font-mono text-xs text-text-primary"
        />
        <p className="mt-1 text-xs text-text-secondary">{t("r.runHint")}</p>
      </div>

      {/* Job output pane */}
      <section className="space-y-2">
        <SectionLabel>{t("r.outputs")}</SectionLabel>
        {running ? (
          <div
            className={cn(cardCls, "flex items-center gap-2 p-3 text-xs text-text-secondary")}
            role="status"
          >
            <LoaderCircle size={13} className="animate-spin" aria-hidden />
            <span className="min-w-0 flex-1 truncate">{running.message || t("r.running")}</span>
            <span className="tabular-nums">{Math.round(running.progress)}%</span>
          </div>
        ) : job ? (
          <div className={cn(cardCls, "p-3")}>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-text-secondary">{t("r.exitCode")}</span>
              <span
                className={cn(
                  "font-mono tabular-nums",
                  job.exit_code === 0 ? "text-success" : "text-danger",
                )}
              >
                {job.exit_code ?? "—"}
              </span>
              <span className="flex-1" />
              {job.state === "done" && (
                <span className="flex items-center gap-1 text-success">
                  <CircleCheck size={12} aria-hidden />
                  {t("r.done")}
                </span>
              )}
              {job.state === "error" && (
                <span className="flex items-center gap-1 text-danger">
                  <CircleAlert size={12} aria-hidden />
                  {t("r.error")}
                </span>
              )}
              {job.error && <span className="text-danger">{job.error}</span>}
            </div>
            <div className="mt-2 grid grid-cols-1 gap-3 lg:grid-cols-2">
              <div>
                <p className="text-xs font-medium text-text-secondary">{t("r.stdout")}</p>
                <pre className="qc-selectable mt-1 max-h-56 overflow-y-auto whitespace-pre-wrap break-words rounded-sm border border-border bg-bg p-2 font-mono text-xs leading-relaxed text-text-primary">
                  {job.stdout || "—"}
                </pre>
              </div>
              <div>
                <p className="text-xs font-medium text-text-secondary">{t("r.stderr")}</p>
                <pre className="qc-selectable mt-1 max-h-56 overflow-y-auto whitespace-pre-wrap break-words rounded-sm border border-border bg-bg p-2 font-mono text-xs leading-relaxed text-text-primary">
                  {job.stderr || "—"}
                </pre>
              </div>
            </div>
          </div>
        ) : (
          <div className={cn(cardCls, "p-3 text-center text-xs text-text-secondary")}>
            {t("r.noOutput")}
          </div>
        )}
      </section>

      {/* Artifacts (PNG rendered, CSV previewed) */}
      <section className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <SectionLabel>{t("r.artifacts")}</SectionLabel>
          <Button
            variant="toolbar"
            onClick={() => void loadArtifacts()}
            icon={<RefreshCw size={11} aria-hidden />}
          >
            {t("r.refresh")}
          </Button>
        </div>
        {artifacts.length === 0 ? (
          <div className={cn(cardCls, "p-3")}>
            <EmptyState>{t("r.noArtifacts")}</EmptyState>
          </div>
        ) : (
          <div className={cn(cardCls, "space-y-4 p-3")}>
            {artifacts.map((a) =>
              a.kind === "png" ? (
                <figure key={a.name}>
                  <figcaption className="text-xs font-medium text-text-primary">{a.name}</figcaption>
                  {pngUrls[a.name] ? (
                    <img
                      src={pngUrls[a.name]}
                      alt={a.name}
                      className="mt-1 max-h-96 w-full border border-border bg-white object-contain"
                    />
                  ) : (
                    <p className="mt-1 flex items-center gap-1.5 text-xs text-text-secondary">
                      <LoaderCircle size={11} className="animate-spin" aria-hidden />
                      {t("r.loading")}
                    </p>
                  )}
                </figure>
              ) : a.kind === "csv" ? (
                <div key={a.name}>
                  <p className="text-xs font-medium text-text-primary">{a.name}</p>
                  {csvPreview[a.name] ? (
                    <div className="qc-scroll mt-1 max-h-80 overflow-auto rounded-sm border border-border">
                      <table className="w-full border-collapse">
                        <tbody>
                          {csvPreview[a.name].map((row, ri) => (
                            <tr key={ri}>
                              {row.map((cell, ci) => (
                                <td
                                  key={ci}
                                  className={cn(tdCls, ri === 0 && "bg-surface-higher font-medium")}
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
                    <p className="mt-1 flex items-center gap-1.5 text-xs text-text-secondary">
                      <LoaderCircle size={11} className="animate-spin" aria-hidden />
                      {t("r.loading")}
                    </p>
                  )}
                </div>
              ) : (
                <p key={a.name} className="text-xs text-text-primary">
                  {a.name} <span className="text-text-secondary">({a.size} B)</span>
                </p>
              ),
            )}
          </div>
        )}
      </section>
    </div>
  );
}
