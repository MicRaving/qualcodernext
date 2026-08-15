/**
 * App screenshot capture for the bug report (html2canvas).
 *
 * Captures `#root` (the whole app shell) to a canvas and returns a PNG
 * data-URL. External images taint the canvas (html2canvas limitation); the
 * app's images are same-origin through the backend, so this is normally a
 * non-issue — but when the export fails the caller gets an error and falls
 * back to an empty canvas instead of blocking the report.
 *
 * Tailwind v4 quirk: opacity modifiers (`bg-x/50`, `border-danger/50`, …)
 * compute to `oklab()`/`oklch()` in Chromium, which html2canvas 1.4.1
 * cannot parse ("unsupported color function oklab"). The `onclone` hook
 * below rewrites every offending computed color to an equivalent hex before
 * the render, so the capture works on stock Tailwind v4 output.
 */
import html2canvas from "html2canvas";

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

function parseOklab(v: string): Rgb | null {
  const m = v.match(/oklab\(\s*([\d.]+)%?\s+([-\d.]+)\s+([-\d.]+)\s*(?:\/\s*([\d.]+%?))?\s*\)/);
  if (!m) return null;
  let l = parseFloat(m[1]);
  if (m[1].endsWith("%")) l /= 100;
  const alpha = parseFloat(m[4] ?? "1");
  const a = m[4]?.endsWith("%") ? alpha / 100 : alpha;
  const { r, g, b } = oklabToRgb(l, parseFloat(m[2]), parseFloat(m[3]));
  return { r, g, b, a };
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
  return { r, g, b, a };
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
  const r = ((n >> 24) & 255) / 255;
  const g = ((n >> 16) & 255) / 255;
  const b = ((n >> 8) & 255) / 255;
  const a = hex.length === 8 ? (n & 255) / 255 : 1;
  return { r, g, b, a };
}

/** Resolve a CSS color string (oklab/oklch/color-mix/color()/rgb/hex). */
function resolveColor(v: string): Rgb | null {
  const value = v.trim();
  return (
    parseOklab(value) ??
    parseOklch(value) ??
    parseColorFn(value) ??
    parseRgb(value) ??
    parseHex(value) ??
    null
  );
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

/** Color function tokens html2canvas cannot parse. */
const UNSUPPORTED_TOKEN = /(oklab|oklch|color-mix|color)\(/i;

/**
 * Rewrite every unsupported color token inside a property value to an
 * equivalent hex. Handles compound values (box-shadow/text-shadow render the
 * color first in computed style) by replacing token-by-token. Returns the
 * rewritten value, or null when nothing needed to change.
 */
function rewriteColors(value: string): string | null {
  if (!UNSUPPORTED_TOKEN.test(value)) return null;
  let out = value;
  let changed = false;
  const tokenRe = /(?:oklab|oklch|color-mix|color)\([^)]*\)/gi;
  for (const match of value.matchAll(tokenRe)) {
    const rgb = resolveColor(match[0]);
    if (!rgb) continue;
    out = out.replace(match[0], hexOf(rgb));
    changed = true;
  }
  return changed ? out : null;
}

/**
 * Normalize unsupported color functions in the cloned document: any computed
 * color html2canvas would choke on (oklab/oklch/color-mix/color()) is
 * replaced by an equivalent hex. Keeps the visual fidelity of Tailwind v4
 * output (the app's own palette is hex; only opacity modifiers go oklab).
 */
function neutralizeColors(clonedDoc: Document): void {
  const dbg = {
    elements: 0,
    styles: 0,
    rewritten: 0,
    oklabValues: [] as string[],
  };
  for (const el of clonedDoc.querySelectorAll<HTMLElement>("*")) {
    dbg.elements++;
    const style = clonedDoc.defaultView?.getComputedStyle(el);
    if (!style) continue;
    dbg.styles++;
    for (const prop of COLOR_PROPS) {
      const value = style.getPropertyValue(prop);
      if (!value) continue;
      if (UNSUPPORTED_TOKEN.test(value)) dbg.oklabValues.push(`${prop}: ${value}`);
      const rewritten = rewriteColors(value);
      if (rewritten !== null) {
        el.style.setProperty(prop, rewritten);
        dbg.rewritten++;
      }
    }
  }
  console.warn("bugreport neutralizeColors", JSON.stringify({ ...dbg, sample: dbg.oklabValues.slice(0, 5) }));
}

export async function captureAppScreenshot(): Promise<CaptureResult> {
  const root = document.querySelector<HTMLElement>("#root");
  if (!root) throw new Error("App root not found");
  const canvas = await html2canvas(root, {
    backgroundColor: null,
    useCORS: true,
    scale: Math.min(MAX_SCALE, window.devicePixelRatio || 1),
    logging: false,
    onclone: neutralizeColors,
  });
  let dataUrl: string;
  try {
    dataUrl = canvas.toDataURL("image/png");
  } catch (err) {
    // Tainted canvas (external image): no pixels can be read.
    throw new Error(err instanceof Error ? err.message : "Canvas export failed");
  }
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("Canvas export produced no image data");
  return { dataUrl, blob };
}

/** Blank white canvas with a note — the fallback when the capture fails so
 *  the user can still file the report. */
export async function blankScreenshot(note: string): Promise<CaptureResult> {
  const canvas = document.createElement("canvas");
  canvas.width = 1280;
  canvas.height = 720;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#666666";
    ctx.font = "20px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(note, canvas.width / 2, canvas.height / 2);
  }
  const dataUrl = canvas.toDataURL("image/png");
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  return { dataUrl, blob: blob ?? new Blob([dataUrl], { type: "image/png" }) };
}
