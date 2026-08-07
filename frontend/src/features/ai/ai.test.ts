import { describe, expect, it } from "vitest";
import { errorDetail, formatScore, welcomeMessage } from "@/features/ai/format";
import { ApiError } from "@/lib/api";

describe("formatScore", () => {
  it("formats to two decimals", () => {
    expect(formatScore(0.87123)).toBe("0.87");
    expect(formatScore(0.5)).toBe("0.50");
    expect(formatScore(1)).toBe("1.00");
  });

  it("degrades non-finite scores to 0.00", () => {
    expect(formatScore(Number.NaN)).toBe("0.00");
    expect(formatScore(Number.POSITIVE_INFINITY)).toBe("0.00");
  });
});

describe("welcomeMessage", () => {
  it("returns the ready message when enabled", () => {
    expect(welcomeMessage(true)).toBe("AI assistant ready. Ask about your project.");
  });

  it("returns the disabled notice when not enabled", () => {
    expect(welcomeMessage(false)).toBe("AI is disabled — enable it in Settings.");
  });
});

describe("errorDetail", () => {
  it("prefers the API detail field", () => {
    const err = new ApiError(503, "API error 503 on /ai/chat", "AI unavailable");
    expect(errorDetail(err)).toBe("AI unavailable");
  });

  it("falls back to the error message", () => {
    expect(errorDetail(new Error("boom"))).toBe("boom");
    expect(errorDetail("nope")).toBe("AI request failed");
  });
});
