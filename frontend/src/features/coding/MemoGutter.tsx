/**
 * MemoGutter — Word-style memo margin for the coders.
 *
 * A single reusable module implemented in the text, website (HTML) and
 * multimedia (image/PDF/AV) coders. Two render modes:
 *
 *  - GUTTER (the "Memos" button in the coder header is ON): a slim column
 *    to the right of the document whose cards are anchored to the vertical
 *    position of each coded segment. A card is shown for every segment that
 *    produced memo and/or weight data, and for the currently selected
 *    segment even when it has no data yet (so the user can add it).
 *  - BUBBLE (the "Memos" button is OFF): selecting a coded segment opens its
 *    textbox as a floating bubble anchored just above the segment.
 *
 * Placement guarantees:
 *  - Each card aligns with its segment's vertical position (top-anchored).
 *  - Cards never overlap: co-located codings stack tightly at the shared
 *    anchor; when more than MAX_STACK share one spot the remainder collapse
 *    into a "+N more" chip.
 *
 * The module is measurement-only and coder-agnostic: coders pass normalized
 * GutterRow entries plus an `anchorOf(id)` resolver so every coder decides
 * how its own DOM anchors (data-ctid / data-imid / iframe marks) map to a
 * row. All memo/weight PATCHes flow through the module's callbacks.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Minus, Plus, Star, Trash2, X } from "lucide-react";
import { IconButton } from "@/components/ui/orchestrator";
import type { CodingKind } from "@/features/coding/codingApi";
import { contentHeightOf, scrollElementOf } from "@/features/coding/scrollRoot";
import { layoutGutterCards, stackRows, type GutterCardEntry } from "@/features/coding/memoLayout";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";

/* ------------------------------------------------------------------ */
/*  Data model                                                         */
/* ------------------------------------------------------------------ */

/** One coded segment's memo-gutter data, normalized across coders. */
export interface GutterRow {
  /** ctid (text) | imid (image) | avid (AV) of the coding. */
  id: number;
  kind: CodingKind;
  memo: string;
  /** Segment weight; 0 = unset. */
  weight: number;
  codeName: string;
  codeColor: string | null;
  date?: string;
  seltext?: string;
  important?: boolean;
}

/** Whether a row produced memo and/or weight data (a card is shown for it). */
// eslint-disable-next-line react-refresh/only-export-components
export function hasGutterData(r: GutterRow): boolean {
  return r.memo.trim().length > 0 || r.weight > 0;
}

/** Build a GutterRow from a coding-shaped object plus its code. */
// eslint-disable-next-line react-refresh/only-export-components
export function toGutterRow(
  row: {
    id: number;
    kind: CodingKind;
    memo?: string;
    weight?: number;
    important?: number;
    date?: string;
    seltext?: string;
  },
  code: { name: string; color: string | null } | undefined,
  fallbackName = "",
): GutterRow {
  return {
    id: row.id,
    kind: row.kind,
    memo: row.memo ?? "",
    weight: row.weight ?? 0,
    important: (row.important ?? 0) !== 0,
    date: row.date,
    seltext: row.seltext,
    codeName: code?.name ?? fallbackName,
    codeColor: code?.color ?? null,
  };
}

/* ------------------------------------------------------------------ */
/*  Sizing constants                                                   */
/* ------------------------------------------------------------------ */

const COLLAPSED_H = 40;
const EXPANDED_H = 132;
const CHIP_H = 24;
/** Max cards rendered per co-located stack before collapsing into "+N more". */
const MAX_STACK = 3;

/* ------------------------------------------------------------------ */
/*  Shared measurement hook                                            */
/* ------------------------------------------------------------------ */

/**
 * Measure each row's anchor top in DOCUMENT coordinates (relative to the
 * scroll container) plus the content height. Re-measures on mount, on
 * `measureSignal` (late-arriving marks — iframe highlights, PDF overlays)
 * and on every scroll of the scroll root.
 */
