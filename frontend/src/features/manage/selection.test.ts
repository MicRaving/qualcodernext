import { describe, expect, it } from "vitest";
import { extendRangeSelection } from "@/features/manage/selection";

// visibleIds: the row order the user sees (current sort/filter order).
const visibleIds = [10, 20, 30, 40, 50, 60];

describe("extendRangeSelection", () => {
  it("selects the range forward from the anchor (add mode)", () => {
    const result = extendRangeSelection(1, 4, new Set(), visibleIds, true);
    expect(result).toEqual(new Set([20, 30, 40, 50]));
  });

  it("selects the range backward from the anchor (add mode)", () => {
    const result = extendRangeSelection(4, 1, new Set(), visibleIds, true);
    expect(result).toEqual(new Set([20, 30, 40, 50]));
  });

  it("add mode unions the range with the existing selection", () => {
    const result = extendRangeSelection(2, 4, new Set([10, 40]), visibleIds, true);
    expect(result).toEqual(new Set([10, 30, 40, 50]));
  });

  it("toggle mode flips each row in the range", () => {
    const result = extendRangeSelection(1, 3, new Set([10, 20, 30, 40]), visibleIds, false);
    expect(result).toEqual(new Set([10]));
  });

  it("a null anchor (plain click) narrows the range to the current row", () => {
    expect(extendRangeSelection(null, 2, new Set([10]), visibleIds, true)).toEqual(
      new Set([10, 30]),
    );
    expect(extendRangeSelection(null, 2, new Set([10, 30]), visibleIds, false)).toEqual(
      new Set([10]),
    );
  });

  it("anchors on the current row when anchor and current coincide", () => {
    expect(extendRangeSelection(3, 3, new Set(), visibleIds, true)).toEqual(new Set([40]));
    expect(extendRangeSelection(3, 3, new Set([10, 40]), visibleIds, false)).toEqual(new Set([10]));
  });

  it("returns an empty set for an empty visible list", () => {
    expect(extendRangeSelection(0, 0, new Set(), [], true)).toEqual(new Set());
  });

  it("leaves the selection untouched when there are no visible rows", () => {
    expect(extendRangeSelection(null, 0, new Set([1, 2]), [], false)).toEqual(new Set([1, 2]));
  });

  it("clamps out-of-range indices to the visible list", () => {
    const result = extendRangeSelection(-1, 99, new Set(), visibleIds, true);
    expect(result).toEqual(new Set(visibleIds));
  });
});
