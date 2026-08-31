/**
 * DetailsBars — the bottom "inspector" strips shown next to a selected
 * coded segment / annotated span. Extracted from the text coder so the CSV
 * table view (and any future coder surface) reuses them unchanged.
 */
import { useState } from "react";
import { Check, Minus, Pencil, Plus, Star, Trash2, X } from "lucide-react";
import { Button, IconButton, Textarea } from "@/components/ui/orchestrator";
import type { Annotation, CodeTreeItem, Coding } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

import { FALLBACK_CODE_COLOR } from "@/features/coding/tint";

/** Segment weight (backend rows carry it; 0 = no weight). */
function weightOf(row: Coding & { weight?: number }): number {
  return row.weight ?? 0;
}

export function CodingDetailsBar({
  rows,
  codeById,
  onDelete,
  onWeight,
  onClose,
}: {
  rows: Coding[];
  codeById: Map<number, CodeTreeItem>;
  onDelete: (row: Coding) => void;
  onWeight: (row: Coding, weight: number) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="qc-enter shrink-0 border-t border-border bg-surface px-3 py-2">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-text-secondary">{t("coder.codingDetails")}</span>
        <div className="flex-1" />
        <IconButton label={t("common.closeDetails")} size="sm" onClick={onClose}>
          <X size={14} aria-hidden />
        </IconButton>
      </div>
      <ul className="mt-1.5 space-y-1.5">
        {rows.map((r) => {
          const code = codeById.get(r.cid);
          return (
            <li
              key={r.ctid}
              className="flex items-center gap-2 rounded-sm border border-border bg-bg px-2 py-1.5 text-sm"
            >
              <span
                className="h-3 w-3 shrink-0 rounded-sm border border-border"
                style={{ backgroundColor: code?.color ?? FALLBACK_CODE_COLOR }}
                aria-hidden
              />
              <span className="font-medium" title={r.date}>
                {code?.name ?? t("coder.fallbackCode", { id: r.cid })}
              </span>
              {r.important !== 0 && (
                <Star size={12} className="text-warning" fill="currentColor" aria-hidden />
              )}
              {code?.memo && <span className="truncate text-xs text-text-secondary">{code.memo}</span>}
              <span className="flex items-center gap-1">
                <span className="text-xs text-text-secondary">{t("coder.weight")}</span>
                <Button
                  variant="toolbarIcon"
                  icon={<Minus size={12} aria-hidden />}
                  title={t("coder.weightDec")}
                  aria-label={t("coder.weightDec")}
                  disabled={weightOf(r) === 0}
                  onClick={() => onWeight(r, weightOf(r) - 1)}
                />
                <span className="min-w-5 text-center text-xs text-text-secondary" aria-label={t("coder.weight")}>
                  {weightOf(r)}
                </span>
                <Button
                  variant="toolbarIcon"
                  icon={<Plus size={12} aria-hidden />}
                  title={t("coder.weightInc")}
                  aria-label={t("coder.weightInc")}
                  disabled={weightOf(r) >= 100}
                  onClick={() => onWeight(r, weightOf(r) + 1)}
                />
              </span>
              <div className="flex-1" />
              <IconButton
                label={t("coder.removeFor", { name: code?.name ?? "code" })}
                title={t("coder.removeThis")}
                size="sm"
                onClick={() => onDelete(r)}
                className="hover:text-danger"
              >
                <Trash2 size={14} aria-hidden />
              </IconButton>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function AnnotationDetailsBar({  rows,
  onUpdateMemo,
  onDelete,
  onClose,
}: {
  rows: Annotation[];
  onUpdateMemo: (anid: number, memo: string) => void;
  onDelete: (ann: Annotation) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [editingAnnMemo, setEditingAnnMemo] = useState<{ anid: number; memo: string } | null>(null);

  return (
    <div className="qc-enter shrink-0 border-t border-border bg-surface px-3 py-2">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-text-secondary">{t("coder.annotationDetails")}</span>
        <div className="flex-1" />
        <IconButton label={t("common.closeDetails")} size="sm" onClick={onClose}>
          <X size={14} aria-hidden />
        </IconButton>
      </div>
      <ul className="mt-1.5 space-y-1.5">
        {rows.map((a) => {
          const editing = editingAnnMemo?.anid === a.anid;
          return (
            <li key={a.anid} className="rounded-sm border border-border bg-bg px-2 py-1.5 text-sm">
              {editing ? (
                <div className="flex items-start gap-1.5">
                  <Textarea
                    value={editingAnnMemo.memo}
                    onChange={(e) => setEditingAnnMemo({ anid: a.anid, memo: e.target.value })}
                    aria-label={t("coder.annotationMemoPlaceholder")}
                    className="min-h-12 w-full resize-none p-1.5"
                  />
                  <Button
                    variant="primary"
                    icon={<Check size={12} aria-hidden />}
                    onClick={() => onUpdateMemo(a.anid, editingAnnMemo.memo)}
                  >
                    {t("common.save")}
                  </Button>
                  <Button variant="secondary" onClick={() => setEditingAnnMemo(null)}>
                    {t("common.cancel")}
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate">
                    {a.memo || <span className="text-text-secondary">{t("coder.noMemoInline")}</span>}
                  </span>
                  <span className="text-xs text-text-secondary">{a.date}</span>
                  <IconButton
                    label={t("coder.editAnnotationMemo")}
                    title={t("common.editMemo")}
                    size="sm"
                    onClick={() => setEditingAnnMemo({ anid: a.anid, memo: a.memo })}
                  >
                    <Pencil size={14} aria-hidden />
                  </IconButton>
                  <IconButton
                    label={t("coder.deleteAnnotation")}
                    title={t("coder.deleteAnnotation")}
                    size="sm"
                    onClick={() => onDelete(a)}
                    className="hover:text-danger"
                  >
                    <Trash2 size={14} aria-hidden />
                  </IconButton>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
