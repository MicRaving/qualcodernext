/**
 * Interchange import/preview HTTP helpers for the ImportPreview manager.
 *
 * The manager needs two things the shared api client does not expose: the
 * sniff+sample preview endpoint and a forced-format import (``force_kind``
 * on the auto-detect import). Both are manager-specific, so the calls live
 * here instead of lib/api.ts.
 */
import {
  ApiError,
  fetchWithTimeout,
  initApiBase,
  type InterchangeResult,
} from "@/lib/api";

/** Formats a picked file can be forced to (Zotero reads a local API and is
 *  therefore not file-importable). */
export const FORCEABLE_FORMATS = [
  "refi",
  "rqda",
  "taguette",
  "transana",
  "nvivo",
  "ris",
  "survey",
  "xlsx",
  "sav",
  "codebook",
  "merge",
] as const;

export type ForceableFormat = (typeof FORCEABLE_FORMATS)[number];

/** Client-side fetch timeouts for the interchange endpoints (ms). The
 *  import call is generous: survey/xlsx/sav imports parse and write many
 *  rows on the backend and can legitimately run for minutes. Aborting the
 *  client fetch mid-import surfaces as Chromium's "signal is aborted
 *  without reason" — the import itself keeps running server-side. The
 *  preview/sniff call stays short. */
export const PREVIEW_TIMEOUT_MS = 30_000;
export const IMPORT_TIMEOUT_MS = 300_000;

/** The backend's sniff+sample response for one upload. */
export interface InterchangePreview {
  format: string;
  /** Header row (survey/xlsx) or variable names (sav). */
  columns?: string[] | null;
  /** First ~15 parsed rows (string cells). */
  rows_sample?: (string | null)[][] | null;
  /** String-ish columns (excluding the case-name column) — prefilled into
   *  the qualitative-columns input. */
  qual_columns?: string[] | null;
  /** First codebook lines. */
  lines?: string[] | null;
}

async function interchangeRequest<T>(
  path: string,
  file: File,
  extra?: { forceKind?: string; qualitativeHeaders?: string[] },
  timeoutMs = PREVIEW_TIMEOUT_MS,
): Promise<T> {
  const base = await initApiBase();
  const form = new FormData();
  form.append("file", file);
  if (extra?.forceKind) form.append("force_kind", extra.forceKind);
  if (extra?.qualitativeHeaders?.length) {
    form.append("qualitative_headers", extra.qualitativeHeaders.join(","));
  }
  const res = await fetchWithTimeout(
    `${base}${path}`,
    { method: "POST", body: form },
    timeoutMs,
  );
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* non-JSON error body */
    }
    const suffix = typeof detail === "string" && detail ? `: ${detail}` : "";
    throw new ApiError(res.status, `API error ${res.status} on ${path}${suffix}`, detail);
  }
  return (await res.json()) as T;
}

/** Sniff an upload and return its content preview (optional forced format). */
export function previewInterchange(
  file: File,
  forceKind?: string,
): Promise<InterchangePreview> {
  return interchangeRequest<InterchangePreview>("/interchange/import/preview", file, {
    forceKind,
  });
}

/** Import one upload through the auto-detect endpoint (optionally forced to
 *  ``forceKind`` and with the survey qualitative columns set). */
export function importInterchange(
  file: File,
  opts: { forceKind?: string; qualitativeHeaders?: string[] } = {},
): Promise<InterchangeResult> {
  return interchangeRequest<InterchangeResult>(
    "/interchange/import/auto",
    file,
    opts,
    IMPORT_TIMEOUT_MS,
  );
}
