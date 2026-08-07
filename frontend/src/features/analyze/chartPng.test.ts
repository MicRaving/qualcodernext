import { describe, expect, it } from "vitest";
import { chartLayout, type ChartRow } from "@/features/analyze/chartPng";

const WIDTH = 900;
const HEIGHT = 520;

describe("chartLayout", () => {
  it("lays out three rows with bar widths proportional to maxCount", () => {
    const rows: ChartRow[] = [
      { name: "Alpha", color: "#ff0000", count: 10 },
      { name: "Beta", color: "#00ff00", count: 5 },
      { name: "Gamma", color: "#0000ff", count: 2 },
    ];
    const layout = chartLayout(rows, WIDTH, HEIGHT);
    expect(layout.maxCount).toBe(10);
    expect(layout.bars).toHaveLength(3);
    expect(layout.bars[0].w).toBe(layout.barAreaWidth);
    expect(layout.bars[1].w).toBeCloseTo(layout.barAreaWidth * 0.5);
    expect(layout.bars[2].w).toBeCloseTo(layout.barAreaWidth * 0.2);
  });

  it("keeps rowHeight at least 26 even for many rows", () => {
    const rows: ChartRow[] = Array.from({ length: 50 }, (_, i) => ({
      name: `Code ${i}`,
      color: null,
      count: i + 1,
    }));
    const layout = chartLayout(rows, WIDTH, HEIGHT);
    expect(layout.rowHeight).toBeGreaterThanOrEqual(26);
  });

  it("bounds labelWidth to at most 280px", () => {
    const rows: ChartRow[] = Array.from({ length: 3 }, (_, i) => ({
      name: "x".repeat(80),
      color: null,
      count: i + 1,
    }));
    const layout = chartLayout(rows, WIDTH, HEIGHT);
    expect(layout.labelWidth).toBeLessThanOrEqual(280);
  });

  it("returns an empty bars array and maxCount 0 for empty rows", () => {
    const layout = chartLayout([], WIDTH, HEIGHT);
    expect(layout.bars).toEqual([]);
    expect(layout.maxCount).toBe(0);
    expect(layout.total).toBe(0);
    expect(layout.rowHeight).toBe(0);
  });

  it("fills the full bar area width for a single row", () => {
    const layout = chartLayout([{ name: "Solo", color: "#123456", count: 7 }], WIDTH, HEIGHT);
    expect(layout.bars).toHaveLength(1);
    expect(layout.bars[0].w).toBe(layout.barAreaWidth);
  });

  it("sums counts into total", () => {
    const layout = chartLayout(
      [
        { name: "A", color: null, count: 3 },
        { name: "B", color: null, count: 0 },
        { name: "C", color: null, count: 11 },
      ],
      WIDTH,
      HEIGHT,
    );
    expect(layout.total).toBe(14);
  });

  it("falls back to the default color when a row has no color", () => {
    const layout = chartLayout([{ name: "Grey", color: null, count: 4 }], WIDTH, HEIGHT);
    expect(layout.bars[0].color).toBe("#9a9ab0");
    expect(layout.bars[0].w).toBe(layout.barAreaWidth);
  });

  it("preserves the given row order and centers bars within their rows", () => {
    const rows: ChartRow[] = [
      { name: "First", color: null, count: 1 },
      { name: "Second", color: null, count: 9 },
      { name: "Third", color: null, count: 4 },
    ];
    const layout = chartLayout(rows, WIDTH, HEIGHT);
    expect(layout.bars.map((b) => b.label)).toEqual(["First", "Second", "Third"]);
    const expectedY = layout.top + (layout.rowHeight - layout.bars[0].h) / 2;
    expect(layout.bars[0].y).toBeCloseTo(expectedY);
    expect(layout.bars[1].y).toBeCloseTo(layout.top + layout.rowHeight + (layout.rowHeight - layout.bars[1].h) / 2);
  });
});
