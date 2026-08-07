import { describe, expect, it } from "vitest";
import { formatTime, secondsToMs, segmentLeft, segmentWidth } from "@/features/coding/media";

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
