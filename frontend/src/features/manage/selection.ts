/**
 * Pure range-selection logic for multi-select lists (files table).
 *
 * `anchor` and `current` are INDICES into `visibleIds` — the rows in the
 * order the user actually sees them (the current sort/filter order). The
 * range covers every id from the anchor row to the current row, inclusive,
 * so a range always follows the visible order even if the user re-sorts.
 * A null anchor (no row directly clicked yet) narrows the range to the
 * single current row. `add` selects the range rows (union with the existing
 * selection); `false` toggles each range row individually.
 */
export function extendRangeSelection(
  anchor: number | null,
  current: number,
  selected: ReadonlySet<number>,
  visibleIds: readonly number[],
  add: boolean,
): Set<number> {
  const result = new Set(selected);
  if (visibleIds.length === 0) return result;
  const from = anchor ?? current;
  const lo = Math.max(0, Math.min(from, current));
  const hi = Math.min(visibleIds.length - 1, Math.max(from, current));
  for (let i = lo; i <= hi; i++) {
    const id = visibleIds[i];
    if (add) {
      result.add(id);
    } else if (result.has(id)) {
      result.delete(id);
    } else {
      result.add(id);
    }
  }
  return result;
}
