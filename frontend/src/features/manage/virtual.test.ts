import { describe, expect, it } from "vitest";
import { ROW_HEIGHT, visibleRange } from "@/features/manage/virtual";

describe("visibleRange", () => {
  it("returns the full range when the viewport fits every row at scrollTop 0", () => {
    expect(visibleRange(0, 5000, 50)).toEqual({ start: 0, end: 50 });
  });

  it("windows around the scroll position with overscan above", () => {
    // scrollTop 720 = row 20 of 36px rows; 10 rows fit in a 360px viewport.
    expect(visibleRange(720, 360, 1000)).toEqual({ start: 10, end: 30 });
  });

  it("clamps the window to the bottom of the list", () => {
    expect(visibleRange(999999, 360, 100)).toEqual({ start: 99, end: 100 });
  });

  it("widens the window when overscan increases", () => {
    const tight = visibleRange(360, 360, 1000, 0);
    const wide = visibleRange(360, 360, 1000, 5);
    expect(tight).toEqual({ start: 10, end: 20 });
    expect(wide.start).toBe(5);
    expect(wide.end - wide.start).toBeGreaterThan(tight.end - tight.start);
  });

  it("never goes negative for overscroll past the top", () => {
    expect(visibleRange(-100, 360, 1000).start).toBe(0);
  });

  it("returns an empty range when the list is empty", () => {
    expect(visibleRange(0, 360, 0)).toEqual({ start: 0, end: 0 });
    expect(visibleRange(500, 360, 0)).toEqual({ start: 0, end: 0 });
  });

  it("exposes a positive ROW_HEIGHT of 36px", () => {
    expect(ROW_HEIGHT).toBe(36);
    expect(ROW_HEIGHT).toBeGreaterThan(0);
  });
});
