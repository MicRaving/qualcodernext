import { describe, expect, it } from "vitest";
import { buildAnnotationSegments, buildRenderedSegments } from "@/features/coding/segments";

const TEXT = "abcdefghij"; // length 10
const COLORS: Record<number, string> = { 1: "#111111", 2: "#222222" };

describe("buildRenderedSegments", () => {
  it("produces sorted atomic segments for non-overlapping codings", () => {
    const segs = buildRenderedSegments(
      TEXT,
      [
        { ctid: 1, cid: 1, pos0: 0, pos1: 3 },
        { ctid: 2, cid: 2, pos0: 5, pos1: 7 },
      ],
      COLORS,
    );
    expect(segs).toEqual([
      { start: 0, end: 3, colors: ["#111111"], ctids: [1] },
      { start: 5, end: 7, colors: ["#222222"], ctids: [2] },
    ]);
  });

  it("splits overlapping codings into atomic intervals", () => {
    const segs = buildRenderedSegments(
      TEXT,
      [
        { ctid: 1, cid: 1, pos0: 2, pos1: 8 },
        { ctid: 2, cid: 2, pos0: 4, pos1: 6 },
      ],
      COLORS,
    );
    expect(segs).toEqual([
      { start: 2, end: 4, colors: ["#111111"], ctids: [1] },
      { start: 4, end: 6, colors: ["#111111", "#222222"], ctids: [1, 2] },
      { start: 6, end: 8, colors: ["#111111"], ctids: [1] },
    ]);
  });

  it("sorts out-of-order input by start", () => {
    const segs = buildRenderedSegments(
      TEXT,
      [
        { ctid: 2, cid: 2, pos0: 5, pos1: 7 },
        { ctid: 1, cid: 1, pos0: 0, pos1: 3 },
      ],
      COLORS,
    );
    expect(segs.map((s) => s.start)).toEqual([0, 5]);
    expect(segs.map((s) => s.ctids)).toEqual([[1], [2]]);
  });

  it("clamps ranges to the text length and drops empty ones", () => {
    const segs = buildRenderedSegments(
      "abc",
      [
        { ctid: 1, cid: 1, pos0: 1, pos1: 99 },
        { ctid: 2, cid: 2, pos0: 2, pos1: 2 },
        { ctid: 3, cid: 3, pos0: -1, pos1: 2 },
      ],
      { ...COLORS, 3: "#333333" },
    );
    expect(segs).toEqual([
      { start: 0, end: 1, colors: ["#333333"], ctids: [3] },
      { start: 1, end: 2, colors: ["#111111", "#333333"], ctids: [1, 3] },
      { start: 2, end: 3, colors: ["#111111"], ctids: [1] },
    ]);
  });

  it("omits colors for codes without a color entry", () => {
    const segs = buildRenderedSegments(
      "abc",
      [{ ctid: 1, cid: 9, pos0: 0, pos1: 2 }],
      COLORS,
    );
    expect(segs).toEqual([{ start: 0, end: 2, colors: [], ctids: [1] }]);
  });
});

describe("buildAnnotationSegments", () => {
  it("splits overlapping annotations atomically", () => {
    const segs = buildAnnotationSegments("abcdef", [
      { anid: 1, pos0: 1, pos1: 5 },
      { anid: 2, pos0: 2, pos1: 3 },
    ]);
    expect(segs).toEqual([
      { start: 1, end: 2, anids: [1] },
      { start: 2, end: 3, anids: [1, 2] },
      { start: 3, end: 5, anids: [1] },
    ]);
  });
});
