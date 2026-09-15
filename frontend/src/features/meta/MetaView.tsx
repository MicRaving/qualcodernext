/**
 * Meta-analysis workspace — hits move through abstract screening, paper
 * download and data extraction. Tab-specific controls live in the center
 * menubar and the study left bar; the center shows the work for the focused
 * (or selected) study: its abstract + verdicts, the download table, or the
 * extraction table.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  Check,
  Eye,
  FilePlus2,
  FileSpreadsheet,
  FileText,
  LoaderCircle,
  Play,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react";
import { api, fetchSourceFile, localRequestBlob } from "@/lib/api";
import type {
  MetaCriterion,
  MetaDocument,
  MetaExtraction,
  MetaHit,
  MetaJob,
  MetaScheme,
  MetaScreening,
} from "@/lib/api/types";
import {
  Button,
  EmptyState,
  ErrorBanner,
  IconButton,
  Input,
  LoadingState,
  Modal,
  Select,
  TableHead,
  Textarea,
  ViewHeader,
} from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { errorMessage } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace";
import { MetaImportDialog } from "@/features/meta/MetaImportDialog";
import { MetaSchemeEditor } from "@/features/meta/MetaSchemeEditor";

type Tab = "screen" | "download" | "extract";

const VERDICT_CHOICES = ["Yes", "No", "Unsure"] as const;
const CERTAINTY_CHOICES = ["High", "Medium", "Low"] as const;

/** Table body cell (mirrors the report tables' `tdCls`). */
const TD = "border-b border-border px-3 py-1.5 text-sm align-top";

function statusBadgeClass(status: string): string {
  switch (status) {
    case "included":
    case "downloaded":
    case "extracted":
    case "done":
      return "bg-success/10 text-success";
    case "excluded":
    case "failed":
      return "bg-danger/10 text-danger";
    case "working":
      return "bg-warning/10 text-warning";
    default:
      return "bg-surface-higher text-text-secondary";
  }
}

/** i18n key for a job kind (reuses the pipeline tab labels). */
function jobKindKey(kind: string): string {
  return kind === "screen"
    ? "meta.jobScreen"
    : kind === "download"
      ? "meta.jobDownload"
      : "meta.jobExtract";
}

function isRunning(job: MetaJob): boolean {
  return job.state === "running" || job.state === "queued";
}

