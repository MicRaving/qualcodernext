/**
 * App screenshot capture for the bug report (html2canvas).
 *
 * Captures `#root` (the whole app shell) to a canvas and returns a PNG
 * data-URL. External images taint the canvas (html2canvas limitation); the
 * app's images are same-origin through the backend, so this is normally a
 * non-issue.
 *
 * Tailwind v4 quirk: opacity modifiers (`bg-x/50`, `border-danger/50`, …)
 * compute to `oklch()`/`oklab()`/`color-mix()` in Chromium, which
 * html2canvas 1.4.1 cannot parse ("unsupported color function oklab"). The
 * `onclone` hook below rewrites every offending computed color to an
 * equivalent hex (or a safe fallback) before the render, so the capture
 * works on stock Tailwind v4 output.
 *
 * Failure handling: a failed render is retried once after a double rAF
 * (transient mid-transition DOM states are the most common cause), and the
 * caller falls back to `textSnapshotScreenshot` — a structured, legible
 * text snapshot (app version, view, last action, last error, timestamp)
 * drawn on a canvas. A bug report NEVER ships a blank placeholder.
 */
import { errorMessage } from "@/lib/utils";
import html2canvas from "html2canvas";
import { t } from "@/lib/i18n";

export interface CaptureResult {
  /** PNG data-URL of the captured view. */
  dataUrl: string;
  /** Same pixels as a Blob (used for the GitHub attachment upload). */
  blob: Blob;
}

/** Max capture scale (very high-DPI displays would balloon the PNG). */
const MAX_SCALE = 2;

interface Rgb {
  r: number;
  g: number;
  b: number;
  a: number;
}

const clamp01 = (v: number): number => (v < 0 ? 0 : v > 1 ? 1 : v);

/** sRGB transfer function (gamma encode / decode) for the Oklab round trip. */
const srgbEncode = (v: number): number =>
  v <= 0.0031308 ? v * 12.92 : 1.055 * Math.pow(v, 1 / 2.4) - 0.055;
const srgbDecode = (v: number): number =>
  v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);

function hexOf(c: Rgb): string {
  const to = (v: number) => Math.round(clamp01(v) * 255).toString(16).padStart(2, "0");
  return `#${to(c.r)}${to(c.g)}${to(c.b)}${to(c.a)}`;
}

/** Oklab → linear sRGB (Björn Ottosson's reference conversion). */
function oklabToRgb(l: number, a: number, b: number): { r: number; g: number; b: number } {
  const l_ = l + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = l - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = l - 0.0894841775 * a - 1.291485548 * b;
  const l3 = l_ * l_ * l_;
  const m3 = m_ * m_ * m_;
  const s3 = s_ * s_ * s_;
  return {
    r: 4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3,
    g: -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3,
    b: -0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3,
  };
}

/** Linear sRGB → Oklab (inverse reference conversion). */
function rgbToOklab(r: number, g: number, b: number): { l: number; a: number; b: number } {
  const lr = srgbDecode(clamp01(r));
  const lg = srgbDecode(clamp01(g));
  const lb = srgbDecode(clamp01(b));
  const l = 0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb;
  const m = 0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb;
  const s = 0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb;
  const l_ = Math.cbrt(l);
  const m_ = Math.cbrt(m);
  const s_ = Math.cbrt(s);
  return {
    l: 0.2104542553 * l_ + 0.793617785 * m_ - 0.0040720468 * s_,
    a: 1.9779984951 * l_ - 2.428592205 * m_ + 0.4505937099 * s_,
    b: 0.0259040371 * l_ + 0.7827717662 * m_ - 0.808675766 * s_,
  };
}

function parseOklab(v: string): Rgb | null {
  const m = v.match(/oklab\(\s*([\d.]+)%?\s+([-\d.]+)\s+([-\d.]+)\s*(?:\/\s*([\d.]+%?))?\s*\)/);
  if (!m) return null;
  let l = parseFloat(m[1]);
  if (m[1].endsWith("%")) l /= 100;
  const alpha = parseFloat(m[4] ?? "1");
  const a = m[4]?.endsWith("%") ? alpha / 100 : alpha;
  const { r, g, b } = oklabToRgb(l, parseFloat(m[2]), parseFloat(m[3]));
  return { r: srgbEncode(r), g: srgbEncode(g), b: srgbEncode(b), a };
}

