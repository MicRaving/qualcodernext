/**
 * Analyze tab (contract §6–§10/§11): pooled model + heterogeneity, two/three
 * level variance decomposition, leave-one-out, Egger/publication bias and an
 * inline SVG forest plot; subgroup/moderator fits; PRISMA counts; a categorical
 * summary; and Markdown/DOCX report export with a small preview.
 *
 * All requests are defensive: a backend that has not shipped a given endpoint
 * yet (or returns an unexpected shape) degrades to an empty state instead of
 * crashing the view.
 */
import { useEffect, useMemo, useState } from "react";
import { Download, FileText, Plus, Sigma, X } from "lucide-react";
import { api, localRequestBlob } from "@/lib/api";
import type {
  MetaAnalysisRequest,
  MetaAuditField,
  MetaAuditIssue,
  MetaAuditResult,
  MetaBayesRequest,
  MetaBayesResult,
  MetaBayesSensitivityRow,
  MetaForest,
  MetaLeaveOneOutResult,
  MetaModerator,
  MetaModeratorResult,
  MetaMultiverseResult,
  MetaMultiverseSpec,
  MetaMultiverseSummary,
  MetaPCurve,
  MetaPetPeese,
  MetaPooledResult,
  MetaPrismaCounts,
  MetaPublicationBiasEgger,
  MetaPublicationBiasResult,
  MetaSubgroupResult,
  MetaSummaryResult,
  MetaTrimAndFill,
} from "@/lib/api/types";
import {
  Button,
  EmptyState,
  ErrorBanner,
  LoadingState,
  Select,
} from "@/components/ui/orchestrator";
import { cardCls, tdCls, thCls } from "@/features/analyze/reportData";
import { Markdown } from "@/components/ui/Markdown";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { errorMessage } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace";

/** Shared report-table cell classes (see analyze/reportData). */
const TD = tdCls;
const NUM = `${tdCls} text-right tabular-nums`;

/** µ prior SD choices: N(0, sd²). */
const MU_PRIORS = [1, 5, 10, 100] as const;

/** τ prior choices; the select value encodes family + scale. */
const TAU_PRIORS = [
  { value: "half-normal:0.25", prior: "half-normal", scale: 0.25, labelKey: "meta.tauHalfNormal" },
  { value: "half-normal:0.5", prior: "half-normal", scale: 0.5, labelKey: "meta.tauHalfNormal" },
  { value: "half-normal:1", prior: "half-normal", scale: 1, labelKey: "meta.tauHalfNormal" },
  { value: "half-cauchy:0.5", prior: "half-cauchy", scale: 0.5, labelKey: "meta.tauHalfCauchy" },
  { value: "half-cauchy:1", prior: "half-cauchy", scale: 1, labelKey: "meta.tauHalfCauchy" },
] as const;

/** The default mock / a missing endpoint returns [] — treat as "no data". */
function asObject<T>(value: unknown): T | null {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as T;
  return null;
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function fmt(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "–";
  return Number(value).toFixed(digits);
}

function fmtP(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "–";
  const n = Number(value);
  if (n < 0.001) return "< .001";
  return n.toFixed(3);
}

function dlBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke on a later tick so an in-flight download is not aborted.
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-sm border border-border bg-surface px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-text-secondary">{label}</div>
      <div className="mt-0.5 text-sm font-semibold tabular-nums text-text-primary">{value}</div>
      {sub ? <div className="text-[10px] text-text-secondary">{sub}</div> : null}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">{title}</h3>
      {children}
    </section>
  );
}

/** Render one spec's chosen levels as a compact "dim=level; …" string. */
function formatChoices(choices: Record<string, unknown> | undefined): string {
  if (!choices) return "–";
  const parts = Object.entries(choices).map(([name, value]) => {
    const text = Array.isArray(value)
      ? value.map((v) => String(v)).join(", ")
      : String(value ?? "–");
    return `${name}=${text}`;
  });
  return parts.length > 0 ? parts.join("; ") : "–";
}

/** Severity → token colour classes (unknown severities read as neutral). */
function severityTone(severity: string): string {
  const s = (severity || "").toLowerCase();
  if (s === "error" || s === "high" || s === "critical") return "bg-danger/10 text-danger";
  if (s === "warning" || s === "warn" || s === "medium") return "bg-warning/10 text-warning";
  return "bg-surface-higher text-text-secondary";
}

function severityLabelKey(severity: string): string {
  const s = (severity || "").toLowerCase();
  if (s === "error" || s === "high" || s === "critical") return "meta.severity_error";
  if (s === "warning" || s === "warn" || s === "medium") return "meta.severity_warning";
  return "meta.severity_info";
}

/** Field issues arrive as a message list; fall back to a numeric count. */
function issueCount(issues: unknown): number {
  if (Array.isArray(issues)) return issues.length;
  const n = Number(issues);
  return Number.isFinite(n) ? n : 0;
}

function issueTitle(issues: unknown): string | undefined {
  if (Array.isArray(issues) && issues.length > 0) return issues.map((s) => String(s)).join("\n");
  return undefined;
}

/** Authenticated PNG preview + download (a raw <img src> cannot send the
 *  bearer header in server mode). Mirrors the PRISMA figure pattern. */
