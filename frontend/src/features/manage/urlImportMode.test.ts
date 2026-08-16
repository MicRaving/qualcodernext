/**
 * UrlImportDialog mode auto-selection tests — the pure URL -> mode helper.
 */
import { describe, expect, it } from "vitest";
import { detectModeFromUrl } from "@/features/manage/urlImportMode";

describe("detectModeFromUrl", () => {
  it("maps youtube.com hosts to youtube", () => {
    expect(detectModeFromUrl("https://www.youtube.com/watch?v=abc")).toBe("youtube");
    expect(detectModeFromUrl("https://youtube.com/watch?v=abc")).toBe("youtube");
    expect(detectModeFromUrl("https://m.youtube.com/watch?v=abc")).toBe("youtube");
    expect(detectModeFromUrl("https://music.youtube.com/watch?v=abc")).toBe("youtube");
  });

  it("maps youtu.be hosts to youtube", () => {
    expect(detectModeFromUrl("https://youtu.be/abc123")).toBe("youtube");
    expect(detectModeFromUrl("https://www.youtu.be/abc123")).toBe("youtube");
  });

  it("no longer maps reddit hosts (Reddit scraper purged → null)", () => {
    expect(detectModeFromUrl("https://www.reddit.com/r/x/comments/abc/")).toBeNull();
    expect(detectModeFromUrl("https://reddit.com/r/x/comments/abc/")).toBeNull();
    expect(detectModeFromUrl("https://old.reddit.com/r/x/comments/abc/")).toBeNull();
  });

  it("accepts scheme-less pastes", () => {
    expect(detectModeFromUrl("youtube.com/watch?v=abc")).toBe("youtube");
    expect(detectModeFromUrl("youtu.be/abc123")).toBe("youtube");
    expect(detectModeFromUrl("www.reddit.com/r/x/comments/abc/")).toBeNull();
  });

  it("leaves unknown, empty or malformed URLs untouched (null)", () => {
    expect(detectModeFromUrl("https://example.org/story")).toBeNull();
    expect(detectModeFromUrl("https://notyoutube.com/watch?v=abc")).toBeNull();
    expect(detectModeFromUrl("https://youtube.com.evil.example/x")).toBeNull();
    expect(detectModeFromUrl("https://reddit.com.example.org/x")).toBeNull();
    expect(detectModeFromUrl("")).toBeNull();
    expect(detectModeFromUrl("   ")).toBeNull();
    expect(detectModeFromUrl("not a url")).toBeNull();
  });
});
