/**
 * Shared unmark/undo stack for coder deletes.
 *
 * TextCoder and CsvCoder each hand-rolled the same "remember deleted rows,
 * restore the last one via POST /codings/undo" stack; Html/Pdf/Av/Image had
 * NO undo at all (a confirmed delete was unrecoverable). Every coder now
 * mounts this hook: deletes push here, the header renders an Unmark button
 * from `canUndo`/`undoLast`.
 */
import { useCallback, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";

const CAPACITY = 20;

export function useUndoStack<T extends object>(opts: {
  refresh: () => Promise<unknown>;
  onError: (msg: string) => void;
}): {
  push: (row: T) => void;
  undoLast: () => void;
  canUndo: boolean;
  /** Drop the stack (source switch / reload must not leak rows across files). */
  clear: () => void;
} {
  const { t } = useI18n();
  const { refresh, onError } = opts;
  // Mirror ref so undoLast always reads the live top-of-stack without
  // depending on render-time state.
  const stackRef = useRef<T[]>([]);
  const [depth, setDepth] = useState(0);

  const push = useCallback((row: T) => {
    stackRef.current = [...stackRef.current.slice(-(CAPACITY - 1)), row];
    setDepth(stackRef.current.length);
  }, []);

  const undoLast = useCallback(() => {
    const row = stackRef.current[stackRef.current.length - 1];
    if (!row) return;
    stackRef.current = stackRef.current.slice(0, -1);
    setDepth(stackRef.current.length);
    void (async () => {
      try {
        await api.undoCodings([row]);
        await refresh();
      } catch (e) {
        onError(errorMessage(e, t("coder.restoreError")));
      }
    })();
  }, [refresh, onError, t]);

  const clear = useCallback(() => {
    stackRef.current = [];
    setDepth(0);
  }, []);

  return useMemo(
    () => ({ push, undoLast, canUndo: depth > 0, clear }),
    [push, undoLast, depth, clear],
  );
}
