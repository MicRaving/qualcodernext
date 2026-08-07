/**
 * Windowing math for the FileManager table.
 *
 * Performance note: only the rows in [start, end) are ever mounted; the
 * table body keeps its full height via top/bottom spacer rows, so the DOM
 * stays O(visible) regardless of how many files the project holds.
 */

/** Fixed height (px) of one FileManager row. */
export const ROW_HEIGHT = 36;

/**
 * Compute the window of rows to render for a given scroll position.
 *
 * Returns a half-open range [start, end); both bounds are clamped to
 * [0, total] and end is exclusive. The window covers the rows currently in
 * the viewport plus `overscan` extra rows above (so fast upward scrolling
 * never flashes empty space).
 */
export function visibleRange(
  scrollTop: number,
  viewportHeight: number,
  total: number,
  overscan = 10,
): { start: number; end: number } {
  if (total <= 0) return { start: 0, end: 0 };
  const visibleCount = Math.ceil(viewportHeight / ROW_HEIGHT) + overscan;
  const firstVisible = Math.floor(scrollTop / ROW_HEIGHT);
  const start = Math.max(0, Math.min(total - 1, firstVisible - overscan));
  const end = Math.min(total, start + visibleCount);
  return { start, end };
}
