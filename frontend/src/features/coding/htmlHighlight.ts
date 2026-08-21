/**
 * Pure helpers behind the HtmlCoder highlights — all side-effect free, so the
 * matching logic can be unit-tested without a DOM:
 *
 *  - `stripPageScripts` / `injectHighlightScript` build the sanitized srcDoc
 *    (the snapshot file itself is never touched).
 *  - `htmlToViewText` extracts the page's visible text the way the iframe's
 *    DOM walk does (entities decoded, whitespace collapsed, script/style/
 *    head/code/pre content dropped) — the test oracle for the matching.
 *  - `qcFindMatches` is the shared matching core. The injected iframe script
 *    embeds its source verbatim (`.toString()`), so the runtime and the tests
 *    can never drift. It matches each segment's `seltext` by exact substring
 *    on the collapsed text, with a 40-char prefix fallback and a
 *    whitespace-free fallback for segments that cross element boundaries in
 *    the rendered DOM (the backend's fulltext inserts "\n" at block tags,
 *    while the DOM joins the same words with no whitespace at all).
 *  - `buildViewModel` builds the SAME collapsed text layer the iframe's DOM
 *    walk produces, while mapping every view-text char back to the source
 *    ranges that produced it — the bridge that lets the parent bake marks
 *    into the serialized HTML.
 *  - `buildHighlightedHtml` pre-computes the highlights: it matches the
 *    codings against the view text and embeds the resulting `<mark>` elements
 *    directly into the snapshot HTML, so the marks render with zero
 *    script/postMessage dependency. The injected script is then only a
 *    live-update layer (re-marks on postMessage, replacing the baked marks).
 */

/** Cap on marked segments per highlight pass. */
export const MAX_HIGHLIGHTS = 500;

/** Payload pushed into the iframe for one coded segment. */
export interface QcCodingPayload {
  seltext: string;
  color: string | null;
  name: string;
  /** Optional segment identity; when present it is baked into the mark so
   *  the memo gutter can anchor to the rendered highlight. */
  ctid?: number;
  /** The code is hidden in the coder — the mark renders dimmed (matches the
   *  `.qc-seg-hidden` treatment of the native coder surfaces). */
  hidden?: boolean;
}

/** One matched segment, positioned in the text coordinate space of `mode`. */
export interface QcFindMatch {
  /** Index into the segments array passed to qcFindMatches. */
  seg: number;
  /** Start offset in the (collapsed or whitespace-free) text. */
  start: number;
  /** Matched length in the same coordinate space as `start`. */
  len: number;
  /** Coordinate space of `start`/`len`. */
  mode: "collapsed" | "stripped";
}

/* ------------------------------------------------------------ html scanning */

const RAW_TEXT_TAGS = ["script", "style", "noscript", "template"];

function isWsCharCode(code: number): boolean {
  return code === 32 || code === 9 || code === 10 || code === 12 || code === 13;
}

/** Read the (lowercased) tag name right after `<`, or null if none. */
function readTagName(html: string, lt: number, n: number): string | null {
  let i = lt + 1;
  if (html.charAt(i) === "/") i++;
  if (i >= n) return null;
  const c = html.charCodeAt(i);
  if (!(c >= 65 && c <= 90) && !(c >= 97 && c <= 122)) return null;
  let j = i + 1;
  while (j < n && /[a-zA-Z0-9-]/.test(html.charAt(j))) j++;
  return html.slice(i, j).toLowerCase();
}

/**
 * Scan a tag from its `<` to the matching `>`, honoring quoted attribute
 * values (quotes only open after an `=`, so apostrophes inside unquoted
 * values are left alone, like browsers do).
 */
function skipTag(html: string, lt: number, n: number): number {
  let i = lt + 1;
  let quote: string | null = null;
  let afterEq = false;
  while (i < n) {
    const c = html.charAt(i);
    if (quote !== null) {
      if (c === quote) quote = null;
    } else if (c === '"' || c === "'") {
      if (afterEq) quote = c;
    } else if (c === "=") {
      afterEq = true;
    } else if (c === ">") {
      return i + 1;
    } else if (!isWsCharCode(c.charCodeAt(0)) && c !== "/") {
      afterEq = false;
    }
    i++;
  }
  return n;
}

/** Scan to the matching `-->` (or the end of the string). */
function skipComment(html: string, lt: number, n: number): number {
  const end = html.indexOf("-->", lt + 4);
  return end < 0 ? n : end + 3;
}

/**
 * Find the end of a `<script>`/`<style>`/... raw-text element: the opening
 * tag plus everything up to its closing tag. `<\/script>` inside a JS string
 * does NOT close the block (it only terminates the string escape, and
 * browsers agree); an unterminated block runs to the end of the input — it
 * must be dropped, never kept (a truncated snapshot must not keep a live
 * script).
 */
