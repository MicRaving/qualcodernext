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
}: UsePdfViewerOptions): UsePdfViewerResult {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRefs = useRef(new Map<number, HTMLCanvasElement>());

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
    [sourceId, reloadTick, loadErrorFallback],
  );

  // Render the page canvases whenever the document/view changes. Re-running
  // when `active` flips back on re-draws pages whose canvases were unmounted.
  useEffect(() => {
    if (!pdf || !active) return;
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
          await task.promise;
        } catch (e) {
          if (!cancelled) {
            onRenderErrorRef.current?.(errorMessage(e, loadErrorFallback));
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
  }, [pdf, scale, currentPage, continuous, active, loadErrorFallback]);

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
    if (el) canvasRefs.current.set(page, el);
    else canvasRefs.current.delete(page);
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
