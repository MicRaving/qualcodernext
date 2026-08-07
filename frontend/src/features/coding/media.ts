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
  let cursorMs = 0;
  for (const line of fulltext.split(/\r?\n/)) {
    const m = line.trim().match(re);
    if (m) {
      const secs = m[3]
        ? Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3])
        : Number(m[1]) * 60 + Number(m[2]);
      const startMs = secs * 1000;
      if (m[4].trim()) {
        segments.push({ startMs, endMs: startMs + 2500, text: m[4].trim() });
      }
      cursorMs = startMs;
    } else if (line.trim()) {
      segments.push({ startMs: cursorMs, endMs: cursorMs + 2500, text: line.trim() });
    }
  }
  return segments;
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