function useAnchorYs(
  rows: GutterRow[],
  scrollRef: React.RefObject<HTMLElement | Document | null>,
  anchorOf: (id: number) => HTMLElement | null,
  visible: boolean,
  measureSignal?: number,
): { ys: Map<number, number>; contentHeight: number } {
  const [ys, setYs] = useState<Map<number, number>>(new Map());
  const [contentHeight, setContentHeight] = useState(0);

  const anchorRef = useRef(anchorOf);
  anchorRef.current = anchorOf;
  const idsRef = useRef(rows.map((r) => r.id).join(","));
  idsRef.current = rows.map((r) => r.id).join(",");

  const measure = useCallback(() => {
    const root = scrollRef.current;
    if (!root) return;
    const scrollEl = scrollElementOf(root);
    const scrollRect = scrollEl.getBoundingClientRect();
    const map = new Map<number, number>();
    for (const id of idsRef.current.split(",")) {
      const n = Number(id);
      if (!Number.isFinite(n)) continue;
      const el = anchorRef.current(n);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      map.set(n, r.top - scrollRect.top + scrollEl.scrollTop);
    }
    setYs(map);
    setContentHeight(contentHeightOf(root));
  }, [scrollRef]);

  // Mount + measureSignal: run twice (rAF for a settled layout, then a
  // fallback timer so late-arriving marks are still caught).
  useEffect(() => {
    if (!visible) return;
    const raf = requestAnimationFrame(measure);
    const timer = setTimeout(measure, 120);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(timer);
    };
  }, [visible, measure, measureSignal]);

  // Scroll listener keeps positions fresh as the document moves.
  useEffect(() => {
    if (!visible) return;
    const root = scrollRef.current;
    if (!root) return;
    const scrollEl = scrollElementOf(root);
    const onScroll = () => measure();
    scrollEl.addEventListener("scroll", onScroll, { passive: true });
    return () => scrollEl.removeEventListener("scroll", onScroll);
  }, [visible, measure, scrollRef, measureSignal]);

  // Re-measure when the row set changes (new segments added/removed).
  useEffect(() => {
    if (!visible || rows.length === 0) return;
    const raf = requestAnimationFrame(measure);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, measure, idsRef.current]);

  return { ys, contentHeight };
}

/* ------------------------------------------------------------------ */
/*  MemoGutter — the Word-style sidebar column                         */
/* ------------------------------------------------------------------ */

export interface MemoGutterProps {
  rows: GutterRow[];
  /** Ids of the currently selected coded segment (a segment can carry
   *  several codings — e.g. overlapping text codings). */
  selectedIds: number[];
  scrollRef: React.RefObject<HTMLElement | Document | null>;
  /** Resolve the DOM anchor of a row inside the scroll root (never null for
   *  an existing row once its span is rendered). */
  anchorOf: (id: number) => HTMLElement | null;
  onSelect: (id: number) => void;
  onDeselect: () => void;
  onUpdateMemo: (id: number, memo: string) => void;
  onUpdateWeight: (id: number, weight: number) => void;
  onDelete: (id: number) => void;
  onToggleImportant?: (id: number) => void;
  /** Optional per-row extension rendered below the expanded editor (e.g.
   *  the image/PDF region geometry editor). */
  extrasFor?: (id: number) => ReactNode;
  visible: boolean;
  measureSignal?: number;
  width?: "sm" | "md";
  /** How the gutter tracks the parent scroll.  "scrollTop" (default) syncs
   *  the gutter's own scroll offset — works when the gutter sits inside the
   *  scrolling container (TextCoder, PdfCoder).  "transform" applies a CSS
   *  translateY instead — required when the gutter overlays an iframe whose
   *  content scrolls independently (HtmlCoder). */
  scrollSync?: "scrollTop" | "transform";
}

