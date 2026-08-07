import { describe, expect, it } from "vitest";
import type { CodeDetails, Source, SourceDetails } from "@/lib/api";
import {
  formatMediaLabel,
  formatStats,
  isCodeDetails,
  isSourceDetails,
} from "@/features/shell/inspector";

function makeSource(overrides: Partial<Source> = {}): Source {
  return {
    id: 1,
    name: "a.txt",
    fulltext: null,
    mediapath: null,
    memo: "",
    owner: "default",
    date: "2024-01-01 00:00:00",
    av_text_id: null,
    risid: null,
    media_type: "text",
    ...overrides,
  };
}

function makeCodeDetails(overrides: Partial<CodeDetails> = {}): CodeDetails {
  return {
    code: {
      cid: 1,
      name: "Theme",
      memo: "",
      catid: null,
      owner: "default",
      date: "2024-01-01 00:00:00",
      color: "#ff0000",
    },
    category_path: [],
    coding_count: 0,
    file_count: 0,
    recent_examples: [],
    ...overrides,
  };
}

function makeSourceDetails(overrides: Partial<SourceDetails> = {}): SourceDetails {
  return {
    source: makeSource(),
    text_codings: 0,
    image_codings: 0,
    av_codings: 0,
    codes_used: [],
    cases: [],
    attributes: [],
    ...overrides,
  };
}

describe("formatStats", () => {
  it("formats code stats as codings and files", () => {
    const stats = formatStats(
      makeCodeDetails({ coding_count: 12, file_count: 3 }),
    );
    expect(stats).toEqual({ primary: "12 codings", secondary: "3 files" });
  });

  it("formats source stats as text / image / av", () => {
    const stats = formatStats(
      makeSourceDetails({ text_codings: 3, image_codings: 0, av_codings: 1 }),
    );
    expect(stats).toEqual({ primary: "3 text", secondary: "0 image · 1 av" });
  });

  it("handles zero counts", () => {
    const stats = formatStats(makeCodeDetails());
    expect(stats).toEqual({ primary: "0 codings", secondary: "0 files" });
  });
});

describe("formatMediaLabel", () => {
  it("reports PDF for .pdf filenames", () => {
    expect(formatMediaLabel(makeSource({ name: "report.pdf" }))).toBe("PDF");
    expect(formatMediaLabel(makeSource({ name: "notes.txt" }))).toBe("Text");
  });

  it("maps media types to labels", () => {
    expect(formatMediaLabel(makeSource({ media_type: "image" }))).toBe("Image");
    expect(formatMediaLabel(makeSource({ media_type: "audio" }))).toBe("Audio");
    expect(formatMediaLabel(makeSource({ media_type: "video" }))).toBe("Video");
  });
});

describe("type guards", () => {
  it("distinguishes code details from source details", () => {
    const code = makeCodeDetails();
    const source = makeSourceDetails();
    expect(isCodeDetails(code)).toBe(true);
    expect(isCodeDetails(source)).toBe(false);
    expect(isSourceDetails(source)).toBe(true);
    expect(isSourceDetails(code)).toBe(false);
  });
});