function rawElementEnd(html: string, start: number, name: string, n: number): number {
  const closeName = `</${name}`;
  let i = start;
  while (i < n) {
    const idx = html.toLowerCase().indexOf(closeName, i);
    if (idx < 0) return n;
    if (idx > 0 && html.charAt(idx - 1) === "\\") {
      i = idx + closeName.length;
      continue;
    }
    const after = html.charAt(idx + closeName.length);
    if (after === "" || after === ">" || after === "/" || isWsCharCode(after.charCodeAt(0))) {
      let j = idx + closeName.length;
      while (j < n && html.charAt(j) !== ">") j++;
      return Math.min(n, j + 1);
    }
    i = idx + closeName.length;
  }
  return n;
}

/** End of a raw-text element starting at its `<` (opening tag + content + closing tag). */
function skipRawElement(html: string, lt: number, name: string, n: number): number {
  return rawElementEnd(html, skipTag(html, lt, n), name, n);
}

/* ----------------------------------------------------------- srcDoc builder */

/** Attribute names that can navigate the frame and must not carry javascript: URLs. */
const NAVIGABLE_ATTRS = new Set(["href", "src", "action", "formaction", "background"]);

/** Attribute value part of a raw "=value" slice, or null when there is none. */
function attrValue(rest: string): string | null {
  if (!rest) return null;
  let v = rest.slice(1).trim();
  const q = v.charAt(0);
  if (q === '"' || q === "'") v = v.slice(1, -1).trim();
  return v;
}

/**
 * Rebuild one raw tag (the "<...>" slice) without executable attributes:
 * on* event handlers (any case, quoted or unquoted) and javascript: URLs on
 * navigable attributes. Everything else is preserved byte-for-byte, including
 * values that merely LOOK like handlers ("title="onclick=foo"" stays intact —
 * a regex strip would corrupt it).
 */
function stripHandlersFromTag(tag: string): string {
  const isClosing = tag.charAt(1) === "/";
  const bodyStart = isClosing ? 2 : 1;
  const bodyEnd = tag.length - 1;
  if (bodyStart >= bodyEnd) return tag;
  const body = tag.slice(bodyStart, bodyEnd);
  const n = body.length;
  const kept: Array<{ name: string; rest: string }> = [];
  let i = 0;
  while (i < n) {
    while (i < n && isWsCharCode(body.charCodeAt(i))) i++;
    if (i >= n) break;
    const nameStart = i;
    while (i < n && !isWsCharCode(body.charCodeAt(i)) && body.charAt(i) !== "=" && body.charAt(i) !== ">" && body.charAt(i) !== "/") i++;
    if (nameStart === i) {
      i++;
      continue;
    }
    const name = body.slice(nameStart, i);
    let j = i;
    while (j < n && isWsCharCode(body.charCodeAt(j))) j++;
    let rest = "";
    if (body.charAt(j) === "=") {
      const valStart = j;
      j++;
      while (j < n && isWsCharCode(body.charCodeAt(j))) j++;
      const q = body.charAt(j);
      if (q === '"' || q === "'") {
        const close = body.indexOf(q, j + 1);
        const valEnd = close < 0 ? n : close + 1;
        rest = body.slice(valStart, valEnd);
        i = valEnd;
      } else {
        while (j < n && !isWsCharCode(body.charCodeAt(j)) && body.charAt(j) !== ">") j++;
        rest = body.slice(valStart, j);
        i = j;
      }
    } else {
      rest = "";
      i = j;
    }
    const lowerName = name.toLowerCase();
    const value = attrValue(rest);
    const isHandler = /^on[a-z][a-z0-9]*$/i.test(name);
    const isJsUrl = NAVIGABLE_ATTRS.has(lowerName) && value !== null && /^\s*javascript:/i.test(value);
    // The first token is the tag name, never a handler — always keep it.
    if (kept.length === 0 || (!isHandler && !isJsUrl)) {
      kept.push({ name, rest });
    }
  }
  let out = tag.charAt(0) + (isClosing ? "/" : "");
  for (let k = 0; k < kept.length; k++) {
    out += (k === 0 ? "" : " ") + kept[k].name + kept[k].rest;
  }
  out += ">";
  return out;
}

/**
 * Remove the page's own executable code from a snapshot copy (the offline
 * file is never modified):
 *  - `<script>…</script>` blocks are dropped entirely (closed or not — an
 *    unterminated block must not survive into a frame where scripts run);
 *  - inline `on*="…"` event handlers are dropped from their tags;
 *  - javascript: URLs on navigable attributes are dropped;
 *  - `<style>`/`<noscript>`/`<template>` content is preserved (inert) but is
 *    skipped during scanning so it cannot fake a tag open.
 * A small scanner rather than a regex: regexes cannot handle unterminated
 * blocks, `<\/script>` inside JS strings, or `<script>` inside attribute
 * values, and a regex would corrupt on* lookalikes inside page text.
 */
