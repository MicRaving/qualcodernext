/**
 * PdfCoder — PDF coding workspace: pdf.js page rendering, rectangle region
 * selection with the shared CodePicker, and per-page coded overlays with an
 * inline details/delete panel. Continuous-scroll and single-page modes.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import * as pdfjsLib from "pdfjs-dist";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import {
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  FileText,
  FileType,
  LoaderCircle,
  Minus,
  Pencil,
  Plus,
  Sparkles,
  Rows3,
  Trash2,
  X,
} from "lucide-react";
import { api, fetchSourceFile, type Annotation, type CodeTreeItem, type Coding, type ImageCoding, type Source } from "@/lib/api";
import { patchCodingWeight } from "@/features/coding/codingApi";
import { CodePicker, type PickedCode } from "@/features/coding/CodePicker";
import { AutocodeDialog } from "@/features/coding/AutocodeDialog";
import { TextCoder } from "@/features/coding/TextCoder";
import {
  buildPageOverlays,
  clampRect,
  DEFAULT_CODING_COLOR,
  type NormalizedRect,
  type PageOverlay,
  type PagePoint,
} from "@/features/coding/pdf";
import { codeTint } from "@/features/coding/tint";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import {
  Button,
  ErrorBanner,
  IconButton,
  Input,
  LoadingState,
  ViewHeader,
} from "@/components/ui/orchestrator";
import { useProjectStore } from "@/stores/project";

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

const DRAG_MIN_SIZE = 5;

/** Download a source's PDF bytes for pdf.js.
 *
 * `fetchSourceFile` builds the URL from the RESOLVED base — the App boot
 * gate holds the UI until `initApiBase()` settles, and on a transport
 * failure (backend still booting / restarted on an ephemeral port) the
 * helper drops the cached base, re-resolves it and retries once — so a
 * stale base can never surface as a spurious "Failed to fetch". HTTP
 * errors stay definitive. */
