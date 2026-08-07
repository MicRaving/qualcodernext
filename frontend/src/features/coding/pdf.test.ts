import { describe, expect, it } from "vitest";
import type { ImageCoding } from "@/lib/api";
import {
  buildPageOverlays,
  canvasToPage,
  clampRect,
  DEFAULT_CODING_COLOR,
  pageToCanvas,
} from "@/features/coding/pdf";

const COLORS = new Map<number, string>([
  [1, "#ff0000"],
  [2, "#00ff00"],
]);

function coding(imid: number, cid: number, page: number | null, extra: Partial<ImageCoding> = {}): ImageCoding {
  return {
    imid,
    id: 7,
    x1: 0,
    y1: 0,
    width: 100,
    height: 50,
    cid,
    memo: "",
    date: "",
    owner: "default",
    important: 0,
    pdf_page: page,
    ...extra,
  };
}

describe("pageToCanvas / canvasToPage", () => {
  it("scales page-space points up to canvas pixels", () => {
    expect(pageToCanvas({ x: 100, y: 200 }, 1.5)).toEqual({ x: 150, y: 300 });
  });

  it("scales canvas pixels back down to page space", () => {
    expect(canvasToPage({ x: 150, y: 300 }, 1.5)).toEqual({ x: 100, y: 200 });
  });

  it("round-trips through a scale change", () => {
    const p = { x: 37.5, y: 12.25 };
    expect(canvasToPage(pageToCanvas(p, 0.75), 0.75)).toEqual(p);
  });
});

describe("buildPageOverlays", () => {
  it("keeps only codings on the requested page and scales coordinates", () => {
    const overlays = buildPageOverlays(
      [
        coding(1, 1, 2),
        coding(2, 2, 1, { x1: 10, y1: 20, width: 30, height: 40 }),
        coding(3, 1, null),
      ],
      1,
      2,
      COLORS,
    );
    expect(overlays).toEqual([
      {
        key: 2,
        left: 20,
        top: 40,
        width: 60,
        height: 80,
        color: "#00ff00",
        coding: expect.objectContaining({ imid: 2 }),
      },
    ]);
  });

  it("sorts by imid regardless of input order", () => {
    const overlays = buildPageOverlays(
      [coding(3, 1, 1), coding(1, 1, 1), coding(2, 1, 1)],
      1,
      1,
      COLORS,
    );
    expect(overlays.map((o) => o.key)).toEqual([1, 2, 3]);
  });

  it("falls back to a neutral color for unknown cids", () => {
    const overlays = buildPageOverlays([coding(1, 99, 1)], 1, 1, COLORS);
    expect(overlays[0].color).toBe(DEFAULT_CODING_COLOR);
  });
});

describe("clampRect", () => {
  it("normalizes a reversed drag", () => {
    expect(clampRect({ x: 50, y: 60 }, { x: 10, y: 20 })).toEqual({
      x1: 10,
      y1: 20,
      x2: 50,
      y2: 60,
    });
  });

  it("clamps negative coordinates to zero", () => {
    expect(clampRect({ x: -10, y: 5 }, { x: 30, y: -20 })).toEqual({
      x1: 0,
      y1: 0,
      x2: 30,
      y2: 5,
    });
  });
});
