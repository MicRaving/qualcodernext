import { mediaTypeLabel } from "@/features/manage/files";

export function barWidth(count: number, max: number): string {
  if (max <= 0) return "0%";
  return `${Math.round((count / max) * 100)}%`;
}

/** Human-readable media type — delegates to the shared label helper. */
export function fileTypeLabel(name: string, mediaType: string): string {
  return mediaTypeLabel(mediaType, name);
}

export function matrixCell(count: number): string {
  return count === 0 ? "—" : String(count);
}

export function formatCount(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}