async function fetchPdfBytes(sourceId: number): Promise<ArrayBuffer> {
  const res = await fetchSourceFile(sourceId);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.arrayBuffer();
}

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
  const activeCodeId = useProjectStore((s) => s.activeCodeId);
  const hiddenCodes = useProjectStore((s) => s.hiddenCodes);

  const [pdfVisible, setPdfVisible] = useState(true);
  const [plainVisible, setPlainVisible] = useState(false);
  const [textW, setTextW] = useState(420);
  const [textDragging, setTextDragging] = useState(false);
  const textResizeRef = useRef<{ startX: number; startW: number } | null>(null);
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
  const [editDraft, setEditDraft] = useState<RectDraft | null>(null);
  /** Freshly created text coding flashed on its matched overlay (~2s). */
  const [flashTextCtid, setFlashTextCtid] = useState<number | null>(null);
  const flashTextTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  function startTextResize(e: ReactMouseEvent<HTMLDivElement>) {
    e.preventDefault();
    textResizeRef.current = { startX: e.clientX, startW: textW };
    setTextDragging(true);
  }

  useEffect(() => {
    if (!textDragging) return;
    const onMove = (e: MouseEvent) => {
      const drag = textResizeRef.current;
      if (!drag) return;
      const containerW = containerRef.current?.clientWidth ?? 0;
      const maxW = containerW > 0 ? Math.round(containerW * 0.7) : 0;
      setTextW(Math.min(maxW, Math.max(220, Math.round(drag.startW + (e.clientX - drag.startX)))));
    };
    const onUp = () => {
      textResizeRef.current = null;
      setTextDragging(false);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [textDragging]);

  const numPages = pdf?.numPages ?? 0;
  const scale = zoom === "fit" ? fittedScale : zoom;

  /* ---------------------------------------------------------------- load */

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setCodings([]);
    setAnnotations([]);
    setCodes([]);
    setSelectedImid(null);
    setPendingRect(null);
    setPickerOpen(false);
    setCurrentPage(1);
    void (async () => {
      try {
        const [cod, textCod, anns, flat] = await Promise.all([
          api.imageCodings(source.id),
          api.sourceCoding(source.id),
          api.fileAnnotations(source.id),
          api.codesFlat(),
        ]);
        if (cancelled) return;
        setCodings(cod);
        setTextCodings(textCod);
        setAnnotations(anns);
        setCodes(flat);
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : t("coder.loadCodingsError"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source.id, reloadTick, t]);

  useEffect(() => {
    let cancelled = false;
    setPdf(null);
    setPdfError(null);
    setPageSizes(new Map());
    setTextItems(new Map());
    setFittedScale(1);
    void (async () => {
      try {
        // Fetch the raw bytes ourselves (with a timeout) and hand them to
        // pdf.js as `data` — this avoids Range/streaming/mixed-content
        // quirks of `url` loading inside WebView2/Tauri custom protocols.
        // fetchPdfBytes resolves the API base first and retries transport
        // failures once, so a still-booting/ephemeral-port backend cannot
        // surface as a spurious "Failed to fetch".
        const data = await fetchPdfBytes(source.id);
        if (cancelled) return;
        const task = pdfjsLib.getDocument({ data });
        const doc = await task.promise;
        if (cancelled) return;
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
        if (cancelled) return;
        setPageSizes(sizes);
        setTextItems(items);
      } catch (e) {
        if (!cancelled) setPdfError(e instanceof Error ? e.message : t("pdfCoder.loadDocumentError"));
      }
    })();
    return () => {
      cancelled = true;
    };
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
            setErrMsg(e instanceof Error ? e.message : t("pdfCoder.loadDocumentError"));
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

  const codeById = useMemo(() => {
    const m = new Map<number, CodeTreeItem>();
    for (const c of codes) if (c.kind === "code") m.set(c.id, c);
    return m;
  }, [codes]);

  const colorByCid = useMemo(() => {
    const m = new Map<number, string>();
    for (const [id, c] of codeById) m.set(id, c.color ?? DEFAULT_CODING_COLOR);
    return m;
  }, [codeById]);

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

  const refreshCodings = useCallback(async () => {
    setCodings(await api.imageCodings(source.id));
  }, [source.id]);

  const refreshTextCodings = useCallback(async () => {
    setTextCodings(await api.sourceCoding(source.id));
  }, [source.id]);

  const refreshCodes = useCallback(async () => {
    setCodes(await api.codesFlat());
  }, []);

  /** Flash a freshly created text coding's overlay and scroll its page into
   *  view (the text overlays are best-effort word matches, so a missing
   *  match just skips the scroll). Takes the created coding directly — the
   *  refreshed codings array is not available in this closure yet. */
  const flashTextCoding = useCallback(
    (coding: Coding | null) => {
      if (!coding || !coding.seltext) return;
      for (const [page, items] of textItems) {
        if (matchCodingItems(items, coding.seltext)) {
          containerRef.current
            ?.querySelector(`[data-page="${page}"]`)
            ?.scrollIntoView({ block: "nearest" });
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
  useEffect(() => {
    const handle = () => {
      void refreshCodings();
      void refreshTextCodings();
      void refreshCodes();
    };
    window.addEventListener("qc:codings-changed", handle);
    return () => window.removeEventListener("qc:codings-changed", handle);
  }, [refreshCodings, refreshTextCodings, refreshCodes]);

  function clampPage(p: number): number {
    return Math.min(Math.max(1, p), Math.max(1, numPages));
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
    setSelectedImid(null);
    setEditDraft(null);
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
          await refreshTextCodings();
          // Auto-show the freshly created coding: flash its overlay and
          // scroll the page it sits on into view.
          flashTextCoding(created);
        } catch (e) {
          setErrMsg(e instanceof Error ? e.message : t("coder.createError"));
        } finally {
          pendingActionRef.current = null;
        }
      })();
    },
    [source.id, t, refreshTextCodings, flashTextCoding],
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
          await refreshCodings();
          // Auto-show the details of the freshly created region coding.
          setSelectedImid(created.imid);
          setEditDraft(null);
        } catch (e) {
          setErrMsg(e instanceof Error ? e.message : t("coder.createError"));
        } finally {
          setPendingRect(null);
        }
      })();
      void refreshCodes().catch(() => undefined);
    },
    [scale, source.id, refreshCodings, refreshCodes, t],
  );

  const finishDrag = useCallback(() => {
    const d = dragRef.current;
    if (!d) return;
    setDrag(null);
    dragRef.current = null;
    if (d.mode === "text") {
      const covered = coveredTextItems(textItems.get(d.pageNumber) ?? [], scale, d.start, d.current);
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
          setErrMsg(e instanceof Error ? e.message : t("pdfCoder.textLocateError"));
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
  }, [activeCodeId, codePendingRect, codePendingText, source.id, t, scale, textItems]);

  // Clicking a code in the left sidebar assigns it to the pending action.
  useEffect(() => {
    const onAssign = (e: Event) => {
      const cid = (e as CustomEvent<{ cid: number }>).detail?.cid;
      if (typeof cid !== "number") return;
      setPickerOpen(false);
      if (pendingActionRef.current?.kind === "text") {
        codePendingText(cid);
      } else {
        codePendingRect(cid);
      }
    };
    window.addEventListener("qc:assign-code", onAssign);
    return () => window.removeEventListener("qc:assign-code", onAssign);
  }, [codePendingRect, codePendingText]);

  // Catch releases that land outside the page element; finishDrag is
  // idempotent, so a fast release inside the element (handled by its own
  // onMouseUp) and this window listener cannot double-fire.
  useEffect(() => {
    if (!drag) return;
    window.addEventListener("mouseup", finishDrag);
    return () => window.removeEventListener("mouseup", finishDrag);
  }, [drag, finishDrag]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (pickerOpen) {
        setPickerOpen(false);
        return;
      }
      setDrag(null);
      setPendingRect(null);
      setSelectedImid(null);
      setEditDraft(null);
      pendingActionRef.current = null;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pickerOpen]);

  function handlePickCode(picked: PickedCode) {
    setPickerOpen(false);
    if (pendingActionRef.current?.kind === "text") {
      codePendingText(picked.cid);
    } else {
      codePendingRect(picked.cid);
    }
  }

  function deleteCoding(row: ImageCoding) {
    const code = codeById.get(row.cid);
    if (!window.confirm(t("pdfCoder.removeConfirm", { name: code?.name ?? t("coder.fallbackCodeLower", { id: row.cid }) }))) return;
    void (async () => {
      try {
        await api.deleteImageCoding(row.imid);
        setSelectedImid(null);
        setEditDraft(null);
        await refreshCodings();
      } catch (e) {
        setErrMsg(e instanceof Error ? e.message : t("coder.removeError"));
      }
    })();
  }

  /** Segment weight (backend rows carry it; 0 = no weight). */
  const imageWeight = (row: ImageCoding): number =>
    (row as ImageCoding & { weight?: number }).weight ?? 0;

  /** Stepper update of a coded region's weight (0-100; 0 = no weight). */
  function updateCodingWeight(row: ImageCoding, weight: number) {
    void (async () => {
      try {
        await patchCodingWeight("image", row.imid, weight);
        await refreshCodings();
      } catch (e) {
        setErrMsg(e instanceof Error ? e.message : t("coder.weightError"));
      }
    })();
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
      setErrMsg(e instanceof Error ? e.message : t("imageCoder.regionSaveError"));
    }
  }

  function onPageInputChange(e: ChangeEvent<HTMLInputElement>) {
    const v = Number.parseInt(e.target.value, 10);
    if (Number.isFinite(v)) setCurrentPage(clampPage(v));
  }

  function overlayTitle(o: PageOverlay): string {
    const code = codeById.get(o.coding.cid);
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
              <Button
                variant="secondary"
                className={cn("h-7", zoom === "fit" && "border-accent text-accent")}
                onClick={() => setZoom("fit")}
              >
                {t("pdfCoder.fitWidth")}
              </Button>
              {([0.5, 0.75, 1, 1.5] as const).map((z) => (
                <Button
                  key={z}
                  variant="secondary"
                  className={cn("h-7", zoom === z && "border-accent text-accent")}
                  onClick={() => setZoom(z)}
                >
                  {Math.round(z * 100)}%
                </Button>
              ))}

              {!continuous && (
                <>
                  <div className="mx-1 h-4 w-px bg-border" aria-hidden />
                  <Button
                    variant="secondary"
                    className="h-7"
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
                    variant="secondary"
                    className="h-7"
                    onClick={() => setCurrentPage((p) => clampPage(p + 1))}
                    disabled={currentPage >= numPages}
                    aria-label={t("pdfCoder.nextPage")}
                    title={t("pdfCoder.nextPage")}
                    icon={<ChevronRight size={14} aria-hidden />}
                  />
                </>
              )}

              <div className="mx-1 h-4 w-px bg-border" aria-hidden />
              <Button
                variant="secondary"
                className={cn("h-7", continuous && "border-accent text-accent")}
                onClick={() => setContinuous((c) => !c)}
                icon={<Rows3 size={12} aria-hidden />}
              >
                {t("pdfCoder.continuous")}
              </Button>

              <div className="mx-1 h-4 w-px bg-border" aria-hidden />
              <Button
                variant="secondary"
                className="h-7"
                onClick={() => setAutoOpen((o) => !o)}
                icon={<Sparkles size={12} aria-hidden />}
              >
                {t("coder.autocode")}
              </Button>

              <div className="mx-1 h-4 w-px bg-border" aria-hidden />
              <Button
                variant="secondary"
                className={cn(
                  "h-7 shrink-0",
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
                variant="secondary"
                className={cn(
                  "h-7 shrink-0",
                  pdfVisible ? "border-accent text-accent" : "bg-bg text-text-secondary",
                )}
                onClick={() => toggleView("pdf")}
                aria-pressed={pdfVisible}
                title={t("pdfCoder.pdfViewHint")}
                icon={<FileType size={12} aria-hidden />}
              >
                {t("pdfCoder.pdfView")}
              </Button>
            </div>
          </>
        }
      />

      {errMsg && <ErrorBanner onClose={() => setErrMsg(null)}>{errMsg}</ErrorBanner>}

      <div className="flex min-h-0 flex-1">
        {pdfVisible && (
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
                  <canvas ref={(el) => setCanvasRef(p, el)} className="block" />

                  {overlays.map((o) => (
                    <div
                      key={o.key}
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
                        setEditDraft(null);
                        setSelectedImid(o.key);
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
        )}
        {pdfVisible && plainVisible && (
          <div
            onMouseDown={startTextResize}
            className={cn(
              "w-1 shrink-0 cursor-col-resize border-r border-border",
              textDragging ? "bg-accent/40" : "bg-surface hover:bg-accent/40",
            )}
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize text panel"
            title="Resize text panel"
          />
        )}
        {plainVisible && (
          <div
            className={cn(
              "flex min-h-0 flex-col overflow-hidden bg-bg",
              pdfVisible ? "shrink-0" : "flex-1",
            )}
            style={pdfVisible ? { width: textW } : undefined}
          >
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
            />
          </div>
        )}
      </div>

      {selectedCoding && (
        <div className="shrink-0 border-t border-border bg-surface px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-text-secondary">{t("coder.codingDetails")}</span>
            <div className="flex-1" />
            <IconButton
              label={t("common.closeDetails")}
              size="sm"
              onClick={() => {
                setSelectedImid(null);
                setEditDraft(null);
              }}
            >
              <X size={14} aria-hidden />
            </IconButton>
          </div>
          <ul className="mt-1.5 space-y-1.5">
            <li className="flex items-center gap-2 rounded-sm border border-border bg-bg px-2 py-1.5 text-sm">
              <span
                className="h-3 w-3 shrink-0 rounded-sm border border-border"
                style={{
                  backgroundColor: codeById.get(selectedCoding.cid)?.color ?? DEFAULT_CODING_COLOR,
                }}
                aria-hidden
              />
              <span className="font-medium">
                {codeById.get(selectedCoding.cid)?.name ?? t("coder.fallbackCode", { id: selectedCoding.cid })}
              </span>
              {selectedCoding.memo && (
                <span className="truncate text-xs text-text-secondary">{selectedCoding.memo}</span>
              )}
              <span
                className="text-xs text-text-secondary"
                title={selectedCoding.date ? t("pdfCoder.codedOn", { date: selectedCoding.date }) : undefined}
                aria-label={selectedCoding.date ? t("pdfCoder.codedOn", { date: selectedCoding.date }) : undefined}
              >
                {t("pdfCoder.pageLabel", { page: selectedCoding.pdf_page ?? "?" })}
              </span>
              <span className="flex items-center gap-1">
                <span className="text-xs text-text-secondary">{t("coder.weight")}</span>
                <Button
                  variant="secondary"
                  className="h-6 w-6 justify-center px-0"
                  icon={<Minus size={12} aria-hidden />}
                  title={t("coder.weightDec")}
                  aria-label={t("coder.weightDec")}
                  disabled={imageWeight(selectedCoding) === 0}
                  onClick={() => updateCodingWeight(selectedCoding, imageWeight(selectedCoding) - 1)}
                />
                <span
                  className="min-w-5 text-center text-xs text-text-secondary"
                  aria-label={t("coder.weight")}
                >
                  {imageWeight(selectedCoding)}
                </span>
                <Button
                  variant="secondary"
                  className="h-6 w-6 justify-center px-0"
                  icon={<Plus size={12} aria-hidden />}
                  title={t("coder.weightInc")}
                  aria-label={t("coder.weightInc")}
                  disabled={imageWeight(selectedCoding) >= 100}
                  onClick={() => updateCodingWeight(selectedCoding, imageWeight(selectedCoding) + 1)}
                />
              </span>
              <div className="flex-1" />
              {!editDraft && (
                <IconButton
                  label={t("pdfCoder.editRegion")}
                  title={t("pdfCoder.editRegion")}
                  size="sm"
                  onClick={() => startEditGeometry(selectedCoding)}
                >
                  <Pencil size={14} aria-hidden />
                </IconButton>
              )}
              <IconButton
                label={t("coder.removeThis")}
                title={t("coder.removeThis")}
                size="sm"
                onClick={() => deleteCoding(selectedCoding)}
                className="hover:text-danger"
              >
                <Trash2 size={14} aria-hidden />
              </IconButton>
            </li>
          </ul>
          {editDraft && (
            <div className="mt-1.5 flex flex-wrap items-end gap-2 rounded-sm border border-border bg-bg px-2 py-1.5">
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
      )}

      <CodePicker
        open={pickerOpen}
        codes={storeCodeTree}
        onClose={() => setPickerOpen(false)}
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
