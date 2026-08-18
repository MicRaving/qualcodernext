/**
 * AI assistant modes — the backend derives the analysis mode automatically
 * from the context picker selections ("auto" mode), so the old mode dropdown
 * is gone. This module only mirrors the derivation for the read-only mode
 * badge in the chat panel and defines the context-picker kinds.
 */

/** Kinds of context pickers a chat request can share. */
export type ContextPickerKind = "memos" | "codes" | "files";

export const CONTEXT_PICKER_KINDS: readonly ContextPickerKind[] = [
  "memos",
  "codes",
  "files",
];

/** Mode labels (used by the auto-mode badge). */
export const AI_MODE_LABELS: Record<string, string> = {
  general: "ai.modeGeneral",
  topic_exploration: "ai.modeTopic",
  code_analysis: "ai.modeCode",
  text_analysis: "ai.modeText",
  memo_analysis: "ai.modeMemos",
  sentiment: "ai.modeSentiment",
};

/**
 * Mirrors the backend's ``derive_mode``: only codes → code_analysis, only
 * memos → memo_analysis, only sources → text_analysis, several kinds →
 * topic_exploration, nothing selected → general. Returns the i18n key for
 * the mode label.
 */
export function deriveModeLabel(ids: {
  memoIds?: number[];
  codeIds?: number[];
  sourceIds?: number[];
}): string {
  const memos = (ids.memoIds?.length ?? 0) > 0;
  const codes = (ids.codeIds?.length ?? 0) > 0;
  const sources = (ids.sourceIds?.length ?? 0) > 0;
  const kinds = Number(memos) + Number(codes) + Number(sources);
  if (kinds >= 2) return "topic_exploration";
  if (codes) return "code_analysis";
  if (memos) return "memo_analysis";
  if (sources) return "text_analysis";
  return "general";
}