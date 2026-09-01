/**
 * TextCoder — text coding workspace: coded-segment rendering, selection
 * toolbar, annotations, edit mode with live shifted highlights, autocode,
 * and an unmark/undo stack.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";
import { useAsyncEffect } from "@/lib/useAsync";
import {
  Bookmark,
  BookmarkCheck,
  CircleAlert,
  FilePen,
  Link as LinkIcon,
  LoaderCircle,
  MessageSquareText,
  Rows3,
  Save,
  Sparkles,
  Undo2,
  X,
} from "lucide-react";
import {
  Button,
  ErrorBanner,
  IconButton,
  LoadError,
  LoadingState,
  ViewHeader,
} from "@/components/ui/orchestrator";
import { AutocodeDialog } from "@/features/coding/AutocodeDialog";
import { useCodeIndex } from "@/features/coding/codingApi";
import { useSegmentActions } from "@/features/coding/shared/useSegmentActions";
import { useCodingsChanged } from "@/features/coding/shared/events";
import { clampToolbarAnchor } from "@/features/coding/shared/toolbarAnchor";
import {
  api,
  type Annotation,
  type CodeTreeItem,
  type Coding,
  type ShiftPositionsResponse,
  type Source,
} from "@/lib/api";
import {
  buildAnnotationSegments,
  buildRenderedSegments,
  type AnnotationSegment,
  type RenderedSegment,
} from "@/features/coding/segments";
import { getSelectionOffsets, type SelectionOffsets } from "@/features/coding/selection";
import { SelectionToolbar } from "@/features/coding/SelectionToolbar";
import {
  AnnotationDetailsBar,
} from "@/features/coding/DetailsBars";
import { MemoGutter, MemoGutterBubble, toGutterRow } from "@/features/coding/MemoGutter";
import { useGutterVisible } from "@/features/coding/viewOptions";
import { FALLBACK_CODE_COLOR, codeTint } from "@/features/coding/tint";
import {
  consumePendingJump,
  fetchOutgoingLinks,
  jumpToSpan,
  type PendingJump,
  type SegmentLink,
} from "@/features/coding/links";
import { usesPdfCoder } from "@/lib/media";
import { cn, errorMessage } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { useCoderStore } from "@/stores/coder";
import { useInspectorStore } from "@/stores/inspector";
import { usePrefsStore } from "@/stores/prefs";
import { useWorkspaceStore } from "@/stores/workspace";
import { useProjectStore } from "@/stores/project";

/** Shared font metrics so the edit-mode textarea and overlay align. */
const DOC_FONT_CLS = "qc-selectable font-sans text-sm leading-6 whitespace-pre-wrap break-words";

/** Soft highlight for coded segments: the code color, transparently. */
function softBackground(color: string): string {
  return codeTint(color);
}

/** The (nearest .qc-seg-wrapped) element covering character `pos`, or null
 *  when the position falls in plain (uncoded) text. Offsets assume the
 *  container's text nodes mirror the document text exactly. */
function elementAtTextPos(container: HTMLElement, pos: number): HTMLElement | null {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let offset = 0;
  let node: Node | null;
  while ((node = walker.nextNode())) {
    const len = (node.textContent ?? "").length;
    if (pos < offset + len) {
      let el: HTMLElement | null = node.parentElement;
      while (el && el !== container && !el.classList.contains("qc-seg")) {
        el = el.parentElement;
      }
      return el && el !== container ? el : null;
    }
    offset += len;
  }
  return null;
}

/** Apply shifted positions back onto coding rows, dropping any the backend marked for deletion. */
function applyCodingShifts(codings: Coding[], res: ShiftPositionsResponse): Coding[] {
  const deleted = new Set(res.deletions.code_text);
  const byId = res.codings.some((e) => e.ctid !== undefined);
  return codings
    .filter((c) => !deleted.has(c.ctid))
    .map((c, idx) => {
      const entry = byId ? res.codings.find((e) => e.ctid === c.ctid) : res.codings[idx];
      if (!entry) return c;
      return { ...c, pos0: entry.newpos0, pos1: entry.newpos1 };
    });
}

/** Same for annotations. */
function applyAnnotationShifts(
  annotations: Annotation[],
  res: ShiftPositionsResponse,
): Annotation[] {
  const deleted = new Set(res.deletions.annotation);
  const byId = res.annotations.some((e) => e.anid !== undefined);
  return annotations
    .filter((a) => !deleted.has(a.anid))
    .map((a, idx) => {
      const entry = byId ? res.annotations.find((e) => e.anid === a.anid) : res.annotations[idx];
      if (!entry) return a;
      return { ...a, pos0: entry.newpos0, pos1: entry.newpos1 };
    });
}

interface DraftPositions {
  codings: Coding[];
  annotations: Annotation[];
}

