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
import {
  Bookmark,
  BookmarkCheck,
  Check,
  CircleAlert,
  Code,
  FilePen,
  Link as LinkIcon,
  LoaderCircle,
  Pencil,
  Rows3,
  Save,
  ScrollText,
  Sparkles,
  Star,
  StickyNote,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import {
  Button,
  ErrorBanner,
  IconButton,
  LoadingState,
  Textarea,
  ViewHeader,
} from "@/components/ui/orchestrator";
import { AutocodeDialog } from "@/features/coding/AutocodeDialog";
import {
  api,
  type Annotation,
  type CodeTreeItem,
  type Coding,
  type ShiftPositionsResponse,
  type Source,
} from "@/lib/api";
import { CodePicker, type PickedCode } from "@/features/coding/CodePicker";
import {
  buildAnnotationSegments,
  buildRenderedSegments,
  type AnnotationSegment,
  type RenderedSegment,
} from "@/features/coding/segments";
import { getSelectionOffsets, type SelectionOffsets } from "@/features/coding/selection";
import { codeTint } from "@/features/coding/tint";
import {
  consumePendingJump,
  copyLinkPayload,
  createLink,
  fetchOutgoingLinks,
  jumpToSpan,
  readLinkPayload,
  type LinkSpanTarget,
  type PendingJump,
  type SegmentLink,
} from "@/features/coding/links";
import { usesPdfCoder } from "@/lib/media";
import { cn } from "@/lib/utils";
import { cls } from "@/components/ui/tokens";
import { Menu, MenuItem } from "@/components/ui/orchestrator";
import { listQttSheets, sendSegmentToQtt, type QttSheet } from "@/lib/qttApi";
import { useI18n } from "@/lib/i18n";
import { useProjectStore } from "@/stores/project";

/** Shared font metrics so the edit-mode textarea and overlay align. */
const DOC_FONT_CLS = "qc-selectable font-sans text-sm leading-6 whitespace-pre-wrap break-words";
const FALLBACK_CODE_COLOR = "var(--qc-accent)";

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
  codings: codingsProp,
  annotations: annotationsProp,
  codes: codesProp,
  onCodingsChange,
  onAnnotationsChange,
  onCodesChange,
}: {
  sourceId: number;
  /** Render the plain text even for PDF sources (PDF "plain text" mode). */
  forceText?: boolean;
  /** When set (PDF plain-text mode), renders a "back to rendered PDF" toggle. */
  onExitPlainText?: () => void;
  /** Omit the view header — renders only the document surface (split view). */
  bare?: boolean;
  /** Controlled mode: the parent owns the codings/annotations/codes state and
   *  is notified of every change, so all panes render from the same arrays. */
  codings?: Coding[];
  annotations?: Annotation[];
  codes?: CodeTreeItem[];
  onCodingsChange?: (codings: Coding[]) => void;
  onAnnotationsChange?: (annotations: Annotation[]) => void;
  onCodesChange?: (codes: CodeTreeItem[]) => void;
}) {
  const { t } = useI18n();
  const storeCodeTree = useProjectStore((s) => s.codeTree);
  const activeCodeId = useProjectStore((s) => s.activeCodeId);
  const hiddenCodes = useProjectStore((s) => s.hiddenCodes);

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
  const [pickerOpen, setPickerOpen] = useState(false);
  const [annotateOpen, setAnnotateOpen] = useState(false);
  const [annotateMemo, setAnnotateMemo] = useState("");

  const [selectedSeg, setSelectedSeg] = useState<RenderedSegment | null>(null);
  const [selectedAnnSeg, setSelectedAnnSeg] = useState<AnnotationSegment | null>(null);
  const [editingAnnMemo, setEditingAnnMemo] = useState<{ anid: number; memo: string } | null>(null);

  /* Segment links: outgoing links of this file (markers), the clipboard
     link payload (paste), and a transient "copied" feedback. */
  const [links, setLinks] = useState<SegmentLink[]>([]);
  const [clipboardLink, setClipboardLink] = useState<LinkSpanTarget | null>(null);
  const [linkCopied, setLinkCopied] = useState(false);
  const linkCopiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* "Send to QTT": pick a worksheet in a small inline menu and store the
     selected span as a segment item (transient "sent" feedback). */
  const [qttOpen, setQttOpen] = useState(false);
  const [qttSheets, setQttSheets] = useState<QttSheet[]>([]);
  const [qttLoading, setQttLoading] = useState(false);
  const [qttSending, setQttSending] = useState<number | null>(null);
  const [qttSent, setQttSent] = useState(false);
  const qttSentTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** A jump target for ANOTHER file opened via the qc:jump-span event. */
  const [pendingFlash, setPendingFlash] = useState<PendingJump | null>(null);

  const [undoStack, setUndoStack] = useState<Coding[]>([]);

  const [editMode, setEditMode] = useState(false);
  const [editText, setEditText] = useState("");
  const [draftPositions, setDraftPositions] = useState<DraftPositions | null>(null);
  const [saving, setSaving] = useState(false);

  const [autoOpen, setAutoOpen] = useState(false);

  const [bookmarkFileId, setBookmarkFileId] = useState<number | null>(null);
  const [bookmarkPos, setBookmarkPos] = useState<number | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const textRef = useRef<HTMLDivElement | null>(null);
  const floatingRef = useRef<HTMLDivElement | null>(null);
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
  const gotoSegment = useProjectStore((s) => s.gotoSegment);

  useEffect(() => {
    if (!gotoSegment) return;
    // The codings arrive async — wait until the segment's span is rendered.
    const el =
      gotoSegment.ctid != null
        ? scrollRef.current?.querySelector(`[data-ctid="${gotoSegment.ctid}"]`)
        : null;
    if (!el) return;
    (el as HTMLElement).scrollIntoView({ block: "center", behavior: "smooth" });
    // Reset first so repeat clicks re-trigger the flash animation.
    setFlashCtid(null);
    requestAnimationFrame(() => setFlashCtid(gotoSegment.ctid));
    if (flashTimer.current) clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlashCtid(null), 2000);
    useProjectStore.getState().setGotoSegment(null);
  }, [gotoSegment, codings]);

  useEffect(
    () => () => {
      if (flashTimer.current) clearTimeout(flashTimer.current);
      if (linkCopiedTimer.current) clearTimeout(linkCopiedTimer.current);
      if (qttSentTimer.current) clearTimeout(qttSentTimer.current);
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
      el.scrollIntoView({ block: "center", behavior: "smooth" });
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
        useProjectStore.getState().setView({ kind: "coding", sourceId: detail.fid });
        return;
      }
      setPendingFlash({ fid: detail.fid, pos0: detail.pos0, pos1: detail.pos1 });
    };
    window.addEventListener("qc:jump-span", handleJump);
    const pending = consumePendingJump(sourceId);
    if (pending) setPendingFlash(pending);
    return () => window.removeEventListener("qc:jump-span", handleJump);
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

  const text = source?.fulltext ?? "";
  const unsaved = editMode && editText !== text;

  /* ---------------------------------------------------------------- load */

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setSource(null);
    setEditMode(false);
    setEditText("");
    setDraftPositions(null);
    draftRef.current = { lastText: "", codings: [], annotations: [] };
    setSelection(null);
    setToolbarPos(null);
    setPickerOpen(false);
    setAnnotateOpen(false);
    setSelectedSeg(null);
    setSelectedAnnSeg(null);
    setEditingAnnMemo(null);
    setUndoStack([]);
    setAutoOpen(false);
    if (!controlled) {
      setLocalCodings([]);
      setLocalAnnotations([]);
      setLocalCodes([]);
    }
    void (async () => {
      try {
        const src = await api.getSource(sourceId);
        if (cancelled) return;
        setSource(src);
        if (!controlled) {
          const [cod, anns, flat] = await Promise.all([
            api.sourceCoding(sourceId),
            api.fileAnnotations(sourceId),
            api.codesFlat(),
          ]);
          if (cancelled) return;
          setLocalCodings(cod);
          setLocalAnnotations(anns);
          setLocalCodes(flat);
        }
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : t("coder.loadError"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sourceId, reloadTick, t, controlled]);

  const refreshCodings = useCallback(async () => {
    const next = await api.sourceCoding(sourceId);
    if (controlled) onCodingsChange?.(next);
    else setLocalCodings(next);
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

  const refreshLinks = useCallback(async () => {
    setLinks(await fetchOutgoingLinks(sourceId));
  }, [sourceId]);

  // Outgoing links of this file — markers + jump targets.
  useEffect(() => {
    let cancelled = false;
    void fetchOutgoingLinks(sourceId)
      .then((ls) => {
        if (!cancelled) setLinks(ls);
      })
      .catch(() => {
        if (!cancelled) setLinks([]);
      });
    return () => {
      cancelled = true;
    };
  }, [sourceId, reloadTick]);

  // Track whether a qcnext-link payload is on the clipboard so the
  // selection toolbar can offer "Paste link here".
  useEffect(() => {
    let cancelled = false;
    void readLinkPayload().then((target) => {
      if (!cancelled) setClipboardLink(target);
    });
    return () => {
      cancelled = true;
    };
  }, [selection]);

  /* ------------------------------------------------------------- bookmark */

  useEffect(() => {
    let cancelled = false;
    void api
      .bookmarks()
      .then((b) => {
        if (!cancelled) {
          setBookmarkFileId(b.bookmark_file_id);
          setBookmarkPos(b.bookmark_pos);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
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
      useProjectStore.getState().setView({ kind: "coding", sourceId: bookmarkFileId });
    }
  }

  /* ------------------------------------------------------------- derived */

  const codeById = useMemo(() => {
    const m = new Map<number, CodeTreeItem>();
    for (const c of codes) if (c.kind === "code") m.set(c.id, c);
    return m;
  }, [codes]);

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

  const segRows = useMemo(
    () =>
      selectedSeg
        ? selectedSeg.ctids
            .map((ctid) => codings.find((c) => c.ctid === ctid))
            .filter((c): c is Coding => Boolean(c))
        : [],
    [selectedSeg, codings],
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

  /* ------------------------------------------------------------ selection */

  function clearSelection() {
    window.getSelection()?.removeAllRanges();
    setSelection(null);
    setToolbarPos(null);
  }

  const hideToolbar = useCallback(() => {
    setToolbarPos(null);
    setAnnotateOpen(false);
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
    const left = scrollRect
      ? Math.min(Math.max(rect.left, scrollRect.left + 4), scrollRect.right - 300)
      : rect.left;
    const top = scrollRect ? Math.min(rect.bottom + 6, scrollRect.bottom - 40) : rect.bottom + 6;
    setSelection(offsets);
    setToolbarPos({ left, top });
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

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (!target) return;
      const insideDoc = scrollRef.current?.contains(target);
      const insideFloating = floatingRef.current?.contains(target);
      if (!insideDoc && !insideFloating) hideToolbar();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [hideToolbar]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (qttOpen) {
        setQttOpen(false);
        return;
      }
      if (pickerOpen) {
        setPickerOpen(false);
        return;
      }
      if (annotateOpen) {
        setAnnotateOpen(false);
        return;
      }
      setToolbarPos(null);
      setSelectedSeg(null);
      setSelectedAnnSeg(null);
      clearSelection();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  /* ----------------------------------------------------------- coding flow */

  /** Code the pending text selection with the given code id. */
  function codeSelection(cid: number) {
    const sel = selection;
    if (!sel) return;
    void (async () => {
      try {
        await api.createTextCoding({
          cid,
          fid: sourceId,
          seltext: text.slice(sel.start, sel.end),
          pos0: sel.start,
          pos1: sel.end,
        });
        await refreshCodings();
      } catch (e) {
        setErrMsg(e instanceof Error ? e.message : t("coder.createError"));
      } finally {
        clearSelection();
      }
    })();
    void refreshCodes().catch(() => undefined);
  }

  // Clicking a code in the left sidebar assigns it to the selected part.
  useEffect(() => {
    const onAssign = (e: Event) => {
      const cid = (e as CustomEvent<{ cid: number }>).detail?.cid;
      if (typeof cid !== "number") return;
      setPickerOpen(false);
      codeSelection(cid);
    };
    window.addEventListener("qc:assign-code", onAssign);
    return () => window.removeEventListener("qc:assign-code", onAssign);
  });

  function handlePickCode(picked: PickedCode) {
    setPickerOpen(false);
    codeSelection(picked.cid);
  }

  function deleteCoding(row: Coding) {
    void (async () => {
      try {
        await api.deleteTextCoding(row.ctid);
        setUndoStack((s) => [...s.slice(-19), row]);
        setSelectedSeg(null);
        await refreshCodings();
      } catch (e) {
        setErrMsg(e instanceof Error ? e.message : t("coder.removeError"));
      }
    })();
  }

  function unmarkLast() {
    const row = undoStack[undoStack.length - 1];
    if (!row) return;
    setUndoStack((s) => s.slice(0, -1));
    void (async () => {
      try {
        await api.undoCodings([row]);
        await refreshCodings();
      } catch (e) {
        setErrMsg(e instanceof Error ? e.message : t("coder.restoreError"));
      }
    })();
  }

  /* ------------------------------------------------------------- annotations */

  function openAnnotate() {
    setAnnotateMemo("");
    setAnnotateOpen(true);
  }

  function saveAnnotation() {
    const sel = selection;
    if (!sel) return;
    void (async () => {
      try {
        await api.createAnnotation({
          fid: sourceId,
          pos0: sel.start,
          pos1: sel.end,
          memo: annotateMemo.trim(),
        });
        await refreshAnnotations();
      } catch (e) {
        setErrMsg(e instanceof Error ? e.message : t("coder.annotationCreateError"));
      } finally {
        setAnnotateOpen(false);
        clearSelection();
      }
    })();
  }

  function updateAnnotationMemo(anid: number, memo: string) {
    void (async () => {
      try {
        await api.updateAnnotation(anid, memo);
        setEditingAnnMemo(null);
        await refreshAnnotations();
      } catch (e) {
        setErrMsg(e instanceof Error ? e.message : t("coder.annotationUpdateError"));
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
        setErrMsg(e instanceof Error ? e.message : t("coder.annotationDeleteError"));
      }
    })();
  }

  /* ------------------------------------------------------------- links */

  function copySegmentLink() {
    const sel = selection;
    if (!sel) return;
    void (async () => {
      try {
        await copyLinkPayload(sourceId, sel.start, sel.end);
        setClipboardLink({ fid: sourceId, pos0: sel.start, pos1: sel.end });
        setLinkCopied(true);
        if (linkCopiedTimer.current) clearTimeout(linkCopiedTimer.current);
        linkCopiedTimer.current = setTimeout(() => setLinkCopied(false), 1500);
      } catch (e) {
        setErrMsg(e instanceof Error ? e.message : t("coder.linkCopyError"));
      }
    })();
  }

  /** Create one link from the current selection to the copied segment. */
  function pasteSegmentLink() {
    const sel = selection;
    const target = clipboardLink;
    if (!sel || !target) return;
    void (async () => {
      try {
        await createLink({
          from_fid: sourceId,
          from_pos0: sel.start,
          from_pos1: sel.end,
          to_fid: target.fid,
          to_pos0: target.pos0,
          to_pos1: target.pos1,
        });
        await refreshLinks();
      } catch (e) {
        setErrMsg(e instanceof Error ? e.message : t("coder.linkCreateError"));
      } finally {
        clearSelection();
      }
    })();
  }

  /* ------------------------------------------------------------- QTT */

  /** Open the worksheet picker for the current selection. */
  function openQttPicker() {
    setQttOpen(true);
    setQttLoading(true);
    void listQttSheets()
      .then((sheets) => setQttSheets(sheets))
      .catch((e) => {
        setErrMsg(e instanceof Error ? e.message : t("qtt.sendError"));
        setQttOpen(false);
      })
      .finally(() => setQttLoading(false));
  }

  /** Store the selected span as a segment item on the given worksheet. */
  function sendSelectionToSheet(sheet: QttSheet) {
    const sel = selection;
    if (!sel || qttSending != null) return;
    setQttSending(sheet.id);
    void (async () => {
      try {
        await sendSegmentToQtt(sheet.id, {
          fid: sourceId,
          pos0: sel.start,
          pos1: sel.end,
        });
        setQttOpen(false);
        setQttSent(true);
        if (qttSentTimer.current) clearTimeout(qttSentTimer.current);
        qttSentTimer.current = setTimeout(() => setQttSent(false), 1500);
        // An open QTT workspace refreshes its sheets/items.
        const { qttUi, setQttUi } = useProjectStore.getState();
        setQttUi({ tick: qttUi.tick + 1 });
        clearSelection();
      } catch (e) {
        setErrMsg(e instanceof Error ? e.message : t("qtt.sendError"));
      } finally {
        setQttSending(null);
      }
    })();
  }

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
        setErrMsg(e instanceof Error ? e.message : t("coder.saveError"));
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
          className={`cursor-pointer rounded-sm qc-seg ${hidden ? "qc-seg-hidden" : ""} ${
            flashCtid != null && seg.ctids.includes(flashCtid) ? "qc-seg-flash" : ""
          } ${
            segLinks.length > 0
              ? "underline decoration-wavy decoration-accent/60 underline-offset-2"
              : ""
          }`}
          title={title}
          onClick={() => {
            setSelectedSeg(seg);
            setSelectedAnnSeg(null);
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
    return (
      <div className="flex h-full items-center justify-center bg-bg">
        <div className="max-w-md text-center">
          <p className="flex items-center justify-center gap-1.5 text-sm text-danger">
            <CircleAlert size={16} aria-hidden />
            {loadError}
          </p>
          <button
            type="button"
            onClick={() => setReloadTick((t) => t + 1)}
            className="mt-3 rounded-sm border border-border bg-surface px-3 py-1.5 text-sm hover:bg-surface-higher"
          >
            {t("common.retry")}
          </button>
        </div>
      </div>
    );
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
                    variant="secondary"
                    icon={<Undo2 size={12} aria-hidden />}
                    onClick={unmarkLast}
                    disabled={undoStack.length === 0}
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
        ref={scrollRef}
        onMouseUp={handleDocMouseUp}
        className="min-h-0 flex-1 overflow-y-auto bg-bg"
      >
        <div className="p-6">
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
      </div>

      {!editMode && segRows.length > 0 && (
        <div className="shrink-0 border-t border-border bg-surface px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-text-secondary">{t("coder.codingDetails")}</span>
            <div className="flex-1" />
            <IconButton label={t("common.closeDetails")} size="sm" onClick={() => setSelectedSeg(null)}>
              <X size={14} aria-hidden />
            </IconButton>
          </div>
          <ul className="mt-1.5 space-y-1.5">
            {segRows.map((r) => {
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
                  <span className="font-medium">
                    {code?.name ?? t("coder.fallbackCode", { id: r.cid })}
                  </span>
                  {r.important !== 0 && (
                    <Star size={12} className="text-warning" fill="currentColor" aria-hidden />
                  )}
                  {code?.memo && <span className="truncate text-xs text-text-secondary">{code.memo}</span>}
                  <span className="text-xs text-text-secondary">{r.date}</span>
                  <div className="flex-1" />
                  <IconButton
                    label={t("coder.removeFor", { name: code?.name ?? "code" })}
                    title={t("coder.removeThis")}
                    size="sm"
                    onClick={() => deleteCoding(r)}
                    className="hover:text-danger"
                  >
                    <Trash2 size={14} aria-hidden />
                  </IconButton>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {!editMode && annRows.length > 0 && (
        <div className="shrink-0 border-t border-border bg-surface px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-text-secondary">{t("coder.annotationDetails")}</span>
            <div className="flex-1" />
            <IconButton label={t("common.closeDetails")} size="sm" onClick={() => setSelectedAnnSeg(null)}>
              <X size={14} aria-hidden />
            </IconButton>
          </div>
          <ul className="mt-1.5 space-y-1.5">
            {annRows.map((a) => {
              const editing = editingAnnMemo?.anid === a.anid;
              return (
                <li key={a.anid} className="rounded-sm border border-border bg-bg px-2 py-1.5 text-sm">
                  {editing ? (
                    <div className="flex items-start gap-1.5">
                      <Textarea
                        value={editingAnnMemo.memo}
                        onChange={(e) => setEditingAnnMemo({ anid: a.anid, memo: e.target.value })}
                        className="min-h-12 w-full resize-none p-1.5"
                      />
                      <Button
                        variant="primary"
                        icon={<Check size={12} aria-hidden />}
                        onClick={() => updateAnnotationMemo(a.anid, editingAnnMemo.memo)}
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
                        onClick={() => deleteAnnotation(a)}
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
      )}

      {toolbarPos && (
        <div
          ref={floatingRef}
          className="fixed z-40"
          style={{ left: toolbarPos.left, top: toolbarPos.top }}
        >
          {annotateOpen ? (
            <div
              className={`w-72 p-2 ${cls.popup}`}
              role="dialog"
              aria-modal="true"
              aria-label={t("coder.addAnnotation")}
            >
              <Textarea
                autoFocus
                value={annotateMemo}
                onChange={(e) => setAnnotateMemo(e.target.value)}
                placeholder={t("coder.annotationMemoPlaceholder")}
                className="h-20 w-full resize-none p-1.5"
              />
              <div className="mt-2 flex justify-end gap-1.5">
                <Button variant="secondary" onClick={() => setAnnotateOpen(false)}>
                  {t("common.cancel")}
                </Button>
                <Button variant="primary" icon={<Check size={12} aria-hidden />} onClick={saveAnnotation}>
                  {t("common.save")}
                </Button>
              </div>
            </div>
          ) : qttOpen ? (
            <Menu role="menu" className="w-64" aria-label={t("qtt.sendTitle")}>
              <div className="border-b border-border px-2 py-1 text-[11px] font-medium uppercase tracking-wide text-text-secondary">
                {t("qtt.sendTitle")}
              </div>
              {qttLoading ? (
                <div className="flex items-center gap-1.5 px-2 py-2 text-xs text-text-secondary">
                  <LoaderCircle size={12} className="animate-spin" aria-hidden />
                  {t("qtt.loading")}
                </div>
              ) : qttSheets.length === 0 ? (
                <div className="px-2 py-2 text-xs text-text-secondary">{t("qtt.sendEmpty")}</div>
              ) : (
                qttSheets.map((sheet) => (
                  <MenuItem
                    key={sheet.id}
                    role="menuitem"
                    disabled={qttSending != null}
                    onClick={() => sendSelectionToSheet(sheet)}
                    className={qttSending === sheet.id ? "opacity-60" : ""}
                  >
                    {qttSending === sheet.id ? (
                      <LoaderCircle size={12} className="animate-spin" aria-hidden />
                    ) : (
                      <ScrollText size={12} aria-hidden />
                    )}
                    <span className="min-w-0 flex-1 truncate">{sheet.name}</span>
                    <span className="shrink-0 rounded-sm bg-surface-higher px-1 py-px text-[10px] font-medium uppercase text-text-secondary">
                      {sheet.kind === "mixed" ? t("qtt.kindMixed") : t("qtt.kindQual")}
                    </span>
                  </MenuItem>
                ))
              )}
            </Menu>
          ) : !editMode ? (
            <div
              className={`flex items-center gap-1 p-1 ${cls.popup}`}
              role="toolbar"
              aria-label={t("coder.selectionActions")}
            >
              <Button
                variant="primary"
                icon={<Code size={12} aria-hidden />}
                className="max-w-56"
                onClick={() => {
                  if (activeCodeId != null) codeSelection(activeCodeId);
                  else setPickerOpen(true);
                }}
                title={
                  activeCodeId != null
                    ? t("coder.codeWithActive", {
                        name: codeById.get(activeCodeId)?.name ?? "",
                      })
                    : t("coder.codeAction")
                }
              >
                <span className="truncate">
                  {activeCodeId != null
                    ? codeById.get(activeCodeId)?.name ?? t("coder.codeAction")
                    : t("coder.codeAction")}
                </span>
              </Button>
              <Button variant="secondary" icon={<StickyNote size={12} aria-hidden />} onClick={openAnnotate}>
                {t("coder.annotate")}
              </Button>
              <Button
                variant="secondary"
                icon={<LinkIcon size={12} aria-hidden />}
                onClick={copySegmentLink}
                title={t("coder.linkCopied")}
              >
                {linkCopied ? t("coder.copyLinkDone") : t("coder.copyLink")}
              </Button>
              {clipboardLink && (
                <Button
                  variant="secondary"
                  icon={<LinkIcon size={12} aria-hidden />}
                  onClick={pasteSegmentLink}
                  title={t("coder.linkCopied")}
                >
                  {t("coder.pasteLinkHere")}
                </Button>
              )}
              <Button
                variant="secondary"
                icon={
                  qttSent ? <Check size={12} aria-hidden /> : <ScrollText size={12} aria-hidden />
                }
                onClick={openQttPicker}
                title={t("qtt.sendTitle")}
              >
                {qttSent ? t("qtt.sendDone") : t("qtt.send")}
              </Button>
            </div>
          ) : null}
        </div>
      )}

      <CodePicker
        open={pickerOpen}
        codes={storeCodeTree}
        onClose={() => setPickerOpen(false)}
        onPick={handlePickCode}
      />
    </div>
  );
}
