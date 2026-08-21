/**
 * Local-fetch client for coding-segment weight updates.
 *
 * The weight PATCH calls (text/image/AV) are not in lib/api.ts, so they
 * follow the same local-fetch pattern as statsApi.ts: initApiBase +
 * fetchWithTimeout, with a single retry on network-level failure (the
 * packaged backend may have restarted on a new port).
 */

import { useMemo } from "react";
import type { CodeTreeItem } from "@/lib/api";
import { ApiError, fetchWithTimeout, initApiBase } from "@/lib/api";

/** Build color-by-id and name-by-id maps from a flat code tree. */
export function useCodeMaps(codes: CodeTreeItem[]) {
  const colorByCid = useMemo(() => {
    const map = new Map<number, string>();
    for (const c of codes) if (c.kind === "code" && c.color) map.set(c.id, c.color);
    return map;
  }, [codes]);

  const nameByCid = useMemo(() => {
    const map = new Map<number, string>();
    for (const c of codes) if (c.kind === "code") map.set(c.id, c.name);
    return map;
  }, [codes]);

  return { colorByCid, nameByCid };
}

/** Build a full code index: by-id map + color/name lookup maps. */
export function useCodeIndex(codes: CodeTreeItem[]) {
  const byId = useMemo(() => {
    const m = new Map<number, CodeTreeItem>();
    for (const c of codes) if (c.kind === "code") m.set(c.id, c);
    return m;
  }, [codes]);
  const { colorByCid, nameByCid } = useCodeMaps(codes);
  return { byId, colorByCid, nameByCid };
}

export type CodingKind = "text" | "image" | "av";

/** The optional weight field on a coding row (0 = unset). */
export function codingWeight(row: unknown): number {
  return (row as { weight?: number } | null | undefined)?.weight ?? 0;
}

const PATCH_PATHS: Record<CodingKind, (id: number) => string> = {
  text: (id) => `/codings/text/${id}`,
  image: (id) => `/codings/image/${id}`,
  av: (id) => `/codings/av/${id}`,
};

export interface CodingRowPatch {
  memo?: string;
  weight?: number;
  important?: number;
}

/**
 * PATCH a segment row's memo/weight/important (text, image or AV) and return
 * the row. Mirrors the weight helper below — same local-fetch + single retry
 * pattern (the packaged backend may have restarted on a new port).
 */
async function patchCodingRow(kind: CodingKind, id: number, body: CodingRowPatch): Promise<unknown> {
  const path = PATCH_PATHS[kind](id);
  const doFetch = async (): Promise<unknown> => {
    const base = await initApiBase();
    const res = await fetchWithTimeout(`${base}${path}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
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
    return (await res.json()) as unknown;
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

/** PATCH a segment's memo (text/image/AV) and return the row. */
export async function patchCodingMemo(kind: CodingKind, id: number, memo: string): Promise<unknown> {
  return patchCodingRow(kind, id, { memo });
}

/** PATCH any combination of memo/weight/important (text/image/AV). */
export async function patchCodingRowMeta(
  kind: CodingKind,
  id: number,
  patch: CodingRowPatch,
): Promise<unknown> {
  return patchCodingRow(kind, id, patch);
}

/** PATCH a segment's weight (0-100; 0 = no weight) and return the row. */
export async function patchCodingWeight(
  kind: CodingKind,
  id: number,
  weight: number,
): Promise<unknown> {
  return patchCodingRow(kind, id, { weight });
}