function parseOklch(v: string): Rgb | null {
  const m = v.match(/oklch\(\s*([\d.]+)%?\s+([-\d.]+)\s+([-\d.]+)\s*(?:\/\s*([\d.]+%?))?\s*\)/);
  if (!m) return null;
  let l = parseFloat(m[1]);
  if (m[1].endsWith("%")) l /= 100;
  const c = parseFloat(m[2]);
  const h = (parseFloat(m[3]) * Math.PI) / 180;
  const alpha = parseFloat(m[4] ?? "1");
  const a = m[4]?.endsWith("%") ? alpha / 100 : alpha;
  const { r, g, b } = oklabToRgb(l, c * Math.cos(h), c * Math.sin(h));
  return { r: srgbEncode(r), g: srgbEncode(g), b: srgbEncode(b), a };
}

function parseColorFn(v: string): Rgb | null {
  const m = v.match(/^color\(\s*srgb\s+([\d.]+%?)\s+([\d.]+%?)\s+([\d.]+%?)\s*(?:\/\s*([\d.]+%?))?\s*\)/);
  if (!m) return null;
  const to = (s: string) => (s.endsWith("%") ? parseFloat(s) / 100 : parseFloat(s));
  const a = m[4] ? to(m[4]) : 1;
  return { r: to(m[1]), g: to(m[2]), b: to(m[3]), a };
}

function parseRgb(v: string): Rgb | null {
  const m = v.match(/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)\s*(?:[,/]\s*([\d.]+%?))?\s*\)/);
  if (!m) return null;
  const to = (s: string) => (s.endsWith("%") ? (parseFloat(s) / 100) * 255 : parseFloat(s));
  const a =
    m[4] === undefined
      ? 1
      : m[4].endsWith("%")
        ? parseFloat(m[4]) / 100
        : parseFloat(m[4]);
  return { r: to(m[1]) / 255, g: to(m[2]) / 255, b: to(m[3]) / 255, a };
}

function parseHex(v: string): Rgb | null {
  const m = v.match(/^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i);
  if (!m) return null;
  let hex = m[1];
  if (hex.length <= 4) {
    hex = hex.split("").map((c) => c + c).join("");
  }
  const n = parseInt(hex, 16);
  if (hex.length === 8) {
    // #RRGGBBAA — 32-bit, alpha in the low byte.
    return {
      r: ((n >> 24) & 255) / 255,
      g: ((n >> 16) & 255) / 255,
      b: ((n >> 8) & 255) / 255,
      a: (n & 255) / 255,
    };
  }
  // #RRGGBB — 24-bit (alpha defaults to 1).
  return {
    r: ((n >> 16) & 255) / 255,
    g: ((n >> 8) & 255) / 255,
    b: (n & 255) / 255,
    a: 1,
  };
}

/**
 * Resolve a CSS `color-mix(...)` value. Handles the spaces Tailwind v4
 * emits (`in srgb`, `in srgb-linear`, `in oklab`, `in oklch`, hue-method
 * keywords) with nested colors (which may themselves be oklab/oklch/…).
 * Returns null when the shape is not recognized.
 */
