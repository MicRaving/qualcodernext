/**
 * Pure helpers for image/AV coding — time formatting and timeline math.
 */

/**
 * Media helpers — time formatting and transcript parsing.
 */

export interface SubtitleSegment {
  startMs: number;
  endMs: number;
  text: string;
}

/** Parse "[mm:ss] text" transcript lines into subtitle segments. */
export function parseTranscript(fulltext: string): SubtitleSegment[] {
  const segments: SubtitleSegment[] = [];
  const re = /^\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*(.*)$/;
  // SRT/VTT style: "00:00:01,000 --> 00:00:04,500" followed by text lines.
  const srtRe =
    /^(\d{1,2}):(\d{2}):(\d{2})[,.]\d{1,3}\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.]\d{1,3}/;
  let cursorMs = 0;
  let pendingSrt: SubtitleSegment | null = null;
  for (const raw of fulltext.split(/\r?\n/)) {
    const line = raw.trim();
    const m = line.match(re);
    if (m) {
      const secs = m[3]
        ? Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3])
        : Number(m[1]) * 60 + Number(m[2]);
      const startMs = secs * 1000;
      if (m[4].trim()) {
        segments.push({ startMs, endMs: startMs + 2500, text: m[4].trim() });
      }
      cursorMs = startMs;
      continue;
    }
    const srt = line.match(srtRe);
    if (srt) {
      const startMs =
        (Number(srt[1]) * 3600 + Number(srt[2]) * 60 + Number(srt[3])) * 1000;
      const endMs =
        (Number(srt[4]) * 3600 + Number(srt[5]) * 60 + Number(srt[6])) * 1000;
      pendingSrt = { startMs, endMs, text: "" };
      cursorMs = startMs;
      continue;
    }
    if (pendingSrt && line) {
      pendingSrt.text = pendingSrt.text ? `${pendingSrt.text} ${line}` : line;
      continue;
    }
    if (line) {
      segments.push({ startMs: cursorMs, endMs: cursorMs + 2500, text: line });
    }
  }
  if (pendingSrt && pendingSrt.text) segments.push(pendingSrt);
  return segments;
}

/**
 * Insert a transcript timestamp (`[mm:ss] ` / `[hh:mm:ss] `) at the caret
 * of a manual-transcription draft. A newline is prefixed unless the caret
 * already sits at the start of a line, so every timestamped entry stays on
 * its own line — the exact format `parseTranscript` expects. Returns the
 * new text and the caret position directly after the inserted timestamp.
 */
export function insertTimestampAtCaret(
  text: string,
  start: number,
  end: number,
  timestamp: string,
): { text: string; caret: number } {
  const before = text.slice(0, start);
  const after = text.slice(end);
  const insertion = before === "" || before.endsWith("\n") ? `${timestamp} ` : `\n${timestamp} `;
  return { text: `${before}${insertion}${after}`, caret: start + insertion.length };
}

export function formatTime(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "0:00";
  const totalSeconds = Math.round(ms / 1000);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return `${h > 0 ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}

export function secondsToMs(s: number): number {
  return Math.round(s * 1000);
}

/** Percent position of a segment start on the timeline, clamped 0..100. */
export function segmentLeft(pos0: number, durationMs: number): number {
  if (!Number.isFinite(durationMs) || durationMs <= 0) return 0;
  return Math.max(0, Math.min(100, (pos0 / durationMs) * 100));
}

/** Percent width of a segment on the timeline, clamped 0..100. */
export function segmentWidth(pos0: number, pos1: number, durationMs: number): number {
  if (!Number.isFinite(durationMs) || durationMs <= 0) return 0;
  const w = ((pos1 - pos0) / durationMs) * 100;
  return Math.max(0, Math.min(100, w));
}

/* ------------------------------------------------------------------ */
/* CRLF offset mapping                                                 */
/* ------------------------------------------------------------------ */

/**
 * Legacy projects store transcripts with CRLF line endings while the
 * transcript panel renders "\n"-only lines, so a position in the rendered
 * text is smaller than the same position in the stored text by the number
 * of CR characters before it. `crAt[pos]` is the count of CR characters
 * before the raw offset `pos`; it converts positions between the two
 * spaces. Stored (pos0/pos1) positions stay in RAW space.
 */
export function buildCrAt(raw: string): Int32Array {
  const counts = new Int32Array(raw.length + 1);
  let n = 0;
  for (let i = 0; i < raw.length; i++) {
    counts[i] = n;
    if (raw.charCodeAt(i) === 13) n += 1;
  }
  counts[raw.length] = n;
  return counts;
}

/** The stored text with every CR removed (the rendered transcript text). */
export function stripCr(raw: string): string {
  return raw.replace(/\r/g, "");
}

/** Raw (stored) offset -> rendered offset. */
export function rawToRendered(crAt: Int32Array, pos: number): number {
  return Math.max(0, pos - (crAt[Math.min(pos, crAt.length - 1)] ?? 0));
}

/** Rendered offset -> raw (stored) offset. */
export function renderedToRaw(raw: string, crAt: Int32Array, pos: number): number {
  let lo = pos;
  let hi = raw.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (mid - crAt[mid] < pos) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export interface PositionedCoding {
  pos0: number;
  pos1: number;
  /** The exact text stored at creation time; may be empty for old builds. */
  seltext?: string | null;
}

/**
 * Normalize one coding's stored positions to RAW space. Codings created by
 * builds that predated CRLF handling were stored in RENDERED space (their
 * seltext then contains text from the following line), so their positions
 * must be shifted back; every other coding is already raw-space.
 */
export function normalizeCodingPositions<C extends PositionedCoding>(
  raw: string,
  crAt: Int32Array,
  coding: C,
): C {
  const sel = (coding.seltext ?? "").replace(/\r/g, "");
  if (raw.slice(coding.pos0, coding.pos1).replace(/\r/g, "") === sel) return coding;
  if (stripCr(raw).slice(coding.pos0, coding.pos1) === sel) {
    return {
      ...coding,
      pos0: renderedToRaw(raw, crAt, coding.pos0),
      pos1: renderedToRaw(raw, crAt, coding.pos1),
    };
  }
  // Broken/empty seltext (old builds) — stored in rendered space.
  return {
    ...coding,
    pos0: renderedToRaw(raw, crAt, coding.pos0),
    pos1: renderedToRaw(raw, crAt, coding.pos1),
  };
}
