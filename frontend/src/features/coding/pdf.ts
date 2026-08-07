/**
 * Pure coordinate/overlay math for the PDF coder. No DOM, no pdf.js imports
 * so it is trivially unit-testable.
 */

import type { ImageCoding } from "@/lib/api";

/** Neutral fallback used when a coding references a missing code color. */
export const DEFAULT_CODING_COLOR = "rgba(0,0,0,0.15)";

export interface PagePoint {
  x: number;
  y: number;
}

export interface NormalizedRect {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface PageOverlay {
  /** imid of the coding, used as the React key. */
  key: number;
  left: number;
  top: number;
  width: number;
  height: number;
  color: string;
  coding: ImageCoding;
}

/** Convert a page-space (PDF points) point to canvas pixels at `scale`. */
export function pageToCanvas(p: PagePoint, scale: number): PagePoint {
  return { x: p.x * scale, y: p.y * scale };
}

/** Convert a canvas-pixel point back to page space (PDF points). */
export function canvasToPage(p: PagePoint, scale: number): PagePoint {
  return { x: p.x / scale, y: p.y / scale };
}

/**
 * Build the overlay rectangles for one page: only codings whose
 * `pdf_page` matches, coordinates scaled to canvas pixels, sorted by imid.
 * Codings referencing an unknown cid get `DEFAULT_CODING_COLOR`.
 */
export function buildPageOverlays(
  codings: ImageCoding[],
  pageNumber: number,
  scale: number,
  colors: Map<number, string>,
): PageOverlay[] {
  return codings
    .filter((c) => c.pdf_page === pageNumber)
    .sort((a, b) => a.imid - b.imid)
    .map((c) => ({
      key: c.imid,
      left: c.x1 * scale,
      top: c.y1 * scale,
      width: c.width * scale,
      height: c.height * scale,
      color: colors.get(c.cid) ?? DEFAULT_CODING_COLOR,
      coding: c,
    }));
}

/**
 * Normalize a drag rectangle (start/end are page-space points) so x1<=x2,
 * y1<=y2, and all coordinates are >= 0.
 */
export function clampRect(start: PagePoint, end: PagePoint): NormalizedRect {
  return {
    x1: Math.max(0, Math.min(start.x, end.x)),
    y1: Math.max(0, Math.min(start.y, end.y)),
    x2: Math.max(0, Math.max(start.x, end.x)),
    y2: Math.max(0, Math.max(start.y, end.y)),
  };
}
