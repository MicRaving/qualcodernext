import { describe, expect, it } from "vitest";
import {
  barWidth,
  fileTypeLabel,
  formatCount,
  matrixCell,
} from "@/features/analyze/reportHelpers";

describe("barWidth", () => {
  it("returns 0% when max is zero or negative", () => {
    expect(barWidth(5, 0)).toBe("0%");
    expect(barWidth(0, 0)).toBe("0%");
    expect(barWidth(3, -2)).toBe("0%");
  });

  it("returns 100% for the maximum count", () => {
    expect(barWidth(8, 8)).toBe("100%");
  });

  it("rounds to the nearest percent", () => {
    expect(barWidth(1, 3)).toBe("33%");
    expect(barWidth(1, 6)).toBe("17%");
  });

  it("returns 0% for a zero count against a positive max", () => {
    expect(barWidth(0, 10)).toBe("0%");
  });
});

describe("fileTypeLabel", () => {
  it("reports PDF when the name ends in .pdf, regardless of media type", () => {
    expect(fileTypeLabel("report.pdf", "text")).toBe("PDF");
    expect(fileTypeLabel("REPORT.PDF", "image")).toBe("PDF");
  });

  it("capitalizes the media type otherwise", () => {
    expect(fileTypeLabel("photo.jpg", "image")).toBe("Image");
    expect(fileTypeLabel("clip.mp4", "video")).toBe("Video");
    expect(fileTypeLabel("recording.wav", "audio")).toBe("Audio");
    expect(fileTypeLabel("notes.txt", "text")).toBe("Text");
  });
});

describe("matrixCell", () => {
  it("renders a dash for zero counts", () => {
    expect(matrixCell(0)).toBe("—");
  });

  it("stringifies positive counts", () => {
    expect(matrixCell(1)).toBe("1");
    expect(matrixCell(42)).toBe("42");
  });
});

describe("formatCount", () => {
  it("formats thousands with separators", () => {
    expect(formatCount(12345)).toBe("12,345");
    expect(formatCount(1000000)).toBe("1,000,000");
  });

  it("leaves small numbers unformatted", () => {
    expect(formatCount(7)).toBe("7");
    expect(formatCount(0)).toBe("0");
  });
});
