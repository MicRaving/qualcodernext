/**
 * Local-fetch client for the creative coding scratchpad endpoints.
 *
 * These endpoints are not (yet) in lib/api.ts, so they follow the same
 * local-fetch pattern as statsApi.ts: initApiBase + fetchWithTimeout, with
 * a single retry on network-level failure (the packaged backend may have
 * restarted on a new port).
 */

import { localRequest } from "@/lib/api";

export interface CreativeItem {
  id: number;
  text: string;
  source_fid: number | null;
  pos0: number | null;
  pos1: number | null;
  note: string;
  owner: string;
  date: string;
  source_name: string;
  source_text: string;
}

export interface PromoteResult {
  cid: number;
  ctid: number | null;
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  return localRequest<T>(path, init);
}


export function listCreativeItems(): Promise<CreativeItem[]> {
  return requestJson<CreativeItem[]>("/creative");
}

export function createCreativeItem(
  body: { text: string; source_fid?: number | null; pos0?: number | null; pos1?: number | null; note?: string },
): Promise<CreativeItem> {
  return requestJson<CreativeItem>("/creative", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function patchCreativeItem(
  id: number,
  body: { text?: string; note?: string },
): Promise<CreativeItem> {
  return requestJson<CreativeItem>(`/creative/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteCreativeItem(id: number): Promise<void> {
  return requestJson<void>(`/creative/${id}`, { method: "DELETE" });
}

export function promoteCreativeItem(
  id: number,
  body: { code_name: string; catid?: number | null },
): Promise<PromoteResult> {
  return requestJson<PromoteResult>(`/creative/${id}/promote`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}


