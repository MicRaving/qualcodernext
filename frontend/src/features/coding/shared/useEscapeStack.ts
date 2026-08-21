/**
 * Layered Escape dismissal for coders.
 *
 * Each entry is a "layer closer": it returns TRUE when it was open and has
 * been closed (the event is consumed), FALSE when that layer was already
 * inert. The handler walks the layers innermost-first and stops at the
 * first one that handled the key — replacing the six divergent per-coder
 * keydown handlers (one of which, AvCoder's transcript popovers, could not
 * be dismissed with Escape at all).
 *
 * Pass the closers in DISMISSAL ORDER (topmost popover first). The array is
 * read through a ref, so inline closures are safe and the listener never
 * re-subscribes.
 */
import { useEffect, useRef } from "react";

export function useEscapeStack(layers: Array<() => boolean>): void {
  const ref = useRef(layers);
  useEffect(() => {
    ref.current = layers;
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      for (const close of ref.current) {
        if (close()) return;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
