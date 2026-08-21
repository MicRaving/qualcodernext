/**
 * Pure layout solver for the memo gutter.
 *
 * Given the desired (anchor) Y of each card and its rendered height, resolve
 * a collision-free Y for every card: the first card at each position stays
 * exactly at its anchor, later cards are nudged down by the minimum amount
 * needed to keep a constant gap. Kept pure and framework-free so the
 * placement rules are unit-testable.
 */

export interface GutterCardEntry {
  id: number;
  /** Vertical position of the coded segment (document coordinates). */
  desiredY: number;
  /** Rendered height of the card at this Y (collapsed vs expanded). */
  height: number;
}

/** Resolve a collision-free Y per card id, or an empty map for no input. */
export function layoutGutterCards(
  entries: GutterCardEntry[],
  gap = 8,
): Map<number, number> {
  if (entries.length === 0) return new Map();
  const sorted = entries.slice().sort((a, b) => a.desiredY - b.desiredY || a.id - b.id);
  const out = new Map<number, number>();
  let cursor = -Infinity;
  for (const e of sorted) {
    const y = Math.max(e.desiredY, cursor + gap);
    out.set(e.id, y);
    cursor = y + e.height;
  }
  return out;
}

/**
 * Group rows that share (nearly) the same anchor Y into vertical stacks, so
 * co-located codings (several codings on one rendered span) render as a
 * tight stack rather than being spread far from their segment. Consecutive
 * entries whose anchor differs by at most `tolerance` px belong to one stack.
 */
export function stackRows<T extends { y: number }>(entries: T[], tolerance = 2): T[][] {
  const sorted = entries.slice().sort((a, b) => a.y - b.y);
  const stacks: T[][] = [];
  for (const e of sorted) {
    const last = stacks[stacks.length - 1];
    if (last && e.y - last[0].y <= tolerance) {
      last.push(e);
    } else {
      stacks.push([e]);
    }
  }
  return stacks;
}