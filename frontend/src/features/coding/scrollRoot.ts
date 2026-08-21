/** Cross-realm safe scroll-root helpers.
 *
 * An iframe's `contentDocument` comes from another JS realm, so
 * `instanceof Document` is false even though the object IS a Document.
 * `nodeType === 9` (Node.DOCUMENT_NODE) works across realms, so all
 * Document detection goes through these predicates.
 */

export function isDocumentNode(root: unknown): root is Document {
  return (
    typeof root === "object" && root !== null && (root as Node).nodeType === 9
  );
}

/** Resolve the scrolling element for an Element or Document scroll root. */
export function scrollElementOf(root: HTMLElement | Document): HTMLElement {
  if (isDocumentNode(root)) {
    return (root.scrollingElement ?? root.documentElement) as HTMLElement;
  }
  return root;
}

/** Resolve the content height of an Element or Document root. */
export function contentHeightOf(root: HTMLElement | Document): number {
  if (isDocumentNode(root)) {
    const se = root.scrollingElement ?? root.documentElement;
    return se.scrollHeight;
  }
  return root.scrollHeight;
}