export function stripPageScripts(html: string): string {
  const n = html.length;
  let out = "";
  let i = 0;
  while (i < n) {
    const lt = html.indexOf("<", i);
    if (lt < 0) {
      out += html.slice(i);
      break;
    }
    out += html.slice(i, lt);
    if (html.startsWith("<!--", lt)) {
      out += html.slice(lt, skipComment(html, lt, n));
      i = skipComment(html, lt, n);
      continue;
    }
    const after = html.charAt(lt + 1);
    if (after === "!" || after === "?") {
      out += html.slice(lt, skipTag(html, lt, n));
      i = skipTag(html, lt, n);
      continue;
    }
    const name = readTagName(html, lt, n);
    if (name === null) {
      out += "<";
      i = lt + 1;
      continue;
    }
    if (name === "script") {
      i = skipRawElement(html, lt, name, n);
      continue;
    }
    if (name === "style" || name === "noscript" || name === "template") {
      out += html.slice(lt, skipRawElement(html, lt, name, n));
      i = skipRawElement(html, lt, name, n);
      continue;
    }
    const tagEnd = skipTag(html, lt, n);
    out += stripHandlersFromTag(html.slice(lt, tagEnd));
    i = tagEnd;
  }
  return out;
}

/**
 * Index of the last `</body>` outside comments/raw-text blocks (a `</body>`
 * inside a comment must not become the injection point — the script would be
 * swallowed by the comment), or -1 when there is none.
 */
function bodyCloseIndex(html: string): number {
  const n = html.length;
  let i = 0;
  let last = -1;
  while (i < n) {
    const lt = html.indexOf("<", i);
    if (lt < 0) break;
    if (html.startsWith("<!--", lt)) {
      i = skipComment(html, lt, n);
      continue;
    }
    const after = html.charAt(lt + 1);
    if (after === "!" || after === "?") {
      i = skipTag(html, lt, n);
      continue;
    }
    const name = readTagName(html, lt, n);
    if (name === null) {
      i = lt + 1;
      continue;
    }
    if (RAW_TEXT_TAGS.includes(name)) {
      i = skipRawElement(html, lt, name, n);
      continue;
    }
    if (name === "body" && html.charAt(lt + 1) === "/") {
      const afterName = html.charAt(lt + name.length + 2);
      if (afterName === "" || afterName === ">" || afterName === "/" || isWsCharCode(afterName.charCodeAt(0))) {
        last = lt;
      }
    }
    i = skipTag(html, lt, n);
  }
  return last;
}

/**
 * Insert our controlled script into the sanitized snapshot, right before the
 * last REAL `</body>` (never inside a comment or a raw-text block); when the
 * document has none, append at the very end (the parser places trailing
 * content in the body, so the script still runs last).
 */
export function injectHighlightScript(html: string, scriptTag: string): string {
  const close = bodyCloseIndex(html);
  if (close < 0) return `${html}${scriptTag}`;
  return `${html.slice(0, close)}${scriptTag}${html.slice(close)}`;
}

/* ----------------------------------------------------- text model / matching */

const NAMED_ENTITIES: Record<string, string> = {
  amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: "\u00A0",
  copy: "©", reg: "®", trade: "™", hellip: "…", mdash: "—", ndash: "–",
  lsquo: "‘", rsquo: "’", ldquo: "“", rdquo: "”", laquo: "«", raquo: "»",
  deg: "°", plusmn: "±", times: "×", divide: "÷", middot: "·", bull: "•",
  sect: "§", para: "¶", micro: "µ", dagger: "†", permil: "‰", euro: "€",
  pound: "£", yen: "¥", cent: "¢", szlig: "ß", auml: "ä", ouml: "ö", uuml: "ü",
  Auml: "Ä", Ouml: "Ö", Uuml: "Ü", agrave: "à", eacute: "é", oacute: "ó",
  uacute: "ú", ntilde: "ñ", Ntilde: "Ñ", ccedil: "ç", Ccedil: "Ç",
};

/** Decode HTML entities (named + decimal + hex) the way a DOM would. */
export function decodeHtmlEntities(text: string): string {
  if (text.indexOf("&") < 0) return text;
  return text.replace(/&(#[0-9]+|#x[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);/g, (m, body: string) => {
    if (body.charAt(0) === "#") {
      const hex = body.charAt(1) === "x" || body.charAt(1) === "X";
      const num = parseInt(hex ? body.slice(2) : body.slice(1), hex ? 16 : 10);
      if (!Number.isNaN(num) && num >= 0 && num <= 0x10ffff) return String.fromCodePoint(num);
      return m;
    }
    return NAMED_ENTITIES[body] ?? m;
  });
}

/** Collapse runs of whitespace (incl. NBSP/BOM) to a single space, trimmed. */
export function collapseWhitespace(text: string): string {
  return text.replace(/[\s\u00A0\uFEFF]+/g, " ").trim();
}

/** Elements whose content is not a text node in the DOM — the iframe's DOM
 * walk never sees their text, so they must not be matchable or markable:
 * script/style/noscript/template (raw text), code/pre (excluded by the
 * injected script), and the RCDATA/fallback elements the parser renders
 * without text children (textarea, title, xmp, noembed, plaintext, iframe,
 * noframes). */