export function MemoGutter({
  rows,
  selectedIds,
  scrollRef,
  anchorOf,
  onSelect,
  onDeselect,
  onUpdateMemo,
  onUpdateWeight,
  onDelete,
  onToggleImportant,
  extrasFor,
  visible,
  measureSignal,
  width = "sm",
  scrollSync = "scrollTop",
}: MemoGutterProps) {
  const { t } = useI18n();
  const gutterRef = useRef<HTMLDivElement | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  /** Stack key whose hidden rows are all revealed ("+N more" clicked). */
  const [revealedStack, setRevealedStack] = useState<string | null>(null);

  // Clear transient editing + revealed stacks when the selection moves.
  useEffect(() => {
    setEditingId(null);
    setRevealedStack(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIds.join(",")]);

  const { ys, contentHeight } = useAnchorYs(rows, scrollRef, anchorOf, visible, measureSignal);

  // Sync the gutter with the document's scroll so cards track their segments.
  // "scrollTop" mode sets the gutter's own scroll offset (for when the gutter
  // sits inside the scrolling container).  "transform" mode applies a CSS
  // translateY (for when the gutter overlays an iframe that scrolls
  // independently — avoids a second scroll context).
  //
  // In "transform" mode we use a rAF loop instead of a scroll event listener
  // because the iframe's scroll may happen on a child element rather than
  // document.scrollingElement, making the event unreliable to capture.
  useEffect(() => {
    if (!visible) return;
    const root = scrollRef.current;
    if (!root) return;
    const scrollEl = scrollElementOf(root);

    if (scrollSync === "transform") {
      let raf: number;
      let prev = -1;
      const tick = () => {
        const el = gutterRef.current;
        if (el) {
          const st = scrollEl.scrollTop;
          if (st !== prev) {
            el.style.transform = `translateY(${-st}px)`;
            prev = st;
          }
        }
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
      return () => cancelAnimationFrame(raf);
    }

    const onScroll = () => {
      if (gutterRef.current) gutterRef.current.scrollTop = scrollEl.scrollTop;
    };
    scrollEl.addEventListener("scroll", onScroll, { passive: true });
    return () => scrollEl.removeEventListener("scroll", onScroll);
  }, [visible, scrollRef, measureSignal, scrollSync]);

  // Rows that must render a card: produced data, or part of the selection.
  const visibleRows = useMemo(
    () => rows.filter((r) => hasGutterData(r) || selectedIds.includes(r.id)),
    [rows, selectedIds],
  );

  const layout = useMemo(() => {
    // Resolve measured Y, drop rows whose span is not yet in the DOM, then
    // group co-located rows into stacks.
    const anchored = visibleRows
      .map((r) => ({ row: r, y: ys.get(r.id) }))
      .filter((e): e is { row: GutterRow; y: number } => e.y !== undefined);
    const stacks = stackRows(anchored);
    const entries: GutterCardEntry[] = [];
    for (const stack of stacks) {
      const key = String(stack[0].row.id);
      const revealed = revealedStack === key;
      const cards = revealed ? stack : stack.slice(0, MAX_STACK);
      for (const e of cards) {
        const expanded = selectedIds.includes(e.row.id) || editingId === e.row.id;
        entries.push({
          id: e.row.id,
          desiredY: e.y,
          height: expanded ? EXPANDED_H : COLLAPSED_H,
        });
      }
      if (!revealed && stack.length > MAX_STACK) {
        entries.push({ id: -stack[0].row.id, desiredY: stack[0].y, height: CHIP_H });
      }
    }
    return {
      stacks,
      resolved: layoutGutterCards(entries),
    };
  }, [visibleRows, ys, selectedIds, editingId, revealedStack]);

  const hasAnyData = visibleRows.some((r) => hasGutterData(r));

  const gutterWidthClass = width === "md" ? "w-72" : "w-56";
  // Like the rightbar, the gutter animates its width when shown/hidden
  // instead of mounting/unmounting instantly.
  if (!visible) {
    return <div className="shrink-0 overflow-hidden border-l border-transparent transition-[width] duration-200 ease-[var(--qc-ease)] w-0" aria-hidden />;
  }

  return (
    <div
      className={cn(
        "shrink-0 overflow-hidden transition-[width] duration-200 ease-[var(--qc-ease)]",
        gutterWidthClass,
      )}
    >
      <div
        ref={gutterRef}
        data-gutter=""
        className={cn(
          "relative h-full border-l border-border bg-surface qc-enter-fade",
          scrollSync === "transform"
            ? "overflow-hidden"
            : "pointer-events-none overflow-y-auto overflow-x-hidden",
          gutterWidthClass,
        )}
        style={{ minHeight: contentHeight || undefined }}
      >
      {visibleRows.length === 0 && (
        <p className="absolute top-4 left-0 right-0 text-center text-xs text-text-secondary italic">
          {rows.length === 0 ? t("coder.memoGutterNoCodings") : t("coder.memoGutterEmpty")}
        </p>
      )}

      {visibleRows.length > 0 && !hasAnyData && selectedIds.length === 0 && (
        <p className="absolute top-4 left-0 right-0 text-center text-xs text-text-secondary italic">
          {t("coder.memoGutterEmpty")}
        </p>
      )}

      {layout.stacks.map((stack) => {
        const key = String(stack[0].row.id);
        const revealed = revealedStack === key;
        const cards = revealed ? stack : stack.slice(0, MAX_STACK);
        const overflow = stack.length > MAX_STACK && !revealed ? stack.length - MAX_STACK : 0;
        return (
          <div key={key}>
            {cards.map(({ row }) => {
              const y = layout.resolved.get(row.id);
              if (y === undefined) return null;
              const expanded = selectedIds.includes(row.id) || editingId === row.id;
              return (
                <div key={row.id} className="pointer-events-auto absolute left-0 right-0 px-1" style={{ top: y }}>
                  <SegmentMemoEditor
                    row={row}
                    expanded={expanded}
                    onActivate={() => onSelect(row.id)}
                    onFocusEditing={() => setEditingId(row.id)}
                    onBlurEditing={() => setEditingId(null)}
                    onUpdateMemo={(memo) => onUpdateMemo(row.id, memo)}
                    onUpdateWeight={(weight) => onUpdateWeight(row.id, weight)}
                    onDelete={() => onDelete(row.id)}
                    onToggleImportant={onToggleImportant ? () => onToggleImportant(row.id) : undefined}
                    onCollapse={() => {
                      if (selectedIds.includes(row.id)) onDeselect();
                      setEditingId(null);
                    }}
                    extras={extrasFor ? extrasFor(row.id) : undefined}
                  />
                </div>
              );
            })}
            {overflow > 0 && (
              <div
                className="pointer-events-auto absolute left-0 right-0 px-1"
                style={{ top: layout.resolved.get(-stack[0].row.id) }}
              >
                <button
                  type="button"
                  onClick={() => setRevealedStack(key)}
                  className="w-full rounded-sm border border-border bg-surface-higher px-1 py-0.5 text-center text-[10px] text-text-secondary hover:text-text-primary"
                >
                  {t("coder.memoOverflow", { count: overflow })}
                </button>
              </div>
            )}
          </div>
        );
      })}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  MemoGutterBubble — floating editor when the gutter is hidden       */
/* ------------------------------------------------------------------ */

export interface MemoGutterBubbleProps {
  /** All codings of the selected segment (a segment can carry several). */
  rows: GutterRow[];
  scrollRef: React.RefObject<HTMLElement | Document | null>;
  anchorOf: (id: number) => HTMLElement | null;
  onClose: () => void;
  onUpdateMemo: (id: number, memo: string) => void;
  onUpdateWeight: (id: number, weight: number) => void;
  onDelete: (id: number) => void;
  onToggleImportant?: (id: number) => void;
  /** Optional extension rendered below the editor (e.g. geometry form). */
  extrasFor?: (id: number) => ReactNode;
  measureSignal?: number;
  /** Keep the bubble open when the user clicks inside the parent document
   *  but outside the bubble (default true). */
  dismissOnOutsideClick?: boolean;
}

export function MemoGutterBubble({
  rows,
  scrollRef,
  anchorOf,
  onClose,
  onUpdateMemo,
  onUpdateWeight,
  onDelete,
  onToggleImportant,
  extrasFor,
  measureSignal,
  dismissOnOutsideClick = true,
}: MemoGutterBubbleProps) {
  const { t } = useI18n();
  const bubbleRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  // Anchor above the FIRST row's segment (all rows of one segment share a
  // span, so their anchors coincide).
  const primaryId = rows[0]?.id ?? null;

  const measure = useCallback(() => {
    if (primaryId == null) return;
    const root = scrollRef.current;
    if (!root) return;
    const el = anchorOf(primaryId);
    if (!el) {
      setPos(null);
      return;
    }
    const r = el.getBoundingClientRect();
    setPos({ left: r.left, top: r.top - 8 });
  }, [primaryId, scrollRef, anchorOf]);

  useEffect(() => {
    if (primaryId == null) return;
    measure();
    const root = scrollRef.current;
    if (root) {
      const scrollEl = scrollElementOf(root);
      scrollEl.addEventListener("scroll", measure, { passive: true });
    }
    window.addEventListener("resize", measure);
    return () => {
      if (root) scrollElementOf(root).removeEventListener("scroll", measure);
      window.removeEventListener("resize", measure);
    };
  }, [primaryId, scrollRef, measure, measureSignal]);

  // Click-away closes the bubble (clicks inside the bubble are ignored).
  useEffect(() => {
    if (!dismissOnOutsideClick) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (target && bubbleRef.current && !bubbleRef.current.contains(target)) onClose();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [dismissOnOutsideClick, onClose]);

  if (rows.length === 0) return null;

  return (
    <div
      ref={bubbleRef}
      data-gutter=""
      className="fixed z-50 w-80 -translate-y-full rounded-sm border border-border bg-surface p-2 shadow-lg qc-enter-fade"
      style={{ left: Math.max(8, pos?.left ?? 8), top: Math.max(8, pos?.top ?? 8) }}
      role="dialog"
      aria-label={t("coder.segmentDetails")}
    >
      <div
        className="absolute left-4 -bottom-1 h-2 w-2 rotate-45 border-b border-r border-border bg-surface"
        aria-hidden
      />
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-text-secondary">{t("coder.segmentDetails")}</span>
        <div className="flex-1" />
        <IconButton label={t("common.closeDetails")} size="sm" onClick={onClose}>
          <X size={14} aria-hidden />
        </IconButton>
      </div>
      <div className="mt-1.5 space-y-2">
        {rows.map((row) => (
          <SegmentMemoEditor
            key={row.id}
            row={row}
            expanded
            autoFocus={row.id === primaryId}
            onActivate={() => undefined}
            onUpdateMemo={(memo) => onUpdateMemo(row.id, memo)}
            onUpdateWeight={(weight) => onUpdateWeight(row.id, weight)}
            onDelete={() => onDelete(row.id)}
            onToggleImportant={onToggleImportant ? () => onToggleImportant(row.id) : undefined}
            extras={extrasFor ? extrasFor(row.id) : undefined}
          />
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  SegmentMemoEditor — the shared memo + weight textbox               */
/* ------------------------------------------------------------------ */

interface SegmentMemoEditorProps {
  row: GutterRow;
  expanded: boolean;
  /** Focus the memo textarea on mount (bubble mode). */
  autoFocus?: boolean;
  onActivate: () => void;
  onFocusEditing?: () => void;
  onBlurEditing?: () => void;
  onUpdateMemo: (memo: string) => void;
  onUpdateWeight: (weight: number) => void;
  onDelete: () => void;
  onToggleImportant?: () => void;
  onCollapse?: () => void;
  extras?: ReactNode;
}

function SegmentMemoEditor({
  row,
  expanded,
  autoFocus,
  onActivate,
  onFocusEditing,
  onBlurEditing,
  onUpdateMemo,
  onUpdateWeight,
  onDelete,
  onToggleImportant,
  onCollapse,
  extras,
}: SegmentMemoEditorProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(row.memo);
  const isEditingRef = useRef(false);

  // Sync the draft with the prop unless the user is actively typing.
  useEffect(() => {
    if (!isEditingRef.current) setDraft(row.memo);
  }, [row.memo]);

  const hasMemo = row.memo.trim().length > 0;
  const weight = row.weight;

  return (
    <div
      className={cn(
        "rounded-sm border-l-2 bg-bg transition-shadow",
        expanded ? "cursor-default p-2 shadow-sm" : "cursor-pointer p-1.5 hover:shadow-sm",
      )}
      style={{ borderLeftColor: row.codeColor ?? undefined }}
      onClick={expanded ? undefined : onActivate}
      role={expanded ? undefined : "button"}
      tabIndex={expanded ? undefined : 0}
      onKeyDown={
        expanded
          ? undefined
          : (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onActivate();
              }
            }
      }
    >
      {/* Header: dot + code name + weight chip (collapsed) / controls (expanded) */}
      <div className="flex items-center gap-1.5">
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: row.codeColor ?? undefined }}
          aria-hidden
        />
        <span className="truncate text-xs font-medium text-text-primary" title={row.date}>
          {row.codeName}
        </span>
        {!expanded && weight > 0 && (
          <span className="ml-auto shrink-0 rounded bg-surface-higher px-1 py-px text-[10px] font-medium text-text-secondary">
            {weight}
          </span>
        )}
        {expanded && (
          <>
            <div className="flex-1" />
            {row.important !== undefined && (
              <IconButton
                label={t("pdfCoder.importantToggle")}
                title={t("pdfCoder.importantToggle")}
                size="sm"
                className={cn(row.important && "text-warning")}
                onClick={onToggleImportant}
              >
                <Star size={12} className={row.important ? "fill-current" : ""} aria-hidden />
              </IconButton>
            )}
            {onCollapse && (
              <IconButton label={t("common.closeDetails")} size="sm" onClick={onCollapse}>
                <X size={12} aria-hidden />
              </IconButton>
            )}
          </>
        )}
      </div>

      {/* Collapsed: memo preview or placeholder */}
      {!expanded ? (
        <p
          className={cn(
            "mt-0.5 text-[11px] line-clamp-1",
            hasMemo ? "text-text-secondary" : "text-text-secondary/50 italic",
          )}
        >
          {hasMemo ? row.memo : t("coder.noMemoInline")}
        </p>
      ) : (
        <div className="mt-2 space-y-1.5" onClick={(e) => e.stopPropagation()}>
          {row.seltext && (
            <p className="truncate text-[11px] text-text-secondary" title={row.seltext}>
              {row.seltext}
            </p>
          )}
          <textarea
            autoFocus={autoFocus}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onFocus={() => {
              isEditingRef.current = true;
              onFocusEditing?.();
            }}
            onBlur={() => {
              isEditingRef.current = false;
              onUpdateMemo(draft);
              onBlurEditing?.();
            }}
            rows={2}
            className="w-full rounded-sm border border-border bg-bg px-2 py-1 text-xs text-text-primary placeholder:text-text-secondary resize-none focus:border-accent focus:outline-none"
            placeholder={t("coder.memoCardPlaceholder")}
            aria-label={t("coder.memoCardMemoLabel", { name: row.codeName })}
          />
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-text-secondary">{t("coder.weight")}</span>
            <button
              type="button"
              onClick={() => onUpdateWeight(weight - 1)}
              disabled={weight === 0}
              title={t("coder.weightDec")}
              aria-label={t("coder.weightDec")}
              className="rounded-sm border border-border px-0.5 text-[10px] hover:bg-surface-higher disabled:opacity-40"
            >
              <Minus size={8} aria-hidden />
            </button>
            <span className="min-w-4 text-center text-[10px] font-medium text-text-primary">
              {weight}
            </span>
            <button
              type="button"
              onClick={() => onUpdateWeight(weight + 1)}
              disabled={weight >= 100}
              title={t("coder.weightInc")}
              aria-label={t("coder.weightInc")}
              className="rounded-sm border border-border px-0.5 text-[10px] hover:bg-surface-higher disabled:opacity-40"
            >
              <Plus size={8} aria-hidden />
            </button>
            <div className="flex-1" />
            <button
              type="button"
              onClick={onDelete}
              title={t("coder.removeThis")}
              aria-label={t("coder.delete")}
              className="rounded-sm p-0.5 text-text-secondary hover:text-danger"
            >
              <Trash2 size={10} aria-hidden />
            </button>
          </div>
          {extras}
        </div>
      )}
    </div>
  );
}