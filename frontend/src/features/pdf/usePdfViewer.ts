/**
 * The shared pdf.js rendering pipeline (`usePdfViewer`) used by both the
 * coding view (`PdfCoder`) and `PdfCanvasViewer` (the meta Extract/Download
 * right bar). Keeping the pipeline here — and the component in
 * `PdfCanvasViewer.tsx` — lets fast-refresh treat the component file as a
 * component-only module.
 *
 * The pdf.js module is imported LAZILY inside the load effect, so the worker
 * is only downloaded when a PDF is actually opened.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from "react";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import { fetchSourceFile } from "@/lib/api";
import { useAsyncEffect } from "@/lib/useAsync";
import { errorMessage } from "@/lib/utils";

/** One page's unscaled (PDF unit) viewport. */
export interface PdfPageSize {
  width: number;
  height: number;
}

/** One pdf.js text item in PDF (unscaled) units, top-left origin. */
export interface PdfTextItem {
  x: number;
  y: number;
  w: number;
  h: number;
  str: string;
  fontName?: string;
}

/** Fit-to-width or a numeric zoom factor. */
export type PdfZoom = number | "fit";

/** The state `PdfCoder` needs to position its own overlays over the pages. */
export interface PdfViewerContext {
  pdf: PDFDocumentProxy | null;
  scale: number;
  pageSizes: Map<number, PdfPageSize>;
  textItems: Map<number, PdfTextItem[]>;
  containerRef: RefObject<HTMLDivElement | null>;
  pageNumbers: number[];
  currentPage: number;
  numPages: number;
  zoom: PdfZoom;
  setZoom: Dispatch<SetStateAction<PdfZoom>>;
  continuous: boolean;
  setContinuous: Dispatch<SetStateAction<boolean>>;
  setCurrentPage: Dispatch<SetStateAction<number>>;
  clampPage: (page: number) => number;
}

export interface UsePdfViewerOptions {
  sourceId: number;
  /** First page shown; defaults to 1. */
  initialPage?: number;
  /** Initial continuous-scroll mode (default true). */
  continuous?: boolean;
  /** When false the pages are unmounted; toggling back re-renders them. */
  active?: boolean;
  /** Message used when the document fails to load. */
  loadErrorFallback?: string;
  /** Forwarded a render failure (a failed canvas render is never silent). */
  onRenderError?: (message: string) => void;
  /** Extract per-page text items (needed only for coding overlays; a plain
   *  viewer skips it — a large PDF extracts far faster without it). */
  extractText?: boolean;
}

export interface UsePdfViewerResult extends PdfViewerContext {
  loading: boolean;
  error: string | null;
  reload: () => void;
  fittedScale: number;
  setCanvasRef: (page: number, el: HTMLCanvasElement | null) => void;
}

const DEFAULT_LOAD_ERROR = "Failed to load document";

/** Download a source's PDF bytes for pdf.js. `fetchSourceFile` resolves the
 *  API base and retries transport failures once, so a stale base never
 *  surfaces as a spurious "Failed to fetch". */
async function fetchPdfBytes(sourceId: number): Promise<ArrayBuffer> {
  const res = await fetchSourceFile(sourceId);
  return res.arrayBuffer();
}

