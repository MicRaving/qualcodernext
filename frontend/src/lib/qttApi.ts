/**
 * Local-fetch client for the QTT worksheet endpoints.
 *
 * These endpoints are not (yet) in lib/api.ts, so they follow the same
 * local-fetch pattern as statsApi.ts / creativeApi.ts: initApiBase +
 * fetchWithTimeout, with a single retry on network-level failure (the
 * packaged backend may have restarted on a new port).
 */

import { ApiError, fetchWithTimeout, initApiBase } from "@/lib/api";

export type QttSheetKind = "qual" | "mixed";
export type QttItemKind = "segment" | "note" | "chart" | "link";

export interface QttSheet {
  id: number;
  name: string;
  kind: QttSheetKind;
  sections: string[];
  /** Per-section item counts (every section key present). */
  counts: Record<string, number>;
  research_question: string;
  purpose: string;
  framework: string;
  owner: string;
  date: string;
}

export interface QttItem {
  id: number;
  sheet_id: number;
  section: string;
  kind: QttItemKind;
  payload: Record<string, unknown>;
  owner: string;
  date: string;
  /** Segment items: the source name + span excerpt (empty when unsourced). */
  source_name: string;
  source_text: string;
}

export interface QttSheetDetail extends QttSheet {
  /** Items grouped by section name (every section key present). */
  items: Record<string, QttItem[]>;
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const doFetch = async (): Promise<T> => {
    const base = await initApiBase();
    const res = await fetchWithTimeout(`${base}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
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
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  };
  try {
    return await doFetch();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    // Network-level failure (packaged backend restarted): retry once so the
    // base URL is resolved afresh.
    return doFetch();
  }
}

export function listQttSheets(): Promise<QttSheet[]> {
  return requestJson<QttSheet[]>("/qtt");
}

export function createQttSheet(body: { name: string; kind: QttSheetKind }): Promise<QttSheet> {
  return requestJson<QttSheet>("/qtt", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function patchQttSheet(
  id: number,
  body: { name?: string; research_question?: string; purpose?: string; framework?: string },
): Promise<QttSheet> {
  return requestJson<QttSheet>(`/qtt/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteQttSheet(id: number): Promise<void> {
  return requestJson<void>(`/qtt/${id}`, { method: "DELETE" });
}

export function getQttSheet(id: number): Promise<QttSheetDetail> {
  return requestJson<QttSheetDetail>(`/qtt/${id}`);
}

export function createQttItem(
  sheetId: number,
  body: { section: string; kind: QttItemKind; payload: Record<string, unknown> },
): Promise<QttItem> {
  return requestJson<QttItem>(`/qtt/${sheetId}/items`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function patchQttItem(
  itemId: number,
  body: { section?: string; payload?: Record<string, unknown> },
): Promise<QttItem> {
  return requestJson<QttItem>(`/qtt/items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteQttItem(itemId: number): Promise<void> {
  return requestJson<void>(`/qtt/items/${itemId}`, { method: "DELETE" });
}

/** Coder convenience: store the source span as a segment item on a sheet. */
export function sendSegmentToQtt(
  sheetId: number,
  body: { fid: number; pos0: number; pos1: number; section?: string },
): Promise<QttItem> {
  return requestJson<QttItem>(`/qtt/${sheetId}/send-segment`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