function hasInertTextContent(name: string): boolean {
  return (
    name === "script" ||
    name === "style" ||
    name === "noscript" ||
    name === "template" ||
    name === "code" ||
    name === "pre" ||
    name === "textarea" ||
    name === "title" ||
    name === "xmp" ||
    name === "noembed" ||
    name === "plaintext" ||
    name === "iframe" ||
    name === "noframes"
  );
}

/**
 * The page's visible text the way the iframe's DOM walk produces it:
 * entities decoded, tags removed, whitespace collapsed, and script/style/
 * noscript/template/head/code/pre content dropped (those produce no visible
 * text nodes). Inter-tag whitespace is kept — it IS a text node in the DOM.
 */
export function htmlToViewText(html: string): string {
  const n = html.length;
  let out = "";
  let i = 0;
  while (i < n) {
    const lt = html.indexOf("<", i);
    if (lt < 0) {
      out += decodeHtmlEntities(html.slice(i));
      break;
    }
    out += decodeHtmlEntities(html.slice(i, lt));
    if (html.startsWith("<!--", lt)) {
      i = skipComment(html, lt, n);
      continue;
    }
    const after = html.charAt(lt + 1);
    if (after === "!" || after === "?") {
      i = skipTag(html, lt, n);
      continue;
    }
    const name = readTagName(html, lt, n);
    if (name === null) {
      out += "<";
      i = lt + 1;
      continue;
    }
    if (hasInertTextContent(name)) {
      i = skipRawElement(html, lt, name, n);
      continue;
    }
    if (name === "head") {
      i = skipHead(html, lt, n);
      continue;
    }
    i = skipTag(html, lt, n);
  }
  return collapseWhitespace(out);
}

/** Elements that are allowed in <head> (anything else ends it implicitly). */
const HEAD_ONLY_TAGS = [
  "title", "base", "link", "meta", "style", "script", "noscript", "template",
];

/**
 * Skip a `<head>` element — its text is not part of document.body, so it
 * must not be matchable. Stops early at `<body` OR at the first element that
 * is not head-only (the parser implicitly closes the head there, so malformed
 * documents without `</head>` still map back to the real body text).
 */
function skipHead(html: string, lt: number, n: number): number {
  let i = skipTag(html, lt, n);
  while (i < n) {
    const nlt = html.indexOf("<", i);
    if (nlt < 0) return n;
    if (html.startsWith("<!--", nlt)) {
      i = skipComment(html, nlt, n);
      continue;
    }
    const name = readTagName(html, nlt, n);
    if (name === "body" || (name !== null && !HEAD_ONLY_TAGS.includes(name))) return nlt;
    if (name === null) {
      i = nlt + 1;
      continue;
    }
    if (name === "head") {
      i = skipTag(html, nlt, n);
      if (html.charAt(nlt + 1) === "/") return i; // </head> — head is done
      continue;
    }
    if (name === "script" || name === "style" || name === "title") {
      i = skipRawElement(html, nlt, name, n);
      continue;
    }
    i = skipTag(html, nlt, n);
  }
  return n;
}

/**
 * The shared matching core, embedded in the injected iframe script verbatim
 * via toString(). Kept deliberately self-contained: no imports, no closures,
 * ES2020-only syntax. `text` must already be whitespace-collapsed (single
 * spaces); each segment is collapsed the same way, then located by exact
 * substring — with a 40-char prefix fallback and a whitespace-free fallback
 * (useful when the segment crosses element boundaries the DOM joins without
 * whitespace, e.g. a "\n" the backend's text extraction inserted at a block
 * tag). First occurrence per segment, deduped by position, capped.
 */
export function qcFindMatches(text: string, segments: string[], maxMarks: number): QcFindMatch[] {
  const PREFIX_LEN = 40;
  const collapsed: string[] = new Array(segments.length);
  for (let s = 0; s < segments.length; s++) {
    const raw = segments[s];
    collapsed[s] = raw ? raw.replace(/[\s\u00A0\uFEFF]+/g, " ").trim() : "";
  }
  let stripped: string | null = null;
  const strippedToText: number[] = [];
  const out: QcFindMatch[] = [];
  const seen: Record<string, boolean> = {};
  let marked = 0;
  for (let s = 0; s < segments.length && marked < maxMarks; s++) {
    const norm = collapsed[s];
    if (!norm) continue;
    let mode: QcFindMatch["mode"] = "collapsed";
    let start = text.indexOf(norm);
    let len = norm.length;
    if (start < 0 && norm.length > PREFIX_LEN) {
      start = text.indexOf(norm.slice(0, PREFIX_LEN));
      len = PREFIX_LEN;
    }
    if (start < 0) {
      if (stripped === null) {
        stripped = "";
        for (let k = 0; k < text.length; k++) {
          if (text.charAt(k) !== " ") {
            strippedToText.push(k);
            stripped += text.charAt(k);
          }
        }
      }
      const normStrip = norm.replace(/ /g, "");
      if (normStrip) {
        let si = stripped.indexOf(normStrip);
        let sl = normStrip.length;
        if (si < 0 && normStrip.length > PREFIX_LEN) {
          si = stripped.indexOf(normStrip.slice(0, PREFIX_LEN));
          sl = PREFIX_LEN;
        }
        if (si >= 0) {
          start = si;
          len = sl;
          mode = "stripped";
        }
      }
    }
    if (start < 0) continue;
    const key = mode + ":" + start;
    if (seen[key]) continue;
    seen[key] = true;
    out.push({ seg: s, start, len, mode });
    marked++;
  }
  return out;
}

