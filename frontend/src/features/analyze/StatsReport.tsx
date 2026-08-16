/**
 * Statistical analysis view — code × attribute crosstabs (chi-square +
 * Cramér's V), group comparisons (Mann-Whitney U + descriptives) and the
 * mixed-methods "code frequency by variable value" matrix.
 *
 * Registered by the analysis registry; all data comes from the stats
 * endpoints via the local-fetch client (statsApi.ts).
 */
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useProjectStore } from "@/stores/project";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Button, EmptyState, SectionLabel, Select } from "@/components/ui/orchestrator";
import { cardCls, tdCls, thCls, useReport } from "@/features/analyze/reportData";
import {
  ColorSwatch,
  ReportCsvButton,
  ReportMenuBar,
  ReportStatus,
} from "@/features/analyze/reportKit";
import { barWidth } from "@/features/analyze/reportHelpers";
import {
  fetchCodeByVariable,
  fetchCrosstab,
  fetchGroupCompare,
  type CodeByVariableResult,
  type CrosstabResult,
  type GroupCompareResult,
} from "@/features/analyze/statsApi";

const fmt = (v: number | null | undefined) =>
  v == null ? "—" : v.toFixed(4);

function fmtP(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v < 0.0001) return "< 0.0001";
  return v.toFixed(4);
}

interface AttrOption {
  name: string;
  scope: "case" | "file";
}

