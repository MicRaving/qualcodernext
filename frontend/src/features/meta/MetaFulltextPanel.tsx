/**
 * Full-text screening panel (Extraction tab).
 *
 * A compact variant of the Screening verdict cards: every project criterion
 * (the same source as the Screening cards) gets an Include/Exclude
 * (pass/fail) control plus a reason text field — the
 * `Fulltext_Verdict` + `Fulltext_Exclusion_Criterion` + `Fulltext_Reason`
 * model. Saves `stage: "fulltext"` screening rows via `api.metaSaveScreening`
 * (per-criterion reasons travel inside their verdict entry; the row's
 * top-level reason carries the first failing criterion). Re-include clears
 * the full-text row. The Screening tab stays abstract-only.
 */
import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { api } from "@/lib/api";
import type { MetaCriterion, MetaHit, MetaScreening } from "@/lib/api/types";
import { Button, Input } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/lib/toast";
import { errorMessage } from "@/lib/utils";

function passValues(c: MetaCriterion): string[] {
  const raw = c.pass_values && c.pass_values.length > 0 ? c.pass_values : ["yes"];
  return raw.map((v) => String(v).toLowerCase());
}

function criterionPasses(c: MetaCriterion, applies: string | undefined): boolean {
  return passValues(c).includes(String(applies ?? "").toLowerCase());
}

function isGating(c: MetaCriterion): boolean {
  return !(c.gating === false || c.gating === 0);
}

interface RowState {
  applies: string;
  reason: string;
}