/**
 * Match coded segments against a snapshot's raw HTML: the visible text is
 * extracted with `htmlToViewText` (entities decoded, whitespace collapsed,
 * script/code/pre content skipped), then `qcFindMatches` locates each
 * segment. Returned positions are in view-text coordinates.
 */
export function buildHighlights(htmlText: string, codings: QcCodingPayload[]): QcFindMatch[] {
  const view = htmlToViewText(htmlText);
  return qcFindMatches(view, codings.map((c) => c.seltext), MAX_HIGHLIGHTS);
}

/* --------------------------------------------------- view model + baking */

/** RGB triplet used when a code has no usable color. */
const ACCENT_RGB = [217, 119, 6];

function isWsChar(c: string): boolean {
  return (
    c === " " ||
    c === "\t" ||
    c === "\n" ||
    c === "\r" ||
    c === "\f" ||
    c === "\v" ||
    c === "\u00A0" ||
    c === "\uFEFF"
  );
}

/** One decoded character plus the absolute source range it came from. */
interface DecodedPiece {
  ch: string;
  start: number;
  end: number;
}

/**
 * Decode the HTML entities in a text slice while keeping a per-character map
 * back to absolute source offsets: an entity is ONE decoded char spanning the
 * entity's whole source range; unknown entities stay literal, char by char.
 */