function parseColorMix(v: string): Rgb | null {
  const m = v.match(/^color-mix\(\s*(?:in\s+([a-z-]+(?:\s+[a-z-]+)*)\s*,)?(.*)\)$/is);
  if (!m) return null;
  const space = (m[1] ?? "srgb").trim().split(/\s+/)[0].toLowerCase();
  const rest = m[2];
  // Split the two color parts at the TOP-LEVEL comma (nested functions may
  // contain commas of their own).
  let depth = 0;
  let splitAt = -1;
  for (let i = 0; i < rest.length; i++) {
    const ch = rest[i];
    if (ch === "(") depth++;
    else if (ch === ")") depth--;
    else if (ch === "," && depth === 0) {
      splitAt = i;
      break;
    }
  }
  if (splitAt < 0) return null;
  const part = (s: string): { color: string; pct: number | null } => {
    s = s.trim();
    const pm = s.match(/^(.*)\s+([\d.]+%)$/s);
    return pm ? { color: pm[1].trim(), pct: parseFloat(pm[2]) / 100 } : { color: s, pct: null };
  };
  const a = part(rest.slice(0, splitAt));
  const b = part(rest.slice(splitAt + 1));
  const ca = resolveColor(a.color);
  const cb = resolveColor(b.color);
  if (!ca || !cb) return null;
  const w1 = a.pct ?? (b.pct === null ? 0.5 : 1 - b.pct);
  const w2 = b.pct ?? (a.pct === null ? 0.5 : 1 - a.pct);
  const sum = w1 + w2;
  const n1 = w1 / sum;
  const n2 = w2 / sum;
  const alpha = ca.a * n1 + cb.a * n2;
  if (space === "srgb") {
    return { r: ca.r * n1 + cb.r * n2, g: ca.g * n1 + cb.g * n2, b: ca.b * n1 + cb.b * n2, a: alpha };
  }
  if (space === "srgb-linear") {
    const lin = (c: Rgb) => ({ r: srgbDecode(c.r), g: srgbDecode(c.g), b: srgbDecode(c.b) });
    const la = lin(ca);
    const lb = lin(cb);
    return {
      r: srgbEncode(la.r * n1 + lb.r * n2),
      g: srgbEncode(la.g * n1 + lb.g * n2),
      b: srgbEncode(la.b * n1 + lb.b * n2),
      a: alpha,
    };
  }
  // oklab / oklch (and unknown spaces): interpolate in Oklab.
  const oa = rgbToOklab(ca.r, ca.g, ca.b);
  const ob = rgbToOklab(cb.r, cb.g, cb.b);
  const mixed = oklabToRgb(
    oa.l * n1 + ob.l * n2,
    oa.a * n1 + ob.a * n2,
    oa.b * n1 + ob.b * n2,
  );
  return { r: srgbEncode(mixed.r), g: srgbEncode(mixed.g), b: srgbEncode(mixed.b), a: alpha };
}

/** Resolve a CSS color string (color-mix/oklab/oklch/color()/rgb/hex). */
export function resolveColor(v: string): Rgb | null {
  const value = v.trim();
  if (value === "transparent") return { r: 0, g: 0, b: 0, a: 0 };
  return (
    parseColorMix(value) ??
    parseOklab(value) ??
    parseOklch(value) ??
    parseColorFn(value) ??
    parseRgb(value) ??
    parseHex(value) ??
    null
  );
}

/**
 * Last-resort replacement when a color token cannot be converted: try the
 * first resolvable color nested inside it (e.g. the inner `oklch(...)` of an
 * unparsable `color-mix`), else opaque black. The guarantee is that NO
 * unsupported color function survives into html2canvas' parser.
 */
function fallbackFor(value: string): string {
  const inner = value.match(/(?:oklab|oklch|color-mix|color|rgb|rgba)\s*\([^)]*\)/gi);
  if (inner) {
    for (const tok of inner) {
      const rgb = resolveColor(tok);
      if (rgb) return hexOf(rgb);
    }
  }
  return "#000000";
}

/** Extract the full function call starting at `start` (balanced parens). */
function extractFnCall(value: string, start: number): string | null {
  const open = value.indexOf("(", start);
  if (open < 0) return null;
  let depth = 0;
  for (let i = open; i < value.length; i++) {
    const ch = value[i];
    if (ch === "(") depth++;
    else if (ch === ")") {
      depth--;
      if (depth === 0) return value.slice(start, i + 1);
    }
  }
  return null;
}

