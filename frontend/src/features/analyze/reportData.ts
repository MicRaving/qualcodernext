/**
 * Shared report data-loading + table scaffolding (constants and the hook;
 * the presentational parts live in reportKit.tsx).
 */
import { errorMessage } from "@/lib/utils";
import { useAsyncEffect } from "@/lib/useAsync";
import { useCallback, useRef, useState } from "react";
import { cls } from "@/components/ui/tokens";

export const thCls = cls.tableHead;
export const tdCls = "border-b border-border px-2 py-1.5 text-sm";
export const cardCls = "overflow-auto rounded-sm border border-border bg-surface";

export interface ReportState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  retry: () => void;
}

/**
 * Load a report; re-runs whenever its loader inputs (`deps`) change — the
 * old per-file copies only re-ran on retry, which left parameterized
 * reports (e.g. the codebook memo toggle) showing stale data forever.
 */
export function useReport<T>(load: () => Promise<T>, deps: unknown[] = []): ReportState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useAsyncEffect(async (signal) => {
    setLoading(true);
    setError(null);
    try {
      const d = await loadRef.current();
      signal.throwIfAborted();
      setData(d);
    } catch (e) {
      signal.throwIfAborted();
      setError(errorMessage(e, "Failed to load report"));
    } finally {
      signal.throwIfAborted();
      setLoading(false);
    }
  }, [attempt, ...deps]);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  return { data, loading, error, retry };
}
