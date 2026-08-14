/**
 * Pure helpers behind the HtmlCoder live-coding highlights — all side-effect
 * free, so the matching logic can be unit-tested without a DOM:
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
 */

/** Cap on marked segments per highlight pass. */
export const MAX_HIGHLIGHTS = 500;

/** Payload pushed into the iframe for one coded segment. */
export interface QcCodingPayload {
  seltext: string;
  color: string | null;
  name: string;
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

/**
 * The page's visible text the way the iframe's DOM walk produces it:
 * entities decoded, tags removed, whitespace collapsed, and script/style/
 * noscript/template/head content dropped (those produce no visible text
 * nodes). Inter-tag whitespace is kept — it IS a text node in the DOM.
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
    if (RAW_TEXT_TAGS.includes(name)) {
      i = skipRawElement(html, lt, name, n);
      continue;
    }
    if (name === "code" || name === "pre") {
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

/**
 * Skip a `<head>` element — its text is not part of document.body, so it
 * must not be matchable. Stops early at `<body` (the head auto-closes there).
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
    if (name === "body") return nlt;
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