function decodeTextSpans(text: string, base: number): DecodedPiece[] {
  const out: DecodedPiece[] = [];
  const n = text.length;
  let i = 0;
  while (i < n) {
    const c = text.charAt(i);
    if (c !== "&") {
      out.push({ ch: c, start: base + i, end: base + i + 1 });
      i++;
      continue;
    }
    const m = /^&(#[0-9]+|#x[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);/.exec(text.slice(i));
    if (!m) {
      out.push({ ch: "&", start: base + i, end: base + i + 1 });
      i++;
      continue;
    }
    const entity = m[0];
    const decoded = decodeHtmlEntities(entity);
    if (decoded === entity) {
      // Unknown entity — keep it literal so the view text stays identical.
      for (let k = 0; k < entity.length; k++) {
        out.push({ ch: entity.charAt(k), start: base + i + k, end: base + i + k + 1 });
      }
    } else {
      out.push({ ch: decoded, start: base + i, end: base + i + entity.length });
    }
    i += entity.length;
  }
  return out;
}

/** The page's visible text plus the way back into the source HTML. */
export interface ViewModel {
  /** Collapsed visible text (single spaces), exactly the iframe's layer. */
  text: string;
  /** Per view-text char: the absolute source range(s) that produced it. */
  charSpans: Array<Array<[number, number]>>;
  /** The whitespace-free variant of `text` (stripped-mode matching). */
  stripped: string;
  /** Index into `text` for every char of `stripped`. */
  strippedToText: number[];
}

/**
 * Build the same collapsed text layer the iframe's DOM walk produces — the
 * authority for matching — while mapping every view-text char back to its
 * source range(s) in the serialized HTML:
 *
 *  - entities are decoded (one view char per entity, spanning its source);
 *  - whitespace-only text nodes are DROPPED (the injected script skips them
 *    via `!nodeValue.trim()` — this is why `<p>a</p>\n<p>b</p>` reads as
 *    "ab", not "a b", unlike `htmlToViewText`);
 *  - runs of whitespace collapse to one space, crossing text-node boundaries;
 *  - script/style/noscript/template/code/pre/head content is skipped, as is
 *    the content of RCDATA/fallback elements (textarea, title, iframe, …)
 *    that never produces DOM text nodes.
 */
export function buildViewModel(html: string): ViewModel {
  const n = html.length;
  const text: string[] = [];
  const charSpans: Array<Array<[number, number]>> = [];
  let lastSpace = false;

  const emitSpace = (spans: Array<[number, number]>) => {
    if (!lastSpace && text.length > 0) {
      text.push(" ");
      charSpans.push(spans);
    }
    lastSpace = true;
  };

  const emitChar = (ch: string, start: number, end: number) => {
    text.push(ch);
    charSpans.push([[start, end]]);
    lastSpace = false;
  };

  const consumeText = (raw: string, base: number) => {
    const pieces = decodeTextSpans(raw, base);
    if (!pieces.length) return;
    let allWs = true;
    for (const p of pieces) {
      if (!isWsChar(p.ch)) {
        allWs = false;
        break;
      }
    }
    // Whitespace-only text nodes are invisible to the iframe's DOM walk.
    if (allWs) return;
    let k = 0;
    while (k < pieces.length) {
      const p = pieces[k];
      if (isWsChar(p.ch)) {
        const spans: Array<[number, number]> = [];
        let runEnd = k;
        while (runEnd < pieces.length && isWsChar(pieces[runEnd].ch)) {
          const sp = pieces[runEnd];
          if (spans.length === 0 || spans[spans.length - 1][1] !== sp.start) {
            spans.push([sp.start, sp.end]);
          } else {
            spans[spans.length - 1][1] = sp.end;
          }
          runEnd++;
        }
        emitSpace(spans);
        k = runEnd;
      } else {
        emitChar(p.ch, p.start, p.end);
        k++;
      }
    }
  };

  let i = 0;
  while (i < n) {
    const lt = html.indexOf("<", i);
    if (lt < 0) {
      consumeText(html.slice(i), i);
      break;
    }
    consumeText(html.slice(i, lt), i);
    if (html.startsWith("<!--", lt)) {
      i = skipComment(html, lt, n);
      continue;
    }
    const after = html.charAt(lt + 1);
    if (after === "!" || after === "?") {
      i = skipTag(html, lt, n);
      continue;
    }
    const name = readTagName(html, lt, n);
    if (name === null) {
      consumeText(html.slice(lt, lt + 1), lt);
      i = lt + 1;
      continue;
    }
    if (hasInertTextContent(name)) {
      i = skipRawElement(html, lt, name, n);
      continue;
    }
    if (name === "head") {
      i = skipHead(html, lt, n);
      continue;
    }
    i = skipTag(html, lt, n);
  }

  const joined = text.join("");
  const strippedToText: number[] = [];
  let stripped = "";
  for (let k = 0; k < joined.length; k++) {
    if (joined.charAt(k) !== " ") {
      strippedToText.push(k);
      stripped += joined.charAt(k);
    }
  }
  return { text: joined, charSpans, stripped, strippedToText };
}

/* ------------------------------------------------- selection → source mapping */

/** A view-text range mapped back into the source HTML. */
export interface ViewSourceRange {
  /** Source start offset (inclusive). */
  pos0: number;
  /** Source end offset (exclusive). */
  pos1: number;
  /** The view-text slice the range covers — exactly what the highlight
   *  matching pipeline matches against, so this is the seltext to store. */
  seltext: string;
}

/**
 * Map a selection over the collapsed view text ([start, end) view indices,
 * as reported by the iframe's own DOM walk) back into absolute source
 * offsets of the serialized HTML. Out-of-range indices are clamped; empty
 * selections return null. Per-view chars carry their source spans (a decoded
 * entity spans its whole source range, a collapsed whitespace run its whole
 * run), so the mapped [pos0, pos1) is the exact source of the view slice.
 */
export function mapViewRangeToSource(
  model: ViewModel,
  start: number,
  end: number,
): ViewSourceRange | null {
  const s = Math.max(0, Math.min(start, model.text.length));
  const e = Math.max(s, Math.min(end, model.text.length));
  if (e <= s) return null;
  const first = model.charSpans[s];
  const last = model.charSpans[e - 1];
  if (first.length === 0 || last.length === 0) return null;
  // Spans are emitted in source order, so the extremes are well-defined.
  const pos0 = first[0][0];
  const pos1 = last[last.length - 1][1];
  if (pos1 <= pos0) return null;
  return { pos0, pos1, seltext: model.text.slice(s, e) };
}

/** Remove all whitespace (incl. NBSP/BOM) — the approximate-equality basis. */
function stripWs(text: string): string {
  return text.replace(/[\s\u00A0\uFEFF]+/g, "");
}

/**
 * Approximate check that a view-text slice (what the user selected on the
 * rendered page) corresponds to a slice of the backend's extracted fulltext
 * (what the plain-text pane codes against). The two may differ only in
 * whitespace: the fulltext collapses runs and inserts "\n" at block tags,
 * while the view text collapses runs and joins blocks without whitespace.
 */
export function viewTextMatchesFulltext(viewText: string, fulltextSlice: string): boolean {
  const a = stripWs(viewText);
  const b = stripWs(fulltextSlice);
  return a.length > 0 && a === b;
}

/** A selected range located in the extracted fulltext. */
export interface FulltextRange {
  /** Fulltext start offset (inclusive). */
  pos0: number;
  /** Fulltext end offset (exclusive). */
  pos1: number;
  /** The exact fulltext slice — what the plain-text pane renders. */
  seltext: string;
}

/**
 * Locate a selection made on the RENDERED page in the backend's extracted
 * fulltext. The view-text slice (from the iframe) and the fulltext differ in
 * whitespace only — the extraction inserts "\n" at block tags (shifting
 * positions!) and the view collapses/joins differently — so the slice is
 * found whitespace-insensitively on the fulltext's collapsed layer
 * (`model` = `buildViewModel(fulltext)`).
 *
 * When the stripped slice occurs several times, the occurrence whose source
 * offset (`srcHintPos0`, the exact source range the selection maps to) is
 * CLOSEST wins: the extraction maps source offsets monotonically, so the
 * correct occurrence sits near the source position. For typical multi-word
 * selections the closest occurrence is the selected one; single-word picks
 * may anchor on a different but textually identical instance.
 *
 * Returns null only when the slice is not in the fulltext at all (or empty)
 * — the guard that stops a selection from being coded.
 */
export function locateInFulltext(
  fulltext: string,
  model: ViewModel,
  viewSlice: string,
  srcHintPos0: number,
): FulltextRange | null {
  const selStrip = stripWs(viewSlice);
  if (!selStrip || selStrip.length > model.stripped.length) return null;
  let best: FulltextRange | null = null;
  let bestDist = Infinity;
  let scanned = 0;
  let from = 0;
  while (scanned < 100) {
    const si = model.stripped.indexOf(selStrip, from);
    if (si < 0) break;
    scanned++;
    from = si + selStrip.length;
    const lastStripped = si + selStrip.length - 1;
    if (lastStripped >= model.strippedToText.length) break;
    const c0 = model.strippedToText[si];
    const c1 = model.strippedToText[lastStripped] + 1;
    const firstSpans = model.charSpans[c0];
    const lastSpans = model.charSpans[c1 - 1];
    if (firstSpans.length === 0 || lastSpans.length === 0) continue;
    const p0 = firstSpans[0][0];
    const p1 = lastSpans[lastSpans.length - 1][1];
    const dist = Math.abs(p0 - srcHintPos0);
    if (dist < bestDist) {
      bestDist = dist;
      best = { pos0: p0, pos1: p1, seltext: fulltext.slice(p0, p1) };
    }
  }
  return best;
}

/**
 * The codings whose [pos0, pos1) spans overlap [pos0, pos1) — used to find
 * the segment(s) under a right-click on the rendered page.
 */
export function codingsOverlappingRange<T extends { pos0: number; pos1: number }>(
  codings: T[],
  pos0: number,
  pos1: number,
): T[] {
  return codings.filter((c) => c.pos0 < pos1 && c.pos1 > pos0);
}

/* ------------------------------------------------- frame ↔ parent protocol */

/**
 * The messages the injected iframe script sends to the parent. The script
 * recomputes its DOM text model on demand (the parent builds the identical
 * `ViewModel` over the serialized html), so the view indices in these
 * messages map 1:1 onto the parent's model.
 */
export interface QcSelectionMessage {
  type: "qc:selection";
  /** Collapsed-view range of the selection (half-open). */
  startView: number;
  endView: number;
  /** The view-text slice the selection covers. */
  text: string;
  /** The selection's bounding box in the iframe's viewport, when visible. */
  rect: { left: number; top: number; bottom: number } | null;
  /** Last mouse-down/up position in the iframe (toolbar fallback anchor). */
  mouseX: number;
  mouseY: number;
}

export interface QcSelectionClearedMessage {
  type: "qc:selection-cleared";
}

export interface QcContextMenuMessage {
  type: "qc:contextmenu";
  /** Cursor position in the iframe's viewport. */
  x: number;
  y: number;
  /** Collapsed-view index of the char under the cursor, when over text. */
  viewIndex: number | null;
}

export interface QcFrameMousedownMessage {
  type: "qc:frame-mousedown";
}

export type QcFrameMessage =
  | QcSelectionMessage
  | QcSelectionClearedMessage
  | QcContextMenuMessage
  | QcFrameMousedownMessage;

function finiteNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/**
 * Validate + shape a frame→parent message. Unknown types (in particular the
 * parent→frame `qc:codings`, which the frame also echoes back into any other
 * listener) and malformed payloads are rejected — the parent's listener must
 * ignore everything it does not understand.
 */
export function parseFrameMessage(data: unknown): QcFrameMessage | null {
  if (typeof data !== "object" || data === null) return null;
  const d = data as Record<string, unknown>;
  switch (d.type) {
    case "qc:selection": {
      const startView = finiteNumber(d.startView);
      const endView = finiteNumber(d.endView);
      if (startView === null || endView === null || typeof d.text !== "string") return null;
      let rect: QcSelectionMessage["rect"] = null;
      if (typeof d.rect === "object" && d.rect !== null) {
        const r = d.rect as Record<string, unknown>;
        rect = {
          left: finiteNumber(r.left) ?? 0,
          top: finiteNumber(r.top) ?? 0,
          bottom: finiteNumber(r.bottom) ?? 0,
        };
      }
      return {
        type: "qc:selection",
        startView,
        endView,
        text: d.text,
        rect,
        mouseX: finiteNumber(d.mouseX) ?? 0,
        mouseY: finiteNumber(d.mouseY) ?? 0,
      };
    }
    case "qc:selection-cleared":
      return { type: "qc:selection-cleared" };
    case "qc:contextmenu": {
      const x = finiteNumber(d.x);
      const y = finiteNumber(d.y);
      if (x === null || y === null) return null;
      return { type: "qc:contextmenu", x, y, viewIndex: finiteNumber(d.viewIndex) };
    }
    case "qc:frame-mousedown":
      return { type: "qc:frame-mousedown" };
    default:
      return null;
  }
}

/**
 * The inline style for a highlight mark — byte-identical to the injected
 * script's styleFor() (same accent fallback), so baked and live marks look
 * the same.
 */
export function markStyleFor(color: string | null): string {
  const m = /^#([0-9a-f]{6})$/i.exec(color ?? "");
  const rgb = m
    ? [
        parseInt(m[1].slice(0, 2), 16),
        parseInt(m[1].slice(2, 4), 16),
        parseInt(m[1].slice(4, 6), 16),
      ]
    : ACCENT_RGB;
  return (
    `background:rgba(${rgb.join(",")},.22);outline:1px solid rgba(${rgb.join(",")},.6);` +
    "border-radius:2px;color:inherit;padding:0"
  );
}

/** Escape a value for a double-quoted HTML attribute. */
function escapeAttr(value: string): string {
  return value.replace(/[&"<>]/g, (c) => {
    switch (c) {
      case "&":
        return "&amp;";
      case '"':
        return "&quot;";
      case "<":
        return "&lt;";
      default:
        return "&gt;";
    }
  });
}

/** Escape literal `<` in marked text so it never joins an adjacent tag. */
function escapeMarkText(text: string): string {
  return text.replace(/</g, "&lt;");
}

/**
 * Embed the codings' marks directly into the serialized snapshot HTML —
 * pre-computed in the parent BEFORE the iframe ever loads, so highlights
 * render with zero script/postMessage dependency. The injected script keeps
 * only the live-update job (re-mark on `qc:codings` messages), replacing
 * these marks in place.
 *
 * Matching runs on the view text (`buildViewModel` — identical to the DOM
 * walk the iframe performs) via the shared `qcFindMatches`; every view-text
 * char carries its source range, so each match expands to concrete source
 * spans. A span never crosses a tag boundary, so the inserted `<mark>` stays
 * inside its text node's parent; spans overlapping an already-placed mark are
 * dropped (marks are never nested). The page markup itself is preserved
 * byte-for-byte except literal `<` inside marked text, which is escaped so
 * it can never be re-parsed as a tag against an adjacent `<mark>`/`</mark>`.
 */
export function buildHighlightedHtml(html: string, codings: QcCodingPayload[]): string {
  const model = buildViewModel(html);
  const matches = qcFindMatches(model.text, codings.map((c) => c.seltext), MAX_HIGHLIGHTS);

  interface Group {
    start: number;
    end: number;
    seg: number;
  }
  const groups: Group[] = [];
  for (const hit of matches) {
    let s = hit.start;
    let e = hit.start + hit.len;
    if (hit.mode === "stripped") {
      if (hit.start + hit.len - 1 >= model.strippedToText.length) continue;
      s = model.strippedToText[hit.start];
      e = model.strippedToText[hit.start + hit.len - 1] + 1;
    }
    if (s < 0 || e <= s || e > model.text.length) continue;
    let cur: Group | null = null;
    for (let k = s; k < e; k++) {
      for (const [fs, fe] of model.charSpans[k]) {
        if (cur && fs === cur.end) {
          cur.end = fe;
        } else {
          if (cur) groups.push(cur);
          cur = { start: fs, end: fe, seg: hit.seg };
        }
      }
    }
    if (cur) groups.push(cur);
  }

  groups.sort((a, b) => a.start - b.start || a.end - b.end);
  let out = "";
  let pos = 0;
  let lastEnd = -1;
  for (const g of groups) {
    if (g.start < lastEnd) continue; // would nest inside an earlier mark
    const coding = codings[g.seg];
    out += html.slice(pos, g.start);
    out += `<mark class="qc-live-coding"`;
    if (coding.name) out += ` title="${escapeAttr(coding.name)}"`;
    if (coding.ctid !== undefined) {
      out += ` data-ctid="${coding.ctid}" data-ctids="${coding.ctid}"`;
    }
    out += ` style="${markStyleFor(coding.color)}${coding.hidden ? ";opacity:.2" : ""}">`;
    out += escapeMarkText(html.slice(g.start, g.end));
    out += `</mark>`;
    pos = g.end;
    lastEnd = g.end;
  }
  out += html.slice(pos);
  return out;
}

/**
 * Normalize extracted website text: normalize line endings, strip trailing
 * whitespace, and collapse runs of blank lines to a single newline so the
 * plaintext view reads as continuous paragraphs.
 */
export function cleanEmptyLines(text: string): string {
  return text
    .replace(/\r\n?/g, "\n")    // normalize CRLF / CR
    .replace(/[ \t]+\n/g, "\n") // strip trailing spaces per line
    .replace(/\n{2,}/g, "\n")   // collapse blank lines
    .trim();
}