function PngFigure({
  label,
  downloadLabel,
  filename,
  load,
  queryKey,
  t,
}: {
  label: string;
  downloadLabel: string;
  filename: string;
  load: () => Promise<Blob>;
  queryKey: string;
  t: (key: string) => string;
}) {
  const toast = useToast();
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    void (async () => {
      try {
        const blob = await load();
        if (cancelled || !(blob instanceof Blob)) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      } catch {
        /* the figure is optional */
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey]);

  const download = async () => {
    try {
      const blob = await load();
      if (!(blob instanceof Blob)) return;
      dlBlob(blob, filename);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[11px] font-medium text-text-secondary">{label}</div>
        <Button
          variant="secondary"
          icon={<Download size={13} aria-hidden />}
          onClick={() => void download()}
        >
          {downloadLabel}
        </Button>
      </div>
      {url ? (
        <img
          src={url}
          alt={label}
          className="max-h-80 w-auto max-w-full rounded-sm border border-border bg-surface"
        />
      ) : (
        <p className="text-xs text-text-secondary">{t("meta.figureEmpty")}</p>
      )}
    </div>
  );
}

/** Minimal inline forest plot (no chart dependency). */
function ForestPlot({ forest, label }: { forest: MetaForest; label: string }) {
  const rows = forest.rows ?? [];
  if (rows.length === 0) return null;
  const points: number[] = [];
  for (const row of rows) {
    if (typeof row.effect === "number") points.push(row.effect);
    if (typeof row.ci_low === "number") points.push(row.ci_low);
    if (typeof row.ci_high === "number") points.push(row.ci_high);
  }
  const pooled = forest.pooled ?? null;
  if (pooled) {
    points.push(pooled.estimate, pooled.ci_low, pooled.ci_high);
  }
  if (points.length === 0) return null;
  let min = Math.min(...points, 0);
  let max = Math.max(...points, 0);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const pad = (max - min) * 0.05;
  min -= pad;
  max += pad;
  const width = 420;
  const left = 8;
  const right = width - 8;
  const rowH = 18;
  const height = rows.length * rowH + 24;
  const x = (v: number) => left + ((v - min) / (max - min)) * (right - left);
  const zeroX = x(0);
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${width} ${height}`}
      className="h-auto w-full max-w-lg text-text-secondary"
    >
      <line x1={zeroX} y1={0} x2={zeroX} y2={rows.length * rowH} stroke="currentColor" strokeDasharray="3 3" opacity={0.5} />
      {rows.map((row, i) => {
        const y = i * rowH + rowH / 2 + 4;
        const lo = typeof row.ci_low === "number" ? row.ci_low : row.effect;
        const hi = typeof row.ci_high === "number" ? row.ci_high : row.effect;
        const mid = typeof row.effect === "number" ? row.effect : 0;
        return (
          <g key={`${row.study_id}-${i}`}>
            <line x1={x(lo)} y1={y} x2={x(hi)} y2={y} stroke="var(--qc-accent)" strokeWidth={1.5} />
            <rect
              x={x(mid) - 3}
              y={y - 4}
              width={6}
              height={8}
              fill="var(--qc-accent)"
            />
          </g>
        );
      })}
      {pooled ? (
        <polygon
          points={`${x(pooled.ci_low)},${rows.length * rowH + 12} ${x(pooled.estimate)},${rows.length * rowH + 7} ${x(pooled.ci_high)},${rows.length * rowH + 12} ${x(pooled.estimate)},${rows.length * rowH + 17}`}
          fill="var(--qc-accent)"
          opacity={0.8}
        />
      ) : null}
    </svg>
  );
}

function PooledView({
  request,
  t,
}: {
  request: MetaAnalysisRequest;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const toast = useToast();
  // Model + estimator live in the menubar (workspace store) so switching tabs
  // keeps the analyst's choice; the Bayes prior selects stay in the body.
  const analysisModel = useWorkspaceStore((s) => s.metaUi.analysisModel);
  const poolModel = useWorkspaceStore((s) => s.metaUi.poolModel);
  const muSd = useWorkspaceStore((s) => s.metaUi.bayesMuSd);
  const tauKey = useWorkspaceStore((s) => s.metaUi.bayesTauKey);
  const setMetaUi = useWorkspaceStore((s) => s.setMetaUi);
  const [pooled, setPooled] = useState<MetaPooledResult | null>(null);
  const [forest, setForest] = useState<MetaForest | null>(null);
  const [loo, setLoo] = useState<MetaLeaveOneOutResult | null>(null);
  const [pubBias, setPubBias] = useState<MetaPublicationBiasResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bayes, setBayes] = useState<MetaBayesResult | null>(null);
  const [bayesLoading, setBayesLoading] = useState(false);
  const [bayesError, setBayesError] = useState<string | null>(null);

  const key = JSON.stringify(request);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const [p, f, l] = await Promise.all([
          api.metaAnalysisPooled({ ...request, model: poolModel }),
          api.metaAnalysisForest({ scheme: request.scheme }),
          api.metaAnalysisLeaveOneOut(request),
        ]);
        if (cancelled) return;
        setPooled(asObject<MetaPooledResult>(p));
        setForest(asObject<MetaForest>(f));
        setLoo(asObject<MetaLeaveOneOutResult>(l));
        setError(null);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, poolModel]);

  // Publication-bias suite is fetched separately so a backend that has not
  // shipped the richer endpoint degrades to an empty state instead of
  // blanking the whole pooled view.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const pb = await api.metaAnalysisPublicationBias(request);
        if (!cancelled) setPubBias(asObject<MetaPublicationBiasResult>(pb));
      } catch {
        if (!cancelled) setPubBias(null);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // Bayes fit: only fetched once the user switches to the Bayesian model.
  useEffect(() => {
    if (analysisModel !== "bayes") return;
    let cancelled = false;
    setBayesLoading(true);
    setBayesError(null);
    const tau = TAU_PRIORS.find((p) => p.value === tauKey) ?? TAU_PRIORS[1];
    void (async () => {
      try {
        const body: MetaBayesRequest = {
          ...request,
          mu_sd: muSd,
          tau_prior: tau.prior,
          tau_scale: tau.scale,
        };
        const b = await api.metaAnalysisBayes(body);
        if (!cancelled) setBayes(asObject<MetaBayesResult>(b));
      } catch (err) {
        if (!cancelled) setBayesError(errorMessage(err));
      } finally {
        if (!cancelled) setBayesLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, analysisModel, muSd, tauKey]);

  const downloadForestPng = async () => {
    try {
      const blob = await api.metaAnalysisForestPng({ scheme: request.scheme });
      dlBlob(blob, "meta_forest.png");
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  if (loading && !pooled) return <LoadingState />;
  if (error) return <ErrorBanner>{error}</ErrorBanner>;
  if (!pooled) return <EmptyState icon={<Sigma size={24} aria-hidden />}>{t("meta.analysisEmpty")}</EmptyState>;

  const studies = Number((pooled as Record<string, unknown>).n_studies ?? (pooled as Record<string, unknown>).studies ?? pooled.k);
  const sensitivity = bayes ? asArray<MetaBayesSensitivityRow>(bayes.sensitivity) : [];
  const egger = pubBias ? asObject<MetaPublicationBiasEgger>(pubBias.egger) : null;
  const petPeese = pubBias ? asObject<MetaPetPeese>(pubBias.pet_peese) : null;
  const trimFill = pubBias ? asObject<MetaTrimAndFill>(pubBias.trim_and_fill) : null;
  const pcurve = pubBias ? asObject<MetaPCurve>(pubBias.p_curve) : null;
  const figureOpts = {
    scheme: request.scheme,
  };
  const figureKey = `${request.scheme ?? ""}`;
  const consensus = asObject<{
    n_consensus_units?: number;
    n_master_resolved?: number;
    n_dropped_conflicts?: number;
    n_dropped_metrics?: number;
  }>((pooled as Record<string, unknown>).consensus);
  return (
    <div className="space-y-5">
      {consensus ? (
        <p className="text-[11px] text-text-secondary">
          {t("meta.consensusNote", {
            units: consensus.n_consensus_units ?? 0,
            resolved: consensus.n_master_resolved ?? 0,
            dropped: consensus.n_dropped_conflicts ?? 0,
            metrics: consensus.n_dropped_metrics ?? 0,
          })}
        </p>
      ) : null}
      {analysisModel === "frequentist" ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-4">
          <Kpi label={t("meta.kpiContrasts")} value={String(pooled.k)} sub={t("meta.kpiStudies", { count: studies })} />
          <Kpi
            label={t("meta.kpiPooled")}
            value={fmt(pooled.estimate)}
            sub={`95% CI [${fmt(pooled.ci_low)}, ${fmt(pooled.ci_high)}]`}
          />
          <Kpi
            label={t("meta.kpiI2")}
            value={`${fmt(pooled.i2, 1)}%`}
            sub={`Q = ${fmt(pooled.q, 2)} · df ${pooled.q_df} · p ${fmtP(pooled.q_p)}`}
          />
          <Kpi label={t("meta.kpiTau2")} value={fmt(pooled.tau2, 4)} sub={`p ${fmtP(pooled.p)}`} />
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-2">
            <label className="block">
              <span className="mb-1 block text-[11px] text-text-secondary">{t("meta.bayesMuPrior")}</span>
              <Select
                value={String(muSd)}
                onChange={(e) => setMetaUi({ bayesMuSd: Number(e.target.value) })}
                className="h-7 w-32 text-xs"
                aria-label={t("meta.bayesMuPrior")}
              >
                {MU_PRIORS.map((sd) => (
                  <option key={sd} value={sd}>
                    {`N(0, ${sd}²)`}
                  </option>
                ))}
              </Select>
            </label>
            <label className="block">
              <span className="mb-1 block text-[11px] text-text-secondary">{t("meta.bayesTauPrior")}</span>
              <Select
                value={tauKey}
                onChange={(e) => setMetaUi({ bayesTauKey: e.target.value })}
                className="h-7 w-40 text-xs"
                aria-label={t("meta.bayesTauPrior")}
              >
                {TAU_PRIORS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {t(p.labelKey, { scale: p.scale })}
                  </option>
                ))}
              </Select>
            </label>
          </div>

          {bayesError ? <ErrorBanner>{bayesError}</ErrorBanner> : null}
          {bayesLoading ? (
            <LoadingState />
          ) : bayes ? (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Kpi
                  label={t("meta.bayesPosterior")}
                  value={fmt(bayes.mu?.mean)}
                  sub={`95% CrI [${fmt(bayes.mu?.ci_low)}, ${fmt(bayes.mu?.ci_high)}]`}
                />
                <Kpi label={t("meta.bayesPGt0")} value={fmt(bayes.mu?.p_gt0)} />
                <Kpi label={t("meta.bayesPTwoSided")} value={fmtP(bayes.mu?.p_two_sided)} />
                <Kpi
                  label={t("meta.bayesBF10")}
                  value={fmt(bayes.bf10)}
                  sub={`${t("meta.bayesBF01Tau0")} ${fmt(bayes.bf01_tau0)}`}
                />
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Kpi
                  label={t("meta.bayesTau")}
                  value={fmt(bayes.tau?.mean)}
                  sub={`95% CrI [${fmt(bayes.tau?.ci_low)}, ${fmt(bayes.tau?.ci_high)}]`}
                />
                <Kpi label={t("meta.bayesMedian")} value={fmt(bayes.mu?.median)} sub={t("meta.bayesPosterior")} />
                <Kpi label={t("meta.kpiContrasts")} value={String(bayes.k)} sub={t("meta.kpiStudies", { count: bayes.k_total })} />
              </div>

              <Section title={t("meta.bayesSensitivity")}>
                {sensitivity.length > 0 ? (
                  <div className={cardCls}>
                    <table className="w-full border-collapse">
                      <thead className="sticky top-0 z-10 bg-surface">
                        <tr>
                          <th className={thCls}>{t("meta.bayesMuPrior")}</th>
                          <th className={thCls}>{t("meta.bayesTauPrior")}</th>
                          <th className={`${thCls} text-right`}>{t("meta.colEffect")}</th>
                          <th className={`${thCls} text-right`}>{t("meta.colCi")}</th>
                          <th className={`${thCls} text-right`}>{t("meta.bayesBF10")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sensitivity.map((row, i) => (
                          <tr key={`${row.mu_sd}-${row.tau_prior}-${row.tau_scale}-${i}`}>
                            <td className={TD}>{`N(0, ${row.mu_sd}²)`}</td>
                            <td className={TD}>
                              {row.tau_prior === "half-cauchy"
                                ? t("meta.tauHalfCauchy", { scale: row.tau_scale })
                                : t("meta.tauHalfNormal", { scale: row.tau_scale })}
                            </td>
                            <td className={NUM}>{fmt(row.mean)}</td>
                            <td className={NUM}>
                              [{fmt(row.ci_low)}, {fmt(row.ci_high)}]
                            </td>
                            <td className={NUM}>{fmt(row.bf10)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-xs text-text-secondary">{t("meta.analysisEmpty")}</p>
                )}
              </Section>
            </div>
          ) : (
            <p className="text-xs text-text-secondary">{t("meta.analysisEmpty")}</p>
          )}
        </div>
      )}

      <Section title={t("meta.figuresTitle")}>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <PngFigure
            label={t("meta.funnelTitle")}
            downloadLabel={t("meta.downloadFunnelPng")}
            filename="meta_funnel.png"
            load={() => api.metaAnalysisFunnelPng(figureOpts)}
            queryKey={figureKey}
            t={t}
          />
          <PngFigure
            label={t("meta.bayesPosteriorTitle")}
            downloadLabel={t("meta.downloadBayesPng")}
            filename="meta_bayes.png"
            load={() => api.metaAnalysisBayesPng(figureOpts)}
            queryKey={figureKey}
            t={t}
          />
        </div>
      </Section>

      {pooled.tau2_within !== undefined && pooled.tau2_within !== null ? (
        <Section title={t("meta.varianceDecomposition")}>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Kpi
              label={t("meta.varianceWithin")}
              value={fmt(pooled.tau2_within, 4)}
              sub={
                pooled.var_within_share !== null && pooled.var_within_share !== undefined
                  ? `${fmt(pooled.var_within_share * 100, 1)}%`
                  : undefined
              }
            />
            <Kpi
              label={t("meta.varianceBetween")}
              value={fmt(pooled.tau2_between, 4)}
              sub={
                pooled.var_between_share !== null && pooled.var_between_share !== undefined
                  ? `${fmt(pooled.var_between_share * 100, 1)}%`
                  : undefined
              }
            />
            {pooled.var_sampling_share !== null && pooled.var_sampling_share !== undefined ? (
              <Kpi
                label={t("meta.varianceSampling")}
                value={`${fmt(pooled.var_sampling_share * 100, 1)}%`}
              />
            ) : null}
          </div>
        </Section>
      ) : null}

      <Section title={t("meta.forestTitle")}>
        <div className="flex flex-wrap items-center justify-end">
          <Button
            variant="secondary"
            icon={<Download size={13} aria-hidden />}
            onClick={() => void downloadForestPng()}
          >
            {t("meta.downloadForestPng")}
          </Button>
        </div>
        {forest && (forest.rows?.length ?? 0) > 0 ? (
          <div className="space-y-3">
            <ForestPlot forest={forest} label={t("meta.forestTitle")} />
            <div className={cardCls}>
              <table className="w-full border-collapse">
                <thead className="sticky top-0 z-10 bg-surface">
                  <tr>
                    <th className={thCls}>{t("meta.colStudy")}</th>
                    <th className={`${thCls} text-right`}>{t("meta.colEffect")}</th>
                    <th className={`${thCls} text-right`}>{t("meta.colCi")}</th>
                    <th className={`${thCls} text-right`}>{t("meta.colWeight")}</th>
                  </tr>
                </thead>
                <tbody>
                  {forest.rows.map((row, i) => (
                    <tr key={`${row.study_id}-${i}`}>
                      <td className={TD}>{row.study_id}</td>
                      <td className={NUM}>{fmt(row.effect)}</td>
                      <td className={NUM}>
                        [{fmt(row.ci_low)}, {fmt(row.ci_high)}]
                      </td>
                      <td className={NUM}>{fmt(row.weight, 1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <p className="text-xs text-text-secondary">{t("meta.analysisEmpty")}</p>
        )}
      </Section>

      <Section title={t("meta.leaveOneOut")}>
        {loo && asArray(loo.rows).length > 0 ? (
          <div className={cardCls}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10 bg-surface">
                <tr>
                  <th className={thCls}>{t("meta.colStudy")}</th>
                  <th className={`${thCls} text-right`}>{t("meta.colEffect")}</th>
                  <th className={`${thCls} text-right`}>{t("meta.colCi")}</th>
                  <th className={`${thCls} text-right`}>{t("meta.kpiTau2")}</th>
                  <th className={`${thCls} text-right`}>{t("meta.kpiI2")}</th>
                </tr>
              </thead>
              <tbody>
                {loo.rows.map((row, i) => (
                  <tr key={`${row.study_id}-${i}`}>
                    <td className={TD}>{row.study_id}</td>
                    <td className={NUM}>{fmt(row.estimate)}</td>
                    <td className={NUM}>
                      [{fmt(row.ci_low)}, {fmt(row.ci_high)}]
                    </td>
                    <td className={NUM}>{fmt(row.tau2, 4)}</td>
                    <td className={NUM}>{fmt(row.i2, 1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs text-text-secondary">{t("meta.analysisEmpty")}</p>
        )}
      </Section>

      <Section title={t("meta.publicationBiasTitle")}>
        <p className="text-xs text-text-secondary">{t("meta.publicationBiasHint")}</p>
        {pubBias ? (
          <div className="space-y-4">
            {egger ? (
              <div className="space-y-2">
                <div className="text-[11px] font-medium text-text-secondary">{t("meta.eggerTitle")}</div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Kpi label={t("meta.eggerIntercept")} value={fmt(egger.intercept)} sub={`SE ${fmt(egger.se)}`} />
                  <Kpi label={t("meta.eggerT")} value={fmt(egger.t)} sub={`p ${fmtP(egger.p)}`} />
                  <Kpi label={t("meta.eggerSlope")} value={fmt(egger.slope)} sub={`SE ${fmt(egger.slope_se)}`} />
                  <Kpi label={t("meta.eggerSlopeP")} value={fmtP(egger.slope_p)} />
                </div>
              </div>
            ) : null}

            {petPeese ? (
              <div className="space-y-2">
                <div className="text-[11px] font-medium text-text-secondary">{t("meta.petPeeseTitle")}</div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <Kpi
                    label={t("meta.petLabel")}
                    value={fmt(petPeese.pet?.intercept)}
                    sub={`SE ${fmt(petPeese.pet?.se)} · p ${fmtP(petPeese.pet?.p)}`}
                  />
                  <Kpi
                    label={t("meta.peeseLabel")}
                    value={fmt(petPeese.peese?.intercept)}
                    sub={`SE ${fmt(petPeese.peese?.se)} · p ${fmtP(petPeese.peese?.p)}`}
                  />
                </div>
                <p className="text-[11px] text-text-secondary">
                  {t("meta.petPeeseRecommended", { arm: petPeese.recommended })}
                </p>
              </div>
            ) : null}

            {trimFill ? (
              <div className="space-y-2">
                <div className="text-[11px] font-medium text-text-secondary">{t("meta.trimFillTitle")}</div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Kpi label={t("meta.trimFillK0")} value={String(trimFill.k0)} sub={trimFill.side} />
                  <Kpi
                    label={t("meta.trimFillAdjusted")}
                    value={fmt(trimFill.estimate)}
                    sub={`95% CI [${fmt(trimFill.ci_low)}, ${fmt(trimFill.ci_high)}]`}
                  />
                </div>
              </div>
            ) : null}

            {pcurve ? (
              <div className="space-y-2">
                <div className="text-[11px] font-medium text-text-secondary">{t("meta.pcurveTitle")}</div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Kpi label={t("meta.pcurveSignificant")} value={String(pcurve.n_significant)} />
                  <Kpi label={t("meta.pcurveP025")} value={String(pcurve.n_p_lt_025)} />
                  <Kpi label={t("meta.pcurveHalf")} value={fmt(pcurve.p_half)} />
                  <Kpi
                    label={t("meta.pcurveEvidential")}
                    value={pcurve.evidential ? t("meta.yes") : t("meta.no")}
                  />
                </div>
                {pcurve.note ? <p className="text-[11px] text-text-secondary">{pcurve.note}</p> : null}
              </div>
            ) : null}
          </div>
        ) : (
          <p className="text-xs text-text-secondary">{t("meta.analysisEmpty")}</p>
        )}
      </Section>
    </div>
  );
}

function SubgroupView({
  request,
  t,
}: {
  request: MetaAnalysisRequest;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const subgroupBy = useWorkspaceStore((s) => s.metaUi.subgroupBy);
  const terms = useWorkspaceStore((s) => s.metaUi.moderatorTerms);
  const interactions = useWorkspaceStore((s) => s.metaUi.moderatorInteractions);
  const setMetaUi = useWorkspaceStore((s) => s.setMetaUi);
  const [subgroup, setSubgroup] = useState<MetaSubgroupResult | null>(null);
  const [moderator, setModerator] = useState<MetaModeratorResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [moderators, setModerators] = useState<MetaModerator[]>([]);
  const [interactionA, setInteractionA] = useState("");
  const [interactionB, setInteractionB] = useState("");
  const [refitNonce, setRefitNonce] = useState(0);

  // The catalogue powering the "add moderator" picker.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const list = await api.metaModerators();
        if (!cancelled) setModerators(Array.isArray(list) ? list : []);
      } catch {
        if (!cancelled) setModerators([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Group the catalogue by its codebook group (study/metric fallback).
  const moderatorGroups = useMemo(() => {
    const groups: [string, MetaModerator[]][] = [];
    for (const entry of moderators) {
      const group =
        entry.group || (entry.kind === "metric" ? t("meta.unitMetric") : t("meta.unitStudy"));
      const bucket = groups.find(([name]) => name === group);
      if (bucket) bucket[1].push(entry);
      else groups.push([group, [entry]]);
    }
    return groups;
  }, [moderators, t]);

  const termLabel = (name: string) =>
    moderators.find((m) => m.name === name)?.label || name;

  const toggleTerm = (name: string) => {
    const next = terms.includes(name) ? terms.filter((term) => term !== name) : [...terms, name];
    setMetaUi({
      moderatorTerms: next,
      moderatorInteractions: interactions.filter(
        ([a, b]) => next.includes(a) && next.includes(b),
      ),
      subgroupBy: next[0] ?? "",
    });
  };

  const removeTerm = (name: string) => {
    const next = terms.filter((term) => term !== name);
    setMetaUi({
      moderatorTerms: next,
      moderatorInteractions: interactions.filter(
        ([a, b]) => next.includes(a) && next.includes(b),
      ),
      subgroupBy: next[0] ?? "",
    });
  };

  const addInteraction = () => {
    if (!interactionA || !interactionB || interactionA === interactionB) return;
    const exists = interactions.some(
      ([a, b]) =>
        (a === interactionA && b === interactionB) ||
        (a === interactionB && b === interactionA),
    );
    if (!exists) setMetaUi({ moderatorInteractions: [...interactions, [interactionA, interactionB]] });
    setInteractionA("");
    setInteractionB("");
  };

  const removeInteraction = (index: number) => {
    setMetaUi({ moderatorInteractions: interactions.filter((_, i) => i !== index) });
  };

  // The builder lives in the workspace store, so the subgroup table (primary
  // term) and the moderator regression (all terms + interactions) refit
  // automatically whenever the selection changes.
  const primary = terms[0] || subgroupBy;
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const [sub, mod] = await Promise.all([
          primary
            ? api.metaAnalysisSubgroup({ ...request, key: primary, field: primary })
            : Promise.resolve(null),
          api.metaAnalysisModerator({
            ...request,
            field: terms[0],
            role: terms[0] ?? "",
            terms,
            interactions,
          }),
        ]);
        if (cancelled) return;
        setSubgroup(asObject<MetaSubgroupResult>(sub));
        setModerator(asObject<MetaModeratorResult>(mod));
        setError(null);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [request, primary, terms, interactions, refitNonce]);

  return (
    <div className="space-y-4">
      {error ? <ErrorBanner>{error}</ErrorBanner> : null}
      {loading ? <LoadingState /> : null}

      {/* Moderator builder: terms + interaction pairs drive the regression. */}
      <div className="space-y-2 rounded-sm border border-border bg-surface p-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-medium uppercase tracking-wide text-text-secondary">
            {t("meta.moderatorTerms")}
          </span>
          {terms.length === 0 ? (
            <span className="text-[11px] text-text-secondary">{t("meta.analysisEmpty")}</span>
          ) : (
            terms.map((term) => (
              <span
                key={term}
                className="flex items-center gap-1 rounded-sm bg-surface-higher px-1.5 py-0.5 text-xs text-text-primary"
              >
                {termLabel(term)}
                <button
                  type="button"
                  aria-label={t("meta.moderatorRemoveTerm")}
                  title={t("meta.moderatorRemoveTerm")}
                  className="text-text-secondary hover:text-danger"
                  onClick={() => removeTerm(term)}
                >
                  <X size={10} aria-hidden />
                </button>
              </span>
            ))
          )}
          <span className="flex-1" />
        </div>

        {/* Moderator catalogue as checkable collapsible groups: checking a
            variable adds it to the regression terms (primary term first). */}
        <div className="space-y-1">
          {moderatorGroups.map(([group, entries]) => (
            <details key={group} className="rounded-sm border border-border">
              <summary className="cursor-pointer px-2 py-1 text-xs font-medium text-text-primary">
                {group} ({entries.filter((entry) => terms.includes(entry.name)).length}/
                {entries.length})
              </summary>
              <div className="space-y-1 px-2 pb-2">
                {entries.map((entry) => (
                  <label
                    key={entry.name}
                    className="flex cursor-pointer items-center gap-1.5 text-xs text-text-primary"
                  >
                    <input
                      type="checkbox"
                      checked={terms.includes(entry.name)}
                      onChange={() => toggleTerm(entry.name)}
                      className="h-3.5 w-3.5 accent-[var(--qc-accent)]"
                      aria-label={entry.label || entry.name}
                    />
                    <span className="min-w-0 flex-1 truncate">{entry.label || entry.name}</span>
                  </label>
                ))}
              </div>
            </details>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-medium uppercase tracking-wide text-text-secondary">
            {t("meta.moderatorInteraction")}
          </span>
          {interactions.map(([a, b], i) => (
            <span
              key={`${a}*${b}-${i}`}
              className="flex items-center gap-1 rounded-sm bg-surface-higher px-1.5 py-0.5 text-xs text-text-primary"
            >
              {a} * {b}
              <button
                type="button"
                aria-label={t("meta.moderatorRemoveTerm")}
                title={t("meta.moderatorRemoveTerm")}
                className="text-text-secondary hover:text-danger"
                onClick={() => removeInteraction(i)}
              >
                <X size={10} aria-hidden />
              </button>
            </span>
          ))}
          <Select
            value={interactionA}
            onChange={(e) => setInteractionA(e.target.value)}
            className="h-7 w-36 text-xs"
            aria-label={`${t("meta.moderatorInteraction")} 1`}
          >
            <option value="">—</option>
            {terms.map((term) => (
              <option key={term} value={term}>
                {termLabel(term)}
              </option>
            ))}
          </Select>
          <Select
            value={interactionB}
            onChange={(e) => setInteractionB(e.target.value)}
            className="h-7 w-36 text-xs"
            aria-label={`${t("meta.moderatorInteraction")} 2`}
          >
            <option value="">—</option>
            {terms.map((term) => (
              <option key={term} value={term}>
                {termLabel(term)}
              </option>
            ))}
          </Select>
          <Button
            variant="secondary"
            icon={<Plus size={12} aria-hidden />}
            disabled={!interactionA || !interactionB || interactionA === interactionB}
            onClick={addInteraction}
          >
            {t("meta.moderatorAddInteraction")}
          </Button>
          <Button variant="secondary" onClick={() => setRefitNonce((n) => n + 1)}>
            {t("meta.moderatorRefit")}
          </Button>
        </div>
      </div>

      {!loading && subgroup && asArray(subgroup.groups).length > 0 ? (
        <div className={cardCls}>
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10 bg-surface">
              <tr>
                <th className={thCls}>{t("meta.colLevel")}</th>
                <th className={`${thCls} text-right`}>{t("meta.kpiContrasts")}</th>
                <th className={`${thCls} text-right`}>{t("meta.colEffect")}</th>
                <th className={`${thCls} text-right`}>{t("meta.colCi")}</th>
                <th className={`${thCls} text-right`}>{t("meta.kpiTau2")}</th>
              </tr>
            </thead>
            <tbody>
              {subgroup.groups.map((group, i) => (
                <tr key={`${group.key}-${i}`}>
                  <td className={TD}>{group.label ?? group.value ?? group.key}</td>
                  <td className={NUM}>{group.k}</td>
                  <td className={NUM}>{fmt(group.estimate)}</td>
                  <td className={NUM}>
                    [{fmt(group.ci_low)}, {fmt(group.ci_high)}]
                  </td>
                  <td className={NUM}>{fmt(group.tau2, 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <Section title={t("meta.moderatorFit")}>
        {moderator ? (
          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Kpi
                label={t("meta.moderatorRole")}
                value={terms.length > 0 ? terms.join(" + ") : moderator.role || subgroupBy || "–"}
              />
              <Kpi label={t("meta.kpiContrasts")} value={String(moderator.k ?? "–")} />
              {subgroup?.qm !== undefined && subgroup.qm !== null ? (
                <Kpi
                  label={t("meta.moderatorQBetween")}
                  value={fmt(subgroup.qm, 2)}
                  sub={`df ${subgroup.qm_df ?? "–"} · p ${fmtP(subgroup.qm_p)}`}
                />
              ) : null}
              {moderator.r2 !== undefined && moderator.r2 !== null ? (
                <Kpi label={t("meta.moderatorR2")} value={`${fmt(Number(moderator.r2) * 100, 1)}%`} />
              ) : null}
            </div>
            {(moderator.coefficients?.length ?? 0) > 0 ? (
              <div className={cardCls}>
                <table className="w-full border-collapse">
                  <thead className="sticky top-0 z-10 bg-surface">
                    <tr>
                      <th className={thCls}>{t("meta.colTerm")}</th>
                      <th className={`${thCls} text-right`}>{t("meta.colEffect")}</th>
                      <th className={`${thCls} text-right`}>{t("meta.colSe")}</th>
                      <th className={`${thCls} text-right`}>z</th>
                      <th className={`${thCls} text-right`}>{t("meta.colCi")}</th>
                      <th className={`${thCls} text-right`}>p</th>
                    </tr>
                  </thead>
                  <tbody>
                    {moderator.coefficients?.map((term, i) => (
                      <tr key={`${term.term}-${i}`}>
                        <td className={TD}>{term.term}</td>
                        <td className={NUM}>{fmt(term.estimate)}</td>
                        <td className={NUM}>{fmt(term.se)}</td>
                        <td className={NUM}>{fmt(term.z)}</td>
                        <td className={NUM}>
                          [{fmt(term.ci_low)}, {fmt(term.ci_high)}]
                        </td>
                        <td className={NUM}>{fmtP(term.p)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-xs text-text-secondary">{t("meta.analysisEmpty")}</p>
            )}
            {moderator.note ? (
              <p className="text-[11px] text-warning">{moderator.note}</p>
            ) : null}
          </div>
        ) : (
          <p className="text-xs text-text-secondary">{t("meta.analysisEmpty")}</p>
        )}
      </Section>
    </div>
  );
}

function MultiverseView({
  request,
  t,
}: {
  request: MetaAnalysisRequest;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const [result, setResult] = useState<MetaMultiverseResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify(request);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const data = await api.metaAnalysisMultiverse(request);
        if (cancelled) return;
        setResult(asObject<MetaMultiverseResult>(data));
        setError(null);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const figureOpts = {
    scheme: request.scheme,
  };
  const figureKey = `${request.scheme ?? ""}`;

  if (loading && !result) return <LoadingState />;
  if (error && !result) return <ErrorBanner>{error}</ErrorBanner>;
  if (!result) return <EmptyState icon={<Sigma size={24} aria-hidden />}>{t("meta.analysisEmpty")}</EmptyState>;

  const specs = asArray<MetaMultiverseSpec>(result.specs);
  const summary = asObject<MetaMultiverseSummary>(result.summary);
  const nSpecs = Number(summary?.n_specs ?? result.n_specs ?? specs.length);
  return (
    <div className="space-y-5">
      <p className="text-xs text-text-secondary">{t("meta.multiverseHint")}</p>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Kpi
          label={t("meta.multiverseSpecs")}
          value={String(nSpecs)}
          sub={t("meta.multiverseFitted", { n: summary?.n_ok ?? specs.length })}
        />
        <Kpi
          label={t("meta.multiverseMedian")}
          value={fmt(summary?.median)}
          sub={`95% CI [${fmt(summary?.ci_low)}, ${fmt(summary?.ci_high)}]`}
        />
        <Kpi label={t("meta.multiverseRange")} value={`${fmt(summary?.min)} – ${fmt(summary?.max)}`} />
        <Kpi label={t("meta.multiversePctPositive")} value={`${fmt(summary?.pct_positive, 1)}%`} />
      </div>

      <Section title={t("meta.multiverseSpecTable")}>
        {specs.length > 0 ? (
          <div className={cardCls}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10 bg-surface">
                <tr>
                  <th className={thCls}>{t("meta.colChoices")}</th>
                  <th className={`${thCls} text-right`}>{t("meta.kpiContrasts")}</th>
                  <th className={`${thCls} text-right`}>{t("meta.colEffect")}</th>
                  <th className={`${thCls} text-right`}>{t("meta.colCi")}</th>
                  <th className={`${thCls} text-right`}>{t("meta.kpiI2")}</th>
                </tr>
              </thead>
              <tbody>
                {specs.map((spec, i) => (
                  <tr key={`${String(spec.id ?? i)}-${i}`}>
                    <td className={TD}>{formatChoices(spec.choices)}</td>
                    <td className={NUM}>{spec.k ?? "–"}</td>
                    <td className={NUM}>{fmt(spec.estimate)}</td>
                    <td className={NUM}>
                      [{fmt(spec.ci_low)}, {fmt(spec.ci_high)}]
                    </td>
                    <td className={NUM}>{fmt(spec.i2, 1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs text-text-secondary">{t("meta.analysisEmpty")}</p>
        )}
      </Section>

      <Section title={t("meta.specCurveTitle")}>
        <PngFigure
          label={t("meta.specCurveTitle")}
          downloadLabel={t("meta.downloadSpecCurvePng")}
          filename="meta_spec_curve.png"
          load={() => api.metaAnalysisSpecCurvePng(figureOpts)}
          queryKey={figureKey}
          t={t}
        />
      </Section>
    </div>
  );
}

function AuditView({
  request,
  t,
}: {
  request: MetaAnalysisRequest;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const [result, setResult] = useState<MetaAuditResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const scheme = (request.scheme as string) || "";

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const data = await api.metaAudit({ scheme: scheme || undefined });
        if (cancelled) return;
        setResult(asObject<MetaAuditResult>(data));
        setError(null);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [scheme]);

  if (loading) return <LoadingState />;
  if (error && !result) return <ErrorBanner>{error}</ErrorBanner>;
  if (!result || asArray(result.fields).length === 0) {
    return <EmptyState icon={<Sigma size={24} aria-hidden />}>{t("meta.analysisEmpty")}</EmptyState>;
  }
  const fields = asArray<MetaAuditField>(result.fields);
  const issues = asArray<MetaAuditIssue>(result.issues);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Kpi label={t("meta.auditExtractions")} value={String(result.n_extractions ?? "–")} />
        <Kpi label={t("meta.auditRecords")} value={String(result.n_records ?? "–")} />
        <Kpi label={t("meta.auditMetrics")} value={String(result.n_metrics ?? "–")} />
      </div>

      <Section title={t("meta.auditCoverage")}>
        <p className="text-xs text-text-secondary">{t("meta.auditHint")}</p>
        <div className={cardCls}>
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10 bg-surface">
              <tr>
                <th className={thCls}>{t("meta.colAuditField")}</th>
                <th className={thCls}>{t("meta.colKind")}</th>
                <th className={thCls}>{t("meta.colRole")}</th>
                <th className={`${thCls} text-right`}>{t("meta.colSetTotal")}</th>
                <th className={`${thCls} text-right`}>{t("meta.auditCoverage")}</th>
                <th className={`${thCls} text-right`}>{t("meta.colIssues")}</th>
              </tr>
            </thead>
            <tbody>
              {fields.map((field, i) => (
                <tr key={`${field.name}-${i}`}>
                  <td className={TD}>{field.label ?? field.name}</td>
                  <td className={TD}>
                    {field.kind ? t(`meta.auditKind_${field.kind}`) : "–"}
                  </td>
                  <td className={TD}>{field.role ? t(`meta.role_${field.role}`) : "–"}</td>
                  <td className={NUM}>{`${field.set ?? 0} / ${field.total ?? 0}`}</td>
                  <td className={NUM}>{`${fmt(Number(field.coverage ?? 0) * 100, 1)}%`}</td>
                  <td className={NUM} title={issueTitle(field.issues)}>
                    {issueCount(field.issues)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title={t("meta.auditIssues")}>
        {issues.length > 0 ? (
          <ul className="space-y-1">
            {issues.map((issue, i) => (
              <li
                key={`${issue.field}-${i}`}
                className="flex items-start gap-2 border-b border-border py-1.5 text-xs"
              >
                <span
                  className={`shrink-0 rounded-sm px-1.5 py-0.5 text-[10px] font-medium ${severityTone(issue.severity)}`}
                >
                  {t(severityLabelKey(issue.severity))}
                </span>
                <span className="min-w-0 flex-1 text-text-primary">
                  <span className="font-medium">{issue.field}</span>
                  {issue.message ? <span className="text-text-secondary"> — {issue.message}</span> : null}
                </span>
                {typeof issue.count === "number" ? (
                  <span className="shrink-0 tabular-nums text-text-secondary">×{issue.count}</span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-text-secondary">{t("meta.auditNoIssues")}</p>
        )}
      </Section>
    </div>
  );
}

function PrismaView({ t }: { t: (key: string) => string }) {
  const toast = useToast();
  const [counts, setCounts] = useState<MetaPrismaCounts | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pngUrl, setPngUrl] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await api.metaPrisma();
        if (cancelled) return;
        setCounts(asObject<MetaPrismaCounts>(data));
        setError(null);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // PRISMA flow-diagram PNG: an authenticated fetch (server mode needs the
  // bearer header, which a raw <img src> cannot send).
  useEffect(() => {
    let cancelled = false;
    let url: string | null = null;
    void (async () => {
      try {
        const blob = await api.metaPrismaPng();
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setPngUrl(url);
      } catch {
        /* the figure is optional */
      }
    })();
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, []);

  const downloadPng = async () => {
    try {
      const blob = await api.metaPrismaPng();
      dlBlob(blob, "prisma.png");
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  if (loading) return <LoadingState />;
  if (error && !counts) return <ErrorBanner>{error}</ErrorBanner>;
  if (!counts) return <EmptyState icon={<Sigma size={24} aria-hidden />}>{t("meta.analysisEmpty")}</EmptyState>;
  // Nested PRISMA 2020 shape, with the legacy flat fields as a fallback.
  const identification = asObject<MetaPrismaCounts["identification"]>(counts.identification);
  const screening = asObject<MetaPrismaCounts["screening"]>(counts.screening);
  const fulltext = asObject<MetaPrismaCounts["fulltext"]>(counts.fulltext);
  const inclusion = asObject<MetaPrismaCounts["inclusion"]>(counts.inclusion);
  const rows: [string, number | undefined][] = identification
    ? [
        [t("meta.prismaIdentified"), identification.total],
        [t("meta.prismaDatabase"), identification.database],
        [t("meta.prismaOther"), identification.other],
        [t("meta.prismaScreened"), screening?.screened],
        [t("meta.prismaExcludedScreening"), screening?.excluded],
        [t("meta.prismaSought"), fulltext?.sought],
        [t("meta.prismaRetrieved"), fulltext?.retrieved],
        [t("meta.prismaNotRetrieved"), fulltext?.not_retrieved],
        [t("meta.prismaFulltext"), fulltext?.assessed],
        [t("meta.prismaExcludedFulltext"), fulltext?.excluded],
        [t("meta.prismaIncluded"), inclusion?.included],
        [t("meta.prismaStudies"), inclusion?.studies],
        [t("meta.prismaReports"), inclusion?.reports],
      ]
    : [
        [t("meta.prismaIdentified"), counts.identified],
        [t("meta.prismaAfterDuplicates"), counts.after_duplicates],
        [t("meta.prismaIncluded"), counts.included],
        [t("meta.prismaExtracted"), counts.extracted],
      ];
  const reasons = asArray<{ reason: string; n: number; count?: number }>(
    counts.exclusion_reasons ?? screening?.reasons,
  );
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {rows.map(([label, value]) => (
          <Kpi key={label} label={label} value={String(value ?? "–")} />
        ))}
      </div>
      <Section title={t("meta.prismaReasons")}>
        {reasons.length > 0 ? (
          <ul className="space-y-1 text-xs text-text-primary">
            {reasons.map((r) => (
              <li key={r.reason} className="flex items-center justify-between gap-3 border-b border-border py-1">
                <span className="min-w-0 truncate">{r.reason}</span>
                <span className="tabular-nums text-text-secondary">{r.n ?? r.count}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-text-secondary">{t("meta.analysisEmpty")}</p>
        )}
      </Section>

      <Section title={t("meta.prismaFigure")}>
        <div className="flex flex-wrap items-center justify-end">
          <Button
            variant="secondary"
            icon={<Download size={13} aria-hidden />}
            onClick={() => void downloadPng()}
          >
            {t("meta.downloadPng")}
          </Button>
        </div>
        {pngUrl ? (
          <img
            src={pngUrl}
            alt={t("meta.prismaFigure")}
            className="max-h-96 w-auto max-w-full rounded-sm border border-border bg-surface"
          />
        ) : (
          <p className="text-xs text-text-secondary">{t("meta.figureEmpty")}</p>
        )}
      </Section>
    </div>
  );
}

function SummaryView({
  request,
  t,
}: {
  request: MetaAnalysisRequest;
  t: (key: string) => string;
}) {
  const [summary, setSummary] = useState<MetaSummaryResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const scheme = (request.scheme as string) || "";
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const data = await api.metaSummary({ scheme: scheme || undefined });
        if (cancelled) return;
        setSummary(asObject<MetaSummaryResult>(data));
        setError(null);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [scheme]);
  if (loading) return <LoadingState />;
  if (error && !summary) return <ErrorBanner>{error}</ErrorBanner>;
  if (!summary || asArray(summary.fields).length === 0) {
    return <EmptyState icon={<Sigma size={24} aria-hidden />}>{t("meta.analysisEmpty")}</EmptyState>;
  }
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Kpi label={t("meta.summaryExtractions")} value={String(summary.n_extractions ?? "–")} />
        <Kpi label={t("meta.summaryRecords")} value={String(summary.n_records ?? "–")} />
        <Kpi
          label={t("meta.summaryStudies")}
          value={String(summary.n_studies ?? summary.studies ?? "–")}
        />
      </div>
      {summary.fields.map((field) => (
        <Section key={field.name} title={field.label ?? field.name}>
          <div className={cardCls}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10 bg-surface">
                <tr>
                  <th className={thCls}>{t("meta.colLevel")}</th>
                  <th className={`${thCls} text-right`}>{t("meta.colCount")}</th>
                  <th className={`${thCls} text-right`}>{t("meta.colStudies")}</th>
                </tr>
              </thead>
              <tbody>
                {asArray<{
                  value: string;
                  n?: number;
                  n_studies?: number;
                  count?: number;
                  studies?: number;
                }>(field.levels).map((level) => (
                  <tr key={level.value}>
                    <td className={TD}>{level.value}</td>
                    <td className={NUM}>{level.n ?? level.count ?? "–"}</td>
                    <td className={NUM}>{level.n_studies ?? level.studies ?? "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      ))}
    </div>
  );
}

function ReportView({
  request,
  t,
}: {
  request: MetaAnalysisRequest;
  t: (key: string) => string;
}) {
  const toast = useToast();
  const [preview, setPreview] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const exportReport = async (format: "md" | "docx" | "pptx") => {
    setBusy(true);
    try {
      const blob = await api.metaReport({ scheme: request.scheme, format });
      const ext = format === "docx" ? "docx" : format === "pptx" ? "pptx" : "md";
      dlBlob(blob, `meta_report.${ext}`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const loadPreview = async () => {
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const blob = await localRequestBlob("/meta/report", {
        method: "POST",
        body: JSON.stringify({ scheme: request.scheme, format: "md" }),
      });
      setPreview(await blob.text());
    } catch (err) {
      setPreviewError(errorMessage(err));
    } finally {
      setPreviewLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          icon={<Download size={13} aria-hidden />}
          disabled={busy}
          onClick={() => void exportReport("md")}
        >
          {t("meta.exportMarkdown")}
        </Button>
        <Button
          variant="secondary"
          icon={<Download size={13} aria-hidden />}
          disabled={busy}
          onClick={() => void exportReport("docx")}
        >
          {t("meta.exportDocx")}
        </Button>
        <Button
          variant="secondary"
          icon={<Download size={13} aria-hidden />}
          disabled={busy}
          onClick={() => void exportReport("pptx")}
        >
          {t("meta.exportPptx")}
        </Button>
        <Button
          variant="secondary"
          icon={<FileText size={13} aria-hidden />}
          disabled={busy || previewLoading}
          onClick={() => void loadPreview()}
        >
          {t("meta.reportPreview")}
        </Button>
      </div>
      {previewLoading ? (
        <LoadingState />
      ) : previewError ? (
        <ErrorBanner>{previewError}</ErrorBanner>
      ) : preview !== null ? (
        <div className="max-h-96 overflow-auto rounded-sm border border-border bg-surface p-3">
          <Markdown text={preview} />
        </div>
      ) : (
        <p className="text-xs text-text-secondary">{t("meta.reportHint")}</p>
      )}
    </div>
  );
}

export function MetaAnalyze() {
  const { t } = useI18n();
  const section = useWorkspaceStore((s) => s.metaUi.analysisSection);

  // NOTE: the Analyze request intentionally carries neither `scheme` (the
  // backend pools every scheme) nor `owner`: analysis always combines every
  // coder's rows into consensus rows (unresolved conflicts excluded +
  // counted), so there is no coder picker on this tab.
  const request = useMemo<MetaAnalysisRequest>(() => ({}), []);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="qc-scroll min-h-0 flex-1 overflow-auto p-4">
        {section === "pooled" ? <PooledView request={request} t={t} /> : null}
        {section === "subgroup" ? <SubgroupView request={request} t={t} /> : null}
        {section === "multiverse" ? <MultiverseView request={request} t={t} /> : null}
        {section === "prisma" ? <PrismaView t={t} /> : null}
        {section === "audit" ? <AuditView request={request} t={t} /> : null}
        {section === "summary" ? <SummaryView request={request} t={t} /> : null}
        {section === "report" ? <ReportView request={request} t={t} /> : null}
      </div>
    </div>
  );
}
