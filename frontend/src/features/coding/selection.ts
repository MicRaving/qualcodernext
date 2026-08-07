/**
 * Character-offset extraction from a DOM selection relative to a container
 * element. The container's text content must equal the logical document
 * text (spans only wrap text, never add any).
 */

export interface SelectionOffsets {
  start: number;
  end: number;
}

/** Total character length of all text inside `node` (recursive). */
function textLength(node: Node): number {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent?.length ?? 0;
  let total = 0;
  for (let i = 0; i < node.childNodes.length; i++) {
    total += textLength(node.childNodes[i]);
  }
  return total;
}

/**
 * Character offset of the point (target, targetOffset) within `node`, or
 * null when `target` is not inside `node`. For element targets the offset
 * is a child index and is converted to a character offset by summing the
 * text length of preceding children.
 */
function offsetWithin(node: Node, target: Node, targetOffset: number): number | null {
  if (node === target) {
    if (node.nodeType === Node.TEXT_NODE) return targetOffset;
    let total = 0;
    for (let i = 0; i < Math.min(targetOffset, node.childNodes.length); i++) {
      total += textLength(node.childNodes[i]);
    }
    return total;
  }
  let total = 0;
  for (let i = 0; i < node.childNodes.length; i++) {
    const child = node.childNodes[i];
    const hit = offsetWithin(child, target, targetOffset);
    if (hit !== null) return total + hit;
    total += textLength(child);
  }
  return null;
}

/**
 * Compute the [start, end) character offsets of `selection` relative to
 * `container`. Returns null when the selection is collapsed, empty, or
 * lies outside the container.
 */
export function getSelectionOffsets(
  container: HTMLElement,
  selection: Selection | null,
): SelectionOffsets | null {
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
  const range = selection.getRangeAt(0);
  const root = range.commonAncestorContainer;
  if (root !== container && !container.contains(root)) return null;
  const start = offsetWithin(container, range.startContainer, range.startOffset);
  const end = offsetWithin(container, range.endContainer, range.endOffset);
  if (start === null || end === null) return null;
  const a = Math.min(start, end);
  const b = Math.max(start, end);
  if (a === b) return null;
  return { start: a, end: b };
}