/** Color function tokens html2canvas cannot parse. */
const UNSUPPORTED_FN = /(?:oklab|oklch|color-mix|color)\s*\(/gi;

/**
 * Rewrite every unsupported color token inside a property value to an
 * equivalent hex. Handles compound values (gradients, shadows) and nested
 * functions (color-mix with parens inside) by extracting each full call with
 * balanced parens. Returns the rewritten value, or null when nothing needed
 * to change.
 */
export function rewriteColors(value: string): string | null {
  if (!UNSUPPORTED_FN.test(value)) return null;
  UNSUPPORTED_FN.lastIndex = 0;
  const hits: { start: number; end: number; replacement: string }[] = [];
  let m: RegExpExecArray | null;
  while ((m = UNSUPPORTED_FN.exec(value)) !== null) {
    const full = extractFnCall(value, m.index);
    if (!full) continue;
    const rgb = resolveColor(full);
    const replacement = rgb ? hexOf(rgb) : fallbackFor(full);
    hits.push({ start: m.index, end: m.index + full.length, replacement });
    UNSUPPORTED_FN.lastIndex = m.index + full.length;
  }
  if (hits.length === 0) return null;
  let out = value;
  for (let i = hits.length - 1; i >= 0; i--) {
    const h = hits[i];
    out = out.slice(0, h.start) + h.replacement + out.slice(h.end);
  }
  return out === value ? null : out;
}

/** The properties html2canvas reads whose values can carry oklab colors. */
const COLOR_PROPS = [
  "color",
  "backgroundColor",
  "backgroundImage",
  "borderTopColor",
  "borderRightColor",
  "borderBottomColor",
  "borderLeftColor",
  "boxShadow",
  "textShadow",
  "outlineColor",
  "textDecorationColor",
  "caretColor",
  "webkitTextStrokeColor",
  "fill",
  "stroke",
] as const;

/**
 * Normalize unsupported color functions in the cloned document: any computed
 * color html2canvas would choke on (oklab/oklch/color-mix/color()) is
 * replaced by an equivalent hex. Keeps the visual fidelity of Tailwind v4
 * output (the app's own palette is hex; only opacity modifiers go
 * oklab/color-mix).
 */
function neutralizeColors(clonedDoc: Document): void {
  const dbg = { elements: 0, styles: 0, rewritten: 0 };
  for (const el of clonedDoc.querySelectorAll<HTMLElement>("*")) {
    dbg.elements++;
    const style = clonedDoc.defaultView?.getComputedStyle(el);
    if (!style) continue;
    dbg.styles++;
    for (const prop of COLOR_PROPS) {
      const value = style.getPropertyValue(prop);
      if (!value) continue;
      const rewritten = rewriteColors(value);
      if (rewritten !== null) {
        el.style.setProperty(prop, rewritten);
        dbg.rewritten++;
      }
    }
    // TEMP DEBUG: full-clone scan for any remaining unsupported function.
    for (let i = 0; i < style.length; i++) {
      const p = style[i];
      const v = style.getPropertyValue(p);
      if (UNSUPPORTED_FN.test(v)) {
        console.warn(`[probe:cloneAll] <${el.tagName.toLowerCase()}> ${p}: ${v.slice(0, 120)}`);
      }
    }
  }
  if (dbg.rewritten > 0) {
    console.warn(`bugreport neutralizeColors: ${dbg.rewritten} colors rewritten (${dbg.elements} elements)`);
  }
}

/** Decode a PNG data-URL into a Blob without relying on canvas.toBlob. */
function dataUrlToBlob(dataUrl: string): Blob {
  const comma = dataUrl.indexOf(",");
  const base64 = comma >= 0 ? dataUrl.slice(comma + 1) : "";
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: "image/png" });
}

/** Valid 1×1 transparent PNG — used only where the canvas API is entirely
 *  unavailable (never reachable in the real app; keeps the data-URL/Blob
 *  contract intact in such environments). */
const MINIMAL_PNG_DATA_URL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

const raf = (): Promise<void> =>
  new Promise((resolve) => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => resolve());
    });
  });

