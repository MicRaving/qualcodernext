import { describe, expect, it } from "vitest";
import {
  formatTime,
  insertTimestampAtCaret,
  secondsToMs,
  segmentLeft,
  segmentWidth,
} from "@/features/coding/media";

describe("formatTime", () => {
  it("formats zero and negative", () => {
    expect(formatTime(0)).toBe("0:00");
    expect(formatTime(-500)).toBe("0:00");
    expect(formatTime(NaN)).toBe("0:00");
  });

  it("formats seconds within a minute", () => {
    expect(formatTime(42000)).toBe("0:42");
    expect(formatTime(84000)).toBe("1:24");
    expect(formatTime(9000)).toBe("0:09");
  });

  it("formats hours", () => {
    expect(formatTime(3725000)).toBe("1:02:05");
    expect(formatTime(3600000)).toBe("1:00:00");
  });
});

describe("secondsToMs", () => {
  it("converts seconds to milliseconds", () => {
    expect(secondsToMs(1.5)).toBe(1500);
    expect(secondsToMs(0)).toBe(0);
  });
});

describe("timeline percent helpers", () => {
  it("computes segment position and width", () => {
    expect(segmentLeft(250, 10000)).toBe(2.5);
    expect(segmentWidth(1000, 3000, 10000)).toBe(20);
  });

  it("clamps out-of-range values", () => {
    expect(segmentLeft(50000, 10000)).toBe(100);
    expect(segmentWidth(1000, 15000, 10000)).toBe(100);
    expect(segmentLeft(-100, 10000)).toBe(0);
    expect(segmentWidth(9000, 12000, 10000)).toBe(30);
  });

  it("handles zero/unknown duration", () => {
    expect(segmentLeft(100, 0)).toBe(0);
    expect(segmentWidth(100, 500, 0)).toBe(0);
  });
});

describe("insertTimestampAtCaret", () => {
  it("inserts into empty text", () => {
    expect(insertTimestampAtCaret("", 0, 0, "[00:05]")).toEqual({
      text: "[00:05] ",
      caret: 8,
    });
  });

  it("starts a new line when the caret is mid-line", () => {
    expect(insertTimestampAtCaret("hello", 5, 5, "[00:05]")).toEqual({
      text: "hello\n[00:05] ",
      caret: 14,
    });
  });

  it("does not double the newline at a line start", () => {
    expect(insertTimestampAtCaret("a\nb", 2, 2, "[00:05]")).toEqual({
      text: "a\n[00:05] b",
      caret: 10,
    });
  });

  it("replaces the current selection", () => {
    expect(insertTimestampAtCaret("hello world", 5, 11, "[00:05]")).toEqual({
      text: "hello\n[00:05] ",
      caret: 14,
    });
  });

  it("places the caret directly after the timestamp", () => {
    expect(insertTimestampAtCaret("a [00:01] b", 10, 10, "[02:00]")).toEqual({
      text: "a [00:01] \n[02:00] b",
      caret: 19,
    });
  });
});
