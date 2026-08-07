import { describe, expect, it } from "vitest";
import { CODING_ALPHA, codeTint } from "@/features/coding/tint";

describe("codeTint", () => {
  it("renders the code color at the shared coding alpha", () => {
    expect(CODING_ALPHA).toBeGreaterThan(0);
    expect(CODING_ALPHA).toBeLessThan(1);
    expect(codeTint("#ff0000")).toBe(
      `color-mix(in srgb, #ff0000 ${Math.round(CODING_ALPHA * 100)}%, transparent)`,
    );
  });
});