export async function captureAppScreenshot(): Promise<CaptureResult> {
  const root = document.querySelector<HTMLElement>("#root");
  if (!root) throw new Error("App root not found");
  const render = () =>
    html2canvas(root, {
      backgroundColor: null,
      useCORS: true,
      allowTaint: true,
      scale: Math.min(MAX_SCALE, window.devicePixelRatio || 1),
      logging: false,
      onclone: neutralizeColors,
    });
  let canvas: HTMLCanvasElement;
  try {
    canvas = await render();
  } catch (first) {
    // Retry once after the next painted frame: transient DOM states (a
    // half-painted flyout, a mid-transition overlay) are the most common
    // single-shot capture failures.
    console.warn("bugreport first capture attempt failed:", first);
    await raf();
    try {
      canvas = await render();
    } catch (second) {
      throw new Error(
        `Screenshot capture failed: ${errorMessage(second, String(second))}`,
      );
    }
  }
  let dataUrl: string;
  try {
    dataUrl = canvas.toDataURL("image/png");
  } catch (err) {
    // Tainted canvas (external image): no pixels can be read.
    throw new Error(errorMessage(err, "Canvas export failed"));
  }
  return { dataUrl, blob: dataUrlToBlob(dataUrl) };
}

/** Runtime context drawn into the text-snapshot fallback. */
interface SnapshotContext {
  version: string;
  view: string;
  lastAction: string | null;
  lastError: string | null;
}

async function snapshotContext(): Promise<SnapshotContext> {
  let view = "unknown";
  let lastAction: string | null = null;
  let lastError: string | null = null;
  try {
    const { useWorkspaceStore, useProjectStore } = await import("@/stores/project");
    view = useWorkspaceStore.getState().view.kind;
    lastAction = useProjectStore.getState().bugReport.lastAction;
    lastError = useProjectStore.getState().bugReport.lastError;
  } catch {
    /* store unreachable (e.g. bare unit test) — keep the unknowns */
  }
  return { version: t("app.version"), view, lastAction, lastError };
}

/**
 * NEVER-BLANK fallback for a failed capture: renders a legible, structured
 * text snapshot (app version, view, last action, last error, timestamp) as a
 * canvas, so a bug report always carries SOMETHING useful even when
 * html2canvas cannot produce pixels.
 */
export async function textSnapshotScreenshot(note: string): Promise<CaptureResult> {
  const ctx = await snapshotContext();
  const when = new Date().toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
  const lines = [
    "QCnext — bug report snapshot",
    "",
    `App version: ${ctx.version}`,
    `View: ${ctx.view}`,
    `Last action: ${ctx.lastAction ?? "—"}`,
    `Last error: ${ctx.lastError ?? "—"}`,
    `Time: ${when}`,
    "",
    note ? `Note: ${note}` : "",
    "",
    "A rendered screenshot could not be captured; this text snapshot",
    "was attached instead. Please describe the problem in the issue body.",
  ];
  const W = 960;
  const pad = 24;
  const lineH = 24;
  const H = pad * 2 + lines.length * lineH;
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const g = canvas.getContext("2d");
  if (g) {
    g.fillStyle = "#ffffff";
    g.fillRect(0, 0, W, H);
    g.fillStyle = "#111111";
    g.font = "600 16px system-ui, sans-serif";
    g.textAlign = "left";
    g.textBaseline = "middle";
    lines.forEach((line, i) => {
      g.fillText(line, pad, pad + i * lineH + lineH / 2);
    });
  }
  const dataUrl = canvas.toDataURL("image/png") || MINIMAL_PNG_DATA_URL;
  return { dataUrl, blob: dataUrlToBlob(dataUrl) };
}

/**
 * Legacy name for `textSnapshotScreenshot` — the store's fallback path calls
 * it after a failed capture. It now renders a structured text snapshot, so a
 * "blank placeholder" is never attached to a bug report.
 */
export const blankScreenshot = textSnapshotScreenshot;
