/** AI assistant modes — chat modes plus the semantic-search view. */
export const AI_MODES = [
  "general",
  "help",
  "topic_exploration",
  "code_analysis",
  "text_analysis",
  "memo_analysis",
  "search",
] as const;

export type AiMode = (typeof AI_MODES)[number];

export const AI_MODE_LABELS: Record<AiMode, string> = {
  general: "ai.modeGeneral",
  help: "ai.modeHelp",
  topic_exploration: "ai.modeTopic",
  code_analysis: "ai.modeCode",
  text_analysis: "ai.modeText",
  memo_analysis: "ai.modeMemos",
  search: "ai.modeSearch",
};

/** Kinds of context pickers a mode can share with the request. */
export type ContextPickerKind = "memos" | "codes" | "files";

export const CONTEXT_PICKER_KINDS: readonly ContextPickerKind[] = [
  "memos",
  "codes",
  "files",
];

/**
 * Which context pickers each mode shows (Option A — additive pickers):
 * every analysis mode exposes ALL three kinds so the user can attach memos
 * to a code review, codes to a text analysis, etc.; the mode-relevant kind
 * (see ``primaryContextKind``) is expanded by default. General/help show
 * none; the semantic-search view shows all three (files act as the filter).
 */
export const CONTEXT_PICKERS: Record<AiMode, Record<ContextPickerKind, boolean>> = {
  general: { memos: false, codes: false, files: false },
  help: { memos: false, codes: false, files: false },
  topic_exploration: { memos: true, codes: true, files: true },
  code_analysis: { memos: true, codes: true, files: true },
  text_analysis: { memos: true, codes: true, files: true },
  memo_analysis: { memos: true, codes: true, files: true },
  search: { memos: true, codes: true, files: true },
};

/**
 * The picker kind a mode treats as its primary context — expanded by
 * default in the picker tab row. ``topic_exploration`` and ``search`` have
 * no single primary; they fall back to the first tab.
 */
export function primaryContextKind(mode: AiMode): ContextPickerKind | null {
  switch (mode) {
    case "memo_analysis":
      return "memos";
    case "code_analysis":
      return "codes";
    case "text_analysis":
      return "files";
    default:
      return null;
  }
}
