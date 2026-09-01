/**
 * PdfCoder — PDF coding workspace: pdf.js page rendering, rectangle region
 * selection with the shared CodePicker, per-page coded overlays with the
 * memo gutter / details bubble, and continuous- or single-page modes.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import { useAsyncEffect } from "@/lib/useAsync";
import * as pdfjsLib from "pdfjs-dist";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import {
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  FileText,
  FileType,
  Link as LinkIcon,
  LoaderCircle,
  MessageSquareText,
  Pencil,
  Rows3,
  Sparkles,
  Undo2,
} from "lucide-react";
import {
  api,
  fetchSourceFile,
  type Annotation,
  type CodeTreeItem,
  type Coding,
  type ImageCoding,
  type Source,
} from "@/lib/api";
import { patchCodingRowMeta, patchCodingWeight, useCodeIndex } from "@/features/coding/codingApi";
import { useCodingsChanged, useAssignCode } from "@/features/coding/shared/events";
import { useEscapeStack } from "@/features/coding/shared/useEscapeStack";
import { useSplitResize } from "@/features/coding/shared/useSplitResize";
import { useUndoStack } from "@/features/coding/shared/useUndoStack";
import { CodePicker, type PickedCode } from "@/features/coding/CodePicker";
import { AutocodeDialog } from "@/features/coding/AutocodeDialog";
import { TextCoder } from "@/features/coding/TextCoder";
import {
  MemoGutter,
  MemoGutterBubble,
  toGutterRow,
} from "@/features/coding/MemoGutter";
import { useGutterVisible } from "@/features/coding/viewOptions";
import {
  buildPageOverlays,
  clampRect,
  DEFAULT_CODING_COLOR,
  type NormalizedRect,
  type PageOverlay,
  type PagePoint,
} from "@/features/coding/pdf";
import { codeTint } from "@/features/coding/tint";
import { cn, errorMessage } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import {
  Button,
  ErrorBanner,
  IconButton,
  Input,
  LoadingState,
  Select,
  ViewHeader,
} from "@/components/ui/orchestrator";
import { useCoderStore } from "@/stores/coder";
import { usePrefsStore } from "@/stores/prefs";
import { useProjectStore } from "@/stores/project";

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

const DRAG_MIN_SIZE = 5;

/** Download a source's PDF bytes for pdf.js.
 *
 *  `fetchSourceFile` builds the URL from the RESOLVED base — the App boot
 *  gate holds the UI until `initApiBase()` settles, and on a transport
 *  failure (backend still booting / restarted on an ephemeral port) the
 *  helper drops the cached base, re-resolves it and retries once — so a
 *  stale base can never surface as a spurious "Failed to fetch". HTTP
 *  errors become `ApiError`s carrying the backend's JSON `detail`, so the
 *  document pane shows the real message. */
async function fetchPdfBytes(sourceId: number): Promise<ArrayBuffer> {
  const res = await fetchSourceFile(sourceId);
  return res.arrayBuffer();
}

/** PATCH a segment row's memo/important (text or image) — the shared
 *  codingApi helper covers both kinds with the same retry semantics. */
const patchCodingRow = patchCodingRowMeta;

interface PageSize {
  width: number;
  height: number;
}

/** One pdf.js text item in PDF (unscaled) units — used to hit-test and
 *  select text over the rendered page. */
interface TextItemData {
  x: number;
  y: number;
  w: number;
  h: number;
  str: string;
}

/** Pending coding action after a drag: a picture region or a text span. */
type PendingAction =
  | { kind: "region"; pageNumber: number; rect: NormalizedRect }
  | { kind: "text"; pos0: number; pos1: number; seltext: string };

/** String draft of a region's geometry (+ page) while the inline editor
 *  is open. Coordinates are in PDF units; the page is pdf_page-aware. */
interface RectDraft {
  x1: string;
  y1: string;
  width: string;
  height: string;
  page: string;
}

/** Parse the geometry draft; null when any field is missing/negative. */
function parseDraftRect(draft: RectDraft): { x1: number; y1: number; width: number; height: number } | null {
  const vals = [draft.x1, draft.y1, draft.width, draft.height].map((v) => Number(v));
  if (vals.some((n) => !Number.isFinite(n) || n < 0)) return null;
  return { x1: vals[0], y1: vals[1], width: vals[2], height: vals[3] };
}

/** Parse the draft page number; null unless it is a positive integer. */
function parseDraftPage(draft: RectDraft): number | null {
  const page = Number(draft.page);
  return Number.isInteger(page) && page >= 1 ? page : null;
}

/** Text items whose rects overlap the drag rectangle (PDF units). */
function coveredTextItems(
  items: TextItemData[],
  scale: number,
  start: PagePoint,
  current: PagePoint,
): TextItemData[] {
  const rect = clampRect(start, current);
  const x1 = rect.x1 / scale;
  const y1 = rect.y1 / scale;
  const x2 = rect.x2 / scale;
  const y2 = rect.y2 / scale;
  return items.filter((it) => it.x < x2 && it.x + it.w > x1 && it.y < y2 && it.y + it.h > y1);
}

/** Best-effort reverse mapping of a text coding (stored in the extracted
 *  plain text) back onto the pdf.js items of one page: find the run of
 *  items that contain the coding's first and last word, in order. */
function matchCodingItems(items: TextItemData[], seltext: string): TextItemData[] | null {
  const words = seltext.split(/\s+/).filter(Boolean);
  if (words.length === 0) return null;
  const first = words[0].toLowerCase();
  const last = words[words.length - 1].toLowerCase();
  const start = items.findIndex((it) => it.str.toLowerCase().includes(first));
  if (start < 0) return null;
  let end = start;
  for (let i = start; i < items.length; i++) {
    if (items[i].str.toLowerCase().includes(last)) {
      end = i;
      break;
    }
  }
  if (!items[end].str.toLowerCase().includes(last)) return null;
  return items.slice(start, end + 1);
}

/** Reconstruct the selected text from the covered pdf.js items: words on
 *  one line join with a space, lines with a newline (matches PyMuPDF's
 *  page text closely enough for the backend's word-sequence matching). */
function buildSelectionText(items: TextItemData[]): string {
  const sorted = [...items].sort((a, b) => {
    const sameLine = Math.abs(a.y - b.y) < Math.max(3, Math.min(a.h, b.h) * 0.5);
    return sameLine ? a.x - b.x : a.y - b.y;
  });
  let out = "";
  let prev: TextItemData | null = null;
  for (const it of sorted) {
    if (prev) {
      const sameLine = Math.abs(it.y - prev.y) < Math.max(3, Math.min(it.h, prev.h) * 0.5);
      out += sameLine ? " " : "\n";
    }
    out += it.str;
    prev = it;
  }
  return out;
}

