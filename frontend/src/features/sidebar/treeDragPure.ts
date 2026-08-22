/**
 * Pure tree-drag geometry + cycle guards. Extracted from
 * components/shell/Sidebar.tsx — behavior-neutral (these functions close
 * over nothing; all inputs are parameters).
 */
import type { CodeTreeItem } from "@/lib/api";
import type { DragNode, DropZone } from "@/features/sidebar/types";

/** A category can only nest in categories; a code nests in a category or
 *  as a sub-code — never under its own descendant (cycle guard). */
export function canDropInto(drag: DragNode, target: CodeTreeItem): boolean {
  if (drag.kind === "category" && target.kind !== "category") return false;
  return !drag.subtree.has(`${target.kind}:${target.id}`);
}

/** before/after land in the target's sibling group — only same-kind rows
 *  can anchor a sibling slot, and never inside the dragged node's own
 *  subtree (the backend would reject that cycle anyway). */
export function canOrderSibling(drag: DragNode, target: CodeTreeItem): boolean {
  if (drag.kind !== target.kind) return false;
  return !drag.subtree.has(`${target.kind}:${target.id}`);
}

/** Merge-onto needs a same-kind target outside the dragged subtree. */
export function canDropMerge(drag: DragNode, target: CodeTreeItem): boolean {
  if (drag.kind !== target.kind) return false;
  return !drag.subtree.has(`${target.kind}:${target.id}`);
}

/** Resolve the drop zone from the pointer position: the top/bottom bands
 *  give the before/after insertion lines, the left indent gutter gives
 *  the "into" (make child) zone, the row body gives the merge target.
 *  Must run inside the event handler itself: React nulls the synthetic
 *  event's ``currentTarget`` once the handler returns, so calling this
 *  from a state-updater callback (which runs at render time) would read
 *  a null rect and crash the tree. */
export function computeDropZone(
  rect: DOMRect,
  clientX: number,
  clientY: number,
  item: CodeTreeItem,
  depth: number,
  drag: DragNode,
): DropZone | null {
  if (drag.kind === item.kind && drag.id === item.id) return null;
  const y = (clientY - rect.top) / Math.max(1, rect.height);
  const x = clientX - rect.left;
  const key = `${item.kind}:${item.id}`;
  if (y < 0.25) return canOrderSibling(drag, item) ? { mode: "before", key } : null;
  if (y > 0.75) return canOrderSibling(drag, item) ? { mode: "after", key } : null;
  if (x < 8 + depth * 16 + 28) {
    return canDropInto(drag, item) ? { mode: "into", key } : null;
  }
  return canDropMerge(drag, item) ? { mode: "merge", key } : null;
}
