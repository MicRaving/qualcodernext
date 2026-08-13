import { describe, expect, it } from "vitest";
import {
  AUDIO_EXTENSIONS,
  IMAGE_EXTENSIONS,
  TEXT_EXTENSIONS,
  VIDEO_EXTENSIONS,
  canTranscribeSource,
  hasRealTranscript,
  isAudioFilename,
  isDocumentFilename,
  isHtml,
  isImageFilename,
  isPdf,
  isVideoFilename,
  usesHtmlCoder,
  usesPdfCoder,
} from "@/lib/media";

function extNames(exts: readonly string[]): string[] {
  return exts.map((ext) => `sample${ext}`);
}

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

  it("detects html files (captured webpages)", () => {
    expect(isHtml("page.HTML")).toBe(true);
    expect(isHtml("page.html")).toBe(true);
    expect(isHtml("page.htm")).toBe(true);
    expect(isHtml("notes.txt")).toBe(false);
    expect(isHtml("paper.pdf")).toBe(false);
  });

  it("routes text sources with .html names to the HTML coder", () => {
    expect(usesHtmlCoder({ name: "page.html", media_type: "text" })).toBe(true);
    expect(usesHtmlCoder({ name: "page.htm", media_type: "text" })).toBe(true);
    expect(usesHtmlCoder({ name: "notes.txt", media_type: "text" })).toBe(false);
    expect(usesHtmlCoder({ name: "paper.pdf", media_type: "text" })).toBe(false);
    expect(usesHtmlCoder({ name: "page.html", media_type: "video" })).toBe(false);
  });

  it("classifies every audio extension", () => {
    for (const name of extNames(AUDIO_EXTENSIONS)) {
      expect(isAudioFilename(name)).toBe(true);
    }
    expect(isAudioFilename("recording.OPUS")).toBe(true);
    expect(isAudioFilename("clip.webm")).toBe(false);
    expect(isAudioFilename("clip.mp4")).toBe(false);
    expect(isAudioFilename("notes.txt")).toBe(false);
  });

  it("classifies every video extension", () => {
    for (const name of extNames(VIDEO_EXTENSIONS)) {
      expect(isVideoFilename(name)).toBe(true);
    }
    expect(isVideoFilename("clip.M4V")).toBe(true);
    // .ogg is audio (Vorbis/Opus), .webm stays video.
    expect(isVideoFilename("talk.ogg")).toBe(false);
    expect(isVideoFilename("talk.webm")).toBe(true);
    expect(isVideoFilename("notes.txt")).toBe(false);
  });

  it("classifies every image extension", () => {
    for (const name of extNames(IMAGE_EXTENSIONS)) {
      expect(isImageFilename(name)).toBe(true);
    }
    expect(isImageFilename("photo.TIFF")).toBe(true);
    expect(isImageFilename("photo.svg")).toBe(true);
    expect(isImageFilename("notes.txt")).toBe(false);
  });

  it("classifies document (text/PDF) extensions", () => {
    for (const name of extNames(TEXT_EXTENSIONS)) {
      expect(isDocumentFilename(name)).toBe(true);
    }
    expect(isDocumentFilename("server.log")).toBe(true);
    expect(isDocumentFilename("survey.csv")).toBe(true);
    expect(isDocumentFilename("paper.pdf")).toBe(true);
    expect(isDocumentFilename("clip.mp4")).toBe(false);
    expect(isDocumentFilename("pic.png")).toBe(false);
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
