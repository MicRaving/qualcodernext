/**
 * Local-fetch client for the code-sets endpoints (MAXQDA-style named
 * subsets of codes).
 *
 * These endpoints are not (yet) in lib/api.ts, so they follow the same
 * local-fetch pattern as statsApi.ts / creativeApi.ts: initApiBase +
 * fetchWithTimeout, with a single retry on network-level failure (the
 * packaged backend may have restarted on a new port).
 */

import { localRequest } from "@/lib/api";

export interface CodeSetSummary {
  id: number;
  name: string;
  owner: string | null;
  created: string | null;
  member_count: number;
}

export interface CodeSetMember {
  cid: number;
  name: string;
}

export interface CodeSetDetail {
  set_id: number;
  members: CodeSetMember[];
}

export interface CodeSetMembersResult {
  set_id: number;
  added?: number;
  removed?: number;
  cids?: number[];
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  return localRequest<T>(path, init);
}


export function listCodeSets(): Promise<CodeSetSummary[]> {
  return requestJson<CodeSetSummary[]>("/code-sets");
}

export function createCodeSet(name: string): Promise<CodeSetSummary> {
  return requestJson<CodeSetSummary>("/code-sets", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function renameCodeSet(setId: number, name: string): Promise<CodeSetSummary> {
  return requestJson<CodeSetSummary>(`/code-sets/${setId}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

export function deleteCodeSet(setId: number): Promise<void> {
  return requestJson<void>(`/code-sets/${setId}`, { method: "DELETE" });
}

export function getCodeSet(setId: number): Promise<CodeSetDetail> {
  return requestJson<CodeSetDetail>(`/code-sets/${setId}`);
}

export function addCodeSetMembers(setId: number, cids: number[]): Promise<CodeSetMembersResult> {
  return requestJson<CodeSetMembersResult>(`/code-sets/${setId}/members`, {
    method: "POST",
    body: JSON.stringify({ cids }),
  });
}

export function removeCodeSetMembers(
  setId: number,
  cids: number[],
): Promise<CodeSetMembersResult> {
  return requestJson<CodeSetMembersResult>(`/code-sets/${setId}/members`, {
    method: "DELETE",
    body: JSON.stringify({ cids }),
  });
}


