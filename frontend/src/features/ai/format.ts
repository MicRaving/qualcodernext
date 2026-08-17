import { errorMessage } from "@/lib/utils";
import { ApiError } from "@/lib/api";

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