export function MetaFulltextPanel({
  hit,
  criteria,
  screening,
  owner,
  onSaved,
}: {
  hit: MetaHit;
  criteria: MetaCriterion[];
  screening: MetaScreening | null;
  owner: string;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [open, setOpen] = useState(true);
  const [busy, setBusy] = useState(false);
  const [rows, setRows] = useState<Record<string, RowState> | null>(null);

  // The verdicts of the latest full-text row seed the panel; touching a
  // control snapshots every criterion so unsaved edits survive reloads until
  // saved (the parent remounts the panel per study via `key`).
  const effective = useMemo<Record<string, RowState>>(() => {
    if (rows) return rows;
    const next: Record<string, RowState> = {};
    for (const c of criteria) {
      const entry = screening?.verdicts?.[c.key] as
        | { applies?: string; reason?: string }
        | undefined;
      next[c.key] = {
        applies:
          typeof entry?.applies === "string"
            ? entry.applies
            : c.kind === "classify"
              ? ""
              : "No",
        reason: typeof entry?.reason === "string" ? entry.reason : "",
      };
    }
    return next;
  }, [rows, criteria, screening]);

  const failing = useMemo(
    () => criteria.filter((c) => isGating(c) && !criterionPasses(c, effective[c.key]?.applies)),
    [criteria, effective],
  );
  const verdict = failing.length === 0 ? "include" : "exclude";

  const setRow = (key: string, patch: Partial<RowState>) =>
    setRows((prev) => {
      const base = effective;
      return { ...base, ...(prev ?? {}), [key]: { ...base[key], ...patch } };
    });

  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const verdicts: Record<string, { applies: string; certainty: string; reason?: string }> = {};
      for (const c of criteria) {
        const row = effective[c.key] ?? { applies: "No", reason: "" };
        const entry: { applies: string; certainty: string; reason?: string } = {
          applies: row.applies,
          certainty: "Medium",
        };
        if (row.reason.trim()) entry.reason = row.reason.trim();
        verdicts[c.key] = entry;
      }
      const firstFailing = failing[0] ?? null;
      const reason = firstFailing
        ? (effective[firstFailing.key]?.reason.trim()
          ? `${firstFailing.label}: ${effective[firstFailing.key].reason.trim()}`
          : firstFailing.exclude_reason || firstFailing.label || firstFailing.key)
        : "";
      await api.metaSaveScreening({
        hit_id: hit.hit_id,
        run_id: screening?.run_id,
        verdicts,
        owner: owner || undefined,
        stage: "fulltext",
        reason,
      });
      toast.success(t("meta.verdictSaved"));
      setRows(null);
      onSaved();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const reinclude = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.metaSaveScreening({
        hit_id: hit.hit_id,
        verdicts: {},
        owner: owner || undefined,
        stage: "fulltext",
        reason: "",
      });
      toast.success(t("meta.verdictSaved"));
      setRows(null);
      onSaved();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mb-3 rounded-sm border border-border bg-surface">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={t("meta.fulltextTitle")}
        className="flex w-full items-center gap-2 px-3 py-2 text-left qc-motion hover:bg-surface-higher"
      >
        {open ? <ChevronUp size={13} aria-hidden /> : <ChevronDown size={13} aria-hidden />}
        <span className="text-xs font-semibold text-text-primary">{t("meta.fulltextTitle")}</span>
        {screening && Object.keys(screening.verdicts ?? {}).length > 0 ? (
          <span
            className={`rounded-sm px-1.5 py-px text-[10px] font-medium ${
              verdict === "include" ? "bg-success/10 text-success" : "bg-danger/10 text-danger"
            }`}
          >
            {verdict === "include" ? t("meta.fulltextInclude") : t("meta.fulltextExclude")}
          </span>
        ) : null}
      </button>
      {open ? (
        <div className="space-y-2 border-t border-border p-2">
          {criteria.length === 0 ? (
            <p className="text-xs text-text-secondary">{t("meta.noCriteriaHint")}</p>
          ) : (
            criteria.map((c) => {
              const row = effective[c.key] ?? { applies: "No", reason: "" };
              const passes = criterionPasses(c, row.applies);
              const gating = isGating(c);
              return (
                <div
                  key={c.key}
                  className={`rounded-sm border p-2 qc-motion ${
                    gating && !passes ? "border-danger/40" : "border-border"
                  }`}
                >
                  <div className="mb-1 flex flex-wrap items-center gap-1.5">
                    <span className="text-xs font-medium text-text-primary">{c.label}</span>
                    <span className="rounded-sm bg-surface-higher px-1 text-[10px] text-text-secondary">
                      {t(`meta.kind_${c.kind ?? "verdict"}`)}
                    </span>
                    {!gating ? (
                      <span className="text-[10px] text-text-secondary">
                        {t("meta.informational")}
                      </span>
                    ) : null}
                  </div>
                  {c.kind === "classify" ? (
                    <div className="flex flex-wrap gap-1">
                      {(c.options ?? []).map((option) => (
                        <button
                          key={option}
                          type="button"
                          onClick={() => setRow(c.key, { applies: option })}
                          aria-pressed={row.applies === option}
                          className={`rounded-sm border px-2 py-0.5 text-xs qc-motion ${
                            row.applies === option
                              ? "border-accent bg-accent/10 text-accent"
                              : "border-border text-text-primary hover:bg-surface-higher"
                          }`}
                        >
                          {option}
                        </button>
                      ))}
                      {(c.options ?? []).length === 0 ? (
                        <span className="text-[11px] text-text-secondary">—</span>
                      ) : null}
                    </div>
                  ) : c.kind === "number" ? (
                    <Input
                      value={row.applies}
                      onChange={(e) => setRow(c.key, { applies: e.target.value })}
                      className="h-7 w-32 text-xs"
                      aria-label={c.label}
                    />
                  ) : (
                    <div className="flex flex-wrap items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => setRow(c.key, { applies: "Yes" })}
                        aria-pressed={passes}
                        className={`rounded-sm border px-2 py-0.5 text-xs qc-motion ${
                          passes
                            ? "border-accent bg-accent/10 text-accent"
                            : "border-border text-text-primary hover:bg-surface-higher"
                        }`}
                      >
                        {t("meta.fulltextInclude")}
                      </button>
                      <button
                        type="button"
                        onClick={() => setRow(c.key, { applies: "No" })}
                        aria-pressed={!passes}
                        className={`rounded-sm border px-2 py-0.5 text-xs qc-motion ${
                          !passes
                            ? "border-danger bg-danger/10 text-danger"
                            : "border-border text-text-primary hover:bg-surface-higher"
                        }`}
                      >
                        {t("meta.fulltextExclude")}
                      </button>
                      {!passes && c.exclude_reason ? (
                        <span className="text-[10px] text-danger">
                          {t("meta.exclusionReasonShort", { reason: c.exclude_reason })}
                        </span>
                      ) : null}
                    </div>
                  )}
                  <Input
                    value={row.reason}
                    onChange={(e) => setRow(c.key, { reason: e.target.value })}
                    placeholder={t("meta.fulltextReason")}
                    className="mt-1.5 h-7 text-xs"
                    aria-label={`${c.label} — ${t("meta.fulltextReason")}`}
                  />
                </div>
              );
            })
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            {failing.length > 0 ? (
              <span className="text-[11px] text-danger">
                {t("meta.derivedReason", { reason: failing[0].exclude_reason || failing[0].label })}
              </span>
            ) : null}
            <span className="flex-1" />
            <Button variant="secondary" disabled={busy} onClick={() => void reinclude()}>
              {t("meta.fulltextReinclude")}
            </Button>
            <Button
              variant="primary"
              disabled={busy || criteria.length === 0}
              onClick={() => void save()}
            >
              {t("meta.saveVerdict")}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
