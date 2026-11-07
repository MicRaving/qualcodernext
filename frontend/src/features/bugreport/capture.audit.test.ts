import { describe, expect, it } from "vitest";
import { COLOR_PROPS, rewriteColors } from "@/features/bugreport/capture";

describe("capture audit regressions", () => {
  it("rewriteColors is not affected by a previous call's regex position", () => {
    // A long value with a match near its end leaves the global regex's
    // lastIndex far along; the next (shorter-prefix) value must still match.
    expect(rewriteColors(`${"x".repeat(200)} oklch(0.5 0.1 10)`)).not.toBeNull();
    expect(rewriteColors("oklch(0.5 0.1 10) 0 0 4px")).not.toBeNull();
  });

  it("COLOR_PROPS are CSS (kebab-case) names usable with getPropertyValue", () => {
    for (const prop of COLOR_PROPS) {
      expect(prop).not.toMatch(/[A-Z]/);
    }
    expect(COLOR_PROPS).toContain("background-color");
  });
});
