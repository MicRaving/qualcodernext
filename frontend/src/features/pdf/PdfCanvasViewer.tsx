/**
 * PdfCanvasViewer — the uniform PDF surface for surfaces that do not host
 * coding overlays (the meta Extract/Download right bar).
 *
 * It renders the pages to `<canvas className="block qc-pdf-canvas">`, the
 * hook the OLED dark theme in `index.css` targets — so a PDF looks identical
 * to the coding view's centre panel. The pdf.js pipeline lives in
 * `usePdfViewer` (lazy module/worker import), which `PdfCoder` consumes
 * directly for its overlay/gutter layout.
 */
import { useState, type CSSProperties, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, CircleAlert, LoaderCircle } from "lucide-react";
import { Button, LoadingState, Select } from "@/components/ui/orchestrator";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { usePdfViewer, type PdfViewerContext } from "@/features/pdf/usePdfViewer";

export interface PdfCanvasViewerProps {
  sourceId: number;
  title?: string;
  /** How much built-in chrome to show: the full coder toolbar, a compact page
   *  nav, or nothing (the page stack only). */
  controls?: "full" | "minimal" | "none";
  initialPage?: number;
  className?: string;
  /** Extra toolbar controls appended to the built-in ones. */
  extraControls?: ReactNode;
  /** Render prop receiving the full viewer context; its output is rendered at
   *  the end of the page stack (used by hosts that add their own overlays). */
  children?: (context: PdfViewerContext) => ReactNode;
  /** Per-page overlay renderer, positioned inside each page container. */
  renderOverlay?: (pageNumber: number, context: PdfViewerContext) => ReactNode;
  /** Forwarded render errors (shown inline as well). */
  onRenderError?: (message: string) => void;
  /** Label for the loading state (defaults to the coder wording). */
  loadingLabel?: string;
  /** Action shown under an error (e.g. an "open in new tab" fallback). */
  errorAction?: ReactNode;
}

/** The uniform PDF surface: themed canvases + fit-to-width + optional
 *  toolbar, with loading/error states. */
export function PdfCanvasViewer({
  sourceId,
  title,
  controls = "none",
  initialPage,
  className = "",
  extraControls,
  children,
  renderOverlay,
  onRenderError,
  loadingLabel,
  errorAction,
}: PdfCanvasViewerProps) {
  const { t } = useI18n();
  const [renderError, setRenderError] = useState<string | null>(null);
  const viewer = usePdfViewer({
    sourceId,
    initialPage,
    loadErrorFallback: t("pdfCoder.loadDocumentError"),
    onRenderError: (message) => {
      setRenderError(message);
      onRenderError?.(message);
    },
  });

  const context: PdfViewerContext = viewer;

  const pageStack = (
    <div
      ref={viewer.containerRef}
      className="min-h-0 min-w-0 flex-1 overflow-y-auto bg-bg"
    >
      <div className="mx-auto flex w-max min-w-full flex-col items-center gap-4 p-6">
        {viewer.pageNumbers.map((p) => {
          const size = viewer.pageSizes.get(p);
          return (
            <div
              key={p}
              data-page={p}
              role="img"
              aria-label={t("pdfCoder.pageOf", { page: p, pages: viewer.numPages })}
              className="relative shrink-0"
              style={
                size
                  ? ({
                      width: size.width * viewer.scale,
                      height: size.height * viewer.scale,
                    } satisfies CSSProperties)
                  : undefined
              }
            >
              <canvas ref={(el) => viewer.setCanvasRef(p, el)} className="block qc-pdf-canvas" />
              {renderOverlay?.(p, context)}
              {!size && (
                <div className="absolute inset-0 flex items-center justify-center gap-2 text-xs text-text-secondary">
                  <LoaderCircle size={14} className="animate-spin" aria-hidden />
                  {t("pdfCoder.rendering", { page: p })}
                </div>
              )}
            </div>
          );
        })}
        {children?.(context)}
      </div>
    </div>
  );

  const toolbar =
    controls === "none" || viewer.numPages === 0 ? null : (
      <div className="flex shrink-0 flex-wrap items-center gap-1 border-b border-border bg-surface px-3 py-1">
        <Button
          variant="toolbarIcon"
          onClick={() => viewer.setCurrentPage((p) => viewer.clampPage(p - 1))}
          disabled={viewer.currentPage <= 1}
          aria-label={t("pdfCoder.prevPage")}
          title={t("pdfCoder.prevPage")}
          icon={<ChevronLeft size={14} aria-hidden />}
        />
        <span className="text-xs tabular-nums text-text-secondary">
          {viewer.currentPage} / {viewer.numPages}
        </span>
        <Button
          variant="toolbarIcon"
          onClick={() => viewer.setCurrentPage((p) => viewer.clampPage(p + 1))}
          disabled={viewer.currentPage >= viewer.numPages}
          aria-label={t("pdfCoder.nextPage")}
          title={t("pdfCoder.nextPage")}
          icon={<ChevronRight size={14} aria-hidden />}
        />
        {controls === "full" ? (
          <>
            <div className="mx-1 h-4 w-px bg-border" aria-hidden />
            <Select
              value={viewer.zoom === "fit" ? "fit" : String(viewer.zoom)}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "fit") viewer.setZoom("fit");
                else if (v === "actual") viewer.setZoom(1);
                else viewer.setZoom(Number(v));
              }}
              aria-label={t("pdfCoder.zoomLevel")}
              className="h-7 w-28 text-xs"
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
            <Button
              variant="toolbar"
              className={cn(viewer.continuous && "border-accent text-accent qc-glow")}
              onClick={() => viewer.setContinuous((c) => !c)}
              aria-pressed={viewer.continuous}
            >
              {t("pdfCoder.continuous")}
            </Button>
          </>
        ) : null}
        {extraControls}
      </div>
    );

  return (
    <div className={cn("flex min-h-0 min-w-0 flex-1 flex-col bg-bg", className)}>
      {viewer.error ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 p-4 text-center">
          <p className="flex items-center justify-center gap-1.5 text-sm text-danger">
            <CircleAlert size={16} aria-hidden />
            {viewer.error}
          </p>
          {renderError ? <p className="text-xs text-text-secondary">{renderError}</p> : null}
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={viewer.reload}>
              {t("common.retry")}
            </Button>
            {errorAction}
          </div>
        </div>
      ) : !viewer.pdf ? (
        <LoadingState>{loadingLabel ?? t("pdfCoder.loadingDocument")}</LoadingState>
      ) : (
        <>
          {toolbar}
          {title ? <span className="sr-only">{title}</span> : null}
          {pageStack}
        </>
      )}
    </div>
  );
}
