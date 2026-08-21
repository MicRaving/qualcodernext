/**
 * Shared floating-toolbar anchoring: viewport clamping + dismissal on
 * scroll/blur — previously duplicated verbatim in TextCoder and CsvCoder
 * (with a third variant in HtmlCoder).
 */
import { useEffect } from "react";

/** Clamp a popup position so it stays inside the scroll container. */
export function clampToolbarAnchor(
  rect: DOMRect,
  scrollRect: DOMRect | undefined,
): { left: number; top: number } {
  const left = scrollRect
    ? Math.min(Math.max(rect.left, scrollRect.left + 4), scrollRect.right - 300)
    : rect.left;
  const top = scrollRect ? Math.min(rect.bottom + 6, scrollRect.bottom - 40) : rect.bottom + 6;
  return { left, top };
}

/** Hide the toolbar when the document scrolls or the window loses focus. */
export function useToolbarDismiss(onDismiss: () => void, active: boolean): void {
  useEffect(() => {
    if (!active) return;
    const hide = () => onDismiss();
    window.addEventListener("scroll", hide, true);
    window.addEventListener("blur", hide);
    return () => {
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("blur", hide);
    };
  }, [onDismiss, active]);
}
