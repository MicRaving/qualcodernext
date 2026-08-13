/**
 * HtmlCoder — webpage snapshot coding workspace: a split view with the
 * extracted plain text (the coding surface) and the captured webpage
 * rendered from the saved raw .html file, mirroring the PdfCoder split
 * pattern (two independent always-visible toggle panes with a draggable
 * divider).
 *
 * Coding happens on the PLAIN TEXT side (html sources are media_type
 * "text", so TextCoder codes them as text); the WEBPAGE side is
 * view-only — the raw file is rendered in a sandboxed iframe
 * (`sandbox="allow-same-origin"` only, no scripts). Live-sync of codings
 * between the panes is intentionally NOT implemented: the webpage is a
 * read-only snapshot of the captured page, so the text side is the single
 * owner of the coding state (the PdfCoder's text-overlay matching does
 * not apply to arbitrary webpages).
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { CircleAlert, Download, FileText, Globe, LoaderCircle } from "lucide-react";
import {
  api,
  fetchWithTimeout,
  sourceFileUrl,
  sourcePdfUrl,
  type Annotation,
  type CodeTreeItem,
  type Coding,
  type Source,
} from "@/lib/api";
import { TextCoder } from "@/features/coding/TextCoder";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { Button, ErrorBanner, LoadingState, ViewHeader } from "@/components/ui/orchestrator";

export function HtmlCoder({ source }: { source: Source }) {
  const { t } = useI18n();

  const [webpageVisible, setWebpageVisible] = useState(true);
  const [plainVisible, setPlainVisible] = useState(false);
  const [textW, setTextW] = useState(420);
  const [textDragging, setTextDragging] = useState(false);
  const textResizeRef = useRef<{ startX: number; startW: number } | null>(null);

  /** The raw captured HTML, loaded through the file-serving endpoint. */
  const [html, setHtml] = useState<string | null>(null);
  const [htmlLoading, setHtmlLoading] = useState(false);
  const [htmlError, setHtmlError] = useState<string | null>(null);
  const [htmlReloadTick, setHtmlReloadTick] = useState(0);

  const [codings, setCodings] = useState<Coding[]>([]);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [codes, setCodes] = useState<CodeTreeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const [downloading, setDownloading] = useState(false);

  const containerRef = useRef<HTMLDivElement | null>(null);

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

  /* ---------------------------------------------------------------- load */

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setCodings([]);
    setAnnotations([]);
    setCodes([]);
    void (async () => {
      try {
        const [cod, anns, flat] = await Promise.all([
          api.sourceCoding(source.id),
          api.fileAnnotations(source.id),
          api.codesFlat(),
        ]);
        if (cancelled) return;
        setCodings(cod);
        setAnnotations(anns);
        setCodes(flat);
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : t("htmlCoder.loadCodingsError"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source.id, reloadTick, t]);

  // Fetch the raw .html file through the file-serving endpoint. When it is
  // unavailable (article-only import or a broken link) the webpage pane
  // shows a hint and the plain-text pane remains fully usable.
  useEffect(() => {
    let cancelled = false;
    setHtmlLoading(true);
    setHtmlError(null);
    void (async () => {
      try {
        const res = await fetchWithTimeout(sourceFileUrl(source.id), undefined, 60_000);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const text = await res.text();
        if (cancelled) return;
        setHtml(text);
      } catch (e) {
        if (!cancelled) {
          setHtml(null);
          setHtmlError(e instanceof Error ? e.message : t("htmlCoder.webpageLoadError"));
        }
      } finally {
        if (!cancelled) setHtmlLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source.id, htmlReloadTick, t]);

  const refreshCodings = useCallback(async () => {
    setCodings(await api.sourceCoding(source.id));
  }, [source.id]);

  const refreshAnnotations = useCallback(async () => {
    setAnnotations(await api.fileAnnotations(source.id));
  }, [source.id]);

  const refreshCodes = useCallback(async () => {
    setCodes(await api.codesFlat());
  }, []);

  // History undo/redo: reload codings/annotations when the audit log reverts
  // a change (the shell only refreshes project metadata).
  useEffect(() => {
    const handle = () => {
      void refreshCodings();
      void refreshAnnotations();
      void refreshCodes();
    };
    window.addEventListener("qc:codings-changed", handle);
    return () => window.removeEventListener("qc:codings-changed", handle);
  }, [refreshCodings, refreshAnnotations, refreshCodes]);

  /* ------------------------------------------------------------- actions */

  /** Toggle a pane on/off; never allow both off (fall back to webpage only). */
  function toggleView(kind: "webpage" | "plain") {
    const next = { webpage: webpageVisible, plain: plainVisible };
    if (kind === "webpage") next.webpage = !next.webpage;
    else next.plain = !next.plain;
    if (!next.webpage && !next.plain) next.webpage = true;
    setWebpageVisible(next.webpage);
    setPlainVisible(next.plain);
  }

  /** "Save as PDF": export the captured page through the backend's HTML ->
   *  PDF endpoint and download the bytes (mirrors the downloadCsv blob
   *  pattern — works for any locale / backend origin). */
  function downloadPdf() {
    setDownloading(true);
    setErrMsg(null);
    void (async () => {
      try {
        const res = await fetchWithTimeout(sourcePdfUrl(source.id), undefined, 120_000);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${source.name.replace(/\.html?$/i, "")}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } catch (e) {
        setErrMsg(e instanceof Error ? e.message : t("htmlCoder.downloadError"));
      } finally {
        setDownloading(false);
      }
    })();
  }

  /* ------------------------------------------------------------ rendering */

  if (loading) {
    return <LoadingState>{t("htmlCoder.loading")}</LoadingState>;
  }

  if (loadError) {
    return (
      <div className="flex h-full items-center justify-center bg-bg">
        <div className="max-w-md text-center">
          <p className="flex items-center justify-center gap-1.5 text-sm text-danger">
            <CircleAlert size={16} aria-hidden />
            {loadError}
          </p>
          <Button variant="secondary" className="mt-3" onClick={() => setReloadTick((v) => v + 1)}>
            {t("common.retry")}
          </Button>
        </div>
      </div>
    );
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
                className={cn(
                  "h-7 shrink-0",
                  plainVisible ? "border-accent text-accent" : "bg-bg text-text-secondary",
                )}
                onClick={() => toggleView("plain")}
                aria-pressed={plainVisible}
                title={t("htmlCoder.plainTextHint")}
                icon={<FileText size={12} aria-hidden />}
              >
                {t("htmlCoder.plainText")}
              </Button>
              <Button
                variant="secondary"
                className={cn(
                  "h-7 shrink-0",
                  webpageVisible ? "border-accent text-accent" : "bg-bg text-text-secondary",
                )}
                onClick={() => toggleView("webpage")}
                aria-pressed={webpageVisible}
                title={t("htmlCoder.webpageHint")}
                icon={<Globe size={12} aria-hidden />}
              >
                {t("htmlCoder.webpage")}
              </Button>

              <div className="mx-1 h-4 w-px bg-border" aria-hidden />
              <Button
                variant="secondary"
                className="h-7"
                icon={
                  downloading ? (
                    <LoaderCircle size={12} className="animate-spin" aria-hidden />
                  ) : (
                    <Download size={12} aria-hidden />
                  )
                }
                onClick={downloadPdf}
                disabled={htmlError != null || downloading}
                title={t("htmlCoder.downloadPdfHint")}
              >
                {t("htmlCoder.downloadPdf")}
              </Button>
            </div>
          </>
        }
      />

      {errMsg && <ErrorBanner onClose={() => setErrMsg(null)}>{errMsg}</ErrorBanner>}

      <div className="flex min-h-0 flex-1">
        {webpageVisible && (
          <div ref={containerRef} className="min-h-0 min-w-0 flex-1 overflow-auto bg-bg">
            {html != null ? (
              <iframe
                title={t("htmlCoder.webpage")}
                srcDoc={html}
                // View-only: same origin for relative images/css, no scripts.
                sandbox="allow-same-origin"
                className="h-full w-full border-0"
              />
            ) : htmlLoading ? (
              <div className="flex h-full items-center justify-center gap-2 text-xs text-text-secondary">
                <LoaderCircle size={14} className="animate-spin" aria-hidden />
                {t("htmlCoder.loadingWebpage")}
              </div>
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
                <p className="flex items-center justify-center gap-1.5 text-sm text-text-secondary">
                  <CircleAlert size={16} aria-hidden />
                  {t("htmlCoder.noSnapshot")}
                </p>
                <Button
                  variant="secondary"
                  className="h-7"
                  onClick={() => setHtmlReloadTick((v) => v + 1)}
                >
                  {t("common.retry")}
                </Button>
              </div>
            )}
          </div>
        )}
        {webpageVisible && plainVisible && (
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
              webpageVisible ? "shrink-0" : "flex-1",
            )}
            style={webpageVisible ? { width: textW } : undefined}
          >
            <TextCoder
              sourceId={source.id}
              forceText
              bare
              codings={codings}
              annotations={annotations}
              codes={codes}
              onCodingsChange={setCodings}
              onAnnotationsChange={setAnnotations}
              onCodesChange={setCodes}
            />
          </div>
        )}
      </div>
    </div>
  );
}