export function TextCoder({
  sourceId,
  forceText = false,
  onExitPlainText,
  bare = false,
  textOverride,
  codings: codingsProp,
  annotations: annotationsProp,
  codes: codesProp,
  onCodingsChange,
  onAnnotationsChange,
  onCodesChange,
  scrollElRef,
  suppressGutter = false,
}: {
  sourceId: number;
  /** Render the plain text even for PDF sources (PDF "plain text" mode). */
  forceText?: boolean;
  /** When set (PDF plain-text mode), renders a "back to rendered PDF" toggle. */
  onExitPlainText?: () => void;
  /** Omit the view header — renders only the document surface (split view). */
  bare?: boolean;
  /** Displayed document text override. When provided it replaces the source's
   *  stored fulltext so a cleaned variant (e.g. empty lines collapsed for
   *  website text) can be shown consistently with the other panes. */
  textOverride?: string;
  /** Controlled mode: the parent owns the codings/annotations/codes state and
   *  is notified of every change, so all panes render from the same arrays. */
  codings?: Coding[];
  annotations?: Annotation[];
  codes?: CodeTreeItem[];
  onCodingsChange?: (codings: Coding[]) => void;
  onAnnotationsChange?: (annotations: Annotation[]) => void;
  onCodesChange?: (codes: CodeTreeItem[]) => void;
  /** Optional parent-owned ref receiving this coder's scroll container —
   *  lets an embedding view (PDF/webpage) link its own scrolling to the
   *  plain text (linked position sync). */
  scrollElRef?: React.MutableRefObject<HTMLElement | null>;
  /** Force-hide this coder's own memo gutter + bubble — used when an
   *  embedding view renders its own gutter anchored to the primary pane
   *  (PDF/webpage), so only one memo column is shown. */
  suppressGutter?: boolean;
}) {
  const { t } = useI18n();
  const storeCodeTree = useProjectStore((s) => s.codeTree);
  const hiddenCodes = useCoderStore((s) => s.hiddenCodes);
  /** When OFF, creating a coding does NOT auto-select it in the details bar. */
  const autoShowDetails = usePrefsStore((s) => s.autoShowSegmentDetails);

  const [source, setSource] = useState<Source | null>(null);
  const [localCodings, setLocalCodings] = useState<Coding[]>([]);
  const [localAnnotations, setLocalAnnotations] = useState<Annotation[]>([]);
  const [localCodes, setLocalCodes] = useState<CodeTreeItem[]>([]);
  const controlled = onCodingsChange !== undefined;
  const codings = useMemo(
    () => (controlled ? (codingsProp ?? []) : localCodings),
    [controlled, codingsProp, localCodings],
  );
  const annotations = useMemo(
    () => (controlled ? (annotationsProp ?? []) : localAnnotations),
    [controlled, annotationsProp, localAnnotations],
  );
  const codes = useMemo(
    () => (controlled ? (codesProp ?? []) : localCodes),
    [controlled, codesProp, localCodes],
  );
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const [selection, setSelection] = useState<SelectionOffsets | null>(null);
  const [toolbarPos, setToolbarPos] = useState<{ left: number; top: number } | null>(null);

  const [selectedSeg, setSelectedSeg] = useState<RenderedSegment | null>(null);
  const [selectedAnnSeg, setSelectedAnnSeg] = useState<AnnotationSegment | null>(null);

  /** Outgoing links of this file — markers + jump targets. */
  const [links, setLinks] = useState<SegmentLink[]>([]);

  /** A jump target for ANOTHER file opened via the qc:jump-span event. */
  const [pendingFlash, setPendingFlash] = useState<PendingJump | null>(null);

  const [editMode, setEditMode] = useState(false);
  const [editText, setEditText] = useState("");
  const [draftPositions, setDraftPositions] = useState<DraftPositions | null>(null);
  const [saving, setSaving] = useState(false);

  const [autoOpen, setAutoOpen] = useState(false);

  const [gutterVisible, toggleGutter] = useGutterVisible();

  const [bookmarkFileId, setBookmarkFileId] = useState<number | null>(null);
  const [bookmarkPos, setBookmarkPos] = useState<number | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const textRef = useRef<HTMLDivElement | null>(null);
  const editAreaRef = useRef<HTMLTextAreaElement | null>(null);
  const draftRef = useRef<DraftPositions & { lastText: string }>({
    lastText: "",
    codings: [],
    annotations: [],
  });
  const shiftTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const shiftSeqRef = useRef(0);

  /* Segment flash highlight ("show this segment" from the code inspector):
     a pending gotoSegment scrolls the segment into view and flashes it. */
  const [flashCtid, setFlashCtid] = useState<number | null>(null);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const gotoSegment = useInspectorStore((s) => s.gotoSegment);

  /** Short accent pulse on the JUST-created coding — independent from the
   *  inspector jump flash, so every new mark visibly lands in place. */
  const [newCtid, setNewCtid] = useState<number | null>(null);
  const newTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** Scroll ONLY this coder's own scroll container so `el` is centered.
   *  scrollIntoView would also scroll every scrollable ancestor (the app
   *  shell, the window), shifting unrelated panes — e.g. it made the PDF
   *  sync button look like it moved the whole workspace. */
  function scrollOwnContainerTo(el: HTMLElement) {
    const scrollEl = scrollRef.current;
    if (!scrollEl) return;
    const elRect = el.getBoundingClientRect();
    const cRect = scrollEl.getBoundingClientRect();
    const delta = elRect.top - cRect.top - scrollEl.clientHeight / 2 + elRect.height / 2;
    scrollEl.scrollTo({ top: Math.max(0, scrollEl.scrollTop + delta), behavior: "smooth" });
  }

  useEffect(() => {
    if (!gotoSegment) return;
    // The codings arrive async — wait until the segment's span is rendered.
    const el =
      gotoSegment.ctid != null
        ? scrollRef.current?.querySelector(`[data-ctid="${gotoSegment.ctid}"]`)
        : null;
    if (!el) return;
    scrollOwnContainerTo(el as HTMLElement);
    // Reset first so repeat clicks re-trigger the flash animation.
    setFlashCtid(null);
    requestAnimationFrame(() => setFlashCtid(gotoSegment.ctid));
    if (flashTimer.current) clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlashCtid(null), 2000);
    useInspectorStore.getState().setGotoSegment(null);
  }, [gotoSegment, codings]);

  useEffect(
    () => () => {
      if (flashTimer.current) clearTimeout(flashTimer.current);
      if (newTimer.current) clearTimeout(newTimer.current);
    },
    [],
  );

  /** Scroll the span [pos0, pos1) into view and flash it (link jumps). */
  function flashSpanAt(pos0: number, pos1: number) {
    const container = textRef.current;
    const scrollEl = scrollRef.current;
    if (!container) return;
    const el = elementAtTextPos(container, pos0);
    if (el) {
      scrollOwnContainerTo(el);
      el.classList.add("qc-seg-flash");
      if (flashTimer.current) clearTimeout(flashTimer.current);
      flashTimer.current = setTimeout(() => el.classList.remove("qc-seg-flash"), 2000);
      return;
    }
    // The span lies in plain (uncoded) text — scroll the document there.
    const len = source?.fulltext?.length ?? 0;
    if (scrollEl && scrollEl.scrollHeight > 0 && len > 0) {
      const ratio = Math.max(0, Math.min(1, (pos0 + pos1) / 2 / len));
      scrollEl.scrollTop = ratio * (scrollEl.scrollHeight - scrollEl.clientHeight);
    }
  }

  // Link jumps: react to qc:jump-span events. For another file the coder
  // view switches and its freshly mounted TextCoder claims the pending jump.
  useEffect(() => {
    const handleJump = (e: Event) => {
      const detail = (e as CustomEvent<{ fid: number; pos0: number; pos1: number }>).detail;
      if (!detail) return;
      if (detail.fid !== sourceId) {
        useWorkspaceStore.getState().setView({ kind: "coding", sourceId: detail.fid });
        return;
      }
      setPendingFlash({ fid: detail.fid, pos0: detail.pos0, pos1: detail.pos1 });
    };
    window.addEventListener("qc:jump-span", handleJump);
    const pending = consumePendingJump(sourceId);
    if (pending) setPendingFlash(pending);
    return () => window.removeEventListener("qc:jump-span", handleJump);
  }, [sourceId]);

  // PDF "link text/PDF position": scroll the plain text to the location that
  // corresponds to the current PDF page (pos0 sent by PdfCoder).
  useEffect(() => {
    const handleSync = (e: Event) => {
      const detail = (e as CustomEvent<{ pos0: number }>).detail;
      if (!detail || typeof detail.pos0 !== "number") return;
      setPendingFlash({ fid: sourceId, pos0: detail.pos0, pos1: detail.pos0 });
    };
    window.addEventListener("qc:pdf-sync-plain", handleSync);
    return () => window.removeEventListener("qc:pdf-sync-plain", handleSync);
  }, [sourceId]);

  // Flash once the target text is actually rendered (mounting a file loads
  // its text asynchronously, so the effect re-runs when `text` arrives).
  useEffect(() => {
    if (!pendingFlash || !source?.fulltext) return;
    const timer = setTimeout(() => {
      flashSpanAt(pendingFlash.pos0, pendingFlash.pos1);
      setPendingFlash(null);
    }, 0);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingFlash, source?.fulltext]);

  const text = textOverride ?? source?.fulltext ?? "";
  const unsaved = editMode && editText !== text;

  /* ---------------------------------------------------------------- load */

  // NOTE: this coder deliberately does NOT use the shared `useCoder` hook —
  // its load owns the source fetch + annotations, is conditional in
  // controlled mode, and resets most coder state on every run, so it stays
  // bespoke here.

  const refreshCodings = useCallback(async (): Promise<Coding[]> => {
    const next = await api.sourceCoding(sourceId);
    if (controlled) onCodingsChange?.(next);
    else setLocalCodings(next);
    return next;
  }, [sourceId, controlled, onCodingsChange]);

  const refreshAnnotations = useCallback(async () => {
    const next = await api.fileAnnotations(sourceId);
    if (controlled) onAnnotationsChange?.(next);
    else setLocalAnnotations(next);
  }, [sourceId, controlled, onAnnotationsChange]);

  const refreshSource = useCallback(async () => {
    setSource(await api.getSource(sourceId));
  }, [sourceId]);

  const refreshCodes = useCallback(async () => {
    const next = await api.codesFlat();
    if (controlled) onCodesChange?.(next);
    else setLocalCodes(next);
  }, [controlled, onCodesChange]);

  /* ------------------------------------------------- memo gutter / bubble */

  // Shared mutation actions (memo/weight/important/delete) with a
  // recoverable-delete undo stack — deletes confirm AND push here.
  const actions = useSegmentActions({
    kind: "text",
    rows: codings,
    idOf: (r) => r.ctid,
    deleteRow: (ctid) => api.deleteTextCoding(ctid),
    refresh: refreshCodings,
    onError: setErrMsg,
    onDeleted: () => {
      setSelectedSeg(null);
      setSelectedAnnSeg(null);
    },
  });
  const { undo } = actions;

  useAsyncEffect(async (signal) => {
    setLoading(true);
    setLoadError(null);
    setSource(null);
    setEditMode(false);
    setEditText("");
    setDraftPositions(null);
    draftRef.current = { lastText: "", codings: [], annotations: [] };
    setSelection(null);
    setToolbarPos(null);
    setSelectedSeg(null);
    setSelectedAnnSeg(null);
    setNewCtid(null);
    undo.clear();
    setAutoOpen(false);
    if (!controlled) {
      setLocalCodings([]);
      setLocalAnnotations([]);
      setLocalCodes([]);
    }
    try {
      const src = await api.getSource(sourceId);
      signal.throwIfAborted();
      setSource(src);
      if (!controlled) {
        const [cod, anns, flat] = await Promise.all([
          api.sourceCoding(sourceId),
          api.fileAnnotations(sourceId),
          api.codesFlat(),
        ]);
        signal.throwIfAborted();
        setLocalCodings(cod);
        setLocalAnnotations(anns);
        setLocalCodes(flat);
      }
    } catch (e) {
      signal.throwIfAborted();
      setLoadError(errorMessage(e, t("coder.loadError")));
    } finally {
      signal.throwIfAborted();
      setLoading(false);
    }
  }, [sourceId, reloadTick, t, controlled, undo]);

  // History undo/redo: reload codings/annotations when the audit log reverts
  // a change (the shell only refreshes project metadata).
  useCodingsChanged(() => {
    void refreshCodings();
    void refreshAnnotations();
  });

  const refreshLinks = useCallback(async () => {
    setLinks(await fetchOutgoingLinks(sourceId));
  }, [sourceId]);

  // Outgoing links of this file — markers + jump targets.
  useAsyncEffect(async (signal) => {
    try {
      setLinks(await fetchOutgoingLinks(sourceId));
    } catch {
      signal.throwIfAborted();
      setLinks([]);
    }
  }, [sourceId, reloadTick]);

  /* ------------------------------------------------------------- bookmark */

  useAsyncEffect(async (signal) => {
    try {
      const b = await api.bookmarks();
      signal.throwIfAborted();
      setBookmarkFileId(b.bookmark_file_id);
      setBookmarkPos(b.bookmark_pos);
    } catch {
      /* a bookmark fetch failure should not disturb the coder */
    }
  }, [sourceId]);

  async function setBookmark() {
    if (!source) return;
    const scrollEl = scrollRef.current;
    const ratio =
      scrollEl && scrollEl.scrollHeight > 0
        ? scrollEl.scrollTop / (scrollEl.scrollHeight - scrollEl.clientHeight)
        : 0;
    const pos = Math.round(ratio * text.length);
    try {
      const b = await api.setBookmark(source.id, pos);
      setBookmarkFileId(b.bookmark_file_id);
      setBookmarkPos(b.bookmark_pos);
    } catch {
      setErrMsg(t("coder.bookmarkSet"));
    }
  }

  async function goBookmark() {
    if (bookmarkFileId == null || !source) return;
    if (bookmarkFileId === source.id) {
      const scrollEl = scrollRef.current;
      if (scrollEl && scrollEl.scrollHeight > 0) {
        const ratio = text.length > 0 ? (bookmarkPos ?? 0) / text.length : 0;
        scrollEl.scrollTop = ratio * (scrollEl.scrollHeight - scrollEl.clientHeight);
      }
    } else {
      useWorkspaceStore.getState().setView({ kind: "coding", sourceId: bookmarkFileId });
    }
  }

  /* ------------------------------------------------------------- derived */

  const { byId: codeById } = useCodeIndex(codes);

  const colorByCid = useMemo(() => {
    const m: Record<number, string> = {};
    for (const [id, c] of codeById) m[id] = c.color ?? FALLBACK_CODE_COLOR;
    return m;
  }, [codeById]);

  const segments = useMemo(
    () => buildRenderedSegments(text, codings, colorByCid),
    [text, codings, colorByCid],
  );

  const annSegments = useMemo(
    () => buildAnnotationSegments(text, annotations),
    [text, annotations],
  );

  const editSegments = useMemo(
    () =>
      draftPositions ? buildRenderedSegments(editText, draftPositions.codings, colorByCid) : [],
    [draftPositions, editText, colorByCid],
  );

  const editAnnSegments = useMemo(
    () => (draftPositions ? buildAnnotationSegments(editText, draftPositions.annotations) : []),
    [draftPositions, editText],
  );

  const annRows = useMemo(
    () =>
      selectedAnnSeg
        ? selectedAnnSeg.anids
            .map((anid) => annotations.find((a) => a.anid === anid))
            .filter((a): a is Annotation => Boolean(a))
        : [],
    [selectedAnnSeg, annotations],
  );

  /* ------------------------------------------------ memo gutter / bubble */

  const gutterRows = useMemo(
    () =>
      codings.map((c) =>
        toGutterRow(
          {
            id: c.ctid,
            kind: "text",
            memo: c.memo,
            weight: (c as Coding & { weight?: number }).weight,
            important: c.important,
            date: c.date,
            seltext: c.seltext,
          },
          codeById.get(c.cid),
          t("coder.fallbackCode", { id: c.cid }),
        ),
      ),
    [codings, codeById, t],
  );

  const selectedIds = useMemo(() => selectedSeg?.ctids ?? [], [selectedSeg]);

  const selectedBubbleRows = useMemo(
    () => gutterRows.filter((r) => selectedIds.includes(r.id)),
    [gutterRows, selectedIds],
  );

  const anchorOf = useCallback(
    (ctid: number) => scrollRef.current?.querySelector<HTMLElement>(`[data-ctids~="${ctid}"]`) ?? null,
    [],
  );

  const handleGutterSelect = useCallback(
    (ctid: number) => {
      const seg = segments.find((s) => s.ctids.includes(ctid));
      if (seg) {
        setSelectedSeg(seg);
        setSelectedAnnSeg(null);
      }
    },
    [segments],
  );

  const handleGutterDeselect = useCallback(() => setSelectedSeg(null), []);

  /* ------------------------------------------------------------ selection */

  const clearSelection = useCallback(() => {
    window.getSelection()?.removeAllRanges();
    setSelection(null);
    setToolbarPos(null);
  }, []);

  /** Hide only the floating popup — the selection survives (outside click). */
  const hideToolbar = useCallback(() => {
    setToolbarPos(null);
  }, []);

  function handleDocMouseUp() {
    if (editMode) return;
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
      hideToolbar();
      return;
    }
    const container = textRef.current;
    if (!container) return;
    const offsets = getSelectionOffsets(container, sel);
    if (!offsets) {
      hideToolbar();
      return;
    }
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    const scrollRect = scrollRef.current?.getBoundingClientRect();
    setToolbarPos(clampToolbarAnchor(rect, scrollRect));
    setSelection(offsets);
  }

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => hideToolbar();
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [hideToolbar]);

  useEffect(() => {
    const onBlur = () => hideToolbar();
    window.addEventListener("blur", onBlur);
    return () => window.removeEventListener("blur", onBlur);
  }, [hideToolbar]);

  // Escape dismisses the toolbar and the segment details (the selection
  // toolbar closes its own popovers first via its capture-phase handler).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setToolbarPos(null);
      setSelectedSeg(null);
      setSelectedAnnSeg(null);
      clearSelection();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [clearSelection]);

  /* ----------------------------------------------------------- coding flow */

  /** Select the details for a freshly created coding: locate the rendered
   *  segment covering its span and show it in the footer/gutter. Gated on
   *  the "Auto-show segment details" pref — when OFF, creating a coding does
   *  not open the bar, but if the memo gutter is open the new segment is
   *  still selected so its empty memo card appears in the gutter until
   *  deselected. */
  function selectCreatedSegment(created: Coding, next: Coding[]) {
    // The freshly coded span always pulses so the mark visibly lands.
    setNewCtid(created.ctid);
    if (newTimer.current) clearTimeout(newTimer.current);
    newTimer.current = setTimeout(() => setNewCtid(null), 1000);
    const gutterOpen = gutterVisible && !suppressGutter;
    if (!autoShowDetails && !gutterOpen) {
      setSelectedSeg(null);
      setSelectedAnnSeg(null);
      return;
    }
    const seg = buildRenderedSegments(text, next, colorByCid).find((s) =>
      s.ctids.includes(created.ctid),
    );
    if (seg) {
      setSelectedAnnSeg(null);
      setSelectedSeg(seg);
    }
  }

  /* ------------------------------------------------- memo gutter / bubble */

  const updateGutterMemo = actions.updateMemo;
  const updateGutterWeight = actions.updateWeight;
  const toggleGutterImportant = actions.toggleImportant;

  function deleteGutterCoding(ctid: number) {
    const row = codings.find((c) => c.ctid === ctid);
    if (
      !window.confirm(
        t("coder.removeConfirm", {
          name: codeById.get(row?.cid ?? -1)?.name ?? t("coder.fallbackCodeLower", { id: ctid }),
        }),
      )
    )
      return;
    actions.remove(ctid);
  }

  /* ------------------------------------------------------------- annotations */

  function updateAnnotationMemo(anid: number, memo: string) {
    void (async () => {
      try {
        await api.updateAnnotation(anid, memo);
        await refreshAnnotations();
      } catch (e) {
        setErrMsg(errorMessage(e, t("coder.annotationUpdateError")));
      }
    })();
  }

  function deleteAnnotation(ann: Annotation) {
    void (async () => {
      try {
        await api.deleteAnnotation(ann.anid);
        setSelectedAnnSeg(null);
        await refreshAnnotations();
      } catch (e) {
        setErrMsg(errorMessage(e, t("coder.annotationDeleteError")));
      }
    })();
  }

  /* ------------------------------------------- selection toolbar callbacks */

  /** A coding was just created (text or in-vivo): refresh the code tree and
   *  auto-select the new segment per the "Auto-show segment details" pref. */
  function handleToolbarCoded(created: Coding, next: Coding[]) {
    void refreshCodes().catch(() => undefined);
    selectCreatedSegment(created, next);
  }

  /** Non-coding mutations (annotation, link, QTT): refresh the rest. */
  const handleToolbarChanged = useCallback(() => {
    void refreshAnnotations();
    void refreshCodes().catch(() => undefined);
    void refreshLinks();
  }, [refreshAnnotations, refreshCodes, refreshLinks]);

  /* --------------------------------------------------------------- edit mode */

  function startEditMode() {
    if (!source) return;
    const full = source.fulltext ?? "";
    setEditText(full);
    draftRef.current = { lastText: full, codings, annotations };
    setDraftPositions({ codings, annotations });
    setEditMode(true);
    setSelectedSeg(null);
    setSelectedAnnSeg(null);
    clearSelection();
  }

  function exitEditMode() {
    setEditMode(false);
    setEditText("");
    setDraftPositions(null);
    draftRef.current = { lastText: "", codings: [], annotations: [] };
    if (shiftTimer.current) {
      clearTimeout(shiftTimer.current);
      shiftTimer.current = null;
    }
    shiftSeqRef.current += 1;
  }

  function toggleEditMode() {
    if (!editMode) {
      startEditMode();
      return;
    }
    if (unsaved && !window.confirm(t("coder.discardConfirm"))) return;
    exitEditMode();
  }

  function autosizeEditArea() {
    const el = editAreaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }

  useEffect(() => {
    if (editMode) autosizeEditArea();
  }, [editMode, editText]);

  useEffect(() => {
    return () => {
      if (shiftTimer.current) clearTimeout(shiftTimer.current);
    };
  }, []);

  function onEditChange(e: ChangeEvent<HTMLTextAreaElement>) {
    const v = e.target.value;
    setEditText(v);
    if (shiftTimer.current) clearTimeout(shiftTimer.current);
    shiftTimer.current = setTimeout(() => void runShift(v), 400);
  }

  async function runShift(newText: string) {
    const { lastText, codings: baseCodings, annotations: baseAnnotations } = draftRef.current;
    if (newText === lastText) return;
    const seq = ++shiftSeqRef.current;
    try {
      const res = await api.shiftPositions({
        prev_text: lastText,
        new_text: newText,
        codings: baseCodings.map((c) => ({ ctid: c.ctid, pos0: c.pos0, pos1: c.pos1 })),
        annotations: baseAnnotations.map((a) => ({ anid: a.anid, pos0: a.pos0, pos1: a.pos1 })),
        case_text: [],
      });
      if (seq !== shiftSeqRef.current) return;
      const next: DraftPositions & { lastText: string } = {
        lastText: newText,
        codings: applyCodingShifts(baseCodings, res),
        annotations: applyAnnotationShifts(baseAnnotations, res),
      };
      draftRef.current = next;
      setDraftPositions({ codings: next.codings, annotations: next.annotations });
    } catch {
      /* transient; the next keystroke retries with the same lastText */
    }
  }

  function saveEdit() {
    setSaving(true);
    setErrMsg(null);
    void (async () => {
      try {
        await api.commitEdit({ fid: sourceId, new_text: editText });
        exitEditMode();
        await refreshSource();
        await refreshCodings();
        await refreshAnnotations();
      } catch (e) {
        setErrMsg(errorMessage(e, t("coder.saveError")));
      } finally {
        setSaving(false);
      }
    })();
  }

  /* ---------------------------------------------------------------- autocode */

  function handleAutocodeDone() {
    void refreshCodings();
    void refreshCodes().catch(() => undefined);
  }

  /* --------------------------------------------------------------- rendering */

  function wrapColors(seg: RenderedSegment, content: string): ReactNode {
    const colors = seg.colors.length > 0 ? seg.colors : [FALLBACK_CODE_COLOR];
    return colors.reduceRight<ReactNode>(
      (inner, color, idx) => (
        <span
          key={`${color}-${idx}`}
          className="rounded-sm"
          style={{ backgroundColor: softBackground(color) }}
        >
          {inner}
        </span>
      ),
      content,
    );
  }

  function renderCodedText(): ReactNode[] {
    const out: ReactNode[] = [];
    let pos = 0;
    segments.forEach((seg, i) => {
      if (seg.start > pos) out.push(text.slice(pos, seg.start));
      const rows = seg.ctids
        .map((ctid) => codings.find((c) => c.ctid === ctid))
        .filter((c): c is Coding => Boolean(c));
      const title = rows
        .map((r) => {
          const code = codeById.get(r.cid);
          const name = code?.name ?? t("coder.fallbackCode", { id: r.cid });
          return r.memo ? `${name} — ${r.memo}` : name;
        })
        .join(" | ");
      const hidden = rows.some((r) => hiddenCodes.includes(r.cid));
      // Links anchored inside this atomic segment: wavy underline + a
      // clickable marker after the segment text (zero-text inline node, so
      // selection offsets stay aligned with the document text).
      const segLinks = links.filter((l) => l.from_pos0 >= seg.start && l.from_pos0 < seg.end);
      out.push(
        <span
          key={`seg-${i}-${seg.start}`}
          data-ctid={seg.ctids[0]}
          data-ctids={seg.ctids.join(" ")}
          className={`cursor-pointer rounded-sm qc-seg ${hidden ? "qc-seg-hidden" : ""} ${
            flashCtid != null && seg.ctids.includes(flashCtid) ? "qc-seg-flash" : ""
          } ${
            newCtid != null && seg.ctids.includes(newCtid) ? "qc-seg-new" : ""
          } ${
            segLinks.length > 0
              ? "underline decoration-wavy decoration-accent/60 underline-offset-2"
              : ""
          }`}
          title={title}
          onClick={() => {
            setSelectedSeg(seg);
            setSelectedAnnSeg(null);
            // Choosing a code occasion also shows its details in the right-bar
            // Inspector (not just the bottom details bar).
            const first = seg.ctids
              .map((ctid) => codings.find((c) => c.ctid === ctid))
              .find(Boolean);
            if (first) void useInspectorStore.getState().selectCode(first.cid);
          }}
        >
          {wrapColors(seg, text.slice(seg.start, seg.end))}
        </span>,
      );
      for (const link of segLinks) {
        out.push(
          <button
            key={`link-marker-${link.id}`}
            type="button"
            data-link-id={link.id}
            title={t("coder.linkJumpTo", { file: link.to_name })}
            aria-label={t("coder.linkAria", { file: link.to_name })}
            onClick={(e) => {
              e.stopPropagation();
              jumpToSpan(link.to_fid, link.to_pos0, link.to_pos1);
            }}
            className="ml-0.5 inline-flex h-3.5 w-3.5 shrink-0 translate-y-[-1px] items-center justify-center rounded-sm border border-border bg-surface align-middle text-accent hover:bg-accent/10"
          >
            <LinkIcon size={9} aria-hidden />
          </button>,
        );
      }
      pos = seg.end;
    });
    if (pos < text.length) out.push(text.slice(pos));
    return out;
  }

  function annotationTitle(seg: AnnotationSegment): string {
    return seg.anids
      .map((anid) => annotations.find((a) => a.anid === anid))
      .filter((a): a is Annotation => Boolean(a))
      .map((a) => a.memo || t("coder.annotationFallback"))
      .join(" | ");
  }

  function renderAnnotationLayer(): ReactNode[] {
    // Render ONLY the annotated fragments — the plain text is already shown
    // by the coded layer. (Rendering the full text again duplicated it in
    // the document and skewed selection offsets past the real text length.)
    return annSegments.map((seg) => (
      <span
        key={`ann-${seg.start}`}
        className="cursor-pointer rounded-sm underline decoration-dashed decoration-text-secondary underline-offset-2"
        title={annotationTitle(seg)}
        onClick={() => {
          setSelectedAnnSeg(seg);
          setSelectedSeg(null);
        }}
      >
        {text.slice(seg.start, seg.end)}
      </span>
    ));
  }

  function renderEditCodingOverlay(): ReactNode[] {
    const out: ReactNode[] = [];
    let pos = 0;
    for (const seg of editSegments) {
      if (seg.start > pos) out.push(editText.slice(pos, seg.start));
      out.push(
        <span key={`eseg-${seg.start}`} className="rounded-sm">
          {wrapColors(seg, editText.slice(seg.start, seg.end))}
        </span>,
      );
      pos = seg.end;
    }
    if (pos < editText.length) out.push(editText.slice(pos));
    return out;
  }

  function renderEditAnnotationOverlay(): ReactNode[] {
    const out: ReactNode[] = [];
    let pos = 0;
    for (const seg of editAnnSegments) {
      if (seg.start > pos) out.push(editText.slice(pos, seg.start));
      out.push(
        <span
          key={`eann-${seg.start}`}
          className="underline decoration-dashed decoration-text-secondary underline-offset-2"
        >
          {editText.slice(seg.start, seg.end)}
        </span>,
      );
      pos = seg.end;
    }
    if (pos < editText.length) out.push(editText.slice(pos));
    return out;
  }

  /* ------------------------------------------------------------------- body */

  if (loading) {
    return <LoadingState>{t("coder.loading")}</LoadingState>;
  }

  if (loadError) {
    return <LoadError message={loadError} onRetry={() => setReloadTick((t) => t + 1)} />;
  }

  if (!source) return null;

  if (!forceText) {
    if (usesPdfCoder(source)) {
      return (
        <div className="flex h-full items-center justify-center bg-bg">
          <div className="max-w-md text-center">
            <h2 className="text-lg font-semibold text-text-primary">{t("coder.unsupportedTitle")}</h2>
            <p className="mt-2 text-sm text-text-secondary">{t("coder.pdfUnsupported")}</p>
          </div>
        </div>
      );
    }
    if (source.media_type !== "text") {
      return (
        <div className="flex h-full items-center justify-center bg-bg">
          <div className="max-w-md text-center">
            <h2 className="text-lg font-semibold text-text-primary">{t("coder.unsupportedTitle")}</h2>
            <p className="mt-2 text-sm text-text-secondary">{t("coder.typeUnsupported")}</p>
          </div>
        </div>
      );
    }
  }

  return (
    <div className="flex h-full flex-col bg-bg">
      {!bare && (
        <ViewHeader
          wrap
          title={source.name}
          meta={source.memo}
          actions={
            <>
              {saving && (
                <span className="flex items-center gap-1 text-xs text-text-secondary" role="status">
                  <LoaderCircle size={12} className="animate-spin" aria-hidden />
                  {t("coder.saving")}
                </span>
              )}
              {editMode ? (
                <>
                  <Button
                    variant="primary"
                    icon={<Save size={12} aria-hidden />}
                    onClick={saveEdit}
                    disabled={saving}
                  >
                    {t("common.save")}
                  </Button>
                  <Button
                    variant="secondary"
                    icon={unsaved ? <CircleAlert size={12} aria-hidden /> : <X size={12} aria-hidden />}
                    onClick={toggleEditMode}
                    disabled={saving}
                  >
                    {unsaved ? t("coder.discard") : t("common.cancel")}
                  </Button>
                </>
              ) : (
                <>
                  {onExitPlainText && (
                    <Button variant="secondary" icon={<Rows3 size={12} aria-hidden />} onClick={onExitPlainText}>
                      {t("pdfCoder.renderedMode")}
                    </Button>
                  )}
                  <Button variant="secondary" icon={<FilePen size={12} aria-hidden />} onClick={toggleEditMode}>
                    {t("coder.editMode")}
                  </Button>
                  <IconButton
                    label={t("coder.bookmarkSet")}
                    title={t("coder.bookmarkSet")}
                    onClick={() => void setBookmark()}
                    className={cn(bookmarkFileId === source.id && "text-accent")}
                  >
                    <Bookmark
                      size={16}
                      className={bookmarkFileId === source.id ? "fill-current" : ""}
                      aria-hidden
                    />
                  </IconButton>
                  <IconButton
                    label={t("coder.bookmarkGo")}
                    title={t("coder.bookmarkGoTitle")}
                    onClick={() => void goBookmark()}
                    disabled={bookmarkFileId == null}
                  >
                    <BookmarkCheck size={16} aria-hidden />
                  </IconButton>
              <Button
                variant="toolbar"
                icon={<Undo2 size={12} aria-hidden />}
                onClick={undo.undoLast}
                disabled={!undo.canUndo}
                title={t("coder.unmarkTitle")}
              >
                {t("coder.unmarkLast")}
              </Button>
                  <Button
                    variant="secondary"
                    icon={<Sparkles size={12} aria-hidden />}
                    onClick={() => setAutoOpen((o) => !o)}
                    className={cn(autoOpen && "border-accent text-accent")}
                  >
                    {t("coder.autocode")}
                  </Button>
                  <Button
                    variant="secondary"
                    icon={<MessageSquareText size={12} aria-hidden />}
                    onClick={toggleGutter}
                    className={cn(gutterVisible && "border-accent text-accent")}
                    title={gutterVisible ? t("coder.hideMemos") : t("coder.showMemos")}
                  >
                    {t("coder.memos")}
                  </Button>
                </>
              )}
            </>
          }
        />
      )}

      {errMsg && <ErrorBanner onClose={() => setErrMsg(null)}>{errMsg}</ErrorBanner>}

      <AutocodeDialog
        open={autoOpen}
        onClose={() => setAutoOpen(false)}
        fid={sourceId}
        codes={storeCodeTree}
        onDone={handleAutocodeDone}
      />

      <div
        ref={(el) => {
          scrollRef.current = el;
          if (scrollElRef) scrollElRef.current = el;
        }}
        onMouseUp={handleDocMouseUp}
        className="min-h-0 flex-1 overflow-y-auto bg-bg"
      >
        <div className="flex">
          <div className="flex-1 p-6">
            {editMode ? (
              <div className="relative">
                <textarea
                  ref={editAreaRef}
                  value={editText}
                  onChange={onEditChange}
                  onKeyDown={(e) => {
                    if ((e.ctrlKey || e.metaKey) && e.key === "s") {
                      e.preventDefault();
                      saveEdit();
                    }
                  }}
                  spellCheck={false}
                  aria-label={t("coder.editAria")}
                  className={cn(
                    DOC_FONT_CLS,
                    "relative z-10 block w-full resize-none overflow-hidden bg-transparent p-0 text-transparent caret-text-primary outline-none",
                  )}
                />
                <div
                  aria-hidden
                  className={cn(
                    DOC_FONT_CLS,
                    "pointer-events-none absolute inset-0 z-0 overflow-hidden text-text-primary",
                  )}
                >
                  {renderEditCodingOverlay()}
                </div>
                <div
                  aria-hidden
                  className={cn(
                    DOC_FONT_CLS,
                    "pointer-events-none absolute inset-0 z-0 overflow-hidden text-transparent",
                  )}
                >
                  {renderEditAnnotationOverlay()}
                </div>
              </div>
            ) : (
              <div ref={textRef} className={DOC_FONT_CLS}>
                {renderCodedText()}
                {renderAnnotationLayer()}
              </div>
            )}
          </div>
          {!editMode && (
            <MemoGutter
              rows={gutterRows}
              selectedIds={selectedIds}
              scrollRef={scrollRef}
              anchorOf={anchorOf}
              onSelect={handleGutterSelect}
              onDeselect={handleGutterDeselect}
              onUpdateMemo={updateGutterMemo}
              onUpdateWeight={updateGutterWeight}
              onToggleImportant={toggleGutterImportant}
              onDelete={deleteGutterCoding}
              visible={gutterVisible && !suppressGutter}
            />
          )}
        </div>
      </div>

      {!editMode && !gutterVisible && selectedBubbleRows.length > 0 && (
        <MemoGutterBubble
          rows={selectedBubbleRows}
          scrollRef={scrollRef}
          anchorOf={anchorOf}
          onClose={handleGutterDeselect}
          onUpdateMemo={updateGutterMemo}
          onUpdateWeight={updateGutterWeight}
          onDelete={deleteGutterCoding}
        />
      )}

      {!editMode && annRows.length > 0 && (
        <AnnotationDetailsBar
          rows={annRows}
          onUpdateMemo={updateAnnotationMemo}
          onDelete={deleteAnnotation}
          onClose={() => setSelectedAnnSeg(null)}
        />
      )}

      <SelectionToolbar
        anchor={toolbarPos}
        selection={
          selection
            ? { pos0: selection.start, pos1: selection.end, text: text.slice(selection.start, selection.end) }
            : null
        }
        fid={sourceId}
        codes={codes}
        refreshCodings={refreshCodings}
        onCoded={handleToolbarCoded}
        onChanged={handleToolbarChanged}
        onHide={hideToolbar}
        onClose={clearSelection}
        onError={(msg) => setErrMsg(msg)}
      />
    </div>
  );
}