export function MetaView() {
  const { t } = useI18n();
  const toast = useToast();
  const tab = useWorkspaceStore((s) => s.metaUi.tab);
  const selectedHit = useWorkspaceStore((s) => s.metaUi.selectedHit);
  const selectedIds = useWorkspaceStore((s) => s.metaUi.selectedIds);
  const scheme = useWorkspaceStore((s) => s.metaUi.scheme);
  const email = useWorkspaceStore((s) => s.metaUi.email);
  const importOpen = useWorkspaceStore((s) => s.metaUi.importOpen);
  const schemeOpen = useWorkspaceStore((s) => s.metaUi.schemeOpen);
  const tick = useWorkspaceStore((s) => s.metaUi.tick);
  const setMetaUi = useWorkspaceStore((s) => s.setMetaUi);

  const [criteria, setCriteria] = useState<MetaCriterion[]>([]);
  const [schemes, setSchemes] = useState<MetaScheme[]>([]);
  const [documents, setDocuments] = useState<MetaDocument[]>([]);
  const [extractions, setExtractions] = useState<MetaExtraction[]>([]);
  const [status, setStatus] = useState<{
    hits: number;
    criteria: number;
    schemes: number;
    eligible: number;
    documents_done: number;
    extracted: number;
  } | null>(null);
  const [jobs, setJobs] = useState<MetaJob[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Screening controls (center menubar).
  const [runId, setRunId] = useState("");
  const [clusterSize, setClusterSize] = useState(8);

  const [showCriteria, setShowCriteria] = useState(false);
  const [detailExt, setDetailExt] = useState<MetaExtraction | null>(null);
  const [selectedScreening, setSelectedScreening] = useState<MetaScreening | null>(null);
  const [pdfDoc, setPdfDoc] = useState<MetaDocument | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);

  /** Bump the shared data version so both this view and the left bar reload. */
  const refresh = useCallback(() => {
    setMetaUi({ tick: useWorkspaceStore.getState().metaUi.tick + 1 });
  }, [setMetaUi]);

  const load = useCallback(async () => {
    try {
      const [c, s, d, e, st] = await Promise.all([
        api.metaCriteria(),
        api.metaSchemes(),
        api.metaDocuments(),
        api.metaExtractions(),
        api.metaStatus(),
      ]);
      setCriteria(c);
      setSchemes(s);
      setDocuments(d);
      setExtractions(e);
      setStatus(st);
      const current = useWorkspaceStore.getState().metaUi.scheme;
      if (s.length > 0 && (!current || !s.some((x) => x.name === current))) {
        setMetaUi({ scheme: s[0].name });
      }
      setError(null);
    } catch (err) {
      // Surface a real load failure instead of spinning forever; a transient
      // miss keeps whatever is already loaded.
      setError(errorMessage(err));
      setStatus((prev) =>
        prev ?? { hits: 0, criteria: 0, schemes: 0, eligible: 0, documents_done: 0, extracted: 0 },
      );
    }
  }, [setMetaUi]);

  const loadJobs = useCallback(async () => {
    try {
      setJobs(await api.metaJobs());
    } catch {
      /* no project open */
    }
  }, []);

  // Keep the latest `load` reachable from the polling interval without
  // restarting it every time `scheme` changes.
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  // Reload data + jobs on tab change and whenever a mutation bumps the tick
  // (including mutations performed by the study left bar).
  useEffect(() => {
    void load();
    void loadJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, tick]);

  // Poll only while a job is running; reload the data once when it settles.
  const runningKey = useMemo(
    () => jobs.filter(isRunning).map((j) => j.id).sort().join(","),
    [jobs],
  );
  useEffect(() => {
    if (!runningKey) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const next = await api.metaJobs();
          if (cancelled) return;
          setJobs(next);
          if (!next.some(isRunning)) {
            window.clearInterval(timer);
            void loadRef.current();
          }
        } catch {
          /* transient */
        }
      })();
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [runningKey]);

  const finishedJobs = jobs.filter((j) => !isRunning(j));

  // ── criteria ────────────────────────────────────────────────────────

  // Criteria are persisted automatically (on blur / add / delete) instead of
  // an explicit save step: they are project data like everything else.
  const persistCriteria = async (list: MetaCriterion[]) => {
    try {
      await api.metaReplaceCriteria(
        list.map((c, i) => ({
          ...c,
          position: i,
          key: c.key || `criterion${i + 1}`,
        })),
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("meta.importFailed"));
    }
  };

  const patchCriterion = (id: number, patch: Partial<MetaCriterion>) => {
    setCriteria((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  };

  const addCriterion = () => {
    const next = [
      ...criteria,
      { id: Date.now(), position: criteria.length, key: "", label: "", prompt_text: "", created: "" },
    ];
    setCriteria(next);
    void persistCriteria(next);
  };

  // ── screening ───────────────────────────────────────────────────────

  const startLlmScreen = async () => {
    try {
      await api.metaLlmScreen({ run_id: runId, cluster_size: clusterSize });
      toast.success(t("meta.screenStarted"));
      void loadJobs();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("meta.importFailed"));
    }
  };

  const refreshSelectedScreening = useCallback(async (hitId: number) => {
    try {
      const rows = await api.metaScreening({ hit_id: hitId });
      const latest = rows.reduce<MetaScreening | null>(
        (best, row) => (!best || row.id > best.id ? row : best),
        null,
      );
      setSelectedScreening(latest);
    } catch {
      setSelectedScreening(null);
    }
  }, []);

  // Focus the study chosen in the left bar and load its verdicts.
  useEffect(() => {
    if (!selectedHit) {
      setSelectedScreening(null);
      return;
    }
    void refreshSelectedScreening(selectedHit.hit_id);
  }, [selectedHit, refreshSelectedScreening]);

  const saveVerdict = async (hit: MetaHit) => {
    if (!selectedScreening) return;
    try {
      await api.metaSaveScreening({
        hit_id: hit.hit_id,
        run_id: selectedScreening.run_id,
        verdicts: selectedScreening.verdicts,
        intervention_type: selectedScreening.intervention_type,
        rationale: selectedScreening.rationale,
      });
      toast.success(t("meta.verdictSaved"));
      refresh();
      void refreshSelectedScreening(hit.hit_id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("meta.importFailed"));
    }
  };

  const updateVerdict = (key: string, field: "applies" | "certainty", value: string) => {
    setSelectedScreening((prev) => {
      if (!prev) return prev;
      const verdicts = { ...prev.verdicts };
      const current = verdicts[key] ?? { applies: "No", certainty: "Medium" };
      verdicts[key] = { ...current, [field]: value };
      return { ...prev, verdicts };
    });
  };

  const updateScreeningField = (field: "intervention_type" | "rationale", value: string) => {
    setSelectedScreening((prev) => (prev ? { ...prev, [field]: value } : prev));
  };

  const ensureScreeningRow = (hit: MetaHit) => {
    if (selectedScreening) return;
    if (criteria.length === 0) {
      toast.error(t("meta.noCriteriaHint"));
      return;
    }
    const empty: Record<string, { applies: string; certainty: string }> = {};
    for (const c of criteria) {
      empty[c.key] = { applies: "No", certainty: "Medium" };
    }
    setSelectedScreening({
      id: -hit.hit_id,
      hit_id: hit.hit_id,
      owner: "",
      run_id: runId,
      verdicts: empty,
      origin: "manual",
      created: "",
      updated: "",
    });
  };

  // ── downloads ───────────────────────────────────────────────────────

  const assignPdf = async (hitId: number, file: File | undefined) => {
    if (!file) return;
    try {
      await api.metaAssignPdf(hitId, file);
      refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("meta.importFailed"));
    }
  };

  const assignRefs = useRef<Record<number, HTMLInputElement | null>>({});

  const currentDocument = useMemo(
    () => documents.find((d) => d.hit_id === selectedHit?.hit_id) ?? null,
    [documents, selectedHit],
  );

  // The Extraction tab only lists papers with an acquired full text.
  const acquiredHitIds = useMemo(
    () => new Set(documents.filter((d) => d.source_id != null).map((d) => d.hit_id)),
    [documents],
  );
  const visibleExtractions = useMemo(
    () => extractions.filter((e) => acquiredHitIds.has(e.hit_id)),
    [extractions, acquiredHitIds],
  );

  const openPdf = (doc: MetaDocument | null) => {
    if (!doc?.source_id) {
      toast.error(t("meta.noPdfLinked"));
      return;
    }
    setPdfDoc(doc);
  };

  // Fetch the PDF bytes and hand them to the viewer as a blob URL — the file
  // endpoint serves an attachment, which an iframe would download otherwise.
  useEffect(() => {
    if (!pdfDoc?.source_id) {
      setPdfUrl(null);
      return;
    }
    const sourceId = pdfDoc.source_id;
    let cancelled = false;
    let url: string | null = null;
    setPdfLoading(true);
    void (async () => {
      try {
        const res = await fetchSourceFile(sourceId);
        const raw = await res.blob();
        if (cancelled) return;
        const blob = raw.type ? raw : new Blob([raw], { type: "application/pdf" });
        url = URL.createObjectURL(blob);
        setPdfUrl(url);
      } catch (err) {
        if (!cancelled) {
          toast.error(errorMessage(err));
          setPdfDoc(null);
        }
      } finally {
        if (!cancelled) setPdfLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
      setPdfUrl(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdfDoc]);

  // ── extraction ──────────────────────────────────────────────────────

  const startExtraction = async () => {
    if (!scheme) {
      toast.error(t("meta.needScheme"));
      return;
    }
    if (selectedIds.length === 0) {
      toast.error(t("meta.selectPapersHint"));
      return;
    }
    try {
      await api.metaExtractRun({
        scheme,
        hit_ids: selectedIds,
      });
      toast.success(t("meta.extractionStarted"));
      void loadJobs();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("meta.importFailed"));
    }
  };

  const exportData = async (fmt: "csv" | "xlsx") => {
    try {
      const blob = await localRequestBlob(`/meta/extract/export?fmt=${fmt}`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fmt === "csv" ? "meta_extraction.csv" : "meta_extraction.xlsx";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("meta.importFailed"));
    }
  };

  const publishExtraction = async (ext: MetaExtraction) => {
    try {
      await api.metaExtractPublish({ hit_id: ext.hit_id, to_cases: true, to_codes: true });
      toast.success(t("meta.published"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("meta.importFailed"));
    }
  };

  const cancelJob = async (jobId: string) => {
    try {
      await api.metaJobControl(jobId, "cancel");
      void loadJobs();
    } catch {
      /* ignore */
    }
  };

  const clearFinishedJobs = async () => {
    for (const job of finishedJobs) {
      try {
        await api.metaJobDelete(job.id);
      } catch {
        /* already gone */
      }
    }
    void loadJobs();
  };

  if (status === null) {
    return (
      <div className="flex h-full flex-col bg-bg">
        <ViewHeader back={false} title={t("nav.meta")} />
        <LoadingState />
      </div>
    );
  }

  const pipelineTabs = (
    <div className="flex items-center gap-1">
      {(
        [
          ["screen", t("meta.tabScreen")],
          ["download", t("meta.tabDownload")],
          ["extract", t("meta.tabExtract")],
        ] as [Tab, string][]
      ).map(([key, label]) => (
        <button
          key={key}
          type="button"
          onClick={() => setMetaUi({ tab: key })}
          aria-pressed={tab === key}
          className={`rounded-sm px-2 py-1 text-xs font-medium qc-motion ${
            tab === key ? "bg-surface-higher text-accent" : "text-text-secondary hover:bg-surface-higher"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );

  return (
    <div className="flex h-full flex-col bg-bg">
      <ViewHeader
        back={false}
        collapseTitle
        title={t("nav.meta")}
        leading={pipelineTabs}
        actions={
          <div className="flex items-center gap-2">
            {tab === "screen" && (
              <div className="flex items-center gap-2">
                <Input
                  value={runId}
                  onChange={(e) => setRunId(e.target.value)}
                  placeholder={t("meta.llmRunId")}
                  className="h-7 w-28 text-xs"
                  aria-label={t("meta.llmRunId")}
                />
                <Select
                  value={clusterSize}
                  onChange={(e) => setClusterSize(Number(e.target.value))}
                  className="h-7 w-12 text-xs"
                  aria-label={t("meta.clusterSize")}
                  title={t("meta.clusterHint")}
                >
                  {[4, 8, 12, 16].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </Select>
                <Button
                  variant="primary"
                  icon={<Sparkles size={13} aria-hidden />}
                  onClick={() => void startLlmScreen()}
                  disabled={criteria.length === 0}
                  title={criteria.length === 0 ? t("meta.noCriteriaHint") : undefined}
                >
                  {t("meta.llmScreen")}
                </Button>
                <Button variant="secondary" onClick={() => setShowCriteria((v) => !v)}>
                  {t("meta.criteriaTitle")}
                </Button>
              </div>
            )}

            {tab === "download" && (
              <Input
                value={email}
                onChange={(e) => setMetaUi({ email: e.target.value })}
                placeholder={t("meta.unpaywallEmail")}
                className="h-7 w-64 text-xs"
                aria-label={t("meta.unpaywallEmail")}
              />
            )}

            {tab === "extract" && (
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  icon={<FileText size={13} aria-hidden />}
                  disabled={!currentDocument?.source_id}
                  onClick={() => openPdf(currentDocument)}
                  title={t("meta.viewPdf")}
                >
                  {t("meta.viewPdf")}
                </Button>
                <Button
                  variant="primary"
                  icon={<Sparkles size={13} aria-hidden />}
                  onClick={() => void startExtraction()}
                  disabled={schemes.length === 0 || selectedIds.length === 0}
                  title={selectedIds.length === 0 ? t("meta.selectPapersHint") : undefined}
                >
                  {t("meta.autocodeSelected")}
                </Button>
                <Button
                  variant="secondary"
                  icon={<FileSpreadsheet size={13} aria-hidden />}
                  onClick={() => void exportData("xlsx")}
                  title={t("meta.exportXlsx")}
                >
                  {t("meta.exportXlsxShort")}
                </Button>
              </div>
            )}
          </div>
        }
      />
      {error && <ErrorBanner onClose={() => setError(null)}>{error}</ErrorBanner>}

      {/* Jobs strip */}
      {jobs.length > 0 && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-surface px-3 py-1 text-xs">
          {jobs.map((job) => (
            <span
              key={job.id}
              className="flex items-center gap-1.5 rounded-sm border border-border px-2 py-0.5"
              title={`${job.label} · ${job.state === "error" ? job.error ?? job.message : job.message ?? ""}`}
            >
              {isRunning(job) ? (
                <LoaderCircle size={11} className="animate-spin text-accent" aria-hidden />
              ) : job.state === "done" ? (
                <Check size={11} className="text-success" aria-hidden />
              ) : job.state === "error" ? (
                <span className="text-danger" aria-hidden>
                  ✗
                </span>
              ) : null}
              <span>
                {t(jobKindKey(job.kind))} · {Math.round(job.progress)}%
              </span>
              {job.state === "error" && job.error ? (
                <span className="max-w-64 truncate text-danger" title={job.error}>
                  {job.error}
                </span>
              ) : null}
              {isRunning(job) ? (
                <IconButton label={t("meta.cancelJob")} size="sm" onClick={() => void cancelJob(job.id)}>
                  <Trash2 size={10} aria-hidden />
                </IconButton>
              ) : null}
            </span>
          ))}
          {finishedJobs.length > 0 && (
            <IconButton
              label={t("meta.clearFinished")}
              size="sm"
              className="ml-auto"
              onClick={() => void clearFinishedJobs()}
            >
              <Trash2 size={11} aria-hidden />
            </IconButton>
          )}
        </div>
      )}

      {/* ── SCREENING (abstract + verdicts in the center) ── */}
      {tab === "screen" && (
        <div className="flex min-h-0 flex-1 flex-col">
          {showCriteria && (
            <div className="shrink-0 border-b border-border bg-surface px-3 py-2">
              <div className="mb-2 flex items-center gap-2">
                <span className="text-xs font-medium text-text-secondary">{t("meta.criteriaTitle")}</span>
                <Button variant="secondary" icon={<FilePlus2 size={12} aria-hidden />} onClick={addCriterion}>
                  {t("meta.addCriterion")}
                </Button>
                <span className="text-[11px] text-text-secondary">{t("meta.autoSaveHint")}</span>
              </div>
              {criteria.length === 0 && (
                <p className="mb-2 text-xs text-text-secondary">{t("meta.noCriteriaHint")}</p>
              )}
              <div className="grid gap-2 md:grid-cols-2">
                {criteria.map((c, i) => (
                  <div key={c.id} className="flex items-start gap-2 rounded-sm border border-border p-2">
                    <span className="mt-1.5 w-5 shrink-0 text-xs text-text-secondary">{i + 1}.</span>
                    <div className="flex-1 space-y-1">
                      <Input
                        value={c.label}
                        onChange={(e) => patchCriterion(c.id, { label: e.target.value })}
                        onBlur={() => void persistCriteria(criteria)}
                        placeholder={t("meta.criterionLabel")}
                        className="h-7 w-full text-xs"
                        aria-label={t("meta.criterionLabel")}
                      />
                      <Textarea
                        value={c.prompt_text}
                        onChange={(e) => patchCriterion(c.id, { prompt_text: e.target.value })}
                        onBlur={() => void persistCriteria(criteria)}
                        placeholder={t("meta.criterionPrompt")}
                        className="w-full text-xs"
                        rows={2}
                        aria-label={t("meta.criterionPrompt")}
                      />
                    </div>
                    <IconButton
                      label={t("common.delete")}
                      size="row"
                      onClick={() => void api.metaDeleteCriterion(c.id).then(() => refresh())}
                    >
                      <Trash2 size={12} aria-hidden />
                    </IconButton>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[1fr_380px]">
            {/* Abstract */}
            <div className="min-h-0 overflow-auto border-b border-border p-4 lg:border-b-0 lg:border-r">
              {selectedHit === null ? (
                <EmptyState icon={<Search size={24} aria-hidden />}>{t("meta.selectHit")}</EmptyState>
              ) : (
                <>
                  <h2 className="text-sm font-semibold text-text-primary">{selectedHit.title}</h2>
                  <p className="mt-0.5 text-xs text-text-secondary">
                    {selectedHit.authors ?? ""} · {selectedHit.year ?? ""} · {selectedHit.doi ?? ""}
                  </p>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-text-secondary">
                    {selectedHit.abstract || t("meta.noAbstract")}
                  </p>
                </>
              )}
            </div>

            {/* Verdict editor */}
            <div className="min-h-0 overflow-auto p-3">
              {selectedHit === null ? null : (
                (() => {
                  const hit = selectedHit;
                  const scr = selectedScreening;
                  return (
                    <div className="space-y-3">
                      {!scr ? (
                        criteria.length === 0 ? (
                          <p className="text-xs text-text-secondary">{t("meta.noCriteriaHint")}</p>
                        ) : (
                          <Button
                            variant="primary"
                            icon={<Play size={13} aria-hidden />}
                            onClick={() => ensureScreeningRow(hit)}
                          >
                            {t("meta.verdicts")}
                          </Button>
                        )
                      ) : (
                        <div className="space-y-2">
                          {criteria.map((c) => {
                            const verdict = scr?.verdicts?.[c.key] ?? { applies: "No", certainty: "Medium" };
                            return (
                              <div key={c.key} className="rounded-sm border border-border p-2">
                                <p className="mb-1.5 text-xs font-medium text-text-primary">{c.label}</p>
                                <div className="flex flex-wrap items-center gap-2">
                                  <label className="text-[10px] uppercase text-text-secondary">{t("meta.applies")}</label>
                                  <Select
                                    value={verdict.applies}
                                    onChange={(e) => updateVerdict(c.key, "applies", e.target.value)}
                                    className="h-7 w-24 text-xs"
                                  >
                                    {VERDICT_CHOICES.map((v) => (
                                      <option key={v} value={v}>
                                        {t(`meta.${v.toLowerCase()}`)}
                                      </option>
                                    ))}
                                  </Select>
                                  <label className="text-[10px] uppercase text-text-secondary">{t("meta.certainty")}</label>
                                  <Select
                                    value={verdict.certainty}
                                    onChange={(e) => updateVerdict(c.key, "certainty", e.target.value)}
                                    className="h-7 w-24 text-xs"
                                  >
                                    {CERTAINTY_CHOICES.map((v) => (
                                      <option key={v} value={v}>
                                        {t(`meta.${v.toLowerCase()}`)}
                                      </option>
                                    ))}
                                  </Select>
                                </div>
                              </div>
                            );
                          })}
                          <label className="block text-xs font-medium text-text-secondary">
                            {t("meta.interventionType")}
                            <Input
                              value={scr?.intervention_type ?? ""}
                              onChange={(e) => updateScreeningField("intervention_type", e.target.value)}
                              className="mt-1 h-7 text-xs"
                            />
                          </label>
                          <label className="block text-xs font-medium text-text-secondary">
                            {t("meta.rationale")}
                            <Textarea
                              value={scr?.rationale ?? ""}
                              onChange={(e) => updateScreeningField("rationale", e.target.value)}
                              className="mt-1 text-xs"
                              rows={3}
                            />
                          </label>
                          <div className="flex items-center gap-2">
                            <Button variant="primary" icon={<Check size={13} aria-hidden />} onClick={() => void saveVerdict(hit)}>
                              {t("meta.saveVerdict")}
                            </Button>
                            {scr?.origin === "llm" && (
                              <span className="rounded-sm bg-warning/10 px-1.5 py-px text-[10px] text-warning">
                                {t("meta.llmProposal")}
                              </span>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })()
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── DOWNLOADS ── */}
      {tab === "download" && (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-auto">
            {documents.length === 0 ? (
              <EmptyState icon={<ArrowDownToLine size={24} aria-hidden />}>{t("meta.noEligible")}</EmptyState>
            ) : (
              <table className="w-full text-left">
                <thead className="sticky top-0 bg-surface">
                  <tr>
                    <TableHead>{t("meta.colTitle")}</TableHead>
                    <TableHead>{t("meta.pdfStatus")}</TableHead>
                    <TableHead>{t("meta.colMethod")}</TableHead>
                    <TableHead className="w-32" />
                  </tr>
                </thead>
                <tbody>
                  {documents.map((doc) => (
                    <tr key={doc.id} className="qc-motion hover:bg-surface-higher">
                      <td className={`${TD} max-w-0`}>
                        <div className="truncate text-text-primary">{doc.title ?? ""}</div>
                        <div className="truncate text-xs text-text-secondary">{doc.doi ?? ""}</div>
                      </td>
                      <td className={TD}>
                        <span className={`rounded-sm px-1.5 py-px text-[10px] font-medium ${statusBadgeClass(doc.status)}`}>
                          {doc.status}
                        </span>
                        {doc.message ? (
                          <span className="ml-1.5 text-xs text-text-secondary">{doc.message}</span>
                        ) : null}
                      </td>
                      <td className={`${TD} text-text-secondary`}>{doc.retrieval_method ?? "—"}</td>
                      <td className={`${TD} text-right`}>
                        <Button
                          variant="secondary"
                          icon={<Eye size={12} aria-hidden />}
                          disabled={!doc.source_id}
                          onClick={() => openPdf(doc)}
                        >
                          {t("meta.viewPdf")}
                        </Button>
                        <Button
                          variant="secondary"
                          className="ml-1.5"
                          icon={<FilePlus2 size={12} aria-hidden />}
                          onClick={() => assignRefs.current[doc.hit_id]?.click()}
                        >
                          {t("meta.assignPdf")}
                        </Button>
                        <input
                          ref={(el) => {
                            assignRefs.current[doc.hit_id] = el;
                          }}
                          type="file"
                          accept=".pdf"
                          className="hidden"
                          onChange={(e) => {
                            void assignPdf(doc.hit_id, e.target.files?.[0]);
                            e.target.value = "";
                          }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* ── EXTRACTION ── */}
      {tab === "extract" && (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-auto">
            {visibleExtractions.length === 0 ? (
              <EmptyState icon={<Sparkles size={24} aria-hidden />}>{t("meta.noEligible")}</EmptyState>
            ) : (
              <table className="w-full text-left">
                <thead className="sticky top-0 bg-surface">
                  <tr>
                    <TableHead className="w-8" />
                    <TableHead>{t("meta.colTitle")}</TableHead>
                    <TableHead>{t("meta.scheme")}</TableHead>
                    <TableHead>{t("meta.hitStatus")}</TableHead>
                    <TableHead>{t("meta.colModel")}</TableHead>
                    <TableHead className="w-56" />
                  </tr>
                </thead>
                <tbody>
                  {visibleExtractions.map((ext) => (
                    <tr key={ext.id} className="qc-motion hover:bg-surface-higher">
                      <td className={`${TD} text-center`}>
                        <input
                          type="checkbox"
                          checked={selectedIds.includes(ext.hit_id)}
                          onChange={() =>
                            setMetaUi({
                              selectedIds: selectedIds.includes(ext.hit_id)
                                ? selectedIds.filter((x) => x !== ext.hit_id)
                                : [...selectedIds, ext.hit_id],
                            })
                          }
                          className="h-3.5 w-3.5 shrink-0 cursor-pointer rounded-sm border border-border accent-[var(--qc-accent)]"
                          aria-label={ext.title ?? ""}
                        />
                      </td>
                      <td className={`${TD} max-w-0`}>
                        <div className="truncate text-text-primary">{ext.title ?? ""}</div>
                        <div className="truncate text-xs text-text-secondary">{ext.doi ?? ""}</div>
                      </td>
                      <td className={`${TD} text-text-secondary`}>{ext.scheme_label ?? ext.scheme}</td>
                      <td className={TD}>
                        <span className={`rounded-sm px-1.5 py-px text-[10px] font-medium ${statusBadgeClass(ext.status)}`}>
                          {ext.status}
                        </span>
                        {ext.missing_reason ? (
                          <span className="ml-1.5 text-xs text-warning" title={ext.missing_reason}>
                            {t("meta.missingStats", { reason: ext.missing_reason })}
                          </span>
                        ) : null}
                      </td>
                      <td className={`${TD} text-text-secondary`}>{ext.model ?? "—"}</td>
                      <td className={`${TD} text-right`}>
                        <Button
                          variant="secondary"
                          icon={<Eye size={12} aria-hidden />}
                          onClick={() => setDetailExt(ext)}
                        >
                          {t("meta.viewDetails")}
                        </Button>
                        {ext.status === "extracted" && (
                          <Button variant="secondary" className="ml-1.5" onClick={() => void publishExtraction(ext)}>
                            {t("meta.publish")}
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      <MetaImportDialog
        open={importOpen}
        onClose={() => setMetaUi({ importOpen: false })}
        onImported={() => refresh()}
      />
      <MetaSchemeEditor
        open={schemeOpen}
        schemes={schemes}
        onClose={() => setMetaUi({ schemeOpen: false })}
        onChanged={() => refresh()}
      />

      {detailExt && (
        <Modal
          open
          onClose={() => setDetailExt(null)}
          size="lg"
          title={detailExt.title ?? detailExt.scheme}
        >
          <div className="max-h-[70vh] space-y-3 overflow-auto p-4 text-xs">
            {detailExt.prescreen ? (
              <div>
                <h4 className="mb-1 font-medium text-text-primary">{t("meta.prescreen")}</h4>
                <pre className="whitespace-pre-wrap rounded-sm bg-surface-higher p-2 text-[11px] text-text-secondary">
                  {JSON.stringify(detailExt.prescreen, null, 2)}
                </pre>
              </div>
            ) : null}
            <div>
              <h4 className="mb-1 font-medium text-text-primary">{t("meta.studyVars")}</h4>
              <pre className="whitespace-pre-wrap rounded-sm bg-surface-higher p-2 text-[11px] text-text-secondary">
                {JSON.stringify(detailExt.study_vars, null, 2)}
              </pre>
            </div>
            <div>
              <h4 className="mb-1 font-medium text-text-primary">
                {t("meta.dvMetrics")} ({detailExt.dv_metrics?.length ?? 0})
              </h4>
              <pre className="whitespace-pre-wrap rounded-sm bg-surface-higher p-2 text-[11px] text-text-secondary">
                {JSON.stringify(detailExt.dv_metrics, null, 2)}
              </pre>
            </div>
          </div>
        </Modal>
      )}

      <Modal
        open={pdfDoc !== null}
        onClose={() => setPdfDoc(null)}
        title={pdfDoc?.title ?? t("meta.viewPdf")}
        panelClassName="w-[85vw] max-w-[85vw]"
      >
        {pdfDoc?.source_id ? (
          pdfLoading || !pdfUrl ? (
            <div className="flex h-[78vh] items-center justify-center gap-2 text-sm text-text-secondary">
              <LoaderCircle size={16} className="animate-spin" aria-hidden />
              {t("meta.loadingPdf")}
            </div>
          ) : (
            <iframe
              title={pdfDoc.title ?? "PDF"}
              src={pdfUrl}
              className="h-[78vh] w-full border-0 bg-surface"
            />
          )
        ) : (
          <p className="p-4 text-sm text-text-secondary">{t("meta.noPdfLinked")}</p>
        )}
      </Modal>
    </div>
  );
}
