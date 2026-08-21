import { describe, expect, it } from "vitest";
import { layoutGutterCards, stackRows, type GutterCardEntry } from "./memoLayout";

describe("layoutGutterCards", () => {
  it("returns empty map for no input", () => {
    expect(layoutGutterCards([])).toEqual(new Map());
  });

  it("places a single card at its desiredY", () => {
    const entries: GutterCardEntry[] = [{ id: 1, desiredY: 100, height: 40 }];
    const result = layoutGutterCards(entries);
    expect(result.get(1)).toBe(100);
  });

  it("does not overlap cards", () => {
    const entries: GutterCardEntry[] = [
      { id: 1, desiredY: 100, height: 40 },
      { id: 2, desiredY: 110, height: 40 }, // overlaps with card 1
    ];
    const result = layoutGutterCards(entries);
    expect(result.get(1)).toBe(100);
    expect(result.get(2)).toBe(148); // 100 + 40 + 8 gap
  });

  it("pushes down multiple overlapping cards", () => {
    const entries: GutterCardEntry[] = [
      { id: 1, desiredY: 100, height: 40 },
      { id: 2, desiredY: 105, height: 40 },
      { id: 3, desiredY: 110, height: 40 },
    ];
    const result = layoutGutterCards(entries);
    expect(result.get(1)).toBe(100);
    expect(result.get(2)).toBe(148);
    expect(result.get(3)).toBe(196);
  });

  it("respects custom gap", () => {
    const entries: GutterCardEntry[] = [
      { id: 1, desiredY: 100, height: 40 },
      { id: 2, desiredY: 110, height: 40 },
    ];
    const result = layoutGutterCards(entries, 16);
    expect(result.get(1)).toBe(100);
    expect(result.get(2)).toBe(156); // 100 + 40 + 16 gap
  });

  it("sorts by desiredY then by id", () => {
    const entries: GutterCardEntry[] = [
      { id: 2, desiredY: 100, height: 40 },
      { id: 1, desiredY: 100, height: 40 },
    ];
    const result = layoutGutterCards(entries);
    expect(result.get(1)).toBe(100);
    expect(result.get(2)).toBe(148);
  });

  it("handles non-overlapping cards", () => {
    const entries: GutterCardEntry[] = [
      { id: 1, desiredY: 100, height: 40 },
      { id: 2, desiredY: 200, height: 40 },
      { id: 3, desiredY: 300, height: 40 },
    ];
    const result = layoutGutterCards(entries);
    expect(result.get(1)).toBe(100);
    expect(result.get(2)).toBe(200);
    expect(result.get(3)).toBe(300);
  });
});

describe("stackRows", () => {
  it("returns empty array for no input", () => {
    expect(stackRows([])).toEqual([]);
  });

  it("groups rows with same y", () => {
    const entries = [
      { y: 100, id: 1 },
      { y: 100, id: 2 },
      { y: 100, id: 3 },
    ];
    const result = stackRows(entries);
    expect(result).toHaveLength(1);
    expect(result[0]).toHaveLength(3);
  });

  it("separates rows with different y beyond tolerance", () => {
    const entries = [
      { y: 100, id: 1 },
      { y: 200, id: 2 },
      { y: 300, id: 3 },
    ];
    const result = stackRows(entries);
    expect(result).toHaveLength(3);
    expect(result[0]).toHaveLength(1);
    expect(result[1]).toHaveLength(1);
    expect(result[2]).toHaveLength(1);
  });

  it("groups rows within tolerance", () => {
    const entries = [
      { y: 100, id: 1 },
      { y: 101, id: 2 },
      { y: 102, id: 3 },
    ];
    const result = stackRows(entries, 2);
    expect(result).toHaveLength(1);
    expect(result[0]).toHaveLength(3);
  });

  it("separates rows beyond tolerance", () => {
    const entries = [
      { y: 100, id: 1 },
      { y: 103, id: 2 },
      { y: 106, id: 3 },
    ];
    const result = stackRows(entries, 2);
    expect(result).toHaveLength(3);
  });

  it("sorts by y", () => {
    const entries = [
      { y: 300, id: 3 },
      { y: 100, id: 1 },
      { y: 200, id: 2 },
    ];
    const result = stackRows(entries);
    expect(result[0][0].y).toBe(100);
    expect(result[1][0].y).toBe(200);
    expect(result[2][0].y).toBe(300);
  });

  it("preserves order within stack", () => {
    const entries = [
      { y: 100, id: 2 },
      { y: 100, id: 1 },
      { y: 100, id: 3 },
    ];
    const result = stackRows(entries);
    expect(result[0].map((e) => e.id)).toEqual([2, 1, 3]);
  });
});
