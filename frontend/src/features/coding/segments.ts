/**
 * Pure segment math for the text coder: converts [pos0, pos1) ranges into
 * disjoint atomic intervals covered by a set of codings/annotations.
 * Kept DOM-free so it is trivially unit-testable.
 */

export interface CodingRange {
  ctid: number;
  cid: number;
  pos0: number;
  pos1: number;
}

export interface AnnotationRange {
  anid: number;
  pos0: number;
  pos1: number;
}

export interface RenderedSegment {
  start: number;
  end: number;
  /** Colors of the covering codings (deterministic order, by ctid). */
  colors: string[];
  ctids: number[];
}

export interface AnnotationSegment {
  start: number;
  end: number;
  anids: number[];
}

interface RangeLike {
  pos0: number;
  pos1: number;
}

/**
 * Split `text` into atomic intervals covered by at least one coding.
 * Intervals are sorted by start; a position covered by several codings
 * yields a single segment carrying all colors/ctids (nested-span rendering).
 * Ranges are clamped to the text and invalid/empty ones dropped.
 */
export function buildRenderedSegments(
  text: string,
  codings: CodingRange[],
  colors: Record<number, string>,
): RenderedSegment[] {
  const len = text.length;
  const valid = clampAndFilter(codings, len);
  const ranges = atomicIntervals(valid);
  const out: RenderedSegment[] = [];
  for (const [start, end] of ranges) {
    const covering = coveringRanges(valid, start, end);
    if (covering.length === 0) continue;
    const sorted = [...covering].sort((a, b) => a.ctid - b.ctid);
    out.push({
      start,
      end,
      colors: sorted
        .map((c) => colors[c.cid])
        .filter((c): c is string => Boolean(c)),
      ctids: sorted.map((c) => c.ctid),
    });
  }
  return out;
}

/** Same atomic-interval math for annotations (underline layer). */
export function buildAnnotationSegments(
  text: string,
  annotations: AnnotationRange[],
): AnnotationSegment[] {
  const len = text.length;
  const valid = clampAndFilter(annotations, len);
  const ranges = atomicIntervals(valid);
  const out: AnnotationSegment[] = [];
  for (const [start, end] of ranges) {
    const covering = coveringRanges(valid, start, end);
    if (covering.length === 0) continue;
    const sorted = [...covering].sort((a, b) => a.anid - b.anid);
    out.push({ start, end, anids: sorted.map((a) => a.anid) });
  }
  return out;
}

function clampAndFilter<T extends RangeLike>(ranges: T[], len: number): T[] {
  return ranges
    .map((r) => ({
      ...r,
      pos0: Math.max(0, Math.min(len, r.pos0)),
      pos1: Math.max(0, Math.min(len, r.pos1)),
    }))
    .filter((r) => r.pos1 > r.pos0);
}

/** Sorted boundary points of all ranges (start of each atomic interval). */
function atomicIntervals<T extends RangeLike>(ranges: T[]): [number, number][] {
  const points = new Set<number>([0, ...ranges.map((r) => r.pos0), ...ranges.map((r) => r.pos1)]);
  const sorted = [...points].sort((a, b) => a - b);
  const out: [number, number][] = [];
  for (let i = 0; i + 1 < sorted.length; i++) {
    out.push([sorted[i], sorted[i + 1]]);
  }
  return out;
}

function coveringRanges<T extends RangeLike>(ranges: T[], start: number, end: number): T[] {
  return ranges.filter((r) => r.pos0 <= start && r.pos1 >= end);
}