/** The pdf.js pipeline shared by the coder and the meta viewer. */
export function usePdfViewer({
  sourceId,
  initialPage = 1,
  continuous: initialContinuous = true,
  active = true,
  loadErrorFallback = DEFAULT_LOAD_ERROR,
  onRenderError,
  extractText = true,
}: UsePdfViewerOptions): UsePdfViewerResult {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRefs = useRef(new Map<number, HTMLCanvasElement>());
  /** page -> "<scale>|<dpr>" already drawn, so re-running the effect (scroll,
   *  unrelated state) never re-renders a page that is already crisp. */
  const renderedRef = useRef(new Map<number, string>());

  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [pageSizes, setPageSizes] = useState<Map<number, PdfPageSize>>(new Map());
  const [textItems, setTextItems] = useState<Map<number, PdfTextItem[]>>(new Map());
  const [continuous, setContinuous] = useState(initialContinuous);
  const [currentPage, setCurrentPage] = useState(Math.max(1, initialPage));
  const [zoom, setZoom] = useState<PdfZoom>("fit");
  const [fittedScale, setFittedScale] = useState(1);

  const numPages = pdf?.numPages ?? 0;
  const scale = zoom === "fit" ? fittedScale : zoom;

  // Keep the latest render-error sink reachable without re-running the render
  // effect (callers pass inline closures).
  const onRenderErrorRef = useRef(onRenderError);
  useEffect(() => {
    onRenderErrorRef.current = onRenderError;
  });

  // Fetch + parse the document, then read every page's geometry and text
  // items. The dynamic import keeps the pdf.js chunk out of the main bundle.
  useAsyncEffect(
    async (signal) => {
      setLoading(true);
      setError(null);
      setPdf(null);
      setPageSizes(new Map());
      setTextItems(new Map());
      setFittedScale(1);
      renderedRef.current.clear();
      try {
        const pdfjsLib = await import("pdfjs-dist");
        pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.min.mjs",
          import.meta.url,
        ).toString();
        const data = await fetchPdfBytes(sourceId);
        signal.throwIfAborted();
        const task = pdfjsLib.getDocument({ data });
        const doc = await task.promise;
        signal.throwIfAborted();
        setPdf(doc);
        const sizes = new Map<number, PdfPageSize>();
        const items = new Map<number, PdfTextItem[]>();
        for (let p = 1; p <= doc.numPages; p++) {
          const page = await doc.getPage(p);
          const vp = page.getViewport({ scale: 1 });
          sizes.set(p, { width: vp.width, height: vp.height });
          if (!extractText) continue;
          const content = await page.getTextContent();
          const list: PdfTextItem[] = [];
          for (const item of content.items) {
            if (!("str" in item) || item.str === "") continue;
            const tr = item.transform;
            // pdf.js reports PDF units with y growing UPWARD; flip to the
            // screen convention (top-left origin) for hit-testing/overlays.
            list.push({
              x: tr[4],
              y: vp.height - (tr[5] + item.height),
              w: item.width,
              h: item.height,
              str: item.str,
              fontName:
                "fontName" in item ? (item as { fontName?: string }).fontName : undefined,
            });
          }
          items.set(p, list);
        }
        signal.throwIfAborted();
        setPageSizes(sizes);
        setTextItems(items);
      } catch (e) {
        signal.throwIfAborted();
        setError(errorMessage(e, loadErrorFallback));
      } finally {
        signal.throwIfAborted();
        setLoading(false);
      }
    },
    [sourceId, reloadTick, loadErrorFallback, extractText],
  );

  // HiDPI: render the canvas backing store at devicePixelRatio so pages are
  // sharp; re-measure when the window moves between displays.
  const [dpr, setDpr] = useState(() =>
    typeof window === "undefined" ? 1 : Math.max(1, window.devicePixelRatio || 1),
  );
  useEffect(() => {
    const update = () => setDpr(Math.max(1, window.devicePixelRatio || 1));
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  // Render the page canvases whenever the document/view changes. Pages are
  // drawn at `scale * dpr` (sharp), cached per page, and — in continuous mode —
  // only when they scroll near the viewport, so a big PDF neither blocks the
  // first paint nor re-renders on every scroll.
  const singlePage = continuous ? null : currentPage;
  useEffect(() => {
    if (!pdf || !active) return;
    const token = `${scale.toFixed(4)}|${dpr}`;
    const tasks: RenderTask[] = [];
    let cancelled = false;
    let observer: IntersectionObserver | null = null;

    const renderPage = async (pageNumber: number) => {
      const canvas = canvasRefs.current.get(pageNumber);
      if (!canvas || cancelled) return;
      if (renderedRef.current.get(pageNumber) === token) return;
      const size = pageSizes.get(pageNumber);
      if (size) {
        // Reserve the CSS box immediately so the scroll layout is stable and an
        // unrendered page is still observable.
        canvas.style.width = `${size.width * scale}px`;
        canvas.style.height = `${size.height * scale}px`;
      }
      try {
        const page = await pdf.getPage(pageNumber);
        if (cancelled) return;
        const viewport = page.getViewport({ scale: scale * dpr });
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        canvas.style.width = `${viewport.width / dpr}px`;
        canvas.style.height = `${viewport.height / dpr}px`;
        const task = page.render({ canvas, viewport });
        tasks.push(task);
        await task.promise;
        if (!cancelled) renderedRef.current.set(pageNumber, token);
      } catch (e) {
        if (!cancelled) {
          onRenderErrorRef.current?.(errorMessage(e, loadErrorFallback));
        }
      }
    };

    const root = containerRef.current;
    if (singlePage !== null) {
      void renderPage(singlePage);
    } else if (typeof IntersectionObserver === "undefined" || !root) {
      void (async () => {
        for (let p = 1; p <= pdf.numPages && !cancelled; p++) await renderPage(p);
      })();
    } else {
      observer = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            const pageNumber = Number((entry.target as HTMLElement).dataset.pdfPage);
            if (pageNumber) void renderPage(pageNumber);
          }
        },
        { root, rootMargin: "800px 0px" },
      );
      for (let p = 1; p <= pdf.numPages; p++) {
        const canvas = canvasRefs.current.get(p);
        if (canvas) observer.observe(canvas);
      }
    }
    return () => {
      cancelled = true;
      observer?.disconnect();
      for (const t of tasks) {
        try {
          t.cancel();
        } catch {
          /* render already finished */
        }
      }
    };
  }, [pdf, scale, dpr, singlePage, active, pageSizes, loadErrorFallback]);

  // Continuous mode: keep `currentPage` in step with the top-visible page and
  // bring a requested page into view. Without this the prev/next buttons and
  // the jump-to-page input only moved the counter while the stack of pages
  // stayed where it was.
  useEffect(() => {
    if (!pdf || !active || !continuous) return;
    const root = containerRef.current;
    if (!root) return;
    let raf = 0;
    const syncFromScroll = () => {
      if (raf) return;
      raf = window.requestAnimationFrame(() => {
        raf = 0;
        const cTop = root.getBoundingClientRect().top;
        let best = 1;
        let bestDist = Number.POSITIVE_INFINITY;
        for (const el of root.querySelectorAll<HTMLElement>("[data-page]")) {
          const p = Number(el.dataset.page);
          if (!Number.isFinite(p) || p < 1) continue;
          const dist = Math.abs(el.getBoundingClientRect().top - cTop);
          if (dist < bestDist) {
            bestDist = dist;
            best = p;
          }
        }
        setCurrentPage((prev) => (prev === best ? prev : best));
      });
    };
    root.addEventListener("scroll", syncFromScroll, { passive: true });
    return () => {
      root.removeEventListener("scroll", syncFromScroll);
      if (raf) window.cancelAnimationFrame(raf);
    };
  }, [pdf, active, continuous]);

  // Bring the requested page into view when the controls change it, but leave
  // an already-visible page alone so a manual scroll never snaps.
  useEffect(() => {
    if (!pdf || !active || !continuous) return;
    const root = containerRef.current;
    if (!root) return;
    const el = root.querySelector<HTMLElement>(`[data-page="${currentPage}"]`);
    if (!el) return;
    const pageRect = el.getBoundingClientRect();
    const rootRect = root.getBoundingClientRect();
    if (pageRect.bottom > rootRect.top && pageRect.top < rootRect.bottom) return;
    root.scrollTo({ top: root.scrollTop + (pageRect.top - rootRect.top), behavior: "smooth" });
  }, [pdf, active, continuous, currentPage]);

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
    if (zoom !== "fit" || !pdf || !active) return;
    void applyFit();
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => void applyFit());
    ro.observe(el);
    return () => ro.disconnect();
  }, [zoom, pdf, applyFit, active]);

  const clampPage = useCallback(
    (page: number) => Math.min(Math.max(1, page), Math.max(1, numPages)),
    [numPages],
  );

  const pageNumbers = useMemo(() => {
    const out: number[] = [];
    if (continuous) {
      for (let p = 1; p <= numPages; p++) out.push(p);
    } else {
      out.push(currentPage);
    }
    return out;
  }, [continuous, numPages, currentPage]);

  const setCanvasRef = useCallback((page: number, el: HTMLCanvasElement | null) => {
    if (el) {
      el.dataset.pdfPage = String(page);
      // A remounted canvas (page unmount/remount, active toggle) has no pixels
      // even though the page was drawn before — invalidate its cache.
      if (canvasRefs.current.get(page) !== el) renderedRef.current.delete(page);
      canvasRefs.current.set(page, el);
    } else {
      canvasRefs.current.delete(page);
      renderedRef.current.delete(page);
    }
  }, []);

  const reload = useCallback(() => setReloadTick((n) => n + 1), []);

  return {
    pdf,
    loading,
    error,
    reload,
    pageSizes,
    textItems,
    scale,
    zoom,
    setZoom,
    fittedScale,
    continuous,
    setContinuous,
    currentPage,
    setCurrentPage,
    numPages,
    pageNumbers,
    containerRef,
    setCanvasRef,
    clampPage,
  };
}
