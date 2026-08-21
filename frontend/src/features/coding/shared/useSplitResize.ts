/**
 * Shared split-pane resize drag (the horizontal text-pane width in
 * Pdf/HtmlCoder and the vertical video height in AvCoder were three
 * identical mousemove/mouseup effects).
 *
 * Returns the current size, the dragging flag and a mousedown handler that
 * starts the drag from the current size. The size is clamped to
 * [min, maxOf(container)] on every move; `containerSize` measures the
 * flex container along the drag axis when provided.
 */
import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";

export interface SplitResizeOptions {
  axis: "x" | "y";
  min: number;
  max: number;
  initial: number;
  /** Current container width/height for ratio clamps — re-read per move. */
  containerSize?: () => number | undefined;
  /** Fraction of the container the pane may occupy (default 0.7). */
  maxFraction?: number;
}

export function useSplitResize(opts: SplitResizeOptions): {
  size: number;
  dragging: boolean;
  onDown: (e: ReactMouseEvent) => void;
} {
  const { axis, min, max, initial, containerSize, maxFraction = 0.7 } = opts;
  const [size, setSize] = useState(initial);
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{ startPos: number; startSize: number } | null>(null);

  function onDown(e: ReactMouseEvent) {
    e.preventDefault();
    dragRef.current = {
      startPos: axis === "x" ? e.clientX : e.clientY,
      startSize: size,
    };
    setDragging(true);
  }

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const pos = axis === "x" ? e.clientX : e.clientY;
      let upper = max;
      if (containerSize) {
        const c = containerSize();
        if (c != null) upper = Math.min(upper, Math.round(c * maxFraction));
      }
      setSize(Math.min(upper, Math.max(min, Math.round(drag.startSize + (pos - drag.startPos)))));
    };
    const onUp = () => {
      dragRef.current = null;
      setDragging(false);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging, axis, min, max, maxFraction, containerSize]);

  return { size, dragging, onDown };
}
