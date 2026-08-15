/**
 * HtmlCoder — webpage snapshot coding workspace: a split view with the
 * extracted plain text (the coding surface) and the captured webpage
 * rendered from the saved raw .html file, mirroring the PdfCoder split
 * pattern (two independent always-visible toggle panes with a draggable
 * divider).
 *
 *  Coding works on BOTH sides. The PLAIN TEXT side codes the extracted text
 *  (html sources are media_type "text", so TextCoder codes them as text);
 *  the WEBPAGE side mirrors those codings LIVE (coded segments are
 *  highlighted in the rendered page) AND lets the user code by selecting
 *  text directly on the rendered page: the injected script reports
 *  selections and right-clicks (`qc:selection` / `qc:contextmenu`), the
 *  parent maps them through `buildViewModel` and `locateInFulltext` into
 *  fulltext offsets and shows a floating toolbar / the app's context menu —
 *  the browser's menu inside the frame never appears.
 *
 *  The highlights are BULLETPROOF: the parent PRE-COMPUTES the `<mark>`
 *  elements into the srcDoc HTML (buildHighlightedHtml — same matching the
 *  iframe script uses), so they render with zero script/postMessage
 *  dependency, and the injected script keeps only the live-update layer
 *  (re-marks on `qc:codings` postMessages, replacing the baked marks in
 *  place).
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
 *  exactly the code the iframe runs. `buildViewModel` in the same module
 *  rebuilds that collapsed layer over the SERIALIZED html — with per-char
 *  source spans — which is what lets the parent bake the marks before the
 *  iframe loads and map webpage selections back to the source.
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
import { CircleAlert, Code, FileText, Globe, LoaderCircle, Tag, Trash2 } from "lucide-react";
import {
  api,
  fetchSourceFile,
  type Annotation,
  type CodeTreeItem,
  type Coding,
  type Source,
} from "@/lib/api";
import {
  MAX_HIGHLIGHTS,
  buildHighlightedHtml,
  buildViewModel,
  codingsOverlappingRange,
  injectHighlightScript,
  locateInFulltext,
  mapViewRangeToSource,
  parseFrameMessage,
  qcFindMatches,
  stripPageScripts,
  type QcCodingPayload,
} from "@/features/coding/htmlHighlight";
import { CodePicker } from "@/features/coding/CodePicker";
import { TextCoder } from "@/features/coding/TextCoder";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";
import { cls } from "@/components/ui/tokens";
import { Menu, MenuItem } from "@/components/ui/orchestrator";
import { useProjectStore } from "@/stores/project";
import {
  Button,
  ErrorBanner,
  LoadingState,
  ViewHeader,
} from "@/components/ui/orchestrator";

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
 * The INITIAL highlights are not its job anymore: the parent pre-computes
 * them into the srcDoc HTML (`buildHighlightedHtml`), so the marks render
 * with zero script/postMessage dependency. The script only keeps the
 * LIVE-UPDATE layer:
 *
 *  - on startup it posts `qc:highlight-ready` to the parent — the signal
 *    that the live path is alive (until then the parent keeps rebaking the
 *    marks into the srcDoc);
 *  - on every `qc:codings` message it removes the old marks — including the
 *    pre-computed ones (same `qc-live-coding` class) — and re-marks:
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
 *  - a text node already inside a `mark.qc-live-coding` is never wrapped
 *    again (dedupe guard against double-wrapping the pre-computed marks);
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

  function hasMarkAncestor(node) {
    for (var el = node.parentNode; el; el = el.parentNode) {
      if (el.nodeType === 1 && el.tagName === "MARK" && el.className === "qc-live-coding") return true;
      if (el === document.body) break;
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
    // Never wrap text that is already inside a highlight mark — the parent
    // pre-computes marks into the srcDoc, so a stale live pass must not
    // double-wrap them (removeMarks normally clears them first).
    if (hasMarkAncestor(node)) return;
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

  /* ------ selection + right-click bridge: the page reports to the parent -- */
  /* The parent maps the collapsed-view indices onto its own ViewModel (the   */
  /* identical text layer built over the serialized html), so the user can    */
  /* code directly on the rendered page and right-click for the app's menu.   */

  var lastMouseX = 0;
  var lastMouseY = 0;
  var lastPostedKey = "";

  function postToParent(msg) {
    if (window.parent && window.parent !== window) {
      window.parent.postMessage(msg, "*");
    }
  }

  function textLength(node) {
    if (node.nodeType === Node.TEXT_NODE) return node.nodeValue.length;
    var kids = node.childNodes;
    var total = 0;
    for (var i = 0; i < kids.length; i++) total += textLength(kids[i]);
    return total;
  }

  function startPoint(node) {
    if (node.nodeType === Node.TEXT_NODE) return { node: node, offset: 0 };
    var kids = node.childNodes;
    if (!kids.length) return null;
    return startPoint(kids[0]);
  }

  function endPoint(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      return { node: node, offset: node.nodeValue.length };
    }
    var kids = node.childNodes;
    if (!kids.length) return null;
    return endPoint(kids[kids.length - 1]);
  }

  // A DOM selection boundary (container, offset) — element offsets are child
  // indexes — resolved to the (text node, raw offset) it actually falls in.
  function boundaryPoint(container, offset) {
    if (container.nodeType === Node.TEXT_NODE) return { node: container, offset: offset };
    var kids = container.childNodes;
    if (!kids.length) return null;
    if (offset >= kids.length) return endPoint(kids[kids.length - 1]);
    if (offset <= 0) return startPoint(kids[0]);
    return endPoint(kids[offset - 1]);
  }

  // The view-index interval [first, lastExclusive) contributed by one node.
  function nodeViewRange(model, ni) {
    var first = -1;
    var last = -1;
    for (var i = 0; i < model.chars.length; i += 2) {
      if (model.chars[i] === ni) {
        if (first < 0) first = i / 2;
        last = i / 2 + 1;
      }
    }
    return first < 0 ? null : [first, last];
  }

  // The view index of the first view char of node 'ni' at raw offset >=
  // 'offset' — one past the last view char strictly before the boundary,
  // which is the correct collapsed index for BOTH selection edges.
  function boundaryViewIndex(model, ni, offset) {
    var range = nodeViewRange(model, ni);
    if (!range) return null;
    var lo = range[0];
    var hi = range[1];
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (model.chars[mid * 2 + 1] >= offset) hi = mid;
      else lo = mid + 1;
    }
    return lo;
  }

  // The current DOM selection as a [startView, endView) range over the
  // collapsed view text, or null when collapsed/empty/outside the body or
  // anchored in excluded content (code/pre/…) that contributes no view text.
  function selectionViewRange(model) {
    var sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
    var range = sel.getRangeAt(0);
    if (!document.body ||
        !document.body.contains(range.startContainer) ||
        !document.body.contains(range.endContainer)) return null;
    var sp = boundaryPoint(range.startContainer, range.startOffset);
    var ep = boundaryPoint(range.endContainer, range.endOffset);
    if (!sp || !ep) return null;
    var si = model.nodes.indexOf(sp.node);
    var ei = model.nodes.indexOf(ep.node);
    if (si < 0 || ei < 0) return null;
    var s = boundaryViewIndex(model, si, sp.offset);
    var e = boundaryViewIndex(model, ei, ep.offset);
    if (s === null || e === null) return null;
    var a = Math.min(s, e);
    var b = Math.max(s, e);
    if (b <= a) return null;
    return { start: a, end: b };
  }

  // The collapsed-view index of the char under a document point — the
  // right-click target, so the parent can find the coding under the cursor.
  function viewIndexAtPoint(model, x, y) {
    var point = null;
    if (document.caretRangeFromPoint) {
      point = document.caretRangeFromPoint(x, y);
    } else if (document.caretPositionFromPoint) {
      var p = document.caretPositionFromPoint(x, y);
      if (p) point = { startContainer: p.offsetNode, startOffset: p.offset };
    }
    if (!point || !point.startContainer || !point.startContainer.parentNode) return null;
    var bp = boundaryPoint(point.startContainer, point.startOffset);
    if (!bp) return null;
    var ni = model.nodes.indexOf(bp.node);
    if (ni < 0) return null;
    return boundaryViewIndex(model, ni, bp.offset);
  }

  var reportScheduled = false;
  function reportSelection() {
    reportScheduled = false;
    var model = buildModel();
    var vr = model ? selectionViewRange(model) : null;
    if (vr) {
      var key = vr.start + ":" + vr.end;
      if (key === lastPostedKey) return;
      var text = model.text.slice(vr.start, vr.end);
      var rect = null;
      try {
        var rangeRect = window.getSelection().getRangeAt(0).getBoundingClientRect();
        if (rangeRect && (rangeRect.width > 0 || rangeRect.height > 0)) {
          rect = { left: rangeRect.left, top: rangeRect.top, bottom: rangeRect.bottom };
        }
      } catch (err) {
        /* collapsed/empty selection — no rect to anchor the toolbar */
      }
      lastPostedKey = key;
      postToParent({
        type: "qc:selection",
        startView: vr.start,
        endView: vr.end,
        text: text,
        rect: rect,
        mouseX: lastMouseX,
        mouseY: lastMouseY,
      });
      return;
    }
    if (lastPostedKey !== "") {
      lastPostedKey = "";
      postToParent({ type: "qc:selection-cleared" });
    }
  }

  function scheduleReport() {
    if (reportScheduled) return;
    reportScheduled = true;
    setTimeout(reportSelection, 30);
  }

  document.addEventListener("mousedown", function (e) {
    lastMouseX = e.clientX;
    lastMouseY = e.clientY;
    // Any click inside the frame dismisses the parent's menus; a new drag
    // re-shows the selection toolbar on the following mouseup.
    postToParent({ type: "qc:frame-mousedown" });
  }, true);

  document.addEventListener("mouseup", function (e) {
    lastMouseX = e.clientX;
    lastMouseY = e.clientY;
    scheduleReport();
  }, true);

  document.addEventListener("selectionchange", scheduleReport, true);

  document.addEventListener("contextmenu", function (e) {
    if (!document.body || !document.body.contains(e.target)) return;
    // The browser's menu must never show — the parent renders its own at the
    // same screen position.
    e.preventDefault();
    var model = buildModel();
    var msg = { type: "qc:contextmenu", x: e.clientX, y: e.clientY, viewIndex: null };
    if (model) msg.viewIndex = viewIndexAtPoint(model, e.clientX, e.clientY);
    postToParent(msg);
  }, true);

  window.addEventListener("message", function (e) {
    var d = e.data;
    if (!d || d.type !== "qc:codings" || !Array.isArray(d.codings)) return;
    if (!isTrustedMessage(e)) return;
    markSegments(d.codings);
  });

  // Report that the live layer is armed — the parent only stops rebaking
  // marks into the srcDoc once this arrives. Posted AFTER the listener is
  // registered, so any subsequent "qc:codings" message is guaranteed to be
  // handled.
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type: "qc:highlight-ready" }, "*");
  }
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
  const [htmlReloadTick, setHtmlReloadTick] = useState(0);

  const [codings, setCodings] = useState<Coding[]>([]);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [codes, setCodes] = useState<CodeTreeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  /** The backend's extracted plain text — the coding surface positions are
   *  anchored in it, so the iframe selections must be validated against it. */
  const [fulltext, setFulltext] = useState<string | null>(null);

  /* ------------------------------------------- frame selection + context ui */
  /** A pending coding selection made on the RENDERED webpage (source offsets
   *  + the view-text slice the highlight pipeline matches against). */
  const [frameSel, setFrameSel] = useState<{
    pos0: number;
    pos1: number;
    seltext: string;
  } | null>(null);
  /** Screen position of the floating coding toolbar (viewport coords). */
  const [frameSelPos, setFrameSelPos] = useState<{ left: number; top: number } | null>(null);
  /** Code-picker for selections made on the rendered webpage. */
  const [pickerOpen, setPickerOpen] = useState(false);
  /** The app's context menu for a right-click inside the webpage, with the
   *  codings the click landed on (empty = selection-only actions). */
  const [ctxMenu, setCtxMenu] = useState<{ left: number; top: number; codings: Coding[] } | null>(
    null,
  );

  const activeCodeId = useProjectStore((s) => s.activeCodeId);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const frameToolbarRef = useRef<HTMLDivElement | null>(null);
  const ctxMenuRef = useRef<HTMLDivElement | null>(null);

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

  // The iframe's text layer rebuilt over the serialized html — the bridge
  // that maps iframe selections (view indices) to source offsets. Script
  // stripping only removes content that is invisible to the view model, so
  // the UNSTRIPPED html yields the identical text.
  const viewModel = useMemo(() => (html != null ? buildViewModel(html) : null), [html]);

  // The backend's extraction rebuilt as a collapsed layer — the anchor that
  // locates webpage selections in the fulltext the plain-text pane codes
  // against (positions differ from source offsets: the extraction inserts
  // "\n" at block tags, so selections are LOCATED, not mapped 1:1).
  const fulltextModel = useMemo(
    () => (fulltext != null ? buildViewModel(fulltext) : null),
    [fulltext],
  );

  // cid -> { name, color } for the toolbar/menu labels.
  const codeById = useMemo(() => {
    const m = new Map<number, CodeTreeItem>();
    for (const c of codes) {
      if (c.kind === "code") m.set(c.id, c);
    }
    return m;
  }, [codes]);

  const postCodingsToFrame = useCallback(() => {
    const frame = iframeRef.current;
    if (!frame?.contentWindow) return;
    frame.contentWindow.postMessage({ type: "qc:codings", codings: highlightPayloadRef.current }, "*");
  }, []);

  // Rebuild the payload and push it into the iframe whenever codings (or the
  // code color/name lookup) change. The injected script removes the old
  // marks (including the pre-computed ones) and re-marks in place, so the
  // webpage keeps its scroll position.
  useEffect(() => {
    const payload: QcCodingPayload[] = [];
    for (const c of codings) {
      const info = codeInfo.get(c.cid);
      payload.push({ seltext: c.seltext, color: info?.color ?? null, name: info?.name ?? "" });
    }
    highlightPayloadRef.current = payload;
    postCodingsToFrame();
  }, [codings, codeInfo, postCodingsToFrame]);

  // The srcDoc carries PRE-COMPUTED highlight marks (baked by
  // buildHighlightedHtml) plus our live-update script. It is frozen per
  // document once the iframe's script reports itself alive
  // (`qc:highlight-ready`) — from then on coding changes flow through
  // postMessage and rebuilding the srcDoc (which would reload the frame and
  // lose the scroll position) is avoided. Until that signal arrives —
  // including packaged WebView2 runs where the script never fires — every
  // coding change RE-BAKES the marks into the srcDoc, so highlights render
  // with zero script/postMessage dependency.
  const frozenSrcDocRef = useRef<{ html: string; payload: QcCodingPayload[]; srcDoc: string } | null>(null);
  const liveReadyRef = useRef(false);
  const [srcDoc, setSrcDoc] = useState<string | null>(null);

  useEffect(() => {
    if (html == null) return;
    const frozen = frozenSrcDocRef.current;
    if (
      frozen?.html === html &&
      (liveReadyRef.current || frozen.payload === highlightPayloadRef.current)
    ) {
      return;
    }
    // New document: the previous frame (and its ready signal) is gone.
    if (frozen?.html !== html) liveReadyRef.current = false;
    const payload = highlightPayloadRef.current;
    const doc = injectScript(buildHighlightedHtml(stripPageScripts(html), payload));
    frozenSrcDocRef.current = { html, payload, srcDoc: doc };
    setSrcDoc(doc);
    // The old document (and its selection) is being replaced — drop any
    // pending iframe selection and menu, they belong to the dead frame.
    setFrameSel(null);
    setFrameSelPos(null);
    setCtxMenu(null);
  }, [html, codings, codeInfo]);

  // The iframe's script posts `qc:highlight-ready` right after registering
  // its message listener — the live layer is fully armed at that point.
  // Only messages from the current iframe count (a stale frame from a
  // previous document must not un-freeze the baking).
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.data?.type !== "qc:highlight-ready") return;
      if (e.source !== iframeRef.current?.contentWindow) return;
      liveReadyRef.current = true;
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  /* ------------------------------------------------- frame selection coding */

  const refreshCodings = useCallback(async () => {
    setCodings(await api.sourceCoding(source.id));
  }, [source.id]);

  const refreshAnnotations = useCallback(async () => {
    setAnnotations(await api.fileAnnotations(source.id));
  }, [source.id]);

  const refreshCodes = useCallback(async () => {
    setCodes(await api.codesFlat());
  }, []);

  const clearFrameSelection = useCallback(() => {
    setFrameSel(null);
    setFrameSelPos(null);
  }, []);

  /** Code the pending webpage selection with the given code id. */
  const codeFrameSelection = useCallback(
    async (cid: number) => {
      const sel = frameSel;
      if (!sel) return;
      try {
        await api.createTextCoding({
          cid,
          fid: source.id,
          seltext: sel.seltext,
          pos0: sel.pos0,
          pos1: sel.pos1,
        });
        await refreshCodings();
      } catch (e) {
        setErrMsg(e instanceof Error ? e.message : t("coder.createError"));
      } finally {
        clearFrameSelection();
      }
      void refreshCodes().catch(() => undefined);
    },
    [frameSel, source.id, refreshCodings, refreshCodes, clearFrameSelection, t],
  );

  /** Delete a coding from the webpage's context menu. */
  const deleteFrameCoding = useCallback(
    async (row: Coding) => {
      try {
        await api.deleteTextCoding(row.ctid);
        await refreshCodings();
      } catch (e) {
        setErrMsg(e instanceof Error ? e.message : t("coder.removeError"));
      } finally {
        setCtxMenu(null);
      }
    },
    [refreshCodings, t],
  );

  // The frame → parent message router: selection reports, right-click
  // forwarding and click-away signals. Everything is validated by
  // parseFrameMessage (unknown types — incl. the parent→frame `qc:codings` —
  // are ignored), and only messages from the CURRENT iframe count.
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.source !== iframeRef.current?.contentWindow) return;
      const msg = parseFrameMessage(e.data);
      if (!msg) return;

      if (msg.type === "qc:selection") {
        if (!viewModel) {
          clearFrameSelection();
          return;
        }
        const mapped = mapViewRangeToSource(viewModel, msg.startView, msg.endView);
        if (!mapped) {
          clearFrameSelection();
          return;
        }
        // The frame's own text layer must agree with the parent's model —
        // view indices only line up when both sides built the same layer.
        if (
          msg.text &&
          msg.text.replace(/[\s\u00A0\uFEFF]+/g, "") !== mapped.seltext.replace(/[\s\u00A0\uFEFF]+/g, "")
        ) {
          clearFrameSelection();
          return;
        }
        // Locate the selected text in the extracted fulltext (the plain-text
        // coding surface). The extraction inserts "\n" at block tags, so
        // source offsets and fulltext offsets differ — the exact source
        // range is used as the hint that picks the right occurrence.
        const ftModel = fulltextModel;
        if (!ftModel) {
          clearFrameSelection();
          return;
        }
        const located = locateInFulltext(fulltext ?? "", ftModel, mapped.seltext, mapped.pos0);
        if (!located || located.pos1 <= located.pos0) {
          clearFrameSelection();
          return;
        }
        const frame = iframeRef.current;
        const iframeRect = frame?.getBoundingClientRect();
        if (!iframeRect) {
          clearFrameSelection();
          return;
        }
        let left: number | null = null;
        let top: number | null = null;
        if (msg.rect) {
          left = iframeRect.left + msg.rect.left;
          top = iframeRect.top + msg.rect.bottom + 6;
        } else if (msg.mouseX > 0 || msg.mouseY > 0) {
          left = iframeRect.left + msg.mouseX;
          top = iframeRect.top + msg.mouseY + 12;
        }
        if (left == null || top == null) {
          clearFrameSelection();
          return;
        }
        setCtxMenu(null);
        setFrameSel({
          pos0: located.pos0,
          pos1: located.pos1,
          seltext: located.seltext,
        });
        setFrameSelPos({
          left: Math.max(8, Math.min(left, window.innerWidth - 320)),
          top: Math.max(8, Math.min(top, window.innerHeight - 64)),
        });
        return;
      }

      if (msg.type === "qc:selection-cleared") {
        clearFrameSelection();
        return;
      }

      if (msg.type === "qc:frame-mousedown") {
        // Any click inside the webpage dismisses the context menu. The
        // selection toolbar survives a right-click (right-click preserves
        // the selection) and is re-anchored by the next qc:selection.
        setCtxMenu(null);
        return;
      }

      if (msg.type === "qc:contextmenu") {
        const frame = iframeRef.current;
        const iframeRect = frame?.getBoundingClientRect();
        if (!iframeRect) {
          setCtxMenu(null);
          return;
        }
        // Codings under the cursor: map the view index to its source span,
        // locate it in the fulltext (fulltext positions are what codings
        // carry) and find the codings overlapping it.
        let covering: Coding[] = [];
        if (msg.viewIndex != null && viewModel && fulltextModel) {
          const mapped = mapViewRangeToSource(viewModel, msg.viewIndex, msg.viewIndex + 1);
          if (mapped && mapped.pos1 > mapped.pos0) {
            const located = locateInFulltext(
              fulltext ?? "",
              fulltextModel,
              mapped.seltext,
              mapped.pos0,
            );
            if (located && located.pos1 > located.pos0) {
              covering = codingsOverlappingRange(codings, located.pos0, located.pos1);
            }
          }
        }
        if (covering.length === 0 && frameSel == null) {
          setCtxMenu(null);
          return;
        }
        setCtxMenu({
          left: Math.max(4, Math.min(iframeRect.left + msg.x, window.innerWidth - 260)),
          top: Math.max(4, Math.min(iframeRect.top + msg.y, window.innerHeight - 220)),
          codings: covering,
        });
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [viewModel, fulltextModel, codings, fulltext, frameSel, clearFrameSelection]);

  // Escape closes the picker, then the context menu and the frame toolbar.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (pickerOpen) {
        setPickerOpen(false);
        return;
      }
      setCtxMenu(null);
      clearFrameSelection();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Clicks outside the context menu (in the parent document) close it.
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (target && ctxMenuRef.current && !ctxMenuRef.current.contains(target)) setCtxMenu(null);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  // Scrolling the webpage pane detaches the fixed overlays — drop them.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onScroll = () => {
      setFrameSelPos(null);
      setCtxMenu(null);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // A code clicked in the left sidebar codes the pending webpage selection.
  useEffect(() => {
    const onAssign = (e: Event) => {
      const cid = (e as CustomEvent<{ cid: number }>).detail?.cid;
      if (typeof cid !== "number") return;
      setPickerOpen(false);
      setCtxMenu(null);
      void codeFrameSelection(cid);
    };
    window.addEventListener("qc:assign-code", onAssign);
    return () => window.removeEventListener("qc:assign-code", onAssign);
  }, [codeFrameSelection]);

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
    setFulltext(null);
    clearFrameSelection();
    setCtxMenu(null);
    void (async () => {
      try {
        const [cod, anns, flat, src] = await Promise.all([
          api.sourceCoding(source.id),
          api.fileAnnotations(source.id),
          api.codesFlat(),
          api.getSource(source.id),
        ]);
        if (cancelled) return;
        setCodings(cod);
        setAnnotations(anns);
        setCodes(flat);
        // The extraction the plain-text pane codes against — the anchor for
        // validating webpage selections (the prop may already carry it).
        setFulltext(src.fulltext ?? source.fulltext ?? null);
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : t("htmlCoder.loadCodingsError"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source.id, source.fulltext, reloadTick, t, clearFrameSelection]);

  // Fetch the raw .html file through the file-serving endpoint. When it is
  // unavailable (article-only import or a broken link) the webpage pane
  // shows a hint and the plain-text pane remains fully usable.
  // fetchSourceFile builds the URL from the resolved base (the App boot
  // gate holds the UI until initApiBase() settles) and re-resolves +
  // retries a transport failure once, so an ephemeral-port backend cannot
  // surface as a spurious "Failed to fetch".
  useEffect(() => {
    let cancelled = false;
    setHtmlLoading(true);
    void (async () => {
      try {
        const res = await fetchSourceFile(source.id);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const bytes = new Uint8Array(await res.arrayBuffer());
        if (cancelled) return;
        const scanLen = Math.min(bytes.length, HTML_CHARSET_SCAN_BYTES);
        const declared = detectHtmlCharset(res.headers, bytes.subarray(0, scanLen));
        setHtml(decodeHtmlBytes(bytes, declared));
      } catch (e) {
        if (!cancelled) {
          setHtml(null);
          console.warn("[html coder] snapshot load failed:", e);
        }
      } finally {
        if (!cancelled) setHtmlLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source.id, htmlReloadTick, t]);

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

      {/* Floating coding toolbar for selections made on the RENDERED webpage.
          Mirrors the plain-text pane's selection toolbar; the primary button
          codes with the active code (or opens the picker when none). */}
      {frameSelPos && frameSel && (
        <div
          ref={frameToolbarRef}
          className="fixed z-40"
          style={{ left: frameSelPos.left, top: frameSelPos.top }}
        >
          <div
            className={`flex items-center gap-1 p-1 ${cls.popup}`}
            role="toolbar"
            aria-label={t("htmlCoder.selectionActions")}
          >
            <Button
              variant="primary"
              icon={<Code size={12} aria-hidden />}
              className="max-w-56"
              onClick={() => {
                if (activeCodeId != null) void codeFrameSelection(activeCodeId);
                else setPickerOpen(true);
              }}
              title={
                activeCodeId != null
                  ? t("coder.codeWithActive", { name: codeById.get(activeCodeId)?.name ?? "" })
                  : t("coder.codeAction")
              }
            >
              <span className="truncate">
                {activeCodeId != null
                  ? codeById.get(activeCodeId)?.name ?? t("coder.codeAction")
                  : t("coder.codeAction")}
              </span>
            </Button>
            <Button
              variant="secondary"
              icon={<Tag size={12} aria-hidden />}
              onClick={() => setPickerOpen(true)}
              title={t("coder.pickCode")}
            >
              {t("coder.pickCode")}
            </Button>
          </div>
        </div>
      )}

      {/* The app's context menu for right-clicks inside the webpage (the
          frame's script forwards the event; the browser menu never shows). */}
      {ctxMenu && (
        <div
          ref={ctxMenuRef}
          className="fixed z-40"
          style={{ left: ctxMenu.left, top: ctxMenu.top }}
        >
          <Menu role="menu" className="min-w-44" aria-label={t("htmlCoder.contextMenu")}>
            {ctxMenu.codings.map((row) => {
              const code = codeById.get(row.cid);
              return (
                <MenuItem
                  key={row.ctid}
                  role="menuitem"
                  onClick={() => void deleteFrameCoding(row)}
                  className="hover:text-danger"
                >
                  <Trash2 size={12} aria-hidden />
                  <span className="min-w-0 flex-1 truncate">
                    {t("coder.removeFor", {
                      name: code?.name ?? t("coder.fallbackCode", { id: row.cid }),
                    })}
                  </span>
                </MenuItem>
              );
            })}
            {frameSel && (
              <>
                <MenuItem
                  role="menuitem"
                  onClick={() => {
                    const cid = activeCodeId;
                    setCtxMenu(null);
                    if (cid != null) void codeFrameSelection(cid);
                    else setPickerOpen(true);
                  }}
                >
                  <Code size={12} aria-hidden />
                  <span className="min-w-0 flex-1 truncate">
                    {activeCodeId != null
                      ? t("coder.codeWithActive", { name: codeById.get(activeCodeId)?.name ?? "" })
                      : t("coder.codeAction")}
                  </span>
                </MenuItem>
                <MenuItem
                  role="menuitem"
                  onClick={() => {
                    setCtxMenu(null);
                    setPickerOpen(true);
                  }}
                >
                  <Tag size={12} aria-hidden />
                  <span className="min-w-0 flex-1 truncate">{t("coder.pickCode")}</span>
                </MenuItem>
              </>
            )}
          </Menu>
        </div>
      )}

      <CodePicker
        open={pickerOpen}
        codes={codes}
        onClose={() => setPickerOpen(false)}
        onPick={(picked) => {
          setPickerOpen(false);
          void codeFrameSelection(picked.cid);
        }}
      />
    </div>
  );
}
