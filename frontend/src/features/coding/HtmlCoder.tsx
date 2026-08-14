/**
 * HtmlCoder — webpage snapshot coding workspace: a split view with the
 * extracted plain text (the coding surface) and the captured webpage
 * rendered from the saved raw .html file, mirroring the PdfCoder split
 * pattern (two independent always-visible toggle panes with a draggable
 * divider).
 *
 *  Coding happens on the PLAIN TEXT side (html sources are media_type
 *  "text", so TextCoder codes them as text); the WEBPAGE side mirrors the
 *  codings LIVE: coded segments are highlighted in the rendered page by a
 *  small controlled script injected into the sandboxed iframe.
 *
 *  Matching reality: the backend's text extraction decodes entities, collapses
 *  spaces and inserts newlines at block tags, so a segment's `seltext` almost
 *  never appears verbatim in a single DOM text node. The injected script
 *  therefore builds ONE collapsed text layer over the page's visible text
 *  nodes (with a per-character mapping back to the nodes) and matches on that
 *  layer — whitespace-insensitively, with a whitespace-free fallback for
 *  segments crossing element boundaries and a 40-char prefix fallback. The
 *  matching core itself lives in `htmlHighlight.ts` (pure, unit-tested) and
 *  its source is embedded into the script verbatim, so the tests exercise
 *  exactly the code the iframe runs.
 *
 *  SECURITY: enabling `allow-scripts` would execute the page's own inline
 *  scripts too, so the srcDoc is sanitized first — all `<script>` blocks
 *  (including unterminated ones), inline `on*="…"` handlers and javascript:
 *  URLs are stripped from the snapshot, and only OUR highlight script runs
 *  (the offline snapshot file itself is never modified). `allow-same-origin`
 *  stays so relative images/css keep resolving.
 *
 *  The raw bytes come from the file-serving endpoint, which sends
 *  application/octet-stream without a charset (and res.text() would
 *  unconditionally decode UTF-8). Snapshot pages may declare a different
 *  charset, so the bytes are decoded honoring the BOM or the charset
 *  declared in the page head, falling back to UTF-8 with replacement.
 */