export function StatsReportView() {
  const { t } = useI18n();
  const codeTree = useProjectStore((state) => state.codeTree);
  const codes = useMemo(
    () =>
      codeTree
        .filter((item) => item.kind === "code")
        .map((item) => ({ cid: item.id, name: item.name, color: item.color }))
        .sort((a, b) => a.name.localeCompare(b.name)),
    [codeTree],
  );

  const [attrName, setAttrName] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const [compareCid, setCompareCid] = useState<number | "">("");

  useEffect(() => {
    if (!compareCid && codes.length > 0) setCompareCid(codes[0].cid);
  }, [codes, compareCid]);

  // Attribute picker: derive the distinct attribute names + scopes from the
  // attributes report (values must exist to be selectable).
  const { data: attrRows, loading: attrsLoading, error: attrsError, retry: attrsRetry } =
    useReport(() => api.reports.attributes(), []);
  const attrs: AttrOption[] = useMemo(() => {
    const seen = new Map<string, "case" | "file">();
    for (const row of attrRows?.rows ?? []) {
      const scope = row.attr_type === "case" ? "case" : "file";
      if (!seen.has(row.name)) seen.set(row.name, scope);
    }
    return [...seen.entries()]
      .map(([name, scope]) => ({ name, scope }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [attrRows]);
  useEffect(() => {
    if (!attrName && attrs.length > 0) setAttrName(attrs[0].name);
  }, [attrs, attrName]);

  const scope: "case" | "file" | null =
    attrs.find((a) => a.name === attrName)?.scope ?? null;
  const codesParam = selected.length > 0 ? selected : null;

  const { data: crosstab, loading: ctLoading, error: ctError, retry: ctRetry } = useReport(
    () => (attrName && scope ? fetchCrosstab(attrName, scope, codesParam) : Promise.resolve(null)),
    [attrName, scope, selected],
  );
  const { data: group, loading: grLoading, error: grError, retry: grRetry } = useReport(
    () =>
      attrName && compareCid !== ""
        ? fetchGroupCompare(attrName, compareCid)
        : Promise.resolve(null),
    [attrName, compareCid],
  );
  const { data: matrix, loading: mxLoading, error: mxError, retry: mxRetry } = useReport(
    () => (attrName ? fetchCodeByVariable(attrName) : Promise.resolve(null)),
    [attrName],
  );

  if (attrsLoading || attrsError) {
    return <ReportStatus loading={attrsLoading} error={attrsError} onRetry={attrsRetry} />;
  }
  if (attrs.length === 0) {
    return (
      <div className="h-48">
        <EmptyState>{t("analyze.statsNoAttributes")}</EmptyState>
      </div>
    );
  }

  const toggleCode = (cid: number) =>
    setSelected((prev) =>
      prev.includes(cid) ? prev.filter((c) => c !== cid) : [...prev, cid],
    );

  return (
    <div className="space-y-4">
      <ReportMenuBar>
        <Select
          value={attrName}
          onChange={(e) => setAttrName(e.target.value)}
          aria-label={t("analyze.statsAttribute")}
        >
          {attrs.map((a) => (
            <option key={a.name} value={a.name}>
              {a.name} ({a.scope === "case" ? t("analyze.statsScopeCase") : t("analyze.statsScopeFile")})
            </option>
          ))}
        </Select>
        {codes.length > 0 && (
          <>
            <span className="text-xs text-text-secondary">{t("analyze.statsComparisonCode")}</span>
            <Select
              value={compareCid}
              onChange={(e) => setCompareCid(e.target.value === "" ? "" : Number(e.target.value))}
              aria-label={t("analyze.statsComparisonCode")}
            >
              {codes.map((c) => (
                <option key={c.cid} value={c.cid}>
                  {c.name}
                </option>
              ))}
            </Select>
          </>
        )}
        {crosstab && (
          <ReportCsvButton
            filename={`crosstab-${crosstab.attr_name}.csv`}
            headers={[t("analyze.colCode"), ...crosstab.values, t("analyze.statsTotal")]}
            rows={crosstab.codes.map((code, ri) => [
              code.name,
              ...crosstab.values.map((_, ci) => crosstab.counts[ri]?.[ci] ?? 0),
              crosstab.row_totals[ri] ?? 0,
            ])}
          />
        )}
        {matrix && (
          <ReportCsvButton
            filename={`code-by-variable-${matrix.attr_name}.csv`}
            headers={[t("analyze.statsValue"), ...matrix.codes.map((c) => c.name), t("analyze.statsTotal")]}
            rows={matrix.values.map((value, vi) => [
              value,
              ...(matrix.counts[vi] ?? []),
              (matrix.counts[vi] ?? []).reduce((a, b) => a + b, 0),
            ])}
          />
        )}
      </ReportMenuBar>

      <div className="space-y-2">
        <SectionLabel>{t("analyze.statsCodes")}</SectionLabel>
        <div className="flex flex-wrap items-center gap-1.5">
          {codes.length === 0 ? (
            <span className="text-xs text-text-secondary">{t("analyze.noData")}</span>
          ) : (
            codes.map((c) => (
              <Button
                key={c.cid}
                variant="toolbar"
                onClick={() => toggleCode(c.cid)}
                className={cn(selected.includes(c.cid) && "border-accent bg-accent/10 text-accent")}
              >
                <ColorSwatch color={c.color} />
                {c.name}
              </Button>
            ))
          )}
          {selected.length > 0 && (
            <Button variant="toolbar" onClick={() => setSelected([])}>
              {t("analyze.clearCode")}
            </Button>
          )}
        </div>
      </div>

      <CrosstabSection result={crosstab} loading={ctLoading} error={ctError} onRetry={ctRetry} />
      <GroupCompareSection result={group} loading={grLoading} error={grError} onRetry={grRetry} />
      <CodeByVariableSection result={matrix} loading={mxLoading} error={mxError} onRetry={mxRetry} />
    </div>
  );
}

/* ------------------------------------------------- crosstab + statistics */

function CrosstabSection({
  result,
  loading,
  error,
  onRetry,
}: {
  result: CrosstabResult | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  if (loading || error) return <ReportStatus loading={loading} error={error} onRetry={onRetry} />;
  if (!result) return null;
  if (result.codes.length === 0 || result.values.length === 0) {
    return (
      <section>
        <SectionLabel>{t("analyze.statsCrosstab")}</SectionLabel>
        <div className="h-48">
          <EmptyState>{t("analyze.statsNotEnough")}</EmptyState>
        </div>
      </section>
    );
  }
  const stats = result.stats;
  return (
    <section>
      <SectionLabel>{t("analyze.statsCrosstab")}</SectionLabel>
      <div className={cn(cardCls, "mt-2 min-w-52 px-3 py-2")}>
        <p className="text-xs text-text-secondary">
          {t("analyze.statsChiSquare")}
          {stats.yates && ` (${t("analyze.statsYates")})`}
        </p>
        <p className="mt-0.5 text-lg font-semibold tabular-nums text-text-primary">
          {fmt(stats.chi2)}
          <span className="ml-2 text-xs font-normal text-text-secondary">
            {t("analyze.statsDf")} {stats.df ?? "—"}
          </span>
        </p>
        <p className="text-xs text-text-secondary">
          {t("analyze.statsP")} = {fmtP(stats.p)} · {t("analyze.statsCramersV")} ={" "}
          {fmt(stats.cramers_v)}
        </p>
        <p className="mt-1 text-xs text-text-secondary">
          {t("analyze.statsUnitsWithValue", { n: result.units_with_value })}
        </p>
        {stats.note && <p className="mt-1 text-xs italic text-text-secondary">{stats.note}</p>}
      </div>
      <div className={cn(cardCls, "mt-2 max-h-96")}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className={cn(thCls, "min-w-40")}>{t("analyze.colCode")}</th>
              {result.values.map((v) => (
                <th key={v} className={cn(thCls, "min-w-24 text-right")}>
                  {v}
                </th>
              ))}
              <th className={cn(thCls, "min-w-16 text-right")}>{t("analyze.statsTotal")}</th>
            </tr>
          </thead>
          <tbody>
            {result.codes.map((code, ri) => (
              <tr key={code.cid} className="hover:bg-surface-higher">
                <td className={cn(tdCls, "max-w-48")}>
                  <span className="flex items-center gap-2">
                    <ColorSwatch color={code.color} />
                    <span className="block truncate font-medium">{code.name}</span>
                  </span>
                </td>
                {result.values.map((v, ci) => (
                  <td key={v} className={cn(tdCls, "text-right tabular-nums text-text-secondary")}>
                    {result.counts[ri]?.[ci] ?? 0}
                  </td>
                ))}
                <td className={cn(tdCls, "text-right font-medium tabular-nums")}>
                  {result.row_totals[ri] ?? 0}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="bg-surface-higher">
              <td className={cn(tdCls, "text-xs text-text-secondary")}>{t("analyze.statsTotal")}</td>
              {result.col_totals.map((n, ci) => (
                <td key={ci} className={cn(tdCls, "text-right tabular-nums")}>
                  {n}
                </td>
              ))}
              <td className={cn(tdCls, "text-right tabular-nums")}>
                {result.col_totals.reduce((a, b) => a + b, 0)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}

/* ------------------------------------------------ group comparison (MWU) */

function GroupCompareSection({
  result,
  loading,
  error,
  onRetry,
}: {
  result: GroupCompareResult | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  if (loading || error) return <ReportStatus loading={loading} error={error} onRetry={onRetry} />;
  if (!result) return null;
  return (
    <section>
      <SectionLabel>{t("analyze.statsGroupCompare")}</SectionLabel>
      <div className="mt-2 space-y-2">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {(
            [
              [t("analyze.statsPresent"), result.present, result.code_color],
              [t("analyze.statsAbsent"), result.absent, null],
            ] as [string, GroupCompareResult["present"], string | null][]
          ).map(([label, desc, color]) => (
            <div key={label} className={cn(cardCls, "px-3 py-2")}>
              <p className="text-xs text-text-secondary">
                {label} <span className="text-text-primary">{result.code_name}</span>
              </p>
              <dl className="mt-1 grid grid-cols-3 gap-x-2 gap-y-1 text-xs">
                {(
                  [
                    [t("analyze.statsN"), desc.count],
                    [t("analyze.statsMean"), fmt(desc.mean)],
                    [t("analyze.statsMedian"), fmt(desc.median)],
                    [t("analyze.statsSd"), fmt(desc.sd)],
                    [t("analyze.statsMin"), fmt(desc.min)],
                    [t("analyze.statsMax"), fmt(desc.max)],
                  ] as [string, string | number][]
                ).map(([k, v]) => (
                  <div key={k} className="flex items-baseline justify-between gap-2">
                    <dt className="text-text-secondary">{k}</dt>
                    <dd className="font-medium tabular-nums">{v}</dd>
                  </div>
                ))}
              </dl>
              {color && <ColorSwatch color={color} />}
            </div>
          ))}
        </div>
        {result.u ? (
          <div className={cn(cardCls, "px-3 py-2")}>
            <p className="text-xs text-text-secondary">
              {t("analyze.statsMwu")}: U = {result.u.u.toFixed(2)}
              <span className="mx-2">·</span>
              {t("analyze.statsP")} = {fmtP(result.u.p)}
              <span className="mx-2">·</span>
              {result.u.method === "exact" ? t("analyze.statsExact") : t("analyze.statsApprox")}
              <span className="mx-2">·</span>
              {t("analyze.statsN")}: {result.u.n1} / {result.u.n2}
            </p>
          </div>
        ) : (
          <div className={cn(cardCls, "px-3 py-2")}>
            <p className="text-xs text-text-secondary">{t("analyze.statsNotEnough")}</p>
          </div>
        )}
        {result.skipped_non_numeric > 0 && (
          <p className="text-xs text-text-secondary">
            {t("analyze.statsSkipped", { n: result.skipped_non_numeric })}
          </p>
        )}
      </div>
    </section>
  );
}

/* ---------------------------------------- code frequency by variable value */

function CodeByVariableSection({
  result,
  loading,
  error,
  onRetry,
}: {
  result: CodeByVariableResult | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  if (loading || error) return <ReportStatus loading={loading} error={error} onRetry={onRetry} />;
  if (!result) return null;
  if (result.codes.length === 0 || result.values.length === 0) {
    return (
      <section>
        <SectionLabel>{t("analyze.statsCodeByVariable")}</SectionLabel>
        <div className="h-48">
          <EmptyState>{t("analyze.statsNotEnough")}</EmptyState>
        </div>
      </section>
    );
  }
  const maxTotal = Math.max(1, ...result.counts.map((row) => row.reduce((a, b) => a + b, 0)));
  return (
    <section>
      <SectionLabel>{t("analyze.statsCodeByVariable")}</SectionLabel>
      <div className={cn(cardCls, "mt-2 space-y-3 p-3")}>
        {result.values.map((value, vi) => {
          const row = result.counts[vi] ?? [];
          const total = row.reduce((a, b) => a + b, 0);
          return (
            <div key={value}>
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <span className="text-sm font-medium text-text-primary">{value}</span>
                <span className="text-xs tabular-nums text-text-secondary">
                  {t("analyze.statsTotal")}: {total}
                </span>
              </div>
              <div className="flex h-3.5 w-full overflow-hidden rounded-sm bg-surface-higher">
                {result.codes.map((code, ci) => {
                  const count = row[ci] ?? 0;
                  if (count === 0) return null;
                  return (
                    <div
                      key={code.cid}
                      title={`${code.name}: ${count}`}
                      style={{
                        width: barWidth(count, maxTotal),
                        backgroundColor: code.color ?? "var(--qc-accent)",
                      }}
                    />
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
      <div className={cn(cardCls, "mt-2 max-h-96")}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className={cn(thCls, "min-w-40")}>{t("analyze.statsValue")}</th>
              {result.codes.map((c) => (
                <th key={c.cid} className={cn(thCls, "min-w-24 text-right")}>
                  <span className="flex items-center justify-end gap-1.5">
                    <ColorSwatch color={c.color} />
                    <span className="truncate">{c.name}</span>
                  </span>
                </th>
              ))}
              <th className={cn(thCls, "min-w-16 text-right")}>{t("analyze.statsTotal")}</th>
            </tr>
          </thead>
          <tbody>
            {result.values.map((value, vi) => (
              <tr key={value} className="hover:bg-surface-higher">
                <td className={cn(tdCls, "font-medium")}>{value}</td>
                {result.codes.map((c, ci) => (
                  <td key={c.cid} className={cn(tdCls, "text-right tabular-nums text-text-secondary")}>
                    {result.counts[vi]?.[ci] ?? 0}
                  </td>
                ))}
                <td className={cn(tdCls, "text-right font-medium tabular-nums")}>
                  {(result.counts[vi] ?? []).reduce((a, b) => a + b, 0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