export function PdfCoder({ source }: { source: Source }) {
  const { t } = useI18n();
  const storeCodeTree = useProjectStore((s) => s.codeTree);
  const activeCodeId = useCoderStore((s) => s.activeCodeId);
  const hiddenCodes = useCoderStore((s) => s.hiddenCodes);
  /** When OFF, creating a coding does NOT auto-select it in the details
   *  footer (clicking a segment still views it). */
  const autoShowDetails = usePrefsStore((s) => s.autoShowSegmentDetails);

  const [pdfVisible, setPdfVisible] = useState(true);
  const [plainVisible, setPlainVisible] = useState(false);
  // Keep the plain-text pane mounted for the width transition (200ms) so the
  // toggle animates like the rightbar; after the transition the content is
  // removed so `getByText` count goes to 0 (e2e expectation).
  const [plainMounted, setPlainMounted] = useState(plainVisible);
  useEffect(() => {
    if (plainVisible) {
      setPlainMounted(true);
    } else {
      const t = setTimeout(() => setPlainMounted(false), 200);
      return () => clearTimeout(t);
    }
  }, [plainVisible]);
  /** Linked position sync: when both panes are visible, scrolling either
   *  one keeps the other at the corresponding location. The toolbar link
   *  button toggles this off/on. */
  const [autoSync, setAutoSync] = useState(true);
  /** The embedded plain-text pane's scroll container (set by TextCoder). */
  const textScrollElRef = useRef<HTMLElement | null>(null);
  const [autoOpen, setAutoOpen] = useState(false);
  const [codings, setCodings] = useState<ImageCoding[]>([]);
  const [textCodings, setTextCodings] = useState<Coding[]>([]);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [codes, setCodes] = useState<CodeTreeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [pdfReloadTick, setPdfReloadTick] = useState(0);
  const [pageSizes, setPageSizes] = useState<Map<number, PageSize>>(new Map());

  const [continuous, setContinuous] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const [zoom, setZoom] = useState<number | "fit">("fit");
  const [fittedScale, setFittedScale] = useState(1);

  /** pdf.js text items per page (PDF units) — enables text marking. */
  const [textItems, setTextItems] = useState<Map<number, TextItemData[]>>(new Map());
  const [drag, setDrag] = useState<
    | { pageNumber: number; start: PagePoint; current: PagePoint; mode: "region" | "text" }
    | null
  >(null);
  const [pendingRect, setPendingRect] = useState<{ pageNumber: number; rect: NormalizedRect } | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedImid, setSelectedImid] = useState<number | null>(null);
  const [selectedTextCtid, setSelectedTextCtid] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<RectDraft | null>(null);
  /** Inline error line inside the details bubble: a background refresh of
   *  the codings failed while a segment is selected — the bubble keeps
   *  showing the client-side data instead of vanishing or toasting a bare
   *  "Failed to fetch". */
  const [footerError, setFooterError] = useState<string | null>(null);
  /** Freshly created text coding flashed on its matched overlay (~2s). */
  const [flashTextCtid, setFlashTextCtid] = useState<number | null>(null);
  const flashTextTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Bumped whenever overlays/page geometry change, so the memo gutter
   *  re-measures its card anchors. */
  const [measureTick, setMeasureTick] = useState(0);
  const [gutterVisible, toggleGutter] = useGutterVisible();

  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRefs = useRef(new Map<number, HTMLCanvasElement>());
  const dragRef = useRef(drag);
  const pendingRectRef = useRef(pendingRect);
  const pendingActionRef = useRef<PendingAction | null>(null);

  useEffect(() => {
    dragRef.current = drag;
  }, [drag]);

  useEffect(() => {
    pendingRectRef.current = pendingRect;
  }, [pendingRect]);

  /* ------------------------------------------------------- split resize */

  const resize = useSplitResize({
    axis: "x",
    min: 220,
    max: Number.POSITIVE_INFINITY,
    initial: 420,
    containerSize: () => containerRef.current?.clientWidth,
  });
  const textW = resize.size;
  const textDragging = resize.dragging;
  const startTextResize = resize.onDown;

  const numPages = pdf?.numPages ?? 0;
  const scale = zoom === "fit" ? fittedScale : zoom;

  /* ------------------------------------------------- linked position sync */

  /** Approximate character offset where each page begins in the extracted
   *  fulltext. Per-page weights come from the pdf.js text items (so a text-
   *  dense page maps to more characters than a sparse one), normalized to
   *  the fulltext length; falls back to uniform pages when no items are
   *  loaded yet. Piecewise-linear interpolation over these offsets is what
   *  keeps the linked scrolling smooth instead of snapping per page. */
  const pageCharOffsets = useMemo(() => {
    const len = source?.fulltext?.length ?? 0;
    const raw: number[] = [];
    let sum = 0;
    for (let p = 1; p <= numPages; p++) {
      let c = 0;
      for (const it of textItems.get(p) ?? []) c += (it.str?.length ?? 0) + 1;
      raw.push(c);
      sum += c;
    }
    const k = sum > 0 && len > 0 ? len / sum : 0;
    const starts: number[] = new Array(Math.max(0, numPages));
    let acc = 0;
    for (let i = 0; i < numPages; i++) {
      starts[i] = acc;
      acc += numPages > 0 && k === 0 ? len / numPages : raw[i] * k;
    }
    return { starts, total: len > 0 ? len : acc };
  }, [textItems, numPages, source?.fulltext]);

  // When both panes are visible and autoSync is on, scrolling either pane
  // scrolls the other to the corresponding location (piecewise-linear page
  // interpolation, rAF-throttled). A short-lived lock on the receiving side
  // suppresses the feedback loop from our own programmatic scrolls.
  useEffect(() => {
    if (!autoSync || !pdfVisible || !plainVisible) return;
    const pdfEl = containerRef.current;
    if (!pdfEl) return;
    const lock = { pdf: 0, text: 0 };

    /** Character offset matching the PDF's current scroll position:
     *  the top-visible page plus the fractional progress into it. */
    const posFromPdf = (): number | null => {
      const cRect = pdfEl.getBoundingClientRect();
      for (const el of Array.from(pdfEl.querySelectorAll<HTMLElement>("[data-page]"))) {
        const r = el.getBoundingClientRect();
        if (r.bottom <= cRect.top + 1) continue;
        const p = Number(el.dataset.page);
        if (!Number.isFinite(p) || p < 1) continue;
        const start = pageCharOffsets.starts[p - 1] ?? 0;
        const end =
          p < pageCharOffsets.starts.length ? pageCharOffsets.starts[p] : pageCharOffsets.total;
        const frac = r.height > 0 ? Math.min(1, Math.max(0, (cRect.top - r.top) / r.height)) : 0;
        return start + frac * (end - start);
      }
      return null;
    };

    /** Scroll the PDF so that character offset `pos` sits at the top edge,
     *  interpolating inside the containing page. */
    const scrollPdfToPos = (pos: number) => {
      const { starts, total } = pageCharOffsets;
      const n = starts.length;
      if (n === 0) return;
      let p = n;
      for (let i = 0; i < n; i++) {
        const end = i + 1 < n ? starts[i + 1] : total;
        if (pos <= end || i === n - 1) {
          p = i + 1;
          break;
        }
      }
      const start = starts[p - 1] ?? 0;
      const end = p < n ? starts[p] : total;
      const frac = end > start ? Math.min(1, Math.max(0, (pos - start) / (end - start))) : 0;
      const pageEl = pdfEl.querySelector<HTMLElement>(`[data-page="${p}"]`);
      if (!pageEl) return;
      const r = pageEl.getBoundingClientRect();
      const c = pdfEl.getBoundingClientRect();
      pdfEl.scrollTop = pdfEl.scrollTop + (r.top - c.top) + frac * r.height;
    };

    const ratioOf = (el: HTMLElement) => {
      const range = el.scrollHeight - el.clientHeight;
      return range > 0 ? el.scrollTop / range : 0;
    };
    const setRatio = (el: HTMLElement | null, ratio: number) => {
      if (!el) return;
      const range = el.scrollHeight - el.clientHeight;
      el.scrollTop = Math.min(1, Math.max(0, ratio)) * Math.max(0, range);
    };

    let rafPdf = 0;
    let rafText = 0;
    const onPdfScroll = () => {
      if (Date.now() < lock.pdf) return;
      cancelAnimationFrame(rafPdf);
      rafPdf = requestAnimationFrame(() => {
        const t = textScrollElRef.current;
        const pos = posFromPdf();
        if (t && pos != null && pageCharOffsets.total > 0) {
          lock.text = Date.now() + 250;
          setRatio(t, pos / pageCharOffsets.total);
        }
      });
    };
    const onTextScroll = () => {
      if (Date.now() < lock.text) return;
      cancelAnimationFrame(rafText);
      rafText = requestAnimationFrame(() => {
        const t = textScrollElRef.current;
        if (!t || pageCharOffsets.total <= 0) return;
        const pos = ratioOf(t) * pageCharOffsets.total;
        lock.pdf = Date.now() + 250;
        scrollPdfToPos(pos);
      });
    };

    pdfEl.addEventListener("scroll", onPdfScroll, { passive: true });
    // The TextCoder (and thus its scroll element) mounts asynchronously —
    // retry until the ref is populated.
    let textEl = textScrollElRef.current;
    let retryTimer = 0;
    const attachText = () => {
      textEl = textScrollElRef.current;
      if (textEl) textEl.addEventListener("scroll", onTextScroll, { passive: true });
      else retryTimer = window.setTimeout(attachText, 100);
    };
    attachText();
    return () => {
      cancelAnimationFrame(rafPdf);
      cancelAnimationFrame(rafText);
      pdfEl.removeEventListener("scroll", onPdfScroll);
      window.clearTimeout(retryTimer);
      textEl?.removeEventListener("scroll", onTextScroll);
    };
  }, [autoSync, pdfVisible, plainVisible, pageCharOffsets]);

  /* ---------------------------------------------------------------- load */

  // NOTE: this coder deliberately does NOT use the shared `useCoder` hook —
  // its load pairs imageCodings with sourceCoding/annotations via
  // allSettled so a companion (text codings, annotations, code tree) failure
  // degrades to a footer note instead of killing the PDF view, so it stays
  // bespoke here.
  useAsyncEffect(async (signal) => {
    setLoading(true);
    setLoadError(null);
    setFooterError(null);
    setCodings([]);
    setAnnotations([]);
    setCodes([]);
    clearSelection();
    setPendingRect(null);
    setPickerOpen(false);
    setCurrentPage(1);
    try {
      // imageCodings is the critical fetch — without it the page shows no
      // overlays at all. The companions (plain-text codings, annotations,
      // code tree) degrade gracefully: their failure must not replace the
      // whole view with an error screen (a codes-tree 500, e.g. from a
      // project with category/code id collisions, used to kill the PDF).
      const [cod, textCod, anns, flat] = await Promise.allSettled([
        api.imageCodings(source.id),
        api.sourceCoding(source.id),
        api.fileAnnotations(source.id),
        api.codesFlat(),
      ]);
      signal.throwIfAborted();
      if (cod.status === "fulfilled") {
        setCodings(cod.value);
      } else {
        setLoadError(errorMessage(cod.reason, t("coder.loadCodingsError")));
        return;
      }
      setTextCodings(textCod.status === "fulfilled" ? textCod.value : []);
      setAnnotations(anns.status === "fulfilled" ? anns.value : []);
      setCodes(flat.status === "fulfilled" ? flat.value : []);
      if (textCod.status === "rejected" || anns.status === "rejected" || flat.status === "rejected") {
        const reason = [textCod, anns, flat].find((r) => r.status === "rejected");
        if (reason && reason.status === "rejected") {
          setFooterError(errorMessage(reason.reason, t("coder.loadCodingsError")));
        }
      }
    } catch (e) {
      signal.throwIfAborted();
      setLoadError(errorMessage(e, t("coder.loadCodingsError")));
    } finally {
      signal.throwIfAborted();
      setLoading(false);
    }
  }, [source.id, reloadTick, t]);

  useAsyncEffect(async (signal) => {
    setPdf(null);
    setPdfError(null);
    setPageSizes(new Map());
    setTextItems(new Map());
    setFittedScale(1);
    try {
      // Fetch the raw bytes ourselves (with a timeout) and hand them to
      // pdf.js as `data` — this avoids Range/streaming/mixed-content
      // quirks of `url` loading inside WebView2/Tauri custom protocols.
      // fetchPdfBytes resolves the API base first and retries transport
      // failures once, so a still-booting/ephemeral-port backend cannot
      // surface as a spurious "Failed to fetch".
      const data = await fetchPdfBytes(source.id);
      signal.throwIfAborted();
      const task = pdfjsLib.getDocument({ data });
      const doc = await task.promise;
      signal.throwIfAborted();
      setPdf(doc);
      const sizes = new Map<number, PageSize>();
      const items = new Map<number, TextItemData[]>();
      for (let p = 1; p <= doc.numPages; p++) {
        const page = await doc.getPage(p);
        const vp = page.getViewport({ scale: 1 });
        sizes.set(p, { width: vp.width, height: vp.height });
        const content = await page.getTextContent();
        const list: TextItemData[] = [];
        for (const item of content.items) {
          if (!("str" in item) || item.str === "") continue;
          const tr = item.transform;
          // pdf.js reports PDF units with y growing UPWARD; flip to the
          // screen convention (top-left origin) for hit-testing.
          list.push({
            x: tr[4],
            y: vp.height - (tr[5] + item.height),
            w: item.width,
            h: item.height,
            str: item.str,
          });
        }
        items.set(p, list);
      }
      signal.throwIfAborted();
      setPageSizes(sizes);
      setTextItems(items);
      // Overlays (and thus gutter anchors) can now be built — re-measure.
      setMeasureTick((n) => n + 1);
    } catch (e) {
      signal.throwIfAborted();
      setPdfError(errorMessage(e, t("pdfCoder.loadDocumentError")));
    }
  }, [source.id, pdfReloadTick, t]);

  /* ------------------------------------------------------------ pdf render */

  useEffect(() => {
    if (!pdf) return;
    const tasks: RenderTask[] = [];
    let cancelled = false;
    const targets: number[] = [];
    if (continuous) {
      for (let p = 1; p <= pdf.numPages; p++) targets.push(p);
    } else {
      targets.push(currentPage);
    }
    for (const p of targets) {
      const canvas = canvasRefs.current.get(p);
      if (!canvas) continue;
      void (async () => {
        try {
          if (cancelled) return;
          const page = await pdf.getPage(p);
          if (cancelled) return;
          const viewport = page.getViewport({ scale });
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.style.width = `${viewport.width}px`;
          canvas.style.height = `${viewport.height}px`;
          const task = page.render({ canvas, viewport });
          tasks.push(task);
          // Await the render: a failed render must be visible, not a silent
          // black page (unhandled rejections left canvases blank before).
          await task.promise;
        } catch (e) {
          if (!cancelled) {
            setErrMsg(errorMessage(e, t("pdfCoder.loadDocumentError")));
          }
        }
      })();
    }
    return () => {
      cancelled = true;
      for (const t of tasks) {
        try {
          t.cancel();
        } catch {
          /* render already finished */
        }
      }
    };
    // Re-render whenever the view (re)mounts — including toggling back to the
    // PDF pane, which unmounts the page canvases.
  }, [pdf, scale, currentPage, continuous, pdfVisible, t]);

  // Zoom / pane-layout changes move the overlays — re-measure gutter anchors.
  useEffect(() => {
    setMeasureTick((n) => n + 1);
  }, [scale, continuous, currentPage, pdfVisible]);

  /* ---------------------------------------------------------------- fit */

  const applyFit = useCallback(async () => {
    const doc = pdf;
    const el = containerRef.current;
    if (!doc || !el) return;
    const page = await doc.getPage(1);
    const vp = page.getViewport({ scale: 1 });
    const avail = el.clientWidth - 48;
    setFittedScale(Math.max(0.25, avail / vp.width));
  }, [pdf]);

  useEffect(() => {
    if (zoom !== "fit" || !pdf) return;
    void applyFit();
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => void applyFit());
    ro.observe(el);
    return () => ro.disconnect();
  }, [zoom, pdf, applyFit, pdfVisible]);

  /* ------------------------------------------------------------ derived */

  const { byId, colorByCid } = useCodeIndex(codes);

  const pageNumbers = useMemo(() => {
    const out: number[] = [];
    if (continuous) {
      for (let p = 1; p <= numPages; p++) out.push(p);
    } else {
      out.push(currentPage);
    }
    return out;
  }, [continuous, numPages, currentPage]);

  const selectedCoding = useMemo(
    () => (selectedImid != null ? codings.find((c) => c.imid === selectedImid) ?? null : null),
    [selectedImid, codings],
  );

  /** Text codings mapped back onto their pages' pdf.js items (best-effort
   *  word matching) so they show as overlays in the rendered view. */
  const textOverlays = useMemo(() => {
    const out = new Map<
      number,
      { items: TextItemData[]; color: string; ctid: number }[]
    >();
    for (const coding of textCodings) {
      for (const [page, items] of textItems) {
        const matched = matchCodingItems(items, coding.seltext ?? "");
        if (matched) {
          const list = out.get(page) ?? [];
          list.push({
            items: matched,
            color: colorByCid.get(coding.cid) ?? DEFAULT_CODING_COLOR,
            ctid: coding.ctid,
          });
          out.set(page, list);
          break;
        }
      }
    }
    return out;
  }, [textCodings, textItems, colorByCid]);

  /* ------------------------------------------------------------- actions */

  /** Background refresh of the region codings. On failure the current
   *  (client-side) list is kept — the details footer of a selected segment
   *  stays usable — and the error is surfaced inline in the footer. Never
   *  throws, so background callers cannot produce unhandled rejections or
   *  a bare "Failed to fetch" toast. */
  const refreshCodings = useCallback(async () => {
    try {
      setCodings(await api.imageCodings(source.id));
      setFooterError(null);
    } catch (e) {
      console.warn("[pdf coder] codings refresh failed:", e);
      setFooterError(errorMessage(e, t("coder.loadCodingsError")));
    }
  }, [source.id, t]);

  const refreshTextCodings = useCallback(async () => {
    try {
      setTextCodings(await api.sourceCoding(source.id));
    } catch (e) {
      console.warn("[pdf coder] text codings refresh failed:", e);
    }
  }, [source.id]);

  const refreshCodes = useCallback(async () => {
    try {
      setCodes(await api.codesFlat());
    } catch (e) {
      // Fallback names/colors stay; the bubble renders from client state.
      console.warn("[pdf coder] codes refresh failed:", e);
    }
  }, []);

  // Recoverable deletes: both kinds' removed rows land on one undo stack.
  const undo = useUndoStack<Coding | ImageCoding>({
    refresh: async () => {
      await refreshCodings();
      await refreshTextCodings();
    },
    onError: setErrMsg,
  });

  /* ---- memo gutter (anchored to the rendered PDF pages) ---------------
     Both region (image) codings and text codings render as overlays carrying
     a `data-ctid` marker, so the gutter can measure their vertical position
     inside the PDF scroll container even when the plain-text pane is hidden.
     The gutter's id is the image coding's `imid` for regions and the text
     coding's real `ctid` for text segments; callbacks route back by kind. */
  const gutterRows = useMemo(() => {
    const rows = [];
    for (const c of codings) {
      rows.push(
        toGutterRow(
          {
            id: c.imid,
            kind: "image",
            memo: c.memo,
            weight: (c as ImageCoding & { weight?: number }).weight,
            important: c.important,
            date: c.date,
          },
          byId.get(c.cid),
          t("coder.fallbackCode", { id: c.cid }),
        ),
      );
    }
    for (const c of textCodings) {
      rows.push(
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
          byId.get(c.cid),
          t("coder.fallbackCode", { id: c.cid }),
        ),
      );
    }
    return rows;
  }, [codings, textCodings, byId, t]);

  const isImageGutterId = useCallback(
    (id: number) => codings.some((c) => c.imid === id),
    [codings],
  );

  const gutterUpdate = useCallback(
    (id: number, patch: { memo?: string; weight?: number }, refresh: () => Promise<void>) => {
      const kind: "text" | "image" = isImageGutterId(id) ? "image" : "text";
      void (async () => {
        try {
          if (patch.memo !== undefined) {
            await patchCodingRow(kind, id, { memo: patch.memo });
          }
          if (patch.weight !== undefined) {
            await patchCodingWeight(kind, id, patch.weight);
          }
          await refresh();
        } catch (e) {
          setErrMsg(errorMessage(e, t("coder.memoUpdateError")));
        }
      })();
    },
    [isImageGutterId, t],
  );

  const gutterDelete = useCallback(
    (id: number) => {
      void (async () => {
        try {
          const kind: "text" | "image" = isImageGutterId(id) ? "image" : "text";
          if (kind === "image") {
            const row = codings.find((c) => c.imid === id);
            await api.deleteImageCoding(id);
            if (row) undo.push(row);
          } else {
            const row = textCodings.find((c) => c.ctid === id);
            await api.deleteTextCoding(id);
            if (row) undo.push(row);
          }
          clearSelection();
          if (kind === "image") await refreshCodings();
          else await refreshTextCodings();
        } catch (e) {
          setErrMsg(errorMessage(e, t("coder.removeError")));
        }
      })();
    },
    [isImageGutterId, refreshCodings, refreshTextCodings, t, undo, codings, textCodings],
  );

  /** Toggle the important flag of a gutter/bubble row (by id). */
  function gutterToggleImportant(id: number) {
    const row = gutterRows.find((r) => r.id === id);
    if (!row) return;
    const next = row.important ? 0 : 1;
    void (async () => {
      try {
        if (isImageGutterId(id)) {
          await patchCodingRow("image", id, { important: next });
          await refreshCodings();
        } else {
          await patchCodingRow("text", id, { important: next });
          await refreshTextCodings();
        }
      } catch (e) {
        setErrMsg(errorMessage(e, t("pdfCoder.updateError")));
      }
    })();
  }

  /** The details bubble's segment id (image imid or text ctid). */
  const bubbleCtid = useMemo(
    () => selectedImid ?? selectedTextCtid,
    [selectedImid, selectedTextCtid],
  );

  /** Rows for the floating details bubble (hidden-gutter mode) — the SAME
   *  GutterRow shape the gutter cards render, resolved from client state. */
  const bubbleRows = useMemo(
    () => (bubbleCtid != null ? gutterRows.filter((r) => r.id === bubbleCtid) : []),
    [gutterRows, bubbleCtid],
  );

  /** Per-row extension below an expanded card: the region-geometry editor
   *  for image codings (shared by gutter cards AND the details bubble, so
   *  both surfaces offer identical functions). Also surfaces refresh errors
   *  that used to live in the deprecated bottom bar. */
  function gutterExtrasFor(id: number): ReactNode {
    const row = codings.find((c) => c.imid === id);
    const isSelected = selectedCoding != null && selectedCoding.imid === id;
    if (!row || !isSelected) {
      return footerError ? (
        <p className="flex items-center gap-1.5 pt-1 text-xs text-warning">
          <CircleAlert size={12} aria-hidden />
          {footerError}
        </p>
      ) : null;
    }
    return (
      <div className="pt-1">
        {footerError && (
          <p className="mb-1 flex items-center gap-1.5 text-xs text-warning">
            <CircleAlert size={12} aria-hidden />
            {footerError}
          </p>
        )}
        {!editDraft ? (
          <Button
            variant="toolbar"
            icon={<Pencil size={12} aria-hidden />}
            onClick={() => startEditGeometry(row)}
          >
            {t("pdfCoder.editRegion")}
          </Button>
        ) : (
          <div className="flex flex-wrap items-end gap-2 rounded-sm border border-border bg-bg px-2 py-1.5">
            <CoordField
              label={t("imageCoder.x")}
              value={editDraft.x1}
              onChange={(v) => setEditDraft((d) => (d ? { ...d, x1: v } : d))}
            />
            <CoordField
              label={t("imageCoder.y")}
              value={editDraft.y1}
              onChange={(v) => setEditDraft((d) => (d ? { ...d, y1: v } : d))}
            />
            <CoordField
              label={t("imageCoder.w")}
              value={editDraft.width}
              onChange={(v) => setEditDraft((d) => (d ? { ...d, width: v } : d))}
            />
            <CoordField
              label={t("imageCoder.h")}
              value={editDraft.height}
              onChange={(v) => setEditDraft((d) => (d ? { ...d, height: v } : d))}
            />
            <CoordField
              label={t("imageCoder.page")}
              value={editDraft.page}
              onChange={(v) => setEditDraft((d) => (d ? { ...d, page: v } : d))}
            />
            <div className="flex-1" />
            <Button variant="secondary" onClick={() => setEditDraft(null)}>
              {t("common.cancel")}
            </Button>
            <Button variant="primaryCompact" onClick={() => void applyEditGeometry()}>
              {t("common.apply")}
            </Button>
          </div>
        )}
      </div>
    );
  }

  /** Flash a freshly created text coding's overlay and scroll its page into
   *  view (the text overlays are best-effort word matches, so a missing
   *  match just skips the scroll). Takes the created coding directly — the
   *  refreshed codings array is not available in this closure yet. */
  const flashTextCoding = useCallback(
    (coding: Coding | null) => {
      if (!coding || !coding.seltext) return;
      for (const [page, items] of textItems) {
        if (matchCodingItems(items, coding.seltext)) {
          // Scroll only the PDF's own container — scrollIntoView would also
          // shift outer ancestors (app shell/window).
          const pageEl = containerRef.current?.querySelector<HTMLElement>(
            `[data-page="${page}"]`,
          );
          const scrollEl = containerRef.current;
          if (pageEl && scrollEl) {
            const r = pageEl.getBoundingClientRect();
            const c = scrollEl.getBoundingClientRect();
            if (r.top < c.top || r.bottom > c.bottom) {
              scrollEl.scrollTo({ top: scrollEl.scrollTop + r.top - c.top, behavior: "smooth" });
            }
          }
          break;
        }
      }
      setFlashTextCtid(coding.ctid);
      if (flashTextTimer.current) clearTimeout(flashTextTimer.current);
      flashTextTimer.current = setTimeout(() => setFlashTextCtid(null), 2000);
    },
    [textItems],
  );

  useEffect(
    () => () => {
      if (flashTextTimer.current) clearTimeout(flashTextTimer.current);
    },
    [],
  );

  // History undo/redo: reload codings/annotations when the audit log reverts
  // a change (the shell only refreshes project metadata).
  useCodingsChanged(() => {
    void refreshCodings();
    void refreshTextCodings();
    void refreshCodes();
  });

  function clampPage(p: number): number {
    return Math.min(Math.max(1, p), Math.max(1, numPages));
  }

  /** Close the details bubble (pure client state — nothing is fetched or
   *  written). */
  function clearSelection() {
    setSelectedImid(null);
    setSelectedTextCtid(null);
    setEditDraft(null);
  }

  function setCanvasRef(pageNumber: number, el: HTMLCanvasElement | null) {
    if (el) canvasRefs.current.set(pageNumber, el);
    else canvasRefs.current.delete(pageNumber);
  }

  /** Toggle a pane on/off; never allow both off (fall back to PDF only). */
  function toggleView(kind: "pdf" | "plain") {
    const next = { pdf: pdfVisible, plain: plainVisible };
    if (kind === "pdf") next.pdf = !next.pdf;
    else next.plain = !next.plain;
    if (!next.pdf && !next.plain) next.pdf = true;
    setPdfVisible(next.pdf);
    setPlainVisible(next.plain);
  }

  function pagePointFromEvent(e: ReactMouseEvent<HTMLDivElement>): PagePoint {
    const rect = e.currentTarget.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  /** Whether the point lands on a text item (starts a TEXT drag). */
  function hitTextItem(pageNumber: number, pt: PagePoint): boolean {
    const items = textItems.get(pageNumber) ?? [];
    if (items.length === 0) return false;
    const px = pt.x / scale;
    const py = pt.y / scale;
    const tol = 2 / scale;
    return items.some(
      (it) =>
        px >= it.x - tol &&
        px <= it.x + it.w + tol &&
        py >= it.y - tol &&
        py <= it.y + it.h + tol,
    );
  }

  function onPageMouseDown(e: ReactMouseEvent<HTMLDivElement>, pageNumber: number) {
    if (e.button !== 0) return;
    e.preventDefault();
    clearSelection();
    setPendingRect(null);
    pendingActionRef.current = null;
    const pt = pagePointFromEvent(e);
    const mode: "region" | "text" = hitTextItem(pageNumber, pt) ? "text" : "region";
    const next = { pageNumber, start: pt, current: pt, mode };
    setDrag(next);
    dragRef.current = next;
  }

  function onPageMouseMove(e: ReactMouseEvent<HTMLDivElement>, pageNumber: number) {
    const pt = pagePointFromEvent(e);
    setDrag((d) => {
      if (!d || d.pageNumber !== pageNumber) return d;
      const next = { ...d, current: pt };
      dragRef.current = next;
      return next;
    });
  }

  /** Code the pending text selection (offsets already mapped to the
   *  plain-text coordinates) with the given code id. */
  const codePendingText = useCallback(
    (cid: number) => {
      const pending = pendingActionRef.current;
      if (!pending || pending.kind !== "text") return;
      setPickerOpen(false);
      void (async () => {
        try {
          const created = await api.createTextCoding({
            cid,
            fid: source.id,
            seltext: pending.seltext,
            pos0: pending.pos0,
            pos1: pending.pos1,
            owner: "default",
          });
          // Auto-show the freshly created coding: append it idempotently by
          // ctid (a re-render or racing refresh can never re-append), then
          // select it — the footer renders from this client list, never
          // from the fresh object. The auto-select is gated on the
          // "Auto-show segment details" pref.
          setTextCodings((cs) =>
            cs.some((c) => c.ctid === created.ctid) ? cs : [...cs, created],
          );
          setSelectedImid(null);
          if (autoShowDetails || gutterVisible) setSelectedTextCtid(created.ctid);
          setEditDraft(null);
          setFooterError(null);
          // Flash its overlay and scroll the page it sits on into view.
          flashTextCoding(created);
          await refreshTextCodings();
        } catch (e) {
          setErrMsg(errorMessage(e, t("coder.createError")));
        } finally {
          pendingActionRef.current = null;
        }
      })();
    },
    [source.id, t, refreshTextCodings, flashTextCoding, autoShowDetails, gutterVisible],
  );

  /** Code the pending drag rectangle with the given code id. */
  const codePendingRect = useCallback(
    (cid: number) => {
      const pending = pendingRectRef.current;
      if (!pending) return;
      setPickerOpen(false);
      void (async () => {
        try {
          const created = await api.createImageCoding({
            id: source.id,
            cid,
            x1: Math.round(pending.rect.x1 / scale),
            y1: Math.round(pending.rect.y1 / scale),
            width: Math.round((pending.rect.x2 - pending.rect.x1) / scale),
            height: Math.round((pending.rect.y2 - pending.rect.y1) / scale),
            owner: "default",
            pdf_page: pending.pageNumber,
          });
          // Render the details footer IMMEDIATELY from client state — the
          // background refresh below reconciles with the backend, so a
          // failed refresh can never block the footer. The append is
          // idempotent by imid: a re-render or a racing refresh can never
          // duplicate the row. The auto-select is gated on the
          // "Auto-show segment details" pref.
          setCodings((cs) =>
            cs.some((c) => c.imid === created.imid) ? cs : [...cs, created],
          );
          if (autoShowDetails || gutterVisible) setSelectedImid(created.imid);
          setSelectedTextCtid(null);
          setEditDraft(null);
          setFooterError(null);
          await refreshCodings();
        } catch (e) {
          setErrMsg(errorMessage(e, t("coder.createError")));
        } finally {
          setPendingRect(null);
        }
      })();
      void refreshCodes().catch(() => undefined);
    },
    [scale, source.id, refreshCodings, refreshCodes, t, autoShowDetails, gutterVisible],
  );

  const finishDrag = useCallback(() => {
    const d = dragRef.current;
    if (!d) return;
    setDrag(null);
    dragRef.current = null;
    if (d.mode === "text") {
      const rect = clampRect(d.start, d.current);
      const covered = coveredTextItems(textItems.get(d.pageNumber) ?? [], scale, d.start, d.current);
      const isClick = rect.x2 - rect.x1 < DRAG_MIN_SIZE && rect.y2 - rect.y1 < DRAG_MIN_SIZE;
      if (isClick) {
        // A click is a VIEW gesture, never a create: if it lands on an
        // existing text coding, select it for the footer (pure client
        // state); otherwise do nothing. Before this guard, a click on a
        // text overlay fell straight through into the coding-create flow
        // and re-inserted an already-coded span (unique-constraint 500).
        const hit = (textOverlays.get(d.pageNumber) ?? []).find((ov) =>
          ov.items.some((it) => covered.includes(it)),
        );
        if (hit) {
          clearSelection();
          setSelectedTextCtid(hit.ctid);
          setFooterError(null);
        }
        return;
      }
      const text = buildSelectionText(covered);
      if (!text.trim()) return;
      void (async () => {
        try {
          const loc = await api.pdfTextLocate(source.id, {
            page: d.pageNumber,
            text,
          });
          pendingActionRef.current = {
            kind: "text",
            pos0: loc.pos0,
            pos1: loc.pos1,
            seltext: loc.seltext,
          };
          if (activeCodeId != null) {
            codePendingText(activeCodeId);
          } else {
            setPickerOpen(true);
          }
        } catch (e) {
          setErrMsg(errorMessage(e, t("pdfCoder.textLocateError")));
        }
      })();
      return;
    }
    const rect = clampRect(d.start, d.current);
    if (rect.x2 - rect.x1 > DRAG_MIN_SIZE && rect.y2 - rect.y1 > DRAG_MIN_SIZE) {
      const next = { pageNumber: d.pageNumber, rect };
      pendingRectRef.current = next;
      setPendingRect(next);
      if (activeCodeId != null) {
        codePendingRect(activeCodeId);
      } else {
        setPickerOpen(true);
      }
    }
  }, [activeCodeId, codePendingRect, codePendingText, source.id, t, scale, textItems, textOverlays]);

  // Clicking a code in the left sidebar assigns it to the pending action.
  useAssignCode((cid) => {
    setPickerOpen(false);
    if (pendingActionRef.current?.kind === "text") {
      codePendingText(cid);
    } else {
      codePendingRect(cid);
    }
  });

  // Catch releases that land outside the page element; finishDrag is
  // idempotent, so a fast release inside the element (handled by its own
  // onMouseUp) and this window listener cannot double-fire.
  useEffect(() => {
    if (!drag) return;
    window.addEventListener("mouseup", finishDrag);
    return () => window.removeEventListener("mouseup", finishDrag);
  }, [drag, finishDrag]);

  // Escape dismisses the picker first, then an in-flight drag/pending
  // action, then the details bubble selection.
  useEscapeStack([
    () => {
      if (!pickerOpen) return false;
      setPickerOpen(false);
      return true;
    },
    () => {
      if (drag == null && pendingRect == null && pendingActionRef.current == null) return false;
      setDrag(null);
      setPendingRect(null);
      pendingActionRef.current = null;
      return true;
    },
    () => {
      if (selectedImid == null && selectedTextCtid == null) return false;
      clearSelection();
      return true;
    },
  ]);

  // Click-away clears the selection. Overlay mousedowns stop propagation,
  // so a click that SELECTS a segment never reaches this handler; the
  // details bubble dismisses itself (its own outside-click handler), and
  // gutter clicks are excluded via [data-gutter].
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (!target) return;
      if ((target as HTMLElement).closest?.("[data-gutter]")) return;
      clearSelection();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  function handlePickCode(picked: PickedCode[]) {
    setPickerOpen(false);
    for (const p of picked) {
      if (pendingActionRef.current?.kind === "text") {
        codePendingText(p.cid);
      } else {
        codePendingRect(p.cid);
      }
    }
  }

  function startEditGeometry(row: ImageCoding) {
    setEditDraft({
      x1: String(Math.round(row.x1)),
      y1: String(Math.round(row.y1)),
      width: String(Math.round(row.width)),
      height: String(Math.round(row.height)),
      page: String(row.pdf_page ?? 1),
    });
  }

  async function applyEditGeometry() {
    const row = selectedCoding;
    if (!editDraft || !row) return;
    const rect = parseDraftRect(editDraft);
    if (!rect) {
      setErrMsg(t("imageCoder.regionSaveError"));
      return;
    }
    try {
      await api.patchImageCoding(row.imid, rect);
      setEditDraft(null);
      await refreshCodings();
    } catch (e) {
      setErrMsg(errorMessage(e, t("imageCoder.regionSaveError")));
    }
  }

  function onPageInputChange(e: ChangeEvent<HTMLInputElement>) {
    const v = Number.parseInt(e.target.value, 10);
    if (Number.isFinite(v)) setCurrentPage(clampPage(v));
  }

  function overlayTitle(o: PageOverlay): string {
    const code = byId.get(o.coding.cid);
    const name = code?.name ?? t("coder.fallbackCode", { id: o.coding.cid });
    return o.coding.memo ? `${name} — ${o.coding.memo}` : name;
  }

  /* ------------------------------------------------------------ rendering */

  if (loading) {
    return <LoadingState>{t("pdfCoder.loading")}</LoadingState>;
  }

  if (loadError) {
    return (
      <div className="flex h-full items-center justify-center bg-bg">
        <div className="max-w-md text-center">
          <p className="flex items-center justify-center gap-1.5 text-sm text-danger">
            <CircleAlert size={16} aria-hidden />
            {loadError}
          </p>
          <Button variant="secondary" className="mt-3" onClick={() => setReloadTick((t) => t + 1)}>
            {t("common.retry")}
          </Button>
        </div>
      </div>
    );
  }

  if (pdfError) {
    return (
      <div className="flex h-full items-center justify-center bg-bg">
        <div className="max-w-md text-center">
          <p className="flex items-center justify-center gap-1.5 text-sm text-danger">
            <CircleAlert size={16} aria-hidden />
            {pdfError}
          </p>
          <Button variant="secondary" className="mt-3" onClick={() => setPdfReloadTick((t) => t + 1)}>
            {t("common.retry")}
          </Button>
        </div>
      </div>
    );
  }

  if (!pdf) {
    return <LoadingState>{t("pdfCoder.loadingDocument")}</LoadingState>;
  }

  return (
    <div className="flex h-full flex-col bg-bg">
      <ViewHeader
        wrap
        title={source.name}
        meta={source.memo}
        actions={
          <>
            <div className="flex flex-wrap items-center gap-1">
              <Select
                value={zoom === "fit" ? "fit" : String(zoom)}
                onChange={(e) => {
                  const v = e.target.value;
                  if (v === "fit") setZoom("fit");
                  else if (v === "actual") setZoom(1);
                  else setZoom(Number(v));
                }}
                aria-label={t("pdfCoder.zoomLevel")}
                className="w-28"
              >
                <option value="fit">{t("pdfCoder.fitWidth")}</option>
                <option value="actual">{t("pdfCoder.actualSize")}</option>
                <option value="0.5">50%</option>
                <option value="0.75">75%</option>
                <option value="1">100%</option>
                <option value="1.25">125%</option>
                <option value="1.5">150%</option>
                <option value="2">200%</option>
              </Select>

              <div className="mx-1 h-4 w-px bg-border" aria-hidden />
              <Button
                variant="toolbarIcon"
                onClick={() => setCurrentPage((p) => clampPage(p - 1))}
                disabled={currentPage <= 1}
                aria-label={t("pdfCoder.prevPage")}
                title={t("pdfCoder.prevPage")}
                icon={<ChevronLeft size={14} aria-hidden />}
              />
              <Input
                type="number"
                value={currentPage}
                min={1}
                max={numPages}
                onChange={onPageInputChange}
                aria-label={t("pdfCoder.jumpToPage")}
                className="w-14 text-center"
              />
              <span className="text-xs text-text-secondary">/ {numPages}</span>
              <Button
                variant="toolbarIcon"
                onClick={() => setCurrentPage((p) => clampPage(p + 1))}
                disabled={currentPage >= numPages}
                aria-label={t("pdfCoder.nextPage")}
                title={t("pdfCoder.nextPage")}
                icon={<ChevronRight size={14} aria-hidden />}
              />

              <div className="mx-1 h-4 w-px bg-border" aria-hidden />
              <Button
                variant="toolbar"
                className={cn(continuous && "border-accent text-accent qc-glow")}
                onClick={() => setContinuous((c) => !c)}
                aria-pressed={continuous}
                icon={<Rows3 size={12} aria-hidden />}
              >
                {t("pdfCoder.continuous")}
              </Button>

              <div className="mx-1 h-4 w-px bg-border" aria-hidden />
              <Button
                variant="toolbar"
                onClick={() => setAutoOpen((o) => !o)}
                icon={<Sparkles size={12} aria-hidden />}
              >
                {t("coder.autocode")}
              </Button>

              <div className="mx-1 h-4 w-px bg-border" aria-hidden />
              <Button
                variant="toolbar"
                className={cn(
                  "shrink-0",
                  plainVisible ? "border-accent text-accent" : "bg-bg text-text-secondary",
                )}
                onClick={() => toggleView("plain")}
                aria-pressed={plainVisible}
                title={t("pdfCoder.plainTextHint")}
                icon={<FileText size={12} aria-hidden />}
              >
                {t("pdfCoder.plainText")}
              </Button>
              <Button
                variant="toolbar"
                className={cn(
                  "shrink-0",
                  pdfVisible ? "border-accent text-accent" : "bg-bg text-text-secondary",
                )}
                onClick={() => toggleView("pdf")}
                aria-pressed={pdfVisible}
                title={t("pdfCoder.pdfViewHint")}
                icon={<FileType size={12} aria-hidden />}
              >
                {t("pdfCoder.pdfView")}
              </Button>

              {/* Linked position sync toggle: when both panes are shown the
                  views follow each other; click to turn the linking off. */}
              <IconButton
                label={t("pdfCoder.linkPosition")}
                title={t("pdfCoder.linkPosition")}
                size="sm"
                disabled={!plainVisible || !pdfVisible}
                aria-pressed={autoSync}
                onClick={() => setAutoSync((v) => !v)}
                className={cn(autoSync && "border-accent text-accent qc-glow")}
              >
                <LinkIcon size={14} aria-hidden />
              </IconButton>

              <div className="mx-1 h-4 w-px bg-border" aria-hidden />
              <Button
                variant="toolbar"
                icon={<MessageSquareText size={12} aria-hidden />}
                onClick={toggleGutter}
                className={cn(gutterVisible && "border-accent text-accent qc-glow")}
                aria-pressed={gutterVisible}
                title={gutterVisible ? t("coder.hideMemos") : t("coder.showMemos")}
              >
                {t("coder.memosToggle")}
              </Button>
              {undo.canUndo && (
                <Button
                  variant="toolbar"
                  icon={<Undo2 size={12} aria-hidden />}
                  onClick={undo.undoLast}
                  title={t("coder.unmarkTitle")}
                >
                  {t("coder.unmarkLast")}
                </Button>
              )}
            </div>
          </>
        }
      />

      {errMsg && <ErrorBanner onClose={() => setErrMsg(null)}>{errMsg}</ErrorBanner>}

      <div className="flex min-h-0 flex-1">
        <div
          className={cn(
            "flex min-h-0 flex-col overflow-hidden bg-bg",
            textDragging ? "" : "transition-[width] duration-200 ease-[var(--qc-ease)]",
            plainVisible ? (pdfVisible ? "shrink-0" : "flex-1") : "shrink-0 w-0",
          )}
          style={plainVisible && pdfVisible ? { width: textW } : undefined}
        >
          {plainMounted && (
          <TextCoder
            sourceId={source.id}
            forceText
            bare
            codings={textCodings}
            annotations={annotations}
            codes={codes}
            onCodingsChange={setTextCodings}
            onAnnotationsChange={setAnnotations}
            onCodesChange={setCodes}
            scrollElRef={textScrollElRef}
            suppressGutter={pdfVisible}
          />
          )}
        </div>
        {pdfVisible && plainVisible && (
          <div
            onMouseDown={startTextResize}
            className={cn(
              "w-1 shrink-0 cursor-col-resize border-l border-border",
              textDragging ? "bg-accent/40" : "bg-surface hover:bg-accent/40",
            )}
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize text panel"
            title="Resize text panel"
          />
        )}
        {pdfVisible && (
          <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden bg-bg qc-enter">
            <div ref={containerRef} className="min-h-0 min-w-0 flex-1 overflow-y-auto bg-bg">
              <div className="mx-auto flex w-max min-w-full flex-col items-center gap-4 p-6">
            {pageNumbers.map((p) => {
              const size = pageSizes.get(p);
              const overlays = buildPageOverlays(codings, p, scale, colorByCid);
              return (
                <div
                  key={p}
                  data-page={p}
                  role="img"
                  aria-label={t("pdfCoder.pageOf", { page: p, pages: numPages })}
                  className="relative shrink-0"
                  style={size ? { width: size.width * scale, height: size.height * scale } : undefined}
                  onMouseDown={(e) => onPageMouseDown(e, p)}
                  onMouseMove={(e) => onPageMouseMove(e, p)}
                  onMouseUp={finishDrag}
                >
                  <canvas ref={(el) => setCanvasRef(p, el)} className="block qc-pdf-canvas" />

                  {overlays.map((o) => (
                    <div
                      key={o.key}
                      data-ctid={o.key}
                      className={cn(
                        "absolute cursor-pointer qc-seg",
                        hiddenCodes.includes(o.coding.cid) && "qc-seg-hidden",
                        selectedImid === o.key && "outline outline-2 outline-accent",
                      )}
                      style={{
                        left: o.left,
                        top: o.top,
                        width: o.width,
                        height: o.height,
                        backgroundColor: codeTint(o.color),
                        border: `1px solid ${o.color}`,
                      }}
                      title={overlayTitle(o)}
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={() => {
                        // Purely client-side: the footer renders from the
                        // loaded codings — no fetch and no create happen on
                        // a view click.
                        clearSelection();
                        setSelectedImid(o.key);
                        setFooterError(null);
                      }}
                    />
                  ))}

                  {/* Live overlay of the geometry being edited (drawn on the
                      page selected in the editor, respecting pdf_page). */}
                  {editDraft && (() => {
                    if (parseDraftPage(editDraft) !== p) return null;
                    const rect = parseDraftRect(editDraft);
                    if (!rect) return null;
                    return (
                      <div
                        className="pointer-events-none absolute border-2 border-accent bg-accent/20"
                        style={{
                          left: rect.x1 * scale,
                          top: rect.y1 * scale,
                          width: rect.width * scale,
                          height: rect.height * scale,
                        }}
                      />
                    );
                  })()}

                  {/* Text codings (shared with the plain-text mode) as
                      best-effort overlays on their matched items. */}
                  {(textOverlays.get(p) ?? []).map((ov) =>
                    ov.items.map((it, i) => (
                      <div
                        key={`t-${ov.ctid}-${i}`}
                        data-ctid={ov.ctid}
                        className={cn(
                          "pointer-events-none absolute qc-seg",
                          hiddenCodes.includes(
                            textCodings.find((c) => c.ctid === ov.ctid)?.cid ?? -1,
                          ) && "qc-seg-hidden",
                          flashTextCtid === ov.ctid && "qc-seg-flash",
                        )}
                        style={{
                          left: it.x * scale,
                          top: it.y * scale,
                          width: it.w * scale,
                          height: it.h * scale,
                          backgroundColor: codeTint(ov.color),
                          border: `1px solid ${ov.color}`,
                        }}
                      />
                    )),
                  )}

                  {drag && drag.pageNumber === p && drag.mode === "region" && (
                    <PreviewRect start={drag.start} current={drag.current} />
                  )}

                  {drag && drag.pageNumber === p && drag.mode === "text" && (
                    <>
                      {coveredTextItems(textItems.get(p) ?? [], scale, drag.start, drag.current).map((it, i) => (
                        <div
                          key={i}
                          className="pointer-events-none absolute"
                          style={{
                            left: it.x * scale,
                            top: it.y * scale,
                            width: it.w * scale,
                            height: it.h * scale,
                            backgroundColor: "var(--qc-accent)",
                            opacity: 0.25,
                          }}
                        />
                      ))}
                    </>
                  )}

                  {!size && (
                    <div className="absolute inset-0 flex items-center justify-center gap-2 text-xs text-text-secondary">
                      <LoaderCircle size={14} className="animate-spin" aria-hidden />
                      {t("pdfCoder.rendering", { page: p })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
            </div>
            {/* Gutter as dedicated stripe next to the PDF scroll (not an overlay) — always mounted for width transition like rightbar. */}
            <MemoGutter
              rows={gutterRows}
              selectedIds={
                selectedImid != null
                  ? [selectedImid]
                  : selectedTextCtid != null
                    ? [selectedTextCtid]
                    : []
              }
              scrollRef={containerRef}
              anchorOf={(id) =>
                containerRef.current?.querySelector<HTMLElement>(`[data-ctid="${id}"]`) ?? null
              }
              onSelect={(id) => {
                if (isImageGutterId(id)) {
                  setSelectedTextCtid(null);
                  setEditDraft(null);
                  setSelectedImid(id);
                  setFooterError(null);
                } else {
                  setSelectedImid(null);
                  setEditDraft(null);
                  setSelectedTextCtid(id);
                  setFooterError(null);
                }
              }}
              onDeselect={() => clearSelection()}
              onUpdateMemo={(id, memo) =>
                gutterUpdate(id, { memo }, isImageGutterId(id) ? refreshCodings : refreshTextCodings)
              }
              onUpdateWeight={(id, weight) =>
                gutterUpdate(id, { weight }, isImageGutterId(id) ? refreshCodings : refreshTextCodings)
              }
              onDelete={gutterDelete}
              onToggleImportant={gutterToggleImportant}
              extrasFor={gutterExtrasFor}
              visible={gutterVisible}
              measureSignal={measureTick}
            />
          </div>
        )}
      </div>

      {!gutterVisible && bubbleRows.length > 0 && (
        <MemoGutterBubble
          rows={bubbleRows}
          scrollRef={containerRef}
          anchorOf={(id) => containerRef.current?.querySelector<HTMLElement>(`[data-ctid="${id}"]`) ?? null}
          onClose={clearSelection}
          onUpdateMemo={(id, memo) =>
            gutterUpdate(id, { memo }, isImageGutterId(id) ? refreshCodings : refreshTextCodings)
          }
          onUpdateWeight={(id, weight) =>
            gutterUpdate(id, { weight }, isImageGutterId(id) ? refreshCodings : refreshTextCodings)
          }
          onDelete={gutterDelete}
          onToggleImportant={gutterToggleImportant}
          extrasFor={gutterExtrasFor}
        />
      )}


      <CodePicker
        open={pickerOpen}
        codes={storeCodeTree}
        onClose={() => {
          setPickerOpen(false);
          // Closing without a pick drops the pending action, so a later
          // sidebar code click (active-code change) can never fire a
          // stale create.
          pendingActionRef.current = null;
        }}
        onPick={handlePickCode}
      />

      <AutocodeDialog
        open={autoOpen}
        onClose={() => setAutoOpen(false)}
        fid={source.id}
        codes={storeCodeTree}
        onDone={() => {
          void refreshTextCodings();
          void refreshCodings();
          void refreshCodes().catch(() => undefined);
        }}
      />
    </div>
  );
}

function PreviewRect({ start, current }: { start: PagePoint; current: PagePoint }) {
  const rect = clampRect(start, current);
  return (
    <div
      className="pointer-events-none absolute border border-accent"
      style={{
        left: rect.x1,
        top: rect.y1,
        width: rect.x2 - rect.x1,
        height: rect.y2 - rect.y1,
        backgroundColor: "var(--qc-accent)",
        opacity: 0.15,
      }}
    />
  );
}

/** Small labeled number input for one region-coordinate field. */
function CoordField({
  label,
  value,
  onChange,
  className = "",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <label className={`flex flex-col gap-0.5 ${className}`}>
      <span className="text-[10px] font-medium uppercase tracking-wide text-text-secondary">{label}</span>
      <Input
        type="number"
        min={0}
        step={1}
        value={value}
        aria-label={label}
        onChange={(e) => onChange(e.target.value)}
        className="w-16"
      />
    </label>
  );
}
