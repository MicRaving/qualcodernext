/**
 * Shared segment mutation actions for coders.
 *
 * Every coder re-implemented the same gutter/details quadruplet — update
 * memo, update weight, toggle important, delete — differing only in the
 * row-id field (ctid/imid/avid) and the delete endpoint. This factory is
 * THE implementation: it owns the PATCH calls (via codingApi), the undo
 * stack push on delete, the refresh and the error channel.
 *
 * `deleteRow` performs the kind-specific DELETE endpoint call; the factory
 * wraps it with the undo push + selection-clearing hook so all coders get
 * recoverable deletes.
 */
import { useCallback, useMemo } from "react";
import { errorMessage } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import {
  patchCodingMemo,
  patchCodingRowMeta,
  patchCodingWeight,
  type CodingKind,
} from "@/features/coding/codingApi";
import { useUndoStack } from "@/features/coding/shared/useUndoStack";

/** The fields any coder row must expose for the shared actions. */
export interface SegmentRow {
  cid: number;
  important?: number;
}

export interface SegmentActionsOptions<R extends SegmentRow = SegmentRow> {
  kind: CodingKind;
  /** All current coding rows (to resolve a row id → important flag). */
  rows: R[];
  /** The row's PATCH/DELETE id field. */
  idOf: (row: R) => number;
  /** Kind-specific DELETE call (api.deleteTextCoding etc.). */
  deleteRow: (id: number) => Promise<unknown>;
  /** Reload codings after any mutation; its result is returned to callers. */
  refresh: () => Promise<unknown>;
  /** Error surface (banner state setter). */
  onError: (msg: string) => void;
  /** Called after a successful delete (clear details selection). */
  onDeleted?: () => void;
}

export function useSegmentActions<R extends SegmentRow>(opts: SegmentActionsOptions<R>) {
  const { t } = useI18n();
  const { kind, rows, idOf, deleteRow, refresh, onError, onDeleted } = opts;
  const undo = useUndoStack<R>({ refresh, onError });

  const updateMemo = useCallback(
    async (id: number, memo: string): Promise<unknown> => {
      try {
        await patchCodingMemo(kind, id, memo);
        return await refresh();
      } catch (e) {
        onError(errorMessage(e, t("coder.memoUpdateError")));
        return undefined;
      }
    },
    [kind, refresh, onError, t],
  );

  const updateWeight = useCallback(
    async (id: number, weight: number): Promise<unknown> => {
      try {
        await patchCodingWeight(kind, id, weight);
        return await refresh();
      } catch (e) {
        onError(errorMessage(e, t("coder.weightError")));
        return undefined;
      }
    },
    [kind, refresh, onError, t],
  );

  const toggleImportant = useCallback(
    async (id: number): Promise<unknown> => {
      const row = rows.find((r) => idOf(r) === id);
      if (!row) return undefined;
      try {
        await patchCodingRowMeta(kind, id, { important: row.important ? 0 : 1 });
        return await refresh();
      } catch (e) {
        onError(errorMessage(e, t("coder.updateError")));
        return undefined;
      }
    },
    [rows, idOf, kind, refresh, onError, t],
  );

  const remove = useCallback(
    (id: number) => {
      const row = rows.find((r) => idOf(r) === id);
      void (async () => {
        try {
          await deleteRow(id);
          if (row) undo.push(row);
          onDeleted?.();
          await refresh();
        } catch (e) {
          onError(errorMessage(e, t("coder.removeError")));
        }
      })();
    },
    [rows, idOf, deleteRow, undo, onDeleted, refresh, onError, t],
  );

  return useMemo(
    () => ({ updateMemo, updateWeight, toggleImportant, remove, undo }),
    [updateMemo, updateWeight, toggleImportant, remove, undo],
  );
}

/** Convenience: the undo stack of a segment-actions instance. */
export type SegmentActions<R extends SegmentRow = SegmentRow> = ReturnType<
  typeof useSegmentActions<R>
>;
