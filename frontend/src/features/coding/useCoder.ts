/**
 * Shared "load codings + flat code tree, manage loading/error state" preamble
 * used by the coding workspaces.
 *
 * Each coder supplies its own coding endpoint via `loadCodings` (text /
 * image / AV); the hook always pairs it with `api.codesFlat()` and tracks
 * the standard `loading` / `error` / `codings` / `codes` state machine.
 *
 * Two deliberate extensions over the bare state machine keep the converted
 * coders behavior-identical:
 *
 *  - `reload()` resolves with the freshly loaded codings array — parity
 *    with the old `const fresh = await load()` pattern that auto-selects a
 *    just-created segment by id.
 *  - `setError` is exposed because coders surface mutation errors (create /
 *    weight / delete …) in the same banner as load errors.
 *
 * NOT used by TextCoder / CsvCoder / PdfCoder / HtmlCoder: those loads are
 * entangled with extra fetches (annotations, source fulltext), store-owned
 * code trees, or a deliberate allSettled degradation policy, so their
 * bespoke loads stay in the coder.
 */
import { useCallback, useRef, useState } from "react";
import { useAsyncEffect } from "@/lib/useAsync";
import { errorMessage } from "@/lib/utils";
import { api, type CodeTreeItem, type Source } from "@/lib/api";

export interface CoderLoad<T> {
  loading: boolean;
  error: string | null;
  /** Direct error writer — coders surface mutation errors here too. */
  setError(error: string | null): void;
  codings: T[];
  codes: CodeTreeItem[];
  /** Re-run the load; resolves with the freshly loaded codings array. */
  reload(): Promise<T[]>;
}

export function useCoder<T>(
  source: Source,
  loadCodings: (sourceId: number) => Promise<T[]>,
  fallback: string,
): CoderLoad<T> {
  const [codings, setCodings] = useState<T[]>([]);
  const [codes, setCodes] = useState<CodeTreeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  /** Resolver of the latest awaited `reload()` — resolved with the fresh
   *  codings once the load settles (never left dangling). */
  const pendingReloadRef = useRef<((codings: T[]) => void) | null>(null);

  useAsyncEffect(async (signal) => {
    setLoading(true);
    setError(null);
    let result: T[] = [];
    try {
      const [cs, flat] = await Promise.all([loadCodings(source.id), api.codesFlat()]);
      signal.throwIfAborted();
      result = cs;
      setCodings(cs);
      setCodes(flat);
    } catch (e) {
      signal.throwIfAborted();
      setError(errorMessage(e, fallback));
    } finally {
      pendingReloadRef.current?.(result);
      pendingReloadRef.current = null;
      signal.throwIfAborted();
      setLoading(false);
    }
  }, [source.id, loadCodings, fallback, tick]);

  const reload = useCallback((): Promise<T[]> => {
    return new Promise((resolve) => {
      pendingReloadRef.current = resolve;
      setTick((n) => n + 1);
    });
  }, []);

  return { loading, error, setError, codings, codes, reload };
}
