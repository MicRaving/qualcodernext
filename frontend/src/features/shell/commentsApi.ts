/**
 * Local-fetch client for the threaded-comments endpoints (comments pinned to
 * sources, codes, codings, ...). Same pattern as features/analyze/statsApi.ts:
 * initApiBase + fetchWithTimeout, with a single retry on network-level
 * failure (the packaged backend may have restarted on a new port).
 */

import { localRequest } from "@/lib/api";

export type CommentTargetKind =
  | "source"
  | "code"
  | "case"
  | "coding"
  | "annotation"
  | "creative_item"
  | "qtt_item";

export interface Comment {
  id: number;
  target_kind: CommentTargetKind;
  target_id: number;
  body: string;
  owner: string;
  created: string;
}

type Translate = (key: string, params?: Record<string, string | number>) => string;

function buildQuery(params: Record<string, string | number | undefined>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value == null) continue;
    parts.push(`${key}=${encodeURIComponent(String(value))}`);
  }
  return parts.length > 0 ? `?${parts.join("&")}` : "";
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  return localRequest<T>(path, init);
}


/** The thread for one target, oldest first. */
export function fetchComments(
  targetKind: CommentTargetKind,
  targetId: number,
): Promise<Comment[]> {
  return requestJson<Comment[]>(
    `/comments${buildQuery({ target_kind: targetKind, target_id: targetId })}`,
  );
}

export function addComment(
  targetKind: CommentTargetKind,
  targetId: number,
  body: string,
): Promise<Comment> {
  return requestJson<Comment>("/comments", {
    method: "POST",
    body: JSON.stringify({ target_kind: targetKind, target_id: targetId, body }),
  });
}

export function deleteComment(commentId: number): Promise<void> {
  return requestJson<void>(`/comments/${commentId}`, { method: "DELETE" });
}

/**
 * Short relative label for a backend timestamp ("2026-08-13 09:30:00",
 * local time): "just now", "5m ago", "2h ago", "3d ago", then the date.
 */
export function formatCommentTime(created: string, t: Translate): string {
  const parsed = new Date(created.replace(" ", "T"));
  if (Number.isNaN(parsed.getTime())) return created;
  const minutes = Math.floor((Date.now() - parsed.getTime()) / 60000);
  if (minutes < 1) return t("inspector.commentJustNow");
  if (minutes < 60) return t("inspector.commentMinAgo", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("inspector.commentHrAgo", { count: hours });
  const days = Math.floor(hours / 24);
  if (days < 7) return t("inspector.commentDayAgo", { count: days });
  return created.slice(0, 10);
}


