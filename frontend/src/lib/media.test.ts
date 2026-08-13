import { describe, expect, it } from "vitest";
import { canTranscribeSource, hasRealTranscript, isPdf, usesPdfCoder } from "@/lib/media";

describe("media helpers", () => {
  it("detects pdf by extension", () => {
    expect(isPdf("paper.PDF")).toBe(true);
    expect(isPdf("paper.pdf")).toBe(true);
    expect(isPdf("notes.txt")).toBe(false);
  });

  it("routes text sources with .pdf names to the PDF coder", () => {
    expect(usesPdfCoder({ name: "paper.pdf", media_type: "text" })).toBe(true);
    expect(usesPdfCoder({ name: "notes.txt", media_type: "text" })).toBe(false);
    expect(usesPdfCoder({ name: "clip.mp4", media_type: "video" })).toBe(false);
  });

  it("treats only audio/video sources as transcribable", () => {
    expect(canTranscribeSource({ media_type: "audio" })).toBe(true);
    expect(canTranscribeSource({ media_type: "video" })).toBe(true);
    expect(canTranscribeSource({ media_type: "text" })).toBe(false);
    expect(canTranscribeSource({ media_type: "pdf" })).toBe(false);
    expect(canTranscribeSource({ media_type: "image" })).toBe(false);
  });

  it("hasRealTranscript requires a linked companion with text", () => {
    expect(hasRealTranscript({ av_text_id: null, has_transcript: false })).toBe(false);
    expect(hasRealTranscript({ av_text_id: null, has_transcript: true })).toBe(false);
    expect(hasRealTranscript({ av_text_id: 7, has_transcript: false })).toBe(false);
    expect(hasRealTranscript({ av_text_id: 7, has_transcript: true })).toBe(true);
    // Defensive: flag missing on non-list data (single-source fetches).
    expect(hasRealTranscript({ av_text_id: 7 })).toBe(false);
  });
});
