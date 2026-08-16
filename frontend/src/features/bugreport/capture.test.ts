/**
 * Bug-report capture unit tests: color neutralization (the html2canvas
 * oklab/color-mix rewrite) and the never-blank text-snapshot fallback.
 * Real-pixel rendering is covered by the Playwright probe; jsdom has no
 * canvas implementation, so the fallback test asserts it resolves to a
 * data-URL without throwing.
 */
// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { rewriteColors, resolveColor, textSnapshotScreenshot } from "@/features/bugreport/capture";

describe("resolveColor", () => {
  it("parses hex and shorthand hex", () => {
    expect(resolveColor("#ef4444")).toMatchObject({ r: 0xef / 255, g: 0x44 / 255, b: 0x44 / 255, a: 1 });
    expect(resolveColor("#f00")).toMatchObject({ r: 1, g: 0, b: 0, a: 1 });
    expect(resolveColor("#ef444480")).toMatchObject({ a: 0x80 / 255 });
  });

  it("parses oklch with and without alpha", () => {
    const opaque = resolveColor("oklch(0.577 0.245 27.325)");
    expect(opaque).not.toBeNull();
    expect(opaque!.a).toBe(1);
    const alpha = resolveColor("oklch(0.577 0.245 27.325 / 0.5)");
    expect(alpha).not.toBeNull();
    expect(alpha!.a).toBeCloseTo(0.5);
  });

  it("parses color-mix in srgb with transparent", () => {
    const mixed = resolveColor("color-mix(in srgb, #ef4444 50%, transparent)");
    expect(mixed).not.toBeNull();
    expect(mixed!.r).toBeCloseTo(0xef / 255 / 2);
    expect(mixed!.g).toBeCloseTo(0x44 / 255 / 2);
    expect(mixed!.a).toBeCloseTo(0.5);
  });

  it("parses nested color-mix in oklab (Tailwind v4 opacity modifiers)", () => {
    const mixed = resolveColor(
      "color-mix(in oklab, oklch(0.577 0.245 27.325) 50%, transparent)",
    );
    expect(mixed).not.toBeNull();
    expect(mixed!.a).toBeCloseTo(0.5);
  });

  it("parses rgb() with commas and transparent keyword", () => {
    expect(resolveColor("rgba(255, 0, 0, 0.4)")).toMatchObject({ r: 1, g: 0, b: 0, a: 0.4 });
    expect(resolveColor("transparent")).toMatchObject({ r: 0, g: 0, b: 0, a: 0 });
  });
});

describe("rewriteColors", () => {
  it("rewrites oklch to a hex (no unsupported function survives)", () => {
    const out = rewriteColors("oklch(0.577 0.245 27.325)");
    expect(out).toMatch(/^#[0-9a-f]{8}$/);
  });

  it("rewrites a color-mix with nested parens (the balanced-parser fix)", () => {
    const out = rewriteColors("color-mix(in oklab, oklch(0.577 0.245 27.325) 50%, transparent)");
    expect(out).not.toBeNull();
    expect(out).toMatch(/^#[0-9a-f]{8}$/);
    expect(out).not.toContain("oklch");
    expect(out).not.toContain("color-mix");
  });

  it("rewrites every token inside a gradient", () => {
    const out = rewriteColors("linear-gradient(oklch(0.5 0.2 0.3) 0%, oklch(0.6 0.2 0.1) 100%)");
    expect(out).not.toBeNull();
    expect(out).not.toContain("oklch");
    expect(out!.match(/#[0-9a-f]{6}/g)).toHaveLength(2);
  });

  it("rewrites compound values with an unresolvable token to a safe color", () => {
    const out = rewriteColors("color-mix(in banana, fantasy 50%, #000)");
    expect(out).not.toBeNull();
    expect(out).not.toContain("color-mix");
    expect(out).toMatch(/^#[0-9a-f]{6}$/);
  });

  it("returns null when nothing needs rewriting", () => {
    expect(rewriteColors("rgba(255, 0, 0, 0.5)")).toBeNull();
    expect(rewriteColors("rgb(0 0 0 / 30%)")).toBeNull();
    expect(rewriteColors("#123456")).toBeNull();
  });
});

describe("textSnapshotScreenshot", () => {
  it("always resolves to a data-URL result (never blank)", async () => {
    const result = await textSnapshotScreenshot("Screenshot unavailable");
    expect(typeof result.dataUrl).toBe("string");
    expect(result.dataUrl.startsWith("data:")).toBe(true);
    expect(result.blob).toBeInstanceOf(Blob);
  });
});
