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
 * Which context pickers each mode shows: memo_analysis shares memos,
 * code_analysis shares codes, text_analysis shares files, topic_exploration
 * and the semantic-search view share all three.
 */
export const CONTEXT_PICKERS: Record<AiMode, Record<ContextPickerKind, boolean>> = {
  general: { memos: false, codes: false, files: false },
  help: { memos: false, codes: false, files: false },
  topic_exploration: { memos: true, codes: true, files: true },
  code_analysis: { memos: false, codes: true, files: false },
  text_analysis: { memos: false, codes: false, files: true },
  memo_analysis: { memos: true, codes: false, files: false },
  search: { memos: true, codes: true, files: true },
};
