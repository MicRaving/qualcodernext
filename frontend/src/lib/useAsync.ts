import { useEffect } from "react";

/**
 * An async effect that handles its own cancelled-flag lifecycle.
 *
 * Usage:
 *   useAsyncEffect(async (signal) => {
 *     const data = await api.someCall();
 *     signal.throwIfAborted();
 *     setData(data);
 *   }, [dep1, dep2]);
 */
export function useAsyncEffect(
  effect: (signal: { throwIfAborted(): void }) => Promise<void | (() => void)>,
  deps: unknown[],
): void {
  useEffect(() => {
    let cancelled = false;
    const signal = {
      throwIfAborted() {
        if (cancelled) throw new DOMException("Aborted", "AbortError");
      },
    };
    let cleanup: (() => void) | undefined;
    void effect(signal)
      .then((fn) => {
        if (typeof fn !== "function") return;
        // Effect resolved after unmount/dep change: clean up immediately.
        if (cancelled) fn();
        else cleanup = fn;
      })
      .catch((err) => {
      // Effects should handle their own errors; log anything that escapes so
      // failures are never silently swallowed (ignore aborts from unmount).
      if (err instanceof DOMException && err.name === "AbortError") return;
      try {
        console.error("useAsyncEffect error", err);
      } catch {
        /* ignore */
      }
    });
    return () => {
      cancelled = true;
      cleanup?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- caller controls deps
  }, deps);
}
