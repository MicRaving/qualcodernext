/**
 * Meta conflicts panel (contract §7/§11) — the center of the Agreement tab:
 * Gwet AC1/AC2 reliability table for screening or extraction, a conflicts list
 * with per-rater value chips and a settle control, plus the "LLM excluded but
 * a rater would include" list for screening when the agreement response
 * carries it.
 *
 * The scope (screening / extraction), the screening stage and the per-study
 * filter live in the workspace store; the conflicts left bar drives them. This
 * component is a first-class tab body, not a modal.
 *
 * Conflicts arrive as an envelope (`{total,rows,fields,studies,master,…}`);
 * each row is a disagreement cell addressed by `criterion_key` (screening) or
 * `field_name` + record/metric coordinates (extraction).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Handshake } from "lucide-react";
import { api } from "@/lib/api";
import type {
  MetaAgreementField,
  MetaAgreementResult,
  MetaConflictRow,
  MetaConflictsResult,
  MetaLlmExcludedRow,
} from "@/lib/api/types";
import { Button, EmptyState, ErrorBanner, LoadingState, TableHead } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { errorMessage } from "@/lib/utils";
import { useCoderStore } from "@/stores/coder";
import { useWorkspaceStore } from "@/stores/workspace";

const TD = "border-b border-border px-3 py-1.5 text-sm align-top";
const NUM = `${TD} text-right tabular-nums`;

function asObject<T>(value: unknown): T | null {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as T;
  return null;
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function acClass(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "text-text-secondary";
  const n = Number(value);
  if (n >= 0.8) return "text-success";
  if (n >= 0.6) return "text-warning";
  return "text-danger";
}

function fmt(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "–";
  return Number(value).toFixed(3);
}

/** Rater chips for a conflict row's `values` map. */
function conflictChips(row: MetaConflictRow): { owner: string; value: unknown }[] {
  const raw = row.values;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
  return Object.entries(raw as Record<string, unknown>).map(([owner, value]) => ({ owner, value }));
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "–";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function MetaAgreementPanel() {
  const { t } = useI18n();
  const toast = useToast();
  const coderScope = useWorkspaceStore((s) => s.metaUi.coderScope);
  const coderName = useCoderStore((s) => s.coderName);
  /** Effective owner: the scoped coder, or the current coder for "All". */
  const writeOwner = coderScope || coderName;
  const schemeName = useWorkspaceStore((s) => s.metaUi.scheme);
  const screeningStage = useWorkspaceStore((s) => s.metaUi.screeningStage);
  const scope = useWorkspaceStore((s) => s.metaUi.agreementScope);
  const study = useWorkspaceStore((s) => s.metaUi.agreementStudy);

  const [agreement, setAgreement] = useState<MetaAgreementResult | null>(null);
  const [conflicts, setConflicts] = useState<MetaConflictsResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyKeys, setBusyKeys] = useState<string[]>([]);

  const load = useCallback(
    async (isCancelled?: () => boolean) => {
      setLoading(true);
      try {
        const studyFilter = study || undefined;
        const [rel, conf] = await Promise.all(
          scope === "screening"
            ? [
                api.metaScreeningAgreement({
                  owner: writeOwner || undefined,
                  stage: screeningStage,
                }),
                api.metaScreeningConflicts({
                  stage: screeningStage,
                  study: studyFilter,
                  status: "all",
                }),
              ]
            : [
                api.metaExtractionAgreement({
                  scheme: schemeName || undefined,
                  owner: writeOwner || undefined,
                }),
                api.metaExtractionConflicts({
                  scheme: schemeName || undefined,
                  study: studyFilter,
                  status: "all",
                }),
              ],
        );
        if (isCancelled?.()) return;
        setAgreement(asObject<MetaAgreementResult>(rel));
        setConflicts(asObject<MetaConflictsResult>(conf));
        setError(null);
      } catch (err) {
        if (isCancelled?.()) return;
        setError(errorMessage(err));
        setAgreement(null);
        setConflicts(null);
      } finally {
        if (!isCancelled?.()) setLoading(false);
      }
    },
    [writeOwner, schemeName, screeningStage, scope, study],
  );

  // Reload on scope / coder / stage / study changes; a cancelled flag drops an
  // out-of-order response so a scope switch can never render the wrong scope.
  useEffect(() => {
    let cancelled = false;
    void load(() => cancelled);
    return () => {
      cancelled = true;
    };
  }, [load]);

  const resolve = async (row: MetaConflictRow, value: unknown) => {
    setBusyKeys((prev) => [...prev, row.key]);
    try {
      if (scope === "screening") {
        await api.metaResolveScreeningConflict({
          hit_id: row.hit_id,
          criterion_key: row.criterion_key ?? row.field,
          value,
          master: writeOwner || undefined,
          stage: screeningStage,
        });
      } else {
        await api.metaResolveExtractionConflict({
          hit_id: row.hit_id,
          field_name: row.field_name ?? row.field,
          value,
          master: writeOwner || undefined,
          record_index: row.record_index,
          metric_key: row.metric_key,
          metric_index: row.metric_index,
          scheme: schemeName || undefined,
        });
      }
      toast.success(t("meta.conflictResolved"));
      await load();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusyKeys((prev) => prev.filter((k) => k !== row.key));
    }
  };

  const fields = useMemo<MetaAgreementField[]>(() => {
    if (!agreement) return [];
    if (Array.isArray(agreement.fields) && agreement.fields.length > 0) return agreement.fields;
    // Overall-only response: render a single synthetic row.
    return [
      {
        name: "overall",
        label: t("meta.agreementOverall"),
        unit: agreement.unit,
        n_items: agreement.overall?.n_items_total ?? agreement.n_units,
        n_raters: agreement.n_raters ?? agreement.raters?.length,
        ac1: agreement.ac1 ?? agreement.overall?.ac1,
        ac2: agreement.ac2 ?? agreement.overall?.ac2,
      },
    ];
  }, [agreement, t]);

  const rows = conflicts?.rows ?? [];
  const llmExcluded = asArray<MetaLlmExcludedRow>(agreement?.llm_excluded);

  return (
    <div className="qc-scroll min-h-0 flex-1 space-y-4 overflow-auto p-4">
      {error ? <ErrorBanner>{error}</ErrorBanner> : null}
      {loading && !agreement ? <LoadingState /> : null}

      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
          {t("meta.reliabilityTitle")}
        </h3>
        {fields.length > 0 ? (
          <div>
            <table className="w-full border-collapse text-left">
              <thead className="sticky top-0 z-10 bg-surface">
                <tr>
                  <TableHead>{t("meta.colRelField")}</TableHead>
                  <TableHead>{t("meta.colUnit")}</TableHead>
                  <TableHead className="text-right">{t("meta.colLevels")}</TableHead>
                  <TableHead className="text-right">{t("meta.colItems")}</TableHead>
                  <TableHead className="text-right">{t("meta.colRaters")}</TableHead>
                  <TableHead className="text-right">AC1</TableHead>
                  <TableHead className="text-right">AC2</TableHead>
                </tr>
              </thead>
              <tbody>
                {fields.map((field) => (
                  <tr key={field.name}>
                    <td className={TD}>
                      <div>{field.label ?? field.name}</div>
                      {field.group ? (
                        <div className="text-[10px] text-text-secondary">{field.group}</div>
                      ) : null}
                    </td>
                    <td className={TD}>
                      {field.unit ?? (field.kind === "metric" ? t("meta.unitMetric") : t("meta.unitStudy"))}
                    </td>
                    <td className={NUM}>
                      {field.n_levels ?? "–"}
                      {field.multi ? "*" : ""}
                    </td>
                    <td className={NUM}>{field.n_items ?? "–"}</td>
                    <td className={NUM}>{field.n_raters ?? "–"}</td>
                    <td className={`${NUM} ${acClass(field.ac1)}`}>{fmt(field.ac1)}</td>
                    <td className={`${NUM} ${acClass(field.ac2)}`}>{fmt(field.ac2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : !loading ? (
          <p className="text-xs text-text-secondary">{t("meta.agreementEmpty")}</p>
        ) : null}
      </section>

      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
          {t("meta.conflictsTitle")} ({conflicts?.total ?? rows.length})
        </h3>
        {rows.length === 0 ? (
          <p className="text-xs text-text-secondary">{t("meta.conflictsEmpty")}</p>
        ) : (
          <div className="space-y-2">
            {rows.map((row) => {
              const chips = conflictChips(row);
              const busy = busyKeys.includes(row.key);
              return (
                <div key={row.key} className="rounded-sm border border-border p-2">
                  <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[11px] text-text-secondary">
                    <span className="font-medium text-text-primary">
                      {row.field_name ?? row.field ?? row.criterion_key ?? row.key}
                    </span>
                    <span>{row.key}</span>
                    {row.settled ? (
                      <span className="rounded-sm bg-success/10 px-1.5 py-px text-[10px] text-success">
                        {t("meta.conflictSettled")}
                      </span>
                    ) : null}
                    {row.record_index !== undefined || row.metric_index !== undefined ? (
                      <span>
                        {t("meta.experiment")} {(row.record_index ?? 0) + 1} · {t("meta.contrast")}{" "}
                        {(row.metric_index ?? 0) + 1}
                      </span>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {chips.map((chip, i) => (
                      <button
                        key={`${chip.owner}-${i}`}
                        type="button"
                        disabled={busy}
                        onClick={() => void resolve(row, chip.value)}
                        title={t("meta.resolveWith", { owner: chip.owner })}
                        className="flex items-center gap-1 rounded-sm border border-border px-1.5 py-0.5 text-[10px] qc-motion hover:border-accent hover:text-accent disabled:opacity-40"
                      >
                        <span className="text-text-secondary">{chip.owner}</span>
                        <b className="text-text-primary">{displayValue(chip.value)}</b>
                      </button>
                    ))}
                    {chips.length === 0 ? (
                      <span className="text-[11px] text-text-secondary">{t("meta.conflictsEmpty")}</span>
                    ) : null}
                    <span className="flex-1" />
                    {row.settled_value !== undefined && row.settled_value !== null ? (
                      <span className="text-[11px] text-text-secondary">
                        {t("meta.settledValue", { value: displayValue(row.settled_value) })}
                      </span>
                    ) : null}
                    <Button variant="secondary" disabled={busy} onClick={() => void resolve(row, null)}>
                      {t("meta.clearResolution")}
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {scope === "screening" && llmExcluded.length > 0 ? (
        <section className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
            {t("meta.llmExcludedTitle")} ({llmExcluded.length})
          </h3>
          <p className="text-[11px] text-text-secondary">{t("meta.llmExcludedHint")}</p>
          <div className="space-y-1">
            {llmExcluded.map((row, i) => (
              <div
                key={row.key || i}
                className="flex flex-wrap items-center gap-2 rounded-sm border border-border px-2 py-1 text-xs"
              >
                <span className="min-w-0 flex-1 truncate text-text-primary">{row.title ?? row.key}</span>
                <span className="text-text-secondary">{[row.authors, row.year].filter(Boolean).join(" · ")}</span>
                <span className="flex flex-wrap gap-1">
                  {asArray<string>(row.include_raters).map((rater) => (
                    <span key={rater} className="rounded-sm bg-accent/10 px-1.5 py-px text-[10px] text-accent">
                      {rater}
                    </span>
                  ))}
                </span>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

/** Kept for callers that want the same empty affordance as the analyze tab. */
export function AgreementEmpty() {
  return <EmptyState icon={<Handshake size={24} aria-hidden />}>—</EmptyState>;
}
