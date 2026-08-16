/**
 * Bug-report GitHub helper tests: the token-less `issues/new` URL builder
 * and `openExternal` (Tauri opener plugin vs. window.open fallback).
 */
// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { githubNewIssueUrl, openExternal, splitRepo } from "@/features/bugreport/github";

describe("splitRepo", () => {
  it("normalizes owner/repo input", () => {
    expect(splitRepo("MicRaving/QCnext")).toEqual({ owner: "MicRaving", name: "QCnext" });
    expect(splitRepo("https://github.com/MicRaving/QCnext.git")).toEqual({
      owner: "MicRaving",
      name: "QCnext",
    });
  });
});

describe("githubNewIssueUrl", () => {
  it("builds a prefilled issues/new URL", () => {
    const url = githubNewIssueUrl("MicRaving/QCnext", "Bug title", "Body line");
    const parsed = new URL(url);
    expect(parsed.host).toBe("github.com");
    expect(parsed.pathname).toBe("/MicRaving/QCnext/issues/new");
    expect(parsed.searchParams.get("title")).toBe("Bug title");
    expect(parsed.searchParams.get("body")).toBe("Body line");
  });
});

describe("openExternal", () => {
  const originalOpen = window.open;

  afterEach(() => {
    window.open = originalOpen;
  });

  it("falls back to window.open in the dev browser (no Tauri)", async () => {
    const spy = vi.fn(() => ({}) as unknown as Window | null);
    window.open = spy;
    await openExternal("https://github.com/MicRaving/QCnext/issues/new?title=x");
    expect(spy).toHaveBeenCalledWith(
      "https://github.com/MicRaving/QCnext/issues/new?title=x",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("throws when the popup is blocked", async () => {
    window.open = vi.fn(() => null);
    await expect(openExternal("https://example.com")).rejects.toThrow(/popup blocked/);
  });
});
