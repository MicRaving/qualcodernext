import { errorMessage } from "@/lib/utils";
import { ApiError, type AiPendingTool, type AiToolCallEvent } from "@/lib/api";

/** Score as a 2-decimal string; NaN/Infinity degrade to "0.00". */
export function formatScore(score: number): string {
  return Number.isFinite(score) ? score.toFixed(2) : "0.00";
}

/** Initial assistant message or the disabled-notice for the AI panels. */
export function welcomeMessage(enabled: boolean): string {
  return enabled
    ? "AI assistant ready. Ask about your project."
    : "AI is disabled — enable it in Settings.";
}

/** Human-readable detail from an API error (falls back to the message). */
export function errorDetail(e: unknown, fallback = "AI request failed"): string {
  if (e instanceof ApiError && typeof e.detail === "string") return e.detail;
  return errorMessage(e, fallback);
}

/** Human-readable summary of one executed (or proposed) MCP tool call. */
export function describeToolCall(tc: AiToolCallEvent): string {
  const a = tc.arguments as Record<string, unknown>;
  switch (tc.tool) {
    case "create_code":
      return `Created code "${String(a.name ?? "")}"`;
    case "rename_code":
      return `Renamed code ${String(a.cid ?? "")} to "${String(a.name ?? "")}"`;
    case "update_code_memo":
      return `Updated memo of code ${String(a.cid ?? "")}`;
    case "delete_code":
      return `Deleted code ${String(a.cid ?? "")}`;
    case "create_category":
      return `Created category "${String(a.name ?? "")}"`;
    case "create_coding":
      return `Created a coding (code ${String(a.cid ?? "")})`;
    case "delete_coding":
      return `Deleted coding ${String(a.ctid ?? "")}`;
    case "create_case":
      return `Created case "${String(a.name ?? "")}"`;
    case "update_case":
      return `Updated case ${String(a.caseid ?? "")}`;
    case "set_attribute_value":
      return `Set ${String(a.attr_type ?? "attribute")} "${String(a.name ?? "")}" to "${String(a.value ?? "")}"`;
    case "get_code_tree":
      return "Read the code tree";
    case "get_sources":
      return "Listed source files";
    case "get_source_text":
      return `Read source ${String(a.source_id ?? "")}`;
    case "get_cases":
      return "Listed cases";
    case "get_codings_for_file":
      return `Listed codings of file ${String(a.fid ?? "")}`;
    case "search_text":
      return `Searched text for "${String(a.pattern ?? "")}"`;
    case "get_project_summary":
      return "Read project statistics";
    default:
      return `Ran ${tc.tool}`;
  }
}

/** Describe a proposed (not yet executed) pending tool call. */
export function describePendingTool(tool: AiPendingTool): string {
  return describeToolCall({ tool: tool.name, arguments: tool.arguments, result: null });
}
