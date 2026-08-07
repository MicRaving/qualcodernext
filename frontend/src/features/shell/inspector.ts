/**
 * Pure helpers for the right-hand Inspector panel.
 */
import type { CodeDetails, Source, SourceDetails } from "@/lib/api";
import { mediaTypeLabel } from "@/features/manage/files";

export function isCodeDetails(details: CodeDetails | SourceDetails): details is CodeDetails {
  return "code" in details;
}

export function isSourceDetails(details: CodeDetails | SourceDetails): details is SourceDetails {
  return "source" in details;
}

/**
 * Primary/secondary stat labels for the Inspector stats row.
 * Codes: "12 codings" · "3 files". Files: "3 text" · "0 image · 1 av".
 */
export function formatStats(details: CodeDetails | SourceDetails): {
  primary: string;
  secondary: string;
} {
  if (isCodeDetails(details)) {
    return {
      primary: `${details.coding_count} codings`,
      secondary: `${details.file_count} files`,
    };
  }
  return {
    primary: `${details.text_codings} text`,
    secondary: `${details.image_codings} image · ${details.av_codings} av`,
  };
}

/** Human-readable media type for a source ("PDF", "Image", "Text", …). */
export function formatMediaLabel(source: Source): string {
  return mediaTypeLabel(source.media_type, source.name);
}
