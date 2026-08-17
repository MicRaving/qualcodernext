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
    void effect(signal).catch(() => {
      /* errors should be handled inside the effect */
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- caller controls deps
  }, deps);
}
