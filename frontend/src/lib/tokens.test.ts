import { describe, expect, it } from "vitest";
import { codePalette, colorFor, designTokens } from "@/lib/tokens";

describe("design tokens", () => {
  it("carries the 120-color legacy code palette", () => {
    expect(codePalette).toHaveLength(120);
    expect(codePalette[0]).toBe("#F5F6CE");
    expect(codePalette[119]).toBe("#A8A8A8");
  });

  it("resolves colors per theme", () => {
    expect(colorFor("dark", "accent")).toBe("#f59e0b");
    expect(colorFor("light", "accent")).toBe("#d97706");
    expect(colorFor("dark", "bg")).toBe("#1e1e2e");
  });

  it("exposes spacing, radius and shell tokens", () => {
    expect(designTokens.spacing.md).toBe("8px");
    expect(designTokens.radius.lg).toBe("8px");
    expect(designTokens.shell.toolbarHeight).toBe("40px");
  });
});