import {
  useCallback,
  useEffect,
  useMemo,
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
import {
  MAX_HIGHLIGHTS,
  injectHighlightScript,
  qcFindMatches,
  stripPageScripts,
  type QcCodingPayload,
} from "@/features/coding/htmlHighlight";
import { TextCoder } from "@/features/coding/TextCoder";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { Button, ErrorBanner, LoadingState, ViewHeader } from "@/components/ui/orchestrator";

/* --------------------------------------------------------- html decoding */

// Browsers sniff the first 1024 bytes for a charset declaration; do the same.
const HTML_CHARSET_SCAN_BYTES = 1024;

/** Charset declared by a snapshot: response header, <meta charset>, XML prolog. */
function detectHtmlCharset(headers: Headers, head: Uint8Array): string | null {
  const header = /charset\s*=\s*["']?([\w-]+)/i.exec(headers.get("content-type") ?? "");
  if (header?.[1]) return header[1];
  // Latin-1 view of the bytes keeps positions 1:1 so ASCII patterns
  // (charset="…") match regardless of the file's actual encoding.
  const headAscii = new TextDecoder("latin1").decode(head);
  const meta = /<meta[^>]+charset\s*=\s*["']?([\w-]+)/i.exec(headAscii);
  if (meta?.[1]) return meta[1];
  const xml = /<\?xml[^>]+encoding\s*=\s*["']([\w-]+)/i.exec(headAscii);
  if (xml?.[1]) return xml[1];
  return null;
}

/** Decode raw HTML bytes honoring BOM/declared charset; else UTF-8 with replacement. */
function decodeHtmlBytes(bytes: Uint8Array, declared: string | null): string {
  if (bytes.length >= 2) {
    if (bytes[0] === 0xff && bytes[1] === 0xfe) {
      // UTF-16LE BOM — strip the BOM and decode natively.
      return new TextDecoder("utf-16le", { fatal: false }).decode(bytes.subarray(2));
    }
    if (bytes[0] === 0xfe && bytes[1] === 0xff) {
      // UTF-16BE BOM — no browser-safe BE decoder, so byte-swap to LE.
      const src = bytes.subarray(2);
      const swapped = new Uint8Array(src.length);
      for (let i = 0; i + 1 < src.length; i += 2) {
        swapped[i] = src[i + 1];
        swapped[i + 1] = src[i];
      }
      return new TextDecoder("utf-16le", { fatal: false }).decode(swapped);
    }
  }
  const candidates = declared ? [declared, "utf-8"] : ["utf-8"];
  for (const charset of candidates) {
    try {
      return new TextDecoder(charset, { fatal: false }).decode(bytes);
    } catch {
      // Unknown/unsupported encoding label — try the next candidate.
    }
  }
  return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
}

/* -------------------------------------------------- highlight injection */
/* The iframe runs with `allow-scripts` (needed for our injected script), */
/* so the page's own code MUST NOT survive into the srcDoc. The snapshot   */
/* file stays untouched; only the in-memory copy is sanitized. Sanitizing, */
/* injection and the matching core live in htmlHighlight.ts (pure,         */
/* unit-tested); the matching core is embedded below verbatim.             */

/**
 * Our controlled highlight script, injected as the LAST element of the
 * iframe document (it runs after the DOM is parsed; the parent reposts the
 * current codings on the iframe `load` event, so nothing is missed).
 *
 * On every `qc:codings` message it removes the old marks and re-marks:
 *
 *  - a text model is built over the visible text nodes — one collapsed
 *    string (whitespace runs -> single space) with a per-character map back
 *    to (node, original offset), plus a whitespace-free variant;
 *  - `qcFindMatches` (the shared core from htmlHighlight.ts, spliced in
 *    verbatim) locates each segment in that model: exact collapsed
 *    substring, then a 40-char prefix fallback, then a whitespace-free
 *    fallback for segments the DOM splits across element boundaries;
 *  - matches are expanded to node ranges and applied right-to-left, so
 *    splitting one text node never shifts a later target; ranges are
 *    clamped per node so overlapping matches cannot corrupt the DOM;
 *  - content inside script/style/noscript/template/code/pre is skipped;
 *  - the total mark count is capped.
 *
 * The message listener verifies the sender (parent window / inherited
 * origin) — about:srcdoc with allow-same-origin inherits the parent origin.
 */
const QC_HIGHLIGHT_SCRIPT = `(function () {
  "use strict";

  var ACCENT_RGB = "217,119,6";
  var MAX_MARKS = ${MAX_HIGHLIGHTS};

  // Matching core — the SAME function the TS side unit-tests. Its source is
  // spliced in verbatim so the iframe and the tests can never drift.
  var CORE = ${qcFindMatches.toString()};

  function hexToRgb(color) {
    var m = /^#([0-9a-f]{6})$/i.exec(color || "");
    if (!m) return null;
    return [parseInt(m[1].substr(0, 2), 16), parseInt(m[1].substr(2, 2), 16), parseInt(m[1].substr(4, 2), 16)];
  }

  function styleFor(color) {
    var rgb = hexToRgb(color) || ACCENT_RGB.split(",");
    return "background:rgba(" + rgb.join(",") + ",.22);outline:1px solid rgba(" + rgb.join(",") + ",.6);border-radius:2px;color:inherit;padding:0";
  }

  function isExcluded(node) {
    for (var el = node.parentNode; el; el = el.parentNode) {
      if (el.nodeType !== 1) continue;
      var tag = el.nodeName;
      if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT" || tag === "TEMPLATE" || tag === "CODE" || tag === "PRE") return true;
      if (el === document.documentElement || el === document.body) break;
    }
    return false;
  }

  function removeMarks() {
    var marks = document.querySelectorAll("mark.qc-live-coding");
    for (var i = marks.length - 1; i >= 0; i--) {
      var m = marks[i];
      // replaceChild detaches m (parentNode becomes null), so grab the
      // parent first — normalize() must run on it, not on m.
      var parent = m.parentNode;
      if (parent) {
        parent.replaceChild(document.createTextNode(m.textContent), m);
        parent.normalize();
      }
    }
  }

  function isWsChar(c) {
    return c === " " || c === "\\t" || c === "\\n" || c === "\\r" || c === "\\f" || c === "\\v" || c === "\\u00A0" || c === "\\uFEFF";
  }

  // One collapsed text layer over the visible text nodes, with a per-char
  // (node, original offset) map, plus a whitespace-free variant for the
  // stripped matching fallback.
  function buildModel() {
    var nodes = [];
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
    while (walker.nextNode()) {
      var n = walker.currentNode;
      if (!n.nodeValue || !n.nodeValue.trim() || isExcluded(n)) continue;
      nodes.push(n);
    }
    if (!nodes.length) return null;

    var text = "";
    var chars = [];
    var firstOrig = [];
    var lastOrig = [];
    var lastSpace = false;
    for (var i = 0; i < nodes.length; i++) {
      var raw = nodes[i].nodeValue;
      firstOrig[i] = -1;
      lastOrig[i] = -1;
      for (var j = 0; j < raw.length; j++) {
        var c = raw.charAt(j);
        if (isWsChar(c)) {
          if (!lastSpace && text.length > 0) {
            text += " ";
            chars.push(i, j);
            if (firstOrig[i] < 0) firstOrig[i] = j;
            lastOrig[i] = j;
          }
          lastSpace = true;
        } else {
          text += c;
          chars.push(i, j);
          if (firstOrig[i] < 0) firstOrig[i] = j;
          lastOrig[i] = j;
          lastSpace = false;
        }
      }
    }

    var stripped = "";
    var strippedToText = [];
    for (var k = 0; k < text.length; k++) {
      if (text.charAt(k) !== " ") {
        strippedToText.push(k);
        stripped += text.charAt(k);
      }
    }

    return {
      nodes: nodes,
      text: text,
      chars: chars,
      firstOrig: firstOrig,
      lastOrig: lastOrig,
      stripped: stripped,
      strippedToText: strippedToText,
    };
  }

  function applyNodeRange(node, from, len, seg) {
    if (!node.parentNode) return;
    // splitText returns the new node holding [offset..end] (for offset 0 the
    // new node holds everything and is inserted before the original).
    var mid = node.splitText(from);
    mid.splitText(len);
    var mark = document.createElement("mark");
    mark.className = "qc-live-coding";
    if (seg.name) mark.setAttribute("title", seg.name);
    mark.setAttribute("style", styleFor(seg.color));
    node.parentNode.replaceChild(mark, mid);
    mark.appendChild(mid);
  }

  function markSegments(payload) {
    removeMarks();
    if (!payload || !payload.length) return;
    var model = buildModel();
    if (!model) return;

    var segTexts = [];
    for (var i = 0; i < payload.length; i++) segTexts.push(payload[i].seltext);
    var matches = CORE(model.text, segTexts, MAX_MARKS);
    if (!matches || !matches.length) return;

    // Expand each match into concrete node ranges (first/last covered char,
    // fully covered nodes in between).
    var ranges = [];
    for (var m = 0; m < matches.length; m++) {
      var hit = matches[m];
      var s = hit.start;
      var e = hit.start + hit.len;
      if (hit.mode === "stripped") {
        if (hit.start + hit.len - 1 >= model.strippedToText.length) continue;
        s = model.strippedToText[hit.start];
        e = model.strippedToText[hit.start + hit.len - 1] + 1;
      }
      if (s < 0 || e <= s || e > model.text.length) continue;
      var f = model.chars[s * 2];
      var fo = model.chars[s * 2 + 1];
      var l = model.chars[(e - 1) * 2];
      var lo = model.chars[(e - 1) * 2 + 1];
      var seg = payload[hit.seg];
      if (f === l) {
        ranges.push({ n: f, from: fo, to: lo, seg: seg });
      } else {
        if (model.lastOrig[f] >= 0) ranges.push({ n: f, from: fo, to: model.lastOrig[f], seg: seg });
        for (var x = f + 1; x < l; x++) {
          if (model.firstOrig[x] >= 0 && model.lastOrig[x] >= 0) {
            ranges.push({ n: x, from: model.firstOrig[x], to: model.lastOrig[x], seg: seg });
          }
        }
        if (model.firstOrig[l] >= 0) ranges.push({ n: l, from: model.firstOrig[l], to: lo, seg: seg });
      }
    }
    if (!ranges.length) return;

    // Apply right-to-left so earlier splits never shift later targets; clamp
    // each range against the next higher split in the same node so
    // overlapping matches cannot corrupt the DOM.
    ranges.sort(function (a, b) { return b.n - a.n || b.from - a.from; });
    var splitAt = {};
    for (var r = 0; r < ranges.length; r++) {
      var rg = ranges[r];
      var node = model.nodes[rg.n];
      if (!node || !node.parentNode) continue;
      var nodeLen = node.nodeValue ? node.nodeValue.length : 0;
      var to = rg.to;
      if (splitAt[rg.n] !== undefined) to = Math.min(to, splitAt[rg.n] - 1);
      if (rg.from < 0 || rg.from > to || to >= nodeLen) continue;
      applyNodeRange(node, rg.from, to - rg.from + 1, rg.seg);
      splitAt[rg.n] = rg.from;
    }
  }

  function isTrustedMessage(e) {
    if (!e || !e.source) return false;
    if (e.source === window.parent) return true;
    // about:srcdoc with allow-same-origin inherits the parent origin; a
    // frame without it reports the opaque "null" origin.
    return e.origin === window.origin || e.origin === "null";
  }

  window.addEventListener("message", function (e) {
    var d = e.data;
    if (!d || d.type !== "qc:codings" || !Array.isArray(d.codings)) return;
    if (!isTrustedMessage(e)) return;
    markSegments(d.codings);
  });
})();`;

/** Insert our controlled script into the sanitized snapshot srcDoc. */
function injectScript(html: string): string {
  return injectHighlightScript(html, `<script>${QC_HIGHLIGHT_SCRIPT}</script>`);
}

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
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  /* ------------------------------------------------------ live highlights */
  // cid -> { name, color } from the flat code tree, used to color the marks
  // with the code's own color and to set the hover tooltip.
  const codeInfo = useMemo(() => {
    const map = new Map<number, { name: string; color: string | null }>();
    for (const c of codes) {
      if (c.kind === "code") map.set(c.id, { name: c.name, color: c.color });
    }
    return map;
  }, [codes]);

  // Latest highlight payload, kept in a ref so the iframe `load` handler can
  // always post the current state (postMessage before load is dropped).
  const highlightPayloadRef = useRef<QcCodingPayload[]>([]);

  const postCodingsToFrame = useCallback(() => {
    const frame = iframeRef.current;
    if (!frame?.contentWindow) return;
    frame.contentWindow.postMessage({ type: "qc:codings", codings: highlightPayloadRef.current }, "*");
  }, []);

  // Rebuild the payload and push it into the iframe whenever codings (or the
  // code color/name lookup) change. The injected script removes the old
  // marks and re-marks in place, so the webpage keeps its scroll position.
  useEffect(() => {
    const payload: QcCodingPayload[] = [];
    for (const c of codings) {
      const info = codeInfo.get(c.cid);
      payload.push({ seltext: c.seltext, color: info?.color ?? null, name: info?.name ?? "" });
    }
    highlightPayloadRef.current = payload;
    postCodingsToFrame();
  }, [codings, codeInfo, postCodingsToFrame]);

  // Sanitized snapshot + our controlled highlight script. Rebuilt only when
  // the raw HTML changes; coding updates flow through postMessage instead.
  const srcDoc = useMemo(() => (html != null ? injectScript(stripPageScripts(html)) : null), [html]);

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
        const bytes = new Uint8Array(await res.arrayBuffer());
        if (cancelled) return;
        const scanLen = Math.min(bytes.length, HTML_CHARSET_SCAN_BYTES);
        const declared = detectHtmlCharset(res.headers, bytes.subarray(0, scanLen));
        setHtml(decodeHtmlBytes(bytes, declared));
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
                ref={iframeRef}
                title={t("htmlCoder.webpage")}
                srcDoc={srcDoc ?? undefined}
                // allow-scripts runs ONLY our injected highlight script — the
                // page's own scripts/handlers were stripped from the srcDoc
                // (see stripPageScripts); same-origin keeps relative
                // images/css resolving.
                sandbox="allow-same-origin allow-scripts"
                onLoad={postCodingsToFrame}
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
