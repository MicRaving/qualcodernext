/** AI chat modes (shared by AiView and AiChatPanel). */
export const AI_MODES = [
  "general",
  "help",
  "topic_exploration",
  "code_analysis",
  "text_analysis",
] as const;

export type AiMode = (typeof AI_MODES)[number];

export const AI_MODE_LABELS: Record<AiMode, string> = {
  general: "ai.modeGeneral",
  help: "ai.modeHelp",
  topic_exploration: "ai.modeTopic",
  code_analysis: "ai.modeCode",
  text_analysis: "ai.modeText",
};
