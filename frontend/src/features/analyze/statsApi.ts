/**
 * Local-fetch client for the statistical analysis endpoints.
 *
 * The endpoints below are not (yet) in lib/api.ts, so they follow the
 * same local-fetch pattern as the interrater POST in merged.tsx:
 * initApiBase + fetchWithTimeout, with a single retry on network-level
 * failure (the packaged backend may have restarted on a new port).
 */

import { localRequest } from "@/lib/api";

export interface StatsCode {
  cid: number;
  name: string;
  color: string;
}

export interface CrosstabStats {
  chi2: number | null;
  df: number | null;
  p: number | null;
  cramers_v: number | null;
  yates: boolean;
  expected: number[][];
  n: number | null;
  note: string | null;
}

export interface CrosstabResult {
  attr_name: string;
  scope: "case" | "file";
  units_total: number;
  units_with_value: number;
  codes: StatsCode[];
  values: string[];
  counts: number[][];
  row_totals: number[];
  col_totals: number[];
  stats: CrosstabStats;
}

export interface GroupDescriptives {
  count: number;
  mean: number | null;
  median: number | null;
  sd: number | null;
  min: number | null;
  max: number | null;
}

export interface MwuResult {
  u1: number;
  u2: number;
  u: number;
  p: number;
  method: "exact" | "normal-approx";
  n1: number;
  n2: number;
}

export interface GroupCompareResult {
  attr_name: string;
  scope: string;
  cid: number;
  code_name: string;
  code_color: string;
  n_values: number;
  skipped_non_numeric: number;
  present: GroupDescriptives;
  absent: GroupDescriptives;
  u: MwuResult | null;
}

export interface CodeByVariableResult {
  attr_name: string;
  scope: string;
  values: string[];
  codes: StatsCode[];
  counts: number[][];
  col_totals: number[];
  chart: {
    kind: string;
    labels: { value: string }[];
    codes: StatsCode[];
    series: { cid: number; count: number }[][];
  };
}

export interface SummaryCellItem {
  kind: "text" | "image" | "av";
  id: number;
  memo: string;
}

export interface SummaryCell {
  memo: string;
  memo_count: number;
  items: SummaryCellItem[];
}

export interface SummaryRow {
  id: number;
  name: string;
  cells: SummaryCell[];
}

export interface SummaryTableResult {
  scope: "file" | "case";
  codes: StatsCode[];
  rows: SummaryRow[];
}

type QueryValue = string | number | (string | number)[] | null | undefined;

function buildQuery(params: Record<string, QueryValue>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value == null) continue;
    if (Array.isArray(value)) {
      for (const item of value) parts.push(`${key}=${encodeURIComponent(String(item))}`);
    } else {
      parts.push(`${key}=${encodeURIComponent(String(value))}`);
    }
  }
  return parts.length > 0 ? `?${parts.join("&")}` : "";
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  return localRequest<T>(path, init);
}


export function fetchCrosstab(
  attrName: string,
  scope: "case" | "file",
  codes: number[] | null,
): Promise<CrosstabResult> {
  const path = scope === "case" ? "/reports/crosstab" : "/reports/crosstab-file";
  return requestJson<CrosstabResult>(
    `${path}${buildQuery({ attr_name: attrName, codes })}`,
  );
}

export function fetchGroupCompare(attrName: string, cid: number): Promise<GroupCompareResult> {
  return requestJson<GroupCompareResult>(
    `/reports/group-compare${buildQuery({ attr_name: attrName, cid })}`,
  );
}

export function fetchCodeByVariable(attrName: string): Promise<CodeByVariableResult> {
  return requestJson<CodeByVariableResult>(
    `/reports/code-by-variable${buildQuery({ attr_name: attrName })}`,
  );
}

export function fetchSummaryTable(
  scope: "file" | "case",
  fids?: number[],
  cids?: number[],
): Promise<SummaryTableResult> {
  return requestJson<SummaryTableResult>(
    `/reports/summary-table${buildQuery({ scope, fids, cids })}`,
  );
}

/** PATCH a coding's memo through the regular codings endpoints. */
export function patchCodingMemo(
  kind: SummaryCellItem["kind"],
  id: number,
  memo: string,
): Promise<unknown> {
  if (kind === "av") {
    // AV codings have no PATCH endpoint yet.
    return Promise.reject(new Error("AV coding memos cannot be edited"));
  }
  const path = kind === "image" ? `/codings/image/${id}` : `/codings/text/${id}`;
  return requestJson<unknown>(path, {
    method: "PATCH",
    body: JSON.stringify({ memo }),
  });
}


