/**
 * Pure helpers for the file manager view — filtering, sorting, type labels.
 */
import type { Source } from "@/lib/api";

export type SortKey = "name" | "type" | "date" | "owner";
export type SortDir = "asc" | "desc";

/** Case-insensitive match on name or memo; an empty query returns everything. */
export function filterSources(sources: Source[], query: string): Source[] {
  const q = query.trim().toLowerCase();
  if (q === "") return sources;
  return sources.filter(
    (s) => s.name.toLowerCase().includes(q) || s.memo.toLowerCase().includes(q),
  );
}

/** Sort a copy by column; dates are "YYYY-MM-DD HH:MM:SS" strings, so plain compare. */
export function sortSources(sources: Source[], key: SortKey, dir: SortDir): Source[] {
  const factor = dir === "asc" ? 1 : -1;
  return [...sources].sort((a, b) => {
    switch (key) {
      case "name":
      case "owner":
        return a[key].localeCompare(b[key]) * factor;
      case "date":
        return (a.date < b.date ? -1 : a.date > b.date ? 1 : 0) * factor;
      case "type":
        return a.media_type.localeCompare(b.media_type) * factor;
    }
  });
}

/** Human-readable media type; filenames ending in .pdf always report "PDF", .html/.htm report "Website". */
export function mediaTypeLabel(mediaType: string, name?: string): string {
  if (name) {
    const lower = name.toLowerCase();
    if (lower.endsWith(".html") || lower.endsWith(".htm")) return "Website";
    if (lower.endsWith(".pdf")) return "PDF";
  }
  switch (mediaType) {
    case "image":
      return "Image";
    case "audio":
      return "Audio";
    case "video":
      return "Video";
    case "pdf":
      return "PDF";
    default:
      return "Text";
  }
}
