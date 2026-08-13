/**
 * Segment links — client for the /links API plus the `qcnext-link://` clipboard
 * payload shared by the coders (copy/paste) and the Inspector (in/out lists).
 *
 * The API surface deliberately mirrors the annotation client: local fetches
 * built on the exported `initApiBase` / `fetchWithTimeout` / `ApiError`
 * primitives (api.ts itself is supervisor-owned).
 */
import { ApiError, fetchWithTimeout, initApiBase } from "@/lib/api";

export interface SegmentLink {
  id: number;
  from_fid: number;
  from_pos0: number;
  from_pos1: number;
  to_fid: number;
  to_pos0: number;
  to_pos1: number;
  memo: string;
  owner: string;
  date: string;
  from_name: string;
  to_name: string;
  from_text: string;
  to_text: string;
}

export interface LinkSpanTarget {
  fid: number;
  pos0: number;
  pos1: number;
}

/** Clipboard payload: `qcnext-link://fid:pos0-pos1` (MAXQDA-style quote link). */
export const LINK_PREFIX = "qcnext-link://";

export function encodeLinkPayload(fid: number, pos0: number, pos1: number): string {
  return `${LINK_PREFIX}${fid}:${pos0}-${pos1}`;
}

export function parseLinkPayload(text: string): LinkSpanTarget | null {
  if (!text.trimStart().startsWith(LINK_PREFIX)) return null;
  const match = /^(\d+):(\d+)-(\d+)$/.exec(text.trim().slice(LINK_PREFIX.length));
  if (!match) return null;
  return { fid: Number(match[1]), pos0: Number(match[2]), pos1: Number(match[3]) };
}

/**
 * In-session memory of the last copied link. The Tauri webview can refuse
 * clipboard *reads* (permission), so "Paste link here" works within the
 * session even when the clipboard read is blocked.
 */
let lastCopied: LinkSpanTarget | null = null;

export function rememberCopiedLink(target: LinkSpanTarget | null): void {
  lastCopied = target;
}

export async function copyLinkPayload(fid: number, pos0: number, pos1: number): Promise<void> {
  const payload = encodeLinkPayload(fid, pos0, pos1);
  lastCopied = { fid, pos0, pos1 };
  try {
    await navigator.clipboard.writeText(payload);
  } catch {
    /* non-secure context — the in-session memory still allows pasting */
  }
}

export async function readLinkPayload(): Promise<LinkSpanTarget | null> {
  if (lastCopied) return lastCopied;
  try {
    return parseLinkPayload(await navigator.clipboard.readText());
  } catch {
    return null;
  }
}

/* ------------------------------------------------------------------ */
/* API — local fetches (same shape as the annotation endpoints)        */
/* ------------------------------------------------------------------ */

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
    // Network-level failure (the packaged backend restarted): retry once
    // so the base URL is resolved afresh.
    return doFetch();
  }
}

/** Outgoing links anchored on a file (from_fid == fid). */
export function fetchOutgoingLinks(fid: number): Promise<SegmentLink[]> {
  return request<SegmentLink[]>(`/links?fid=${fid}`);
}

/** Incoming links pointing AT a file (to_fid == fid). */
export function fetchIncomingLinks(fid: number): Promise<SegmentLink[]> {
  return request<SegmentLink[]>(`/links/source/${fid}`);
}

export function createLink(body: {
  from_fid: number;
  from_pos0: number;
  from_pos1: number;
  to_fid: number;
  to_pos0: number;
  to_pos1: number;
  memo?: string;
}): Promise<SegmentLink> {
  return request<SegmentLink>("/links", { method: "POST", body: JSON.stringify(body) });
}

export function deleteLink(linkId: number): Promise<void> {
  return request<void>(`/links/${linkId}`, { method: "DELETE" });
}

/* ------------------------------------------------------------------ */
/* Jump-to-target: a window event any mounted coder can react to.      */
/* The coder for the target file flashes the span (scroll + highlight).*/
/* ------------------------------------------------------------------ */

export interface PendingJump {
  fid: number;
  pos0: number;
  pos1: number;
}

let pendingJump: PendingJump | null = null;

export function jumpToSpan(fid: number, pos0: number, pos1: number): void {
  pendingJump = { fid, pos0, pos1 };
  window.dispatchEvent(
    new CustomEvent("qc:jump-span", { detail: { fid, pos0, pos1 } }),
  );
}

/**
 * Claim the pending jump when the target file's coder mounts (the jump may
 * have been requested while another file was open).
 */
export function consumePendingJump(fid: number): PendingJump | null {
  if (pendingJump && pendingJump.fid === fid) {
    const jump = pendingJump;
    pendingJump = null;
    return jump;
  }
  return null;
}
