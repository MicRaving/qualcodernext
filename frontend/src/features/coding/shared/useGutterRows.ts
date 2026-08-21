/**
 * Shared gutter-row mapping: codings → MemoGutter rows.
 *
 * Every coder mapped its coding list through toGutterRow with the same
 * id/kind/weight plumbing; PdfCoder kept a hand-rolled variant because it
 * mixes image+text rows. One hook, one mapping — mixed-kind coders call it
 * once per row list and merge.
 */
import { useMemo } from "react";
import type { CodeTreeItem, Coding } from "@/lib/api";
import { toGutterRow, type GutterRow } from "@/features/coding/MemoGutter";
import { codingWeight, type CodingKind } from "@/features/coding/codingApi";

export function useGutterRows(opts: {
  rows: Coding[];
  kind: CodingKind;
  idOf: (row: Coding) => number;
  codeById: Map<number, CodeTreeItem>;
  /** i18n-bound fallback label, e.g. (cid) => t("coder.fallbackCode", {id: cid}) */
  fallbackName: (cid: number) => string;
}): GutterRow[] {
  const { rows, kind, idOf, codeById, fallbackName } = opts;
  return useMemo(
    () =>
      rows.map((c) =>
        toGutterRow(
          {
            id: idOf(c),
            kind,
            memo: c.memo,
            weight: codingWeight(c),
            important: c.important,
            date: c.date,
            seltext: c.seltext,
          },
          codeById.get(c.cid),
          fallbackName(c.cid),
        ),
      ),
    [rows, kind, idOf, codeById, fallbackName],
  );
}